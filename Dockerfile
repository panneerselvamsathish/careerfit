# careerfit web app: keyword pass only, no LLM credentials in the image.
# Build: docker build -t careerfit .    Run: docker run --rm -p 8000:8000 careerfit

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /bin/uv
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
# CAREERFIT_HOST=0.0.0.0: inside a container the platform's proxy is the only way in.
# FORWARDED_ALLOW_IPS is left at uvicorn's default (127.0.0.1). Set it to the platform proxy's
# address (or "*" if the container is reachable only through that proxy), or every visitor
# shares one rate-limit bucket: the proxy's.
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 CAREERFIT_HOST=0.0.0.0 PORT=8000
USER careerfit
WORKDIR /home/careerfit
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['PORT'] + '/healthz', timeout=3)"
CMD ["careerfit-server"]
