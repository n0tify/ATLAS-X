"""Entry point for running the FastAPI server."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api:app",
        host=os.environ.get("ATLAS_HOST", "127.0.0.1"),
        port=int(os.environ.get("ATLAS_PORT", "8000")),
        reload=os.environ.get("ATLAS_ENVIRONMENT", "development").strip().lower()
        == "development",
    )
