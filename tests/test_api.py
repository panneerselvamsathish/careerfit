from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from careerfit.api import MAX_FILE_BYTES, MAX_PDF_PAGES, RateLimiter, create_app, max_request_bytes, run, safe_filename
from careerfit.facts.schema import GapAnalysisFacts, SkillStatus
from careerfit.store import MemoryStore

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


WEB = Path(__file__).parent.parent / "src" / "careerfit" / "web"


class _Controls(HTMLParser):
    """Collects the page's form controls: (tag, type, name, id, value, accept)."""

    def __init__(self):
        super().__init__()
        self.controls = []

    def handle_starttag(self, tag, attrs):
        if tag in ("input", "textarea"):
            a = dict(attrs)
            self.controls.append((tag, a.get("type"), a.get("name"), a.get("id"), a.get("value"), a.get("accept")))


def test_page_keeps_the_native_controls_the_api_reads():
    # Restyled upload areas and segmented controls still sit on real file inputs and radios,
    # named exactly as /api/analyze expects.
    parser = _Controls()
    parser.feed((WEB / "index.html").read_text(encoding="utf-8"))
    assert parser.controls == [
        ("input", "file", "resume", "resume", None, ".pdf,.txt"),
        ("input", "radio", "jd_mode", "jd-mode-file", "file", None),
        ("input", "radio", "jd_mode", "jd-mode-text", "text", None),
        ("input", "file", "jd", "jd", None, ".pdf,.txt"),
        ("textarea", None, "jd_text", "jd_text", None, None),
        ("input", "checkbox", "donate_jd", "donate_jd", None, None),  # unticked unless the visitor ticks it
        ("input", "radio", "perspective", "perspective-candidate", "candidate", None),
        ("input", "radio", "perspective", "perspective-hiring-manager", "hiring_manager", None),
        ("input", "email", "email", "waitlist-email", None, None),
    ]
    assert 'id="donate_jd" name="donate_jd" class="checkbox">' in (WEB / "index.html").read_text(encoding="utf-8")


def test_the_font_is_bundled_with_its_licence_and_nothing_is_fetched_remotely(client):
    font = client.get("/static/fonts/SourceSans3VF-Upright.woff2")
    assert font.status_code == 200
    assert font.headers["content-type"] == "font/woff2"
    assert "SIL Open Font License" in (WEB / "fonts" / "SourceSans3-LICENSE.md").read_text(encoding="utf-8")
    for asset in ("index.html", "style.css"):
        text = (WEB / asset).read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text and "//fonts." not in text, asset


def test_page_never_inserts_document_text_as_html():
    for name in ("app.js", "privacy.js"):
        script = (WEB / name).read_text(encoding="utf-8")
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            assert sink not in script, name


# ---- usage records, the waitlist and donations ----

NOW = datetime(2026, 10, 16, 21, 45, 12, tzinfo=timezone.utc)
VISITOR = "3f2b8c1e-9a4d-4c7b-8e2f-1a2b3c4d5e6f"


class FailingStore(MemoryStore):
    def put(self, record):
        raise ConnectionError("DynamoDB unreachable")

    def delete(self, pk, sk):
        raise ConnectionError("DynamoDB unreachable")


def _client(store, **kwargs):
    return TestClient(create_app(rate_limit=(1000, 60.0), store=store, now=lambda: NOW, **kwargs))


def test_an_event_is_stored_with_the_day_and_no_address():
    store = MemoryStore()
    response = _client(store).post("/api/event", json={"type": "download", "visitor": VISITOR, "props": {"kind": "md"}})
    assert response.status_code == 204
    [record] = store.records.values()
    assert set(record) == {"pk", "sk", "type", "day", "props", "expires_at", "visitor"}
    assert (record["pk"], record["type"], record["props"]) == ("EVENT#2026-10-16", "download", {"kind": "md"})
    assert "testclient" not in repr(record)  # TestClient's client address


def test_an_event_outside_the_allow_list_is_a_400_and_not_stored():
    store = MemoryStore()
    response = _client(store).post("/api/event", json={"type": "download", "props": {"resume_text": "Jane Doe"}})
    assert response.status_code == 400
    assert response.json() == {"detail": "Property 'resume_text' is not allowed for download."}
    assert store.records == {}


def test_an_event_with_a_non_string_type_is_a_400_not_a_500():
    response = _client(MemoryStore()).post("/api/event", json={"type": []})
    assert response.status_code == 400
    assert response.json() == {"detail": "Unknown event type."}


def test_an_opted_out_browser_adds_no_skill_statistics():
    store = MemoryStore()
    response = analyze(_client(store), usage_opt_out="true")
    assert response.status_code == 200
    assert store.records == {}


