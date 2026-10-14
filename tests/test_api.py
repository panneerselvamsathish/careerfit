from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from careerfit.api import MAX_FILE_BYTES, MAX_PDF_PAGES, RateLimiter, create_app, max_request_bytes, run, safe_filename
from careerfit.facts.schema import GapAnalysisFacts, SkillStatus

FIXTURES = Path(__file__).parent.parent / "fixtures"
RESUME = (FIXTURES / "resume.txt").read_bytes()
JD = (FIXTURES / "jd.txt").read_bytes()

EXPECTED = {
    "python": (SkillStatus.MATCHED, "must"),
    "aws": (SkillStatus.MATCHED, "must"),
    "kubernetes": (SkillStatus.GAP, "must"),
    "terraform": (SkillStatus.GAP, "must"),
    "postgresql": (SkillStatus.MATCHED, "must"),
    "rest": (SkillStatus.MATCHED, "must"),
    "go": (SkillStatus.UNRESOLVABLE, "nice"),
    "kafka": (SkillStatus.GAP, "nice"),
    "react": (SkillStatus.UNRESOLVABLE, "nice"),
    "backend development": (SkillStatus.MATCHED, "must"),  # "Backend Engineer" title in both documents
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(rate_limit=(1000, 60.0)))  # the rate limit has its own tests


def analyze(client: TestClient, resume=("resume.txt", RESUME), jd=("jd.txt", JD), **form):
    files = {"resume": resume}
    if jd is not None:
        files["jd"] = jd
    return client.post("/api/analyze", files=files, data=form)


def test_analyze_returns_the_same_facts_as_the_cli(client):
    response = analyze(client)
    assert response.status_code == 200
    facts = GapAnalysisFacts.model_validate(response.json()["facts"])
    assert {o.skill: (o.status, o.requirement) for o in facts.skill_observations} == EXPECTED
    assert facts.llm_used is False
    assert facts.judge is None
    assert (facts.resume_source, facts.jd_source) == ("resume.txt", "jd.txt")


def test_analyze_returns_the_report_and_plain_text_blind_spots(client):
    body = analyze(client).json()
    assert body["report_markdown"].startswith("# ")
    assert body["blind_spots"][0] == ("Only skills in careerfit's skill list were checked. "
                                      "Anything else the job asks for is not shown here.")
    # Plain text for textContent, so no Markdown escaping
    assert "2 skill(s) could not be decided from keywords alone (go, react). Run with --deep to have Claude settle them." \
        in body["blind_spots"]


def test_pasted_jd_gives_the_same_verdicts_as_a_jd_file(client):
    response = analyze(client, jd=None, jd_text=JD.decode("utf-8"))
    assert response.status_code == 200
    facts = GapAnalysisFacts.model_validate(response.json()["facts"])
    assert {o.skill: (o.status, o.requirement) for o in facts.skill_observations} == EXPECTED
    assert facts.jd_source == "pasted-job-description.txt"


def test_perspective_is_recorded_and_changes_the_report(client):
    candidate = analyze(client).json()
    manager = analyze(client, perspective="hiring_manager").json()
    assert manager["facts"]["perspective"] == "hiring_manager"
    assert manager["report_markdown"] != candidate["report_markdown"]


def test_unknown_perspective_is_rejected(client):
    assert analyze(client, perspective="recruiter").status_code == 422


@pytest.mark.parametrize("jd,jd_text", [(None, None), (None, "   "), (("jd.txt", JD), "also pasted")])
def test_jd_must_be_exactly_one_of_file_or_text(client, jd, jd_text):
    form = {"jd_text": jd_text} if jd_text is not None else {}
    response = analyze(client, jd=jd, **form)
    assert response.status_code == 422
    assert response.json() == {"detail": "Give the job description either as a file or as pasted text, not both."}


def test_unsupported_file_type_is_a_clear_422(client):
    response = analyze(client, resume=("resume.docx", b"not really a docx"))
    assert response.status_code == 422
    assert response.json()["detail"] == "Unsupported file type: .docx Load either .txt or .pdf only (resume.docx)"


