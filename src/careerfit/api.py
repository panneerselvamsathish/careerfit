"""Composition root for web use. Reads the clock; analyze/ and report/ never see the request.

Keyword pass only. The LLM judge (--deep) stays in the CLI: a paid call behind a public
endpoint needs identity, metering and rate limits first, and those belong here, not in judge/.
"""

import argparse
import re
import tempfile
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
MAX_FILE_BYTES = 5 * 1024 * 1024
# Two files plus multipart framing and the small form fields.
MAX_REQUEST_BYTES = 2 * MAX_FILE_BYTES + 256 * 1024

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


def _save(upload: UploadFile, folder: Path, fallback: str) -> Path:
    data = upload.file.read(MAX_FILE_BYTES + 1)
    name = safe_filename(upload.filename, fallback)
    if len(data) > MAX_FILE_BYTES:
        raise UploadError(413, f"{name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    if not data:
        raise UploadError(422, f"{name} is empty.")
    path = folder / name
    path.write_bytes(data)
    return path


def _read(path: Path) -> tuple[str, Coverage]:
    try:
        return read_document(path)
    except UnicodeDecodeError as e:
        raise UploadError(422, f"{path.name} is not UTF-8 text. Save it as UTF-8 or upload a PDF.") from e
    except (OSError, ValueError) as e:
        raise UploadError(422, str(e)) from e


def _given(upload: UploadFile | None) -> bool:
    # A browser sends an empty, unnamed part for a file input left blank.
    return upload is not None and bool(upload.filename)


def create_app(ontology_path: Path = DEFAULT_ONTOLOGY) -> FastAPI:
    ontology = load_ontology(ontology_path)
    app = FastAPI(title="careerfit", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def limits_and_headers(request: Request, call_next):
        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_REQUEST_BYTES):
            response = JSONResponse({"detail": "Upload too large."}, status_code=413)
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
            resume_path = _save(resume, folder / "resume", "resume")
            if has_text:
                jd_path = folder / "jd" / "pasted-job-description.txt"
                jd_path.write_text(jd_text, encoding="utf-8")
            else:
                jd_path = _save(jd, folder / "jd", "job-description")
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
    return app


def run(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="careerfit-server", description="Serve the careerfit web app.")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: this machine only)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    print(f"careerfit: open http://{args.host}:{args.port}/ (keyword pass only; --deep stays in the CLI)")
    uvicorn.run(create_app(), host=args.host, port=args.port)
