"""One persistent model process; deadlines kill computation, not just HTTP waiting."""

import asyncio
import json
import logging
import multiprocessing
import resource
import sys
import threading
import time
from pathlib import Path

from ops_pilot.ai.finetuned_classifier import ClassifierLabels


class InvalidPrediction(ValueError):
    pass


def _peak_rss_mib():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024 if sys.platform == "darwin" else 1024)


def model_process(connection, adapter_path, device, qlora, cpu_threads, base_only):
    """Only the child imports ML libraries. Never send incident text to logs."""
    try:
        from tqdm import tqdm

        # This process has no concurrent progress writers. Avoid named multiprocessing
        # locks that cannot be finalized when a timed-out model must be killed.
        tqdm.set_lock(threading.RLock())
        import torch

        from finetuning.model_runtime import load_runtime, predict_labels

        torch.set_num_threads(cpu_threads)
        model, tokenizer = load_runtime(
            Path(adapter_path), device=device, qlora=qlora, with_adapter=not base_only
        )
        connection.send_bytes(
            json.dumps({"status": "ready", "peak_rss_mib": _peak_rss_mib()}).encode()
        )
        while True:
            payload = json.loads(connection.recv_bytes(64 * 1024))
            if payload.get("shutdown") is True:
                break
            try:
                labels = predict_labels(
                    model, tokenizer, title=payload["title"], description=payload["description"]
                )
                result = {"status": "valid", "labels": labels.model_dump(mode="json")}
            except ValueError:
                result = {"status": "invalid"}
            except RuntimeError:
                result = {"status": "error"}
            result["peak_rss_mib"] = _peak_rss_mib()
            connection.send_bytes(json.dumps(result).encode())
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        logging.getLogger(__name__).error(
            "classifier_child_failed", extra={"error_type": type(exc).__name__}
        )
    finally:
        connection.close()


class ProcessModelWorker:
    @property
    def ready(self):
        return self._ready and self._process is not None and self._process.is_alive()

    @ready.setter
    def ready(self, value):
        self._ready = value

    def __init__(
        self,
        adapter_path: Path,
        *,
        device="cpu",
        qlora=None,
        startup_timeout=120.0,
        prediction_timeout=8.0,
        cpu_threads=2,
        process_target=model_process,
        base_only=False,
    ):
        self.adapter_path = adapter_path
        self.device = device
        self.qlora = qlora
        self.startup_timeout = startup_timeout
        self.prediction_timeout = prediction_timeout
        self.cpu_threads = cpu_threads
        self.process_target = process_target
        self.base_only = base_only
        self.peak_rss_mib = 0.0
        self.ready = False
        self._process = None
        self._connection = None
        self._recovery = None
        self._closed = False

    async def _receive(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            connection, process = self._connection, self._process
            if connection is None or process is None:
                raise RuntimeError("Model process is unavailable")
            if await asyncio.to_thread(
                connection.poll, min(0.05, max(0, deadline - time.monotonic()))
            ):
                return json.loads(connection.recv_bytes(4096))
            if not process.is_alive():
                raise RuntimeError("Model process exited")
        raise TimeoutError("Model computation exceeded deadline")

    async def start(self):
        self.ready = False
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        self._connection = parent
        self._process = context.Process(
            target=self.process_target,
            args=(
                child,
                str(self.adapter_path),
                self.device,
                self.qlora,
                self.cpu_threads,
                self.base_only,
            ),
            daemon=True,
        )
        self._process.start()
        child.close()
        try:
            message = await self._receive(self.startup_timeout)
            if message.get("status") != "ready":
                raise RuntimeError("Model startup failed")
            self.peak_rss_mib = max(self.peak_rss_mib, float(message.get("peak_rss_mib", 0)))
            self.ready = True
        except BaseException:
            await self._stop_process()
            raise

    async def _stop_process(self, *, graceful=False):
        self.ready = False
        process, connection = self._process, self._connection
        self._process = self._connection = None
        if process is not None:
            if graceful and process.is_alive() and connection is not None:
                try:
                    connection.send_bytes(b'{"shutdown":true}')
                    await asyncio.to_thread(process.join, 2)
                except (OSError, BrokenPipeError):
                    pass
            if process.is_alive():
                process.terminate()
            await asyncio.to_thread(process.join, 1)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join, 1)
            process.close()
        if connection is not None:
            connection.close()

    async def _recover(self):
        try:
            await self._stop_process()
            await self.start()
        except Exception:
            logging.getLogger(__name__).error("classifier_recovery_failed")

    def ensure_recovery(self):
        if (
            not self._closed
            and not self.ready
            and (self._recovery is None or self._recovery.done())
        ):
            self._recovery = asyncio.create_task(self._recover())

    async def _invalidate(self):
        await self._stop_process()
        self.ensure_recovery()

    async def predict(self, *, title, description):
        if not self.ready or self._connection is None:
            raise RuntimeError("Model is not ready")
        try:
            self._connection.send_bytes(
                json.dumps({"title": title, "description": description}).encode()
            )
            result = await self._receive(self.prediction_timeout)
            self.peak_rss_mib = max(self.peak_rss_mib, float(result.get("peak_rss_mib", 0)))
            if result.get("status") == "invalid":
                raise InvalidPrediction("Model did not return valid labels")
            if result.get("status") != "valid":
                raise RuntimeError("Model process failed")
            return ClassifierLabels.model_validate(result["labels"])
        except InvalidPrediction:
            raise
        except BaseException:
            await asyncio.shield(self._invalidate())
            raise

    async def close(self):
        self._closed = True
        if self._recovery is not None:
            self._recovery.cancel()
            try:
                await self._recovery
            except asyncio.CancelledError:
                pass
        await self._stop_process(graceful=True)
