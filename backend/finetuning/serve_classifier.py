"""Serve a trained adapter separately, on loopback by default."""

import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from finetuning.model_runtime import load_runtime, predict_labels
from ops_pilot.ai.finetuned_classifier import ClassifierLabels


class ClassificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=8192)


@asynccontextmanager
async def lifespan(app: FastAPI):
    token = os.environ.get("CLASSIFIER_SERVING_TOKEN", "")
    if len(token) < 32:
        raise ValueError("CLASSIFIER_SERVING_TOKEN must contain at least 32 characters")
    model, tokenizer = await asyncio.to_thread(
        load_runtime,
        Path(os.environ["CLASSIFIER_ADAPTER_PATH"]),
        device=os.getenv("CLASSIFIER_DEVICE", "cpu"),
        qlora=os.getenv("CLASSIFIER_QLORA", "false").lower() == "true",
    )
    app.state.model = model
    app.state.tokenizer = tokenizer
    app.state.serving_token = token
    app.state.slot = asyncio.Semaphore(1)
    yield


app = FastAPI(title="OpsPilot classifier worker", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.post("/classify", response_model=ClassifierLabels)
async def classify(payload: ClassificationInput, authorization: Annotated[str, Header()] = ""):
    expected = f"Bearer {app.state.serving_token}"
    if not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid worker credentials")
    try:
        await asyncio.wait_for(app.state.slot.acquire(), timeout=0.1)
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail="Classifier busy") from exc
    try:
        # Shield the thread and retain its slot if the HTTP client disconnects.
        task = asyncio.create_task(
            asyncio.to_thread(
                predict_labels,
                app.state.model,
                app.state.tokenizer,
                title=payload.title,
                description=payload.description,
            )
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=422, detail="Classifier could not produce valid labels"
        ) from exc
    finally:
        app.state.slot.release()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("finetuning.serve_classifier:app", host="127.0.0.1", port=8001, workers=1)
