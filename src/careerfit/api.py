"""Composition root for web use. Reads the clock; analyze/ and report/ never see the request.

Keyword pass only. The LLM judge (--deep) stays in the CLI: a paid call behind a public
endpoint needs identity, metering and rate limits first, and those belong here, not in judge/.
"""

import argparse
import os
import re
import tempfile
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from careerfit.analyze.observations import build_facts
from careerfit.analyze.ontology import load_ontology
from careerfit.facts.schema import Coverage
from careerfit.ingest.document import read_document
from careerfit.report import blind_spot_notes, render_markdown

DEFAULT_ONTOLOGY = Path(__file__).parent / "ontology" / "skills.yaml"
WEB_DIR = Path(__file__).parent / "web"
MAX_FILE_MB = 5  # AWS Lambda sets 2 (CAREERFIT_MAX_FILE_MB): its 6 MB payload limit counts base64'd bytes
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
MAX_PDF_PAGES = 20  # a resume or JD is a few pages; parsing hundreds is a way to burn the server's CPU
RATE_LIMIT = (10, 60.0)  # analyses per client IP per window (seconds)

SECURITY_HEADERS = {
    # No inline script or style anywhere, so the page cannot run markup injected from a document.
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
                               "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class UploadError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def safe_filename(filename: str | None, fallback: str) -> str:
    """The client's name, reduced to a plain basename. Used for the temp file and for the facts' source.

    The name only labels the file: it is written inside a fresh temporary folder, so even a hostile
    name cannot reach anywhere else. The extension is kept so read_document can route on it.
    """
    name = re.split(r"[\\/]", filename or "")[-1]
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    stem = stem[:80] or fallback
    return f"{stem}.{suffix[:10]}" if suffix else stem


def max_request_bytes(max_file_mb: int) -> int:
    """Two files plus multipart framing and the small form fields."""
    return 2 * max_file_mb * 1024 * 1024 + 256 * 1024


def _save(upload: UploadFile, folder: Path, fallback: str, max_file_mb: int) -> Path:
    limit = max_file_mb * 1024 * 1024
    data = upload.file.read(limit + 1)
    name = safe_filename(upload.filename, fallback)
    if len(data) > limit:
        raise UploadError(413, f"{name} is larger than {max_file_mb} MB.")
    if not data:
        raise UploadError(422, f"{name} is empty.")
    path = folder / name
    path.write_bytes(data)
    return path


def _read(path: Path) -> tuple[str, Coverage]:
    try:
        return read_document(path, max_pdf_pages=MAX_PDF_PAGES)
    except UnicodeDecodeError as e:
        raise UploadError(422, f"{path.name} is not UTF-8 text. Save it as UTF-8 or upload a PDF.") from e
    except (OSError, ValueError) as e:
        raise UploadError(422, str(e)) from e


def _given(upload: UploadFile | None) -> bool:
    # A browser sends an empty, unnamed part for a file input left blank.
    return upload is not None and bool(upload.filename)


class BodyLimit:
    """Refuses a request body over `limit` bytes, whether or not it declares a Content-Length.

    Pure ASGI so it sees the bytes as they arrive: Starlette would otherwise spool an unbounded
    chunked upload to disk before the route runs, and FastAPI turns a failed read into a 400.
    """

    def __init__(self, app, limit: int):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > self.limit):
            return await _too_large(send)
        received = 0
        exceeded = False
        started = False

        async def counting_receive():
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            nonlocal started
            if exceeded:
                return  # whatever the app answers to a cut-off body, the client gets the 413 below
            started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not started:
            await _too_large(send)


async def _too_large(send) -> None:
    body = b'{"detail":"Upload too large."}'
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                            *((k.lower().encode(), v.encode()) for k, v in SECURITY_HEADERS.items())]})
    await send({"type": "http.response.body", "body": body})


class RateLimiter:
    """Sliding window per key, in memory. One process only: behind several instances each counts alone.

    Memory and work per request stay bounded however many clients arrive: at most max_clients
    buckets of at most `limit` timestamps each. Past that, the client seen least recently is
    forgotten (and starts afresh if it returns), so a flood of addresses costs O(1) per request.
    """

    def __init__(self, limit: int, window: float, clock: Callable[[], float], max_clients: int = 10_000):
        self.limit, self.window, self.clock, self.max_clients = limit, window, clock, max_clients
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int | None:
        """None if this request may go ahead (and counts it); otherwise seconds until it may."""
        now = self.clock()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = self._hits[key] = deque()
                if len(self._hits) > self.max_clients:
                    self._hits.popitem(last=False)
            else:
                self._hits.move_to_end(key)
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, int(hits[0] + self.window - now + 0.999))
            hits.append(now)
            return None

    def __len__(self) -> int:
        return len(self._hits)


