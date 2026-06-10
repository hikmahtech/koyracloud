"""ASGI entrypoint: ``uvicorn koyracloud.main:app``."""
from koyracloud.app import create_app

app = create_app()
