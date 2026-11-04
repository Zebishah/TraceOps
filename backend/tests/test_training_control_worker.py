import json
import sys
import time
import uuid
import zipfile
from io import BytesIO

import httpx

from finetuning import control_worker


def job():
    return {
        "id": str(uuid.uuid4()),
        "lease_token": str(uuid.uuid4()),
        "max_runtime_seconds": 60,
        "payload": {
            "model_id": "Qwen/Qwen2.5-0.5B-Instruct",
            "model_revision": "a" * 40,
            "epochs": 1,
            "rank": 4,
            "max_steps": 3,
            "max_tokens": 256,
            "method": "lora",
            "examples": [{"title": "Synthetic input"}],
        },
    }


def test_commands_use_existing_cli_flags_and_cuda_guard(tmp_path):
    value = job()["payload"]
    stages = control_worker.commands(tmp_path, value, "cpu")
    assert [stage for stage, _ in stages] == ["preparing", "loading", "evaluating", "packaging"]
    assert "--progress-file" in stages[1][1]
    assert "--input" in stages[3][1] and "--source" not in stages[3][1]
    value["method"] = "qlora"
    import pytest

    with pytest.raises(ValueError, match="CUDA"):
        control_worker.commands(tmp_path, value, "cpu")
    stages = control_worker.commands(tmp_path, value, "cuda")
    assert "--qlora" in stages[1][1] and "--qlora" in stages[2][1]


def test_real_subprocess_orchestration_uploads_only_package(monkeypatch, tmp_path):
    value = job()
    calls = []
    metrics = {
        "total": 1,
        "category_accuracy": 1,
        "priority_accuracy": 1,
        "joint_accuracy": 1,
        "invalid_outputs": 0,
        "infrastructure_errors": 0,
        "critical_misses": 0,
        "high_risk_downgrades": 0,
    }

    def commands(root, payload, device):
        script = (
            f"from pathlib import Path; import json; root=Path({str(root)!r}); "
            "(root/'progress.json').write_text(json.dumps({'stage':'validating',"
            "'completed_steps':3,'epoch':1,'validation_loss':1.25})); "
            f"(root/'evaluation.summary.json').write_text({json.dumps(metrics)!r}); "
            "(root/'package').mkdir(); (root/'package'/'artifact.json').write_text('{}'); "
            "(root/'package'/'adapter_model.safetensors').write_bytes(b'synthetic-test-only')"
        )
        return [("loading", [sys.executable, "-c", script])]

    monkeypatch.setattr(control_worker, "commands", commands)

    def handle(request):
        calls.append(request)
        assert request.headers["x-training-lease"] == value["lease_token"]
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"cancel_requested": False})
        if request.url.path.endswith("/artifact"):
            with zipfile.ZipFile(BytesIO(request.read())) as archive:
                assert set(archive.namelist()) == {"artifact.json", "adapter_model.safetensors"}
            return httpx.Response(200, json={"sha256": "a" * 64})
        assert json.loads(request.content)["status"] == "succeeded"
        return httpx.Response(200, json={})

    with httpx.Client(
        base_url="https://api.example.test/api/v1/", transport=httpx.MockTransport(handle)
    ) as client:
        control_worker.run_job(client, value, tmp_path, "cpu")
    assert any(request.url.path.endswith("/artifact") for request in calls)
    assert json.loads(calls[-1].content)["metrics"] == metrics


def test_cancel_prevents_process_start(monkeypatch, tmp_path):
    monkeypatch.setattr(
        control_worker.subprocess,
        "Popen",
        lambda *args, **kw: (_ for _ in ()).throw(AssertionError("must not start")),
    )
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200, json={"cancel_requested": True} if request.url.path.endswith("/heartbeat") else {}
        )

    with httpx.Client(
        base_url="https://api.example.test/api/v1/", transport=httpx.MockTransport(handle)
    ) as client:
        control_worker.run_job(client, job(), tmp_path, "cpu")
    assert json.loads(calls[-1].content) == {"status": "cancelled"}


def test_runtime_deadline_kills_real_child(monkeypatch, tmp_path):
    value = job()
    value["max_runtime_seconds"] = 0.1
    monkeypatch.setattr(
        control_worker,
        "commands",
        lambda *a: [("loading", [sys.executable, "-c", "import time; time.sleep(30)"])],
    )
    children = []
    original = control_worker.subprocess.Popen

    def start(*args, **kw):
        child = original(*args, **kw)
        children.append(child)
        return child

    monkeypatch.setattr(control_worker.subprocess, "Popen", start)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200, json={"cancel_requested": False} if request.url.path.endswith("/heartbeat") else {}
        )

    started = time.monotonic()
    with httpx.Client(
        base_url="https://api.example.test/api/v1/", transport=httpx.MockTransport(handle)
    ) as client:
        control_worker.run_job(client, value, tmp_path, "cpu")
    assert time.monotonic() - started < 5
    assert children and children[0].poll() is not None
    assert json.loads(calls[-1].content)["error_code"] == "runtime_limit"


def test_worker_rejects_path_traversal_in_job_identity(tmp_path):
    import pytest

    value = job()
    value["id"] = "../outside-work-directory"
    with pytest.raises(ValueError):
        control_worker.run_job(None, value, tmp_path, "cpu")
    assert list(tmp_path.iterdir()) == []


def test_process_exit_race_is_safe_to_stop(monkeypatch):
    from types import SimpleNamespace

    def gone(*_):
        raise ProcessLookupError()

    monkeypatch.setattr(control_worker.os, "killpg", gone)
    control_worker.stop_process(SimpleNamespace(pid=123, poll=lambda: None))
