# careerfit web app: keyword pass only, no LLM credentials in the image.
# Build: docker build -t careerfit .    Run: docker run --rm -p 8000:8000 careerfit
# On AWS Lambda: see template.yaml (sam build && sam deploy --guided).

FROM python:3.12-slim AS build
# Third-party images are pinned by digest (tag kept for readability): a re-pushed tag can't
# change what gets built. Bump both together when upgrading.
COPY --from=ghcr.io/astral-sh/uv:0.11.16@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# Dependencies first, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 careerfit
COPY --from=build /app/.venv /app/.venv
# AWS Lambda Web Adapter: a Lambda extension that turns invocations into plain HTTP requests to
# the server below. Outside Lambda it is an inert file, so the same image runs anywhere.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0@sha256:17cfd08eff1dfea3f6a9a1e9c65fdac80aa4919b6085e746615530f43f57d2f1 /lambda-adapter /opt/extensions/lambda-adapter
# CAREERFIT_HOST=0.0.0.0: inside a container the platform's proxy is the only way in.
# FORWARDED_ALLOW_IPS is left at uvicorn's default (127.0.0.1). Set it to the platform proxy's
# address (or "*" if the container is reachable only through that proxy), or every visitor
# shares one rate-limit bucket: the proxy's.
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 CAREERFIT_HOST=0.0.0.0 PORT=8000
# USER applies to docker run. Lambda ignores it and runs the image as its own unprivileged user
# on a read-only file system (only /tmp is writable), so everything the server needs must work
# for any user: a root-owned, world-readable working directory, and a start command that
# doesn't depend on PATH. (The user's home is mode 700: Lambda's user couldn't even enter it.)
USER careerfit
WORKDIR /app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['PORT'] + '/healthz', timeout=3)"
CMD ["/app/.venv/bin/careerfit-server"]
