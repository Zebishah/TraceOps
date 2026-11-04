"""Pull durable dashboard training jobs onto a dedicated Linux CPU/CUDA machine.

Run from backend with the isolated training environment. No inbound worker port is needed.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx


class JobStopped(Exception):
    pass


class JobFailed(Exception):
    pass


def stop_process(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def commands(root, payload, device):
    base = [sys.executable, "-m"]
    data, adapter = root / "data", root / "adapter"
    train = [
        *base,
        "finetuning.train_classifier",
        "--data",
        str(data),
        "--output",
        str(adapter),
        "--model",
        payload["model_id"],
        "--revision",
        payload["model_revision"],
        "--device",
        device,
        "--epochs",
        str(payload["epochs"]),
        "--rank",
        str(payload["rank"]),
        "--alpha",
        str(2 * payload["rank"]),
        "--max-steps",
        str(payload["max_steps"]),
        "--max-tokens",
        str(payload["max_tokens"]),
        "--progress-file",
        str(root / "progress.json"),
    ]
    evaluation = [
        *base,
        "finetuning.evaluate_classifier",
        "--backend",
        "adapter",
        "--adapter",
        str(adapter),
        "--input",
        str(data / "test.jsonl"),
        "--output",
        str(root / "evaluation.json"),
        "--device",
        device,
        "--timeout-seconds",
        "30",
        "--startup-timeout-seconds",
        "600",
    ]
    if payload["method"] == "qlora":
        if device != "cuda":
            raise ValueError("QLoRA needs a CUDA worker")
        train += ["--qlora"]
        evaluation += ["--qlora"]
    return [
        (
            "preparing",
            [
                *base,
                "finetuning.prepare_dataset",
                "--input",
                str(root / "input.jsonl"),
                "--output",
                str(data),
            ],
        ),
        ("loading", train),
        ("evaluating", evaluation),
        (
            "packaging",
            [
                *base,
                "finetuning.package_artifact",
                "--input",
                str(adapter),
                "--output",
                str(root / "package"),
            ],
        ),
    ]


def run_job(client, job, work_dir, device):
    job = {
        **job,
        "id": str(uuid.UUID(job["id"])),
        "lease_token": str(uuid.UUID(job["lease_token"])),
    }
    root = work_dir / job["id"] / job["lease_token"]
    root.mkdir(parents=True, exist_ok=False)
    payload = job["payload"]
    (root / "input.jsonl").write_text(
        "\n".join(json.dumps(e) for e in payload["examples"]) + "\n", encoding="utf-8"
    )
    prefix = f"internal/training/runs/{job['id']}"
    headers = {"X-Training-Lease": job["lease_token"]}
    deadline = time.monotonic() + job["max_runtime_seconds"]
    progress = {"stage": "preparing", "completed_steps": 0, "epoch": 0}
    process = None
    phase = "preparing"

    def heartbeat():
        response = client.post(prefix + "/heartbeat", headers=headers, json=progress)
        response.raise_for_status()
        if response.json()["cancel_requested"]:
            raise JobStopped()

    try:
        for phase, command in commands(root, payload, device):
            progress["stage"] = phase
            heartbeat()
            with (root / f"{phase}.log").open("wb") as log:
                process = subprocess.Popen(
                    command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
                )
                last_heartbeat = time.monotonic()
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        phase = "runtime_limit"
                        raise JobFailed()
                    if time.monotonic() - last_heartbeat >= 5:
                        file = root / "progress.json"
                        if phase == "loading" and file.exists():
                            if file.stat().st_size > 4096:
                                raise JobFailed()
                            progress = json.loads(file.read_text())
                        heartbeat()
                        last_heartbeat = time.monotonic()
                    time.sleep(0.25)
                if process.returncode != 0:
                    raise JobFailed()
            if phase == "loading" and (root / "progress.json").exists():
                progress = json.loads((root / "progress.json").read_text())
        progress["stage"] = "packaging"
        heartbeat()
        archive = root / "adapter.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for file in sorted((root / "package").iterdir()):
                if not file.is_file() or file.is_symlink():
                    raise JobFailed()
                output.write(file, arcname=file.name)
        if archive.stat().st_size > 64 * 1024 * 1024:
            raise JobFailed()
        phase = "upload"
        with archive.open("rb") as data:
            response = client.put(
                prefix + "/artifact",
                headers={**headers, "Content-Type": "application/zip"},
                content=data,
            )
            response.raise_for_status()
        heartbeat()
        metrics = json.loads((root / "evaluation.summary.json").read_text())
        response = client.post(
            prefix + "/finish", headers=headers, json={"status": "succeeded", "metrics": metrics}
        )
        response.raise_for_status()
        print(f"Completed training run {job['id']}; adapter remains unapproved.", flush=True)
    except BaseException as exc:
        if process is not None:
            stop_process(process)
        error = {
            "preparing": "preparation_failed",
            "loading": "training_failed",
            "evaluating": "evaluation_failed",
            "packaging": "packaging_failed",
            "upload": "upload_failed",
            "runtime_limit": "runtime_limit",
        }.get(phase, "worker_interrupted")
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            error = "worker_interrupted"
        try:
            result = (
                {"status": "cancelled"}
                if isinstance(exc, JobStopped)
                else {"status": "failed", "error_code": error}
            )
            response = client.post(prefix + "/finish", headers=headers, json=result)
            response.raise_for_status()
        except Exception:
            print(
                "Worker connection/lease lost; local process stopped. "
                "The API will expire the lease.",
                flush=True,
            )
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        print(f"Run {job['id']} stopped. Inspect its private worker logs for details.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument(
        "--watch", action="store_true", help="Keep polling; keeps the backend database awake"
    )
    parser.add_argument("--work-dir", type=Path, default=Path("finetuning/control-work"))
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    url = os.environ.get("TRAINING_API_URL", "").rstrip("/")
    token = os.environ.get("TRAINING_WORKER_TOKEN", "")
    parsed = urlsplit(url)
    if (
        (
            parsed.scheme != "https"
            and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})
        )
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != "/api/v1"
        or len(token) < 32
    ):
        raise SystemExit(
            "Set TRAINING_API_URL to the backend /api/v1 HTTPS URL and a 32+ character "
            "TRAINING_WORKER_TOKEN. Local HTTP is allowed only on loopback."
        )
    os.umask(0o077)
    args.work_dir = args.work_dir.resolve()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        base_url=url + "/",
        headers={"Authorization": "Bearer " + token},
        follow_redirects=False,
        timeout=60,
    ) as client:
        while True:
            response = client.post("internal/training/claim", json={"device": args.device})
            response.raise_for_status()
            job = response.json()["job"]
            if job:
                run_job(client, job, args.work_dir, args.device)
            elif not args.watch:
                print("No eligible queued training run.", flush=True)
            if not args.watch:
                break
            time.sleep(30)


if __name__ == "__main__":
    main()
