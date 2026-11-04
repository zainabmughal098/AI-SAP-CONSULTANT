"""Explicit loopback-only entry point; never loads production settings."""

from offline_demo.network import install

install()

import uvicorn  # noqa: E402

from offline_demo.application import create_app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8765, log_level="warning")
