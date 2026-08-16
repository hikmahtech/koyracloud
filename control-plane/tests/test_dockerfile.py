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


def test_build_args_are_declared_before_the_build_steps():
    """Undeclared --build-arg is a warning, not an error, so docker silently
    dropped every one of them: a VITE_*/NEXT_PUBLIC_* set on the app forced a
    rebuild (it's in the image tag) but never reached the bundle."""
    df = render_dockerfile(parse_manifest(NODE), "koyra-runtime:latest",
                           {"VITE_API_BASE_URL": "https://api.example.com",
                            "NEXT_PUBLIC_X": "1"})
    lines = df.splitlines()
    assert "ARG VITE_API_BASE_URL" in lines and "ARG NEXT_PUBLIC_X" in lines
    # in scope before the build runs, and ahead of COPY so the args sit on a
    # layer of their own rather than re-copying the repo when one changes
    assert max(lines.index("ARG VITE_API_BASE_URL"),
               lines.index("ARG NEXT_PUBLIC_X")) < lines.index("COPY . /app")
    assert lines.index("COPY . /app") < lines.index("RUN npm run build")


def test_build_args_with_unsafe_names_are_dropped():
    """Env keys are user input; a newline in one would otherwise inject
    instructions into the Dockerfile we generate."""
    df = render_dockerfile(parse_manifest(NODE), "koyra-runtime:latest",
                           {"GOOD": "1", "BAD NAME": "x", "2LEADING": "x",
                            "INJECT\nRUN touch /pwned": "x", "": "x"})
    assert "/pwned" not in df
    assert [lbl for lbl in df.splitlines() if lbl.startswith("ARG ")] == ["ARG GOOD"]


def test_go_build_args_declared_in_the_build_stage():
    """ARG is per-stage: it has to land in the golang stage, not the runner."""
    df = render_dockerfile(parse_manifest(GO), "koyra-runtime:latest", {"LDFLAGS": "-s"})
    lines = df.splitlines()
    assert lines.index("FROM golang:1.23 AS build") < lines.index("ARG LDFLAGS")
    assert lines.index("ARG LDFLAGS") < lines.index("FROM gcr.io/distroless/static-debian12")


def test_no_build_args_renders_unchanged():
    """Apps with no env keep byte-for-byte the Dockerfile they had before."""
    assert render_dockerfile(parse_manifest(PY), "koyra-runtime:latest", {}) == \
        render_dockerfile(parse_manifest(PY), "koyra-runtime:latest")