def test_empty_file_is_rejected(client):
    response = analyze(client, resume=("resume.txt", b""))
    assert response.status_code == 422
    assert response.json() == {"detail": "resume.txt is empty."}


def test_non_utf8_text_is_a_clear_422(client):
    response = analyze(client, resume=("resume.txt", "Python développeur".encode("latin-1")))
    assert response.status_code == 422
    assert response.json() == {"detail": "resume.txt is not UTF-8 text. Save it as UTF-8 or upload a PDF."}


def test_password_protected_pdf_is_a_clear_422(client, tmp_path):
    pdf = FPDF()
    pdf.set_encryption(owner_password="owner", user_password="user")
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(text="Python")
    path = tmp_path / "locked.pdf"
    pdf.output(str(path))
    response = analyze(client, resume=("locked.pdf", path.read_bytes()))
    assert response.status_code == 422
    assert response.json() == {"detail": "locked.pdf is password-protected. Remove the password and upload it again."}


def test_file_over_the_limit_is_413(client):
    response = analyze(client, resume=("resume.txt", b"a" * (MAX_FILE_BYTES + 1)))
    assert response.status_code == 413
    assert response.json() == {"detail": "resume.txt is larger than 5 MB."}


def test_request_over_the_limit_is_refused_before_parsing(client):
    response = client.post("/api/analyze", content=b"x", headers={"content-length": str(20 * 1024 * 1024)})
    assert response.status_code == 413


def test_hostile_filename_is_reduced_to_a_plain_basename(client):
    response = analyze(client, resume=("../../etc/<img src=x>.txt", RESUME))
    assert response.status_code == 200
    assert response.json()["facts"]["resume_source"] == "_img src_x_.txt"


@pytest.mark.parametrize("name,expected", [
    ("cv.pdf", "cv.pdf"),
    ("C:\\Users\\me\\My CV.PDF", "My CV.PDF"),
    ("../../secret.txt", "secret.txt"),
    ("", "resume"),
    ("..", "resume"),
    (".txt", "txt"),
    ("a" * 200 + ".txt", "a" * 80 + ".txt"),
])
def test_safe_filename(name, expected):
    assert safe_filename(name, "resume") == expected


def test_index_and_static_files_are_served_with_a_strict_csp(client):
    page = client.get("/")
    assert page.status_code == 200
    assert '<script src="/static/app.js" defer></script>' in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/favicon.ico").status_code == 204


def test_api_responses_are_not_cached(client):
    assert analyze(client).headers["cache-control"] == "no-store"


def test_page_never_inserts_document_text_as_html():
    script = (Path(__file__).parent.parent / "src" / "careerfit" / "web" / "app.js").read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in script


