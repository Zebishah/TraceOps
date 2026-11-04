"""Repeatable real-Qwen CPU verification using synthetic data; never approves production."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from finetuning.artifacts import atomic_json, verify_artifact
from ops_pilot.ai.finetuned_classifier import ClassifierLabels

MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"


def verify_http(adapter, data, output):
    token = secrets.token_urlsafe(32)
    environment = {
        **os.environ,
        "CLASSIFIER_ENVIRONMENT": "development",
        "CLASSIFIER_ADAPTER_PATH": str(adapter.resolve()),
        "CLASSIFIER_SERVING_TOKEN": token,
        "CLASSIFIER_GENERATION_TIMEOUT_SECONDS": "30",
        "HF_HUB_OFFLINE": "1",
    }
    environment.pop("CLASSIFIER_RELEASE_MANIFEST", None)
    environment.pop("CLASSIFIER_RELEASE_PUBLIC_KEY", None)
    environment.pop("CLASSIFIER_QLORA", None)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    address = f"http://127.0.0.1:{port}"
    process = None
    with (output / "worker.log").open("w") as log:
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "finetuning.serve_classifier:app",
                    "--fd",
                    str(listener.fileno()),
                    "--no-access-log",
                    "--log-level",
                    "warning",
                ],
                pass_fds=(listener.fileno(),),
                env=environment,
                stdout=log,
                stderr=log,
            )
            listener.close()
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Worker exited; inspect the local worker.log")
                try:
                    with opener.open(address + "/health/ready", timeout=0.5) as response:
                        if json.load(response)["ready"]:
                            break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("Worker readiness deadline exceeded")
            rows = [
                json.loads(line) for line in (data / "validation.jsonl").read_text().splitlines()
            ]
            accepted = rejected = 0
            for row in rows:
                request = urllib.request.Request(
                    address + "/classify",
                    data=json.dumps(
                        {"title": row["title"], "description": row["description"]}
                    ).encode(),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                try:
                    with opener.open(request, timeout=35) as response:
                        ClassifierLabels.model_validate_json(response.read())
                        if response.headers.get("X-Classifier-Release") != "development":
                            raise RuntimeError("Development release identity missing")
                        accepted += 1
                except urllib.error.HTTPError as exc:
                    if exc.code != 422:
                        raise
                    rejected += 1
            request = urllib.request.Request(
                address + "/metrics", headers={"Authorization": f"Bearer {token}"}
            )
            with opener.open(request, timeout=2) as response:
                if b"opspilot_classifier_requests_total" not in response.read():
                    raise RuntimeError("Worker metrics missing")
            unauthorized = urllib.request.Request(
                address + "/classify",
                data=b'{"title":"t","description":"d"}',
                headers={"Content-Type": "application/json"},
            )
            try:
                opener.open(unauthorized, timeout=2)
            except urllib.error.HTTPError as exc:
                if exc.code != 401:
                    raise
            else:
                raise RuntimeError("Worker accepted an unauthenticated request")
            return {
                "accepted_schema_valid_outputs": accepted,
                "rejected_invalid_outputs": rejected,
                "authentication_checked": True,
                "metrics_checked": True,
            }
        finally:
            listener.close()
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Verification output must be empty")
    args.output.mkdir(parents=True, exist_ok=True)
    data, adapter = args.output / "data", args.output / "adapter"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "finetuning.prepare_dataset",
            "--input",
            str(Path(__file__).parent / "examples/incidents.demo.jsonl"),
            "--output",
            str(data),
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "finetuning.train_classifier",
            "--data",
            str(data),
            "--output",
            str(adapter),
            "--model",
            MODEL,
            "--revision",
            REVISION,
            "--device",
            "cpu",
            "--epochs",
            "1",
            "--max-steps",
            "1",
            "--gradient-accumulation",
            "1",
            "--max-tokens",
            "512",
            "--cpu-threads",
            "2",
        ],
        check=True,
    )
    for backend in ("adapter", "base"):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "finetuning.evaluate_classifier",
                "--backend",
                backend,
                "--adapter",
                str(adapter),
                "--input",
                str(data / "validation.jsonl"),
                "--split",
                "validation",
                "--output",
                str(args.output / f"{backend}.json"),
                "--timeout-seconds",
                "30",
            ],
            check=True,
        )
    http_result = verify_http(adapter, data, args.output)
    artifact = verify_artifact(adapter)
    report = {
        "model": MODEL,
        "revision": REVISION,
        "optimizer_steps": 1,
        "artifact_sha256": artifact.fingerprint(),
        "data_source": "synthetic_demo",
        "adapter_validation": json.loads((args.output / "adapter.summary.json").read_text()),
        "base_validation": json.loads((args.output / "base.summary.json").read_text()),
        "http_contract": http_result,
        "production_approved": False,
        "limitations": [
            "One optimizer step verifies mechanics, not model quality.",
            "Synthetic data is not reviewed production incident data.",
            "No live Groq baseline or CUDA/QLoRA run was performed.",
        ],
    }
    atomic_json(args.output / "verification.json", report)
    print(
        json.dumps(
            {
                "verification_report": str(args.output / "verification.json"),
                "production_approved": False,
            }
        )
    )


if __name__ == "__main__":
    main()
