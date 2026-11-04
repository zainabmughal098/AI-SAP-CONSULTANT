"""ASGI entrypoint: explicitly select the demo before production bootstrap."""

import os

# Read the deployment environment directly. Loading .env here would initialize
# production configuration before the caller's explicit mode has been selected.
_mode = os.environ.get("SAP_APP_MODE", "rag").strip().lower() or "rag"

if _mode == "demo":
    from offline_demo.application import create_app

    app = create_app()
elif _mode == "rag":
    from api.main import app as app
else:
    raise ValueError("SAP_APP_MODE must be 'demo' or 'rag'")