def test_no_api_docs_are_exposed(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_chunked_upload_without_content_length_is_cut_off_at_the_limit(client):
    def body():
        for _ in range(12):  # 12 MiB, more than the whole request may carry
            yield b"a" * (1024 * 1024)

    response = client.post("/api/analyze", content=body(),
                           headers={"content-type": "multipart/form-data; boundary=x"})
    assert "content-length" not in response.request.headers
    assert response.status_code == 413
    assert response.json() == {"detail": "Upload too large."}
    assert response.headers["x-content-type-options"] == "nosniff"


def test_pdf_over_the_page_limit_is_refused(client, tmp_path):
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for _ in range(MAX_PDF_PAGES + 1):
        pdf.add_page()
        pdf.cell(text="Python")
    path = tmp_path / "long.pdf"
    pdf.output(str(path))
    response = analyze(client, resume=("long.pdf", path.read_bytes()))
    assert response.status_code == 422
    assert response.json() == {"detail": "long.pdf has 21 pages; the limit is 20. Upload a shorter version."}


def test_analyses_are_rate_limited_per_client_and_the_window_slides():
    now = [1000.0]
    limited = TestClient(create_app(rate_limit=(2, 60.0), clock=lambda: now[0]))
    assert analyze(limited).status_code == 200
    assert analyze(limited).status_code == 200
    third = analyze(limited)
    assert third.status_code == 429
    assert third.headers["retry-after"] == "60"
    assert third.json() == {"detail": "Too many analyses from this address. Try again in 60 s."}
    assert limited.get("/").status_code == 200  # only analyses count
    now[0] += 60.0
    assert analyze(limited).status_code == 200


def test_rate_limiter_counts_each_client_separately():
    limiter = RateLimiter(1, 10.0, clock=lambda: 0.0)
    assert limiter.retry_after("10.0.0.1") is None
    assert limiter.retry_after("10.0.0.2") is None
    assert limiter.retry_after("10.0.0.1") == 10


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_server_binds_locally_by_default_and_takes_port_from_the_environment(monkeypatch):
    calls = []
    monkeypatch.setattr("careerfit.api.uvicorn.run", lambda app, **kw: calls.append(kw))
    run([], env={})
    run([], env={"PORT": "9000", "CAREERFIT_HOST": "0.0.0.0"})
    assert [(c["host"], c["port"]) for c in calls] == [("127.0.0.1", 8000), ("0.0.0.0", 9000)]
    assert all(c["proxy_headers"] is True and c["server_header"] is False for c in calls)


def test_rate_limiter_memory_is_bounded_under_a_flood_of_addresses():
    limiter = RateLimiter(1, 60.0, clock=lambda: 0.0, max_clients=100)
    for n in range(5000):  # every address still inside its window
        limiter.retry_after(f"10.0.{n // 256}.{n % 256}")
    assert len(limiter) == 100


def test_rate_limiter_forgets_the_client_seen_least_recently():
    limiter = RateLimiter(1, 60.0, clock=lambda: 0.0, max_clients=2)
    assert limiter.retry_after("a") is None
    assert limiter.retry_after("b") is None
    assert limiter.retry_after("a") == 60  # a is now the most recent
    assert limiter.retry_after("c") is None  # evicts b, not a
    assert limiter.retry_after("a") == 60
    assert limiter.retry_after("b") is None  # b was forgotten, so it starts afresh


def test_upload_limit_is_configurable_for_hosts_with_smaller_payloads():
    small = TestClient(create_app(rate_limit=(1000, 60.0), max_file_mb=2))
    assert small.get("/api/limits").json() == {"max_file_mb": 2, "max_pdf_pages": 20}
    response = analyze(small, resume=("resume.txt", b"a" * (2 * 1024 * 1024 + 1)))
    assert response.status_code == 413
    assert response.json() == {"detail": "resume.txt is larger than 2 MB."}
    assert analyze(small).status_code == 200


def test_lambda_sized_requests_fit_the_6_mb_payload_once_base64_encoded():
    # Lambda's 6 MB limit counts the base64'd body plus the event's headers; keep 256 KB spare.
    assert max_request_bytes(2) * 4 / 3 < 6 * 1024 * 1024 - 256 * 1024


def test_server_reads_the_upload_limit_from_the_environment(monkeypatch):
    apps = []
    monkeypatch.setattr("careerfit.api.uvicorn.run", lambda app, **kw: apps.append(app))
    run([], env={"CAREERFIT_MAX_FILE_MB": "2"})
    assert TestClient(apps[0]).get("/api/limits").json()["max_file_mb"] == 2
def test_retry_after_rounds_up_so_a_client_never_retries_too_early():
    now = [0.0]
    limiter = RateLimiter(1, 10.0, clock=lambda: now[0])
    assert limiter.retry_after("a") is None
    now[0] = 8.9995  # 1.0005 s of the window left
    assert limiter.retry_after("a") == 2


@pytest.mark.parametrize("value", ["0", "-1", "two", ""])
def test_server_refuses_to_start_with_an_unusable_upload_limit(monkeypatch, capsys, value):
    monkeypatch.setattr("careerfit.api.uvicorn.run", lambda app, **kw: pytest.fail("must not start"))
    with pytest.raises(SystemExit):
        run([], env={"CAREERFIT_MAX_FILE_MB": value})
    assert "CAREERFIT_MAX_FILE_MB must be a whole number of MB, at least 1" in capsys.readouterr().err


def test_create_app_rejects_a_non_positive_upload_limit():
    with pytest.raises(ValueError, match="max_file_mb must be at least 1, got 0"):
        create_app(max_file_mb=0)
