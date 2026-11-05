"""Modal GPU endpoint for the OpsPilot QLoRA classifier demo.

Run from the backend directory after importing the adapter artifact locally:
    modal deploy finetuning/modal_app.py
"""
from pathlib import Path

import modal

APP_NAME = "opspilot-qwen-qlora-demo"
ADAPTER_DIR = Path("finetuning/adapters/synthetic-v1-qlora")
REMOTE_BACKEND = "/root/backend"

app = modal.App(APP_NAME)

# Fail locally before deployment if the ignored, locally imported adapter is absent.
if not (ADAPTER_DIR / "artifact_manifest.json").is_file():
    raise FileNotFoundError(
        f"Missing {ADAPTER_DIR}/artifact_manifest.json. "
        "Import and verify your QLoRA adapter before deploying."
    )
if not (ADAPTER_DIR / "adapter_model.safetensors").is_file():
    raise FileNotFoundError(f"Missing adapter weights in {ADAPTER_DIR}")

image = (
    modal.Image.debian_slim(python_version="3.13")
    .pip_install(
        "torch==2.11.0",
        "transformers==5.22.1",
        "peft==0.21.2",
        "accelerate==1.15.0",
        "safetensors==0.8.0",
        "bitsandbytes==0.50.2",
        "fastapi",
        "pydantic>=2,<3",
        "pydantic-settings>=2,<3",
        "sqlalchemy>=2,<2.2",
        "httpx>=0.28.1",
        "cryptography==50.0.2",
        "tqdm",
    )
    .add_local_dir(
        "finetuning",
        remote_path=f"{REMOTE_BACKEND}/finetuning",
        ignore=["checkpoints", "__pycache__"],
    )
    .add_local_dir(
        "src",
        remote_path=f"{REMOTE_BACKEND}/src",
        ignore=["__pycache__"],
    )
)


@app.function(
    image=image,
    gpu="T4",
    secrets=[modal.Secret.from_name("opspilot-classifier-demo")],
    timeout=900,
    startup_timeout=900,
    scaledown_window=600,
    max_containers=1,
)
@modal.asgi_app()
def classifier_api():
    """Expose the repo's authenticated /classify FastAPI worker through Modal."""
    import sys

    sys.path.insert(0, f"{REMOTE_BACKEND}/")
    sys.path.insert(0, f"{REMOTE_BACKEND}/src")

    from finetuning.serve_classifier import app as worker_app

    return worker_app
