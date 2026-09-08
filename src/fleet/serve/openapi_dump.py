"""Dump the serve OpenAPI schema as JSON for UI type generation.

Called by ``just ui-types`` (``uv run python -m fleet.serve.openapi_dump``):
builds the FastAPI app with a throwaway ``FLEET_HOME`` and prints
``app.openapi()`` to stdout. The lifespan never runs, so no daemon starts;
the dummy home only hosts the question-store sqlite file ``QuestionStore``
creates on init.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

from fastapi import FastAPI

from fleet.serve.app import create_app


def build_dump_app() -> FastAPI:
    """Build the serve app against a throwaway fleet home for schema export."""
    dummy = tempfile.mkdtemp(prefix="fleet-openapi-")
    os.environ["FLEET_HOME"] = dummy
    return create_app()


def main() -> None:
    """Print the OpenAPI schema JSON to stdout."""
    app = build_dump_app()
    json.dump(app.openapi(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
