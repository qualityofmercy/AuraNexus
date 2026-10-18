"""``python -m auranexus`` starts the API (uvicorn factory mode)."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "auranexus.api.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 (container entrypoint)
        port=int(os.environ.get("PORT", "8080")),
    )