def create_app(
    ontology_path: Path = DEFAULT_ONTOLOGY,
    rate_limit: tuple[int, float] = RATE_LIMIT,
    clock: Callable[[], float] = time.monotonic,
    max_file_mb: int = MAX_FILE_MB,
) -> FastAPI:
    ontology = load_ontology(ontology_path)
    limiter = RateLimiter(*rate_limit, clock=clock)
    app = FastAPI(title="careerfit", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def limits_and_headers(request: Request, call_next):
        wait = None
        if request.url.path == "/api/analyze" and request.method == "POST":
            # request.client is the real client only when uvicorn trusts the proxy (see run()).
            wait = limiter.retry_after(request.client.host if request.client else "unknown")
        if wait is not None:
            response = JSONResponse({"detail": f"Too many analyses from this address. Try again in {wait} s."},
                                    status_code=429, headers={"Retry-After": str(wait)})
        else:
            response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"  # responses quote the resume
        return response

    @app.exception_handler(UploadError)
    async def upload_error(_: Request, e: UploadError) -> JSONResponse:
        return JSONResponse({"detail": e.message}, status_code=e.status)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/limits")
    def limits() -> dict[str, int]:
        # The page checks sizes before uploading: on Lambda an oversized body is refused by the
        # Function URL before careerfit runs, with an error the page couldn't explain.
        return {"max_file_mb": max_file_mb, "max_pdf_pages": MAX_PDF_PAGES}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)  # no icon; saves a 404 in every browser console

    @app.post("/api/analyze")
    def analyze(
        resume: UploadFile = File(...),
        jd: UploadFile | None = File(None),
        jd_text: str | None = Form(None),
        perspective: Literal["candidate", "hiring_manager"] = Form("candidate"),
    ) -> JSONResponse:
        # Sync on purpose: FastAPI runs it in a worker thread, so PDF parsing never blocks the event loop.
        has_text = bool(jd_text and jd_text.strip())
        if _given(jd) == has_text:
            raise UploadError(422, "Give the job description either as a file or as pasted text, not both.")
        with tempfile.TemporaryDirectory(prefix="careerfit-") as tmp:
            folder = Path(tmp)
            (folder / "resume").mkdir()
            (folder / "jd").mkdir()
            resume_path = _save(resume, folder / "resume", "resume", max_file_mb)
            if has_text:
                jd_path = folder / "jd" / "pasted-job-description.txt"
                jd_path.write_text(jd_text, encoding="utf-8")
            else:
                jd_path = _save(jd, folder / "jd", "job-description", max_file_mb)
            resume_text, resume_coverage = _read(resume_path)
            jd_text_read, jd_coverage = _read(jd_path)

        facts = build_facts(
            resume_text=resume_text,
            resume_coverage=resume_coverage,
            resume_source=resume_path.name,
            jd_text=jd_text_read,
            jd_coverage=jd_coverage,
            jd_source=jd_path.name,
            ontology=ontology,
            at=datetime.now(timezone.utc),
            perspective=perspective,
        )
        return JSONResponse({
            "facts": facts.model_dump(mode="json"),
            "blind_spots": blind_spot_notes(facts),  # plain text: the page shows it with textContent
            "report_markdown": render_markdown(facts),
        })

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    app.add_middleware(BodyLimit, limit=max_request_bytes(max_file_mb))
    return app


def run(argv: list[str] | None = None, env: dict[str, str] | None = None) -> None:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="careerfit-server", description="Serve the careerfit web app.")
    parser.add_argument("--host", default=env.get("CAREERFIT_HOST", "127.0.0.1"),
                        help="interface to bind (default: this machine only; a container sets 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(env.get("PORT", "8000")),
                        help="port (default: $PORT, which most hosting platforms set, else 8000)")
    args = parser.parse_args(argv)
    print(f"careerfit: serving on http://{args.host}:{args.port}/ (keyword pass only; --deep stays in the CLI)")
    max_file_mb = int(env.get("CAREERFIT_MAX_FILE_MB", MAX_FILE_MB))
    # proxy_headers: behind the platform's proxy, the client IP for rate limiting comes from
    # X-Forwarded-For, trusted only from FORWARDED_ALLOW_IPS (uvicorn's default: 127.0.0.1).
    # On Lambda the Web Adapter is that proxy and connects from 127.0.0.1, so the default is right.
    uvicorn.run(create_app(max_file_mb=max_file_mb), host=args.host, port=args.port, proxy_headers=True,
                server_header=False)
