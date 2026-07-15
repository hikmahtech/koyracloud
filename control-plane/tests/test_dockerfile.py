"""Unit tests for the per-app Dockerfile renderer (pure)."""
import pytest

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

GO = """
name: gopher
runtime: go
port: 8080
"""

GO_CUSTOM = """
name: gopher
runtime: go
port: 8080
build:
  - go vet ./...
  - CGO_ENABLED=0 go build -o /app/server ./cmd/gopher
start: /app/server --port 8080
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


def test_go_dockerfile_two_stages_default_build_and_cmd():
    df = render_dockerfile(parse_manifest(GO), "koyra-runtime:latest")
    # base_image is ignored entirely — go doesn't build on the shared runtime image
    assert "koyra-runtime:latest" not in df
    assert "FROM golang:1.23 AS build" in df
    assert "FROM gcr.io/distroless/static-debian12" in df
    assert "COPY . ." in df
    assert "RUN CGO_ENABLED=0 go build -o /app/server ." in df
    assert "COPY --from=build /app/server /app/server" in df
    # distroless has no shell: CMD must be exec-form, not ["sh", "-c", ...]
    cmd = next(lbl for lbl in df.splitlines() if lbl.startswith("CMD "))
    assert cmd == 'CMD ["/app/server"]'


def test_go_dockerfile_custom_build_and_start():
    df = render_dockerfile(parse_manifest(GO_CUSTOM), "koyra-runtime:latest")
    assert "RUN go vet ./..." in df
    assert "RUN CGO_ENABLED=0 go build -o /app/server ./cmd/gopher" in df
    # a custom `start:` is exec-split (no shell to run it through)
    cmd = next(lbl for lbl in df.splitlines() if lbl.startswith("CMD "))
    assert cmd == 'CMD ["/app/server", "--port", "8080"]'


def test_go_healthcheck_rejected():
    with pytest.raises(Exception, match="healthcheck"):
        parse_manifest(GO + "healthcheck: /health\n")


def test_go_predeploy_rejected():
    with pytest.raises(Exception, match="predeploy"):
        parse_manifest(GO + "predeploy:\n  - echo hi\n")
