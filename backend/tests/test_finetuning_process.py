import asyncio
import json
import time

import pytest

from finetuning.process_worker import ProcessModelWorker


def controlled_model(connection, *unused):
    connection.send_bytes(b'{"status":"ready","peak_rss_mib":10}')
    while True:
        try:
            payload = json.loads(connection.recv_bytes())
        except EOFError:
            return
        if payload.get("shutdown"):
            return
        if payload["title"] == "hang":
            time.sleep(5)
        connection.send_bytes(
            b'{"status":"valid","labels":{"category":"payment","priority":"high"},"peak_rss_mib":12}'
        )


@pytest.mark.asyncio
async def test_deadline_terminates_model_and_recovery_accepts_next_request(tmp_path):
    worker = ProcessModelWorker(
        tmp_path, process_target=controlled_model, prediction_timeout=0.1, startup_timeout=15
    )
    await worker.start()
    original_pid = worker._process.pid
    try:
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await worker.predict(title="hang", description="d")
        assert time.monotonic() - started < 3
        await asyncio.wait_for(worker._recovery, timeout=15)
        assert worker.ready and worker._process.pid != original_pid
        labels = await worker.predict(title="valid", description="d")
        assert labels.category == "payment"
        assert worker.peak_rss_mib == 12
    finally:
        await worker.close()
    assert worker._process is None and not worker.ready


@pytest.mark.asyncio
async def test_cancelled_request_also_stops_its_computation(tmp_path):
    worker = ProcessModelWorker(
        tmp_path, process_target=controlled_model, prediction_timeout=5, startup_timeout=15
    )
    await worker.start()
    try:
        original_pid = worker._process.pid
        task = asyncio.create_task(worker.predict(title="hang", description="d"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(worker._recovery, timeout=15)
        assert worker._process.pid != original_pid
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_dead_child_is_unready_and_can_be_recovered(tmp_path):
    worker = ProcessModelWorker(tmp_path, process_target=controlled_model, startup_timeout=15)
    await worker.start()
    try:
        worker._process.terminate()
        await asyncio.to_thread(worker._process.join, 1)
        assert not worker.ready
        worker.ensure_recovery()
        await asyncio.wait_for(worker._recovery, timeout=15)
        assert worker.ready
    finally:
        await worker.close()
