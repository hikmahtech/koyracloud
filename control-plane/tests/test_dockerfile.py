"""Unit tests for the per-app Dockerfile renderer (pure)."""
from koyracloud.dockerfile import render_dockerfile
from koyracloud.manifest import parse_manifest

NODE = """
name: web
runtime: node
port: 3000
build:
  - npm ci
  - npm run build
start: npm run start -- -p 3000
healthcheck: /
"""

PY = """
name: api
runtime: python
port: 8000
build:
  - pip install -r requirements.txt
predeploy:
  - alembic upgrade head
start: uvicorn app:app --host 0.0.0.0 --port 8000
persist:
  - data
"""

STATIC = """
name: site
runtime: static
build:
  - npm ci
  - npm run build
"""


def test_node_dockerfile():
    df = render_dockerfile(parse_manifest(NODE), "koyra-runtime:latest")
    assert df.startswith("FROM koyra-runtime:latest")
    assert "ENTRYPOINT []" in df          # clear the base build entrypoint
    assert "COPY . /app" in df
    assert "RUN npm ci" in df and "RUN npm run build" in df
    # start runs as the container command, no predeploy prefix
    cmd = next(lbl for lbl in df.splitlines() if lbl.startswith("CMD "))
    assert "exec npm run start -- -p 3000" in cmd and "&&" not in cmd


def test_python_dockerfile_predeploy_and_persist():
    df = render_dockerfile(parse_manifest(PY), "koyra-runtime:latest")
    assert "RUN pip install -r requirements.txt" in df
    assert "RUN mkdir -p /app/data" in df          # persist dir exists in image
    cmd = next(lbl for lbl in df.splitlines() if lbl.startswith("CMD "))
    # predeploy runs every start, then exec start
    assert "alembic upgrade head && exec uvicorn app:app" in cmd


def test_static_dockerfile_serves_detected_dir():
    df = render_dockerfile(parse_manifest(STATIC), "koyra-runtime:latest")
    assert "RUN npm ci" in df
    cmd = next(lbl for lbl in df.splitlines() if lbl.startswith("CMD "))
    assert "/koyra_static.py" in cmd and "--port 8000" in cmd
