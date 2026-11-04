# OpsPilot Backend

FastAPI backend for OpsPilot.

## Development

All commands below are run from the `backend/` directory.

### Install dependencies

```bash
uv sync
## Dashboard training jobs

The frontend can queue, inspect, cancel and retry LoRA / QLoRA jobs through an owner/admin-only API. A separately authenticated CPU/CUDA pull worker runs the existing training pipeline and uploads a verified private adapter ZIP. Apply migration `9e30f0000001` before enabling `TRAINING_ENABLED`. See [dashboard training setup](../docs/dashboard-training-control.md) for all settings, worker commands, limits, storage and verification. Training does not activate a production model.
