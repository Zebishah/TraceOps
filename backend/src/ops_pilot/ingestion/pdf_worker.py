"""Resource-limited PDF extraction child process.

Run only through the trusted parent extractor:
python -m ops_pilot.ingestion.pdf_worker
"""

import json
import resource
import sys

from ops_pilot.ingestion.extractors import (
    MAX_EXTRACT_INPUT_BYTES,
    extract_pdf,
)

MAX_PDF_WORKER_OUTPUT_BYTES = 16 * 1024 * 1024
PDF_MEMORY_LIMIT_BYTES = 768 * 1024 * 1024
PDF_CPU_LIMIT_SECONDS = 10


def apply_resource_limits() -> None:
    """Set OS limits before parsing untrusted PDF content."""

    # Unix/Linux only. Fail closed if limits cannot be applied.
    resource.setrlimit(
        resource.RLIMIT_AS,
        (PDF_MEMORY_LIMIT_BYTES, PDF_MEMORY_LIMIT_BYTES),
    )

    resource.setrlimit(
        resource.RLIMIT_CPU,
        (PDF_CPU_LIMIT_SECONDS, PDF_CPU_LIMIT_SECONDS + 1),
    )

    # The child must never write files.
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))

    # Avoid large core dumps after crashes.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main() -> int:
    try:
        apply_resource_limits()

        data = sys.stdin.buffer.read(MAX_EXTRACT_INPUT_BYTES + 1)

        if len(data) > MAX_EXTRACT_INPUT_BYTES:
            raise ValueError("PDF exceeds input size limit")

        result = extract_pdf(data)

        response = {
            "ok": True,
            "document": result.model_dump(mode="json"),
        }

    except Exception as exc:
        response = {
            "ok": False,
            "error": type(exc).__name__,
        }

    encoded = json.dumps(
        response,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")

    if len(encoded) > MAX_PDF_WORKER_OUTPUT_BYTES:
        response = {
            "ok": False,
            "error": "PDF output exceeds worker limit",
        }

        encoded = json.dumps(response).encode("utf-8")

    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()

    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
