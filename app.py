"""ASGI entrypoint: explicitly select the demo before production bootstrap."""

import logging
import os


# Read the deployment environment directly. Loading .env here would initialize
# production configuration before the caller's explicit mode has been selected.
def create_application():
    """Select the application before importing either runtime bootstrap."""
    mode = os.environ.get("SAP_APP_MODE", "rag").strip().lower() or "rag"

    if mode == "demo":
        from offline_demo.application import create_app

        selected_app = create_app()
    elif mode == "rag":
        from api.main import app as selected_app
    else:
        raise ValueError("SAP_APP_MODE must be 'demo' or 'rag'")

    # WARNING is visible with Python's default logging configuration, including
    # cold starts before the server configures INFO logging. Never log raw input.
    logging.getLogger("sap.application").warning("SAP application mode: %s", mode)
    return selected_app


# Vercel's static discovery requires a module-level app declaration.
app = create_application()