def test_an_oversized_or_non_json_event_is_refused():
    client = _client(MemoryStore())
    assert client.post("/api/event", content=b"{" + b" " * 3000 + b"}").status_code == 413
    assert client.post("/api/event", content=b"not json").json() == {"detail": "Send a JSON object."}


def test_events_have_their_own_rate_limit():
    client = TestClient(create_app(store=MemoryStore(), clock=lambda: 0.0))  # every request inside one window
    for _ in range(120):
        assert client.post("/api/event", json={"type": "waitlist_joined"}).status_code == 204
    refused = client.post("/api/event", json={"type": "waitlist_joined"})
    assert refused.status_code == 429
    assert refused.json()["detail"].startswith("Too many events from this address.")


def test_joining_and_leaving_the_waitlist():
    store = MemoryStore()
    client = _client(store)
    joined = client.post("/api/waitlist", json={"email": "  Jane.Doe@Example.com "})
    assert joined.status_code == 201
    assert store.query("WAITLIST") == [{"pk": "WAITLIST", "sk": "jane.doe@example.com", "day": "2026-10-16",
                                        "consent": "v1: email me when careerfit's AI analysis launches"}]
    left = client.post("/api/waitlist/remove", json={"email": "jane.doe@example.com"})
    assert left.json() == {"detail": "If that address was on the waitlist, it has been removed."}
    assert store.query("WAITLIST") == []
    # the same answer for an address that was never listed, so the form can't look one up
    assert client.post("/api/waitlist/remove", json={"email": "never@example.com"}).json() == left.json()


def test_an_invalid_waitlist_email_is_a_clear_422():
    response = _client(MemoryStore()).post("/api/waitlist", json={"email": "jane@"})
    assert response.status_code == 422
    assert response.json() == {"detail": "Enter a valid email address."}


def test_a_waitlist_that_cannot_be_saved_says_so():
    response = _client(FailingStore()).post("/api/waitlist", json={"email": "jane@example.com"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Your email could not be saved just now. Please try again later."}


def test_an_analysis_keeps_skill_statistics_only_and_never_document_text():
    store = MemoryStore()
    response = analyze(_client(store))
    assert response.status_code == 200
    assert response.json()["jd_donated"] is False
    [record] = store.records.values()
    assert record["pk"] == "SKILLS#2026-10-16"
    assert set(record) == {"pk", "sk", "day", "skills", "expires_at"}
    assert sorted(record["skills"]) == sorted([name, level, status.value] for name, (status, level) in EXPECTED.items())
    assert "Backend Engineer" not in repr(store.records)  # a line from both documents


def test_a_donated_job_description_is_kept_scrubbed_and_never_the_resume():
    store = MemoryStore()
    jd = "Requirements\n- Python\n- Kubernetes\nQuestions: hiring@acme.example or 980-555-0101\n"
    response = analyze(_client(store), jd=None, jd_text=jd, donate_jd="true")
    assert response.json()["jd_donated"] is True
    [donation] = store.query("JD#2026-10-16")
    assert donation["text"] == "Requirements\n- Python\n- Kubernetes\nQuestions: [email removed] or [phone removed]"
    assert donation["source_format"] == "pasted"
    assert "Backend Engineer" not in repr(store.records)  # the resume's title line


def test_a_storage_failure_never_breaks_an_analysis():
    response = analyze(_client(FailingStore()), jd=None, jd_text="Requirements\n- Python\n", donate_jd="true")
    assert response.status_code == 200
    assert response.json()["jd_donated"] is False


def test_the_privacy_page_is_served_with_the_csp_and_states_the_log_retention():
    page = _client(MemoryStore()).get("/privacy")
    assert page.status_code == 200
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert '<script src="/static/privacy.js" defer></script>' in page.text
    assert "14 days" in page.text and "IP address" in page.text


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


def test_image_only_jd_pdf_is_accepted_and_says_nothing_was_read(client, tmp_path):
    # The page words its empty state from jd_coverage: no skills found in what could be read,
    # never "the job description mentions no skills".
    pdf = FPDF()
    pdf.add_page()
    pdf.rect(20, 20, 120, 60)  # a drawing only: no extractable text, like a scanned page
    path = tmp_path / "scanned-jd.pdf"
    pdf.output(str(path))
    response = analyze(client, jd=("scanned-jd.pdf", path.read_bytes()))
    assert response.status_code == 200
    facts = response.json()["facts"]
    assert facts["skill_observations"] == []
    assert facts["jd_coverage"]["chars_extracted"] == 0
    assert "scanned_pages" in facts["jd_coverage"]["known_blind_spots"]


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
