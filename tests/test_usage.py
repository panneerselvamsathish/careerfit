"""The rules for what careerfit stores about visitors (usage.py) and the in-memory store."""

import re
import time
from datetime import datetime, timezone

import pytest

from careerfit import usage
from careerfit.store import MemoryStore

NOW = datetime(2026, 10, 16, 21, 45, 12, tzinfo=timezone.utc)
VISITOR = "3f2b8c1e-9a4d-4c7b-8e2f-1a2b3c4d5e6f"
OTHER = "0c5d2a7e-1b3f-4e9a-a6c8-7d1e2f3a4b5c"


# ---- events: an allow-list, nothing else ----

def test_a_known_event_with_allowed_props_is_accepted():
    assert usage.parse_event({"type": "download", "visitor": VISITOR, "props": {"kind": "md"}}) == \
        ("download", VISITOR, {"kind": "md"})


def test_an_event_without_a_visitor_id_is_accepted():
    assert usage.parse_event({"type": "page_view", "props": {"path": "/", "ref_host": "www.linkedin.com"}}) == \
        ("page_view", None, {"path": "/", "ref_host": "www.linkedin.com"})


@pytest.mark.parametrize("payload,message", [
    ({"type": "keystrokes"}, "Unknown event type."),
    ({"type": []}, "Unknown event type."),  # unhashable: must be a 400, not a TypeError
    ({"type": {}}, "Unknown event type."),
    ({"type": 5}, "Unknown event type."),
    ({"type": "download", "props": {"kind": "md", "resume": "Jane Doe"}}, "Property 'resume' is not allowed for download."),
    ({"type": "download", "props": {"kind": "docx"}}, "Property 'kind' is not allowed for download."),
    ({"type": "page_view", "props": {"utm_source": "has spaces"}}, "Property 'utm_source' is not allowed for page_view."),
    ({"type": "page_view", "props": {"ref_host": "https://evil.example/path"}}, "Property 'ref_host' is not allowed for page_view."),
    ({"type": "analysis_completed", "props": {"skills": -1}}, "Property 'skills' is not allowed for analysis_completed."),
    ({"type": "analysis_completed", "props": {"skills": True}}, "Property 'skills' is not allowed for analysis_completed."),
    ({"type": "download", "visitor": "203.0.113.7"}, "The visitor ID must be a random UUID."),
    ({"type": "download", "ip": "203.0.113.7"}, "An event is an object with type, visitor and props."),
    (["download"], "An event is an object with type, visitor and props."),
])
def test_anything_outside_the_allow_list_is_refused(payload, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        usage.parse_event(payload)


# ---- records: the day only, expiry, no visitor ID where none belongs ----

def test_an_event_record_keeps_the_day_not_the_time_and_expires():
    record = usage.event_record("download", VISITOR, {"kind": "md"}, NOW)
    assert set(record) == {"pk", "sk", "type", "day", "props", "expires_at", "visitor"}
    assert (record["pk"], record["day"], record["visitor"]) == ("EVENT#2026-10-16", "2026-10-16", VISITOR)
    assert record["expires_at"] == 1826668800  # midnight UTC 2027-11-20: 400 days from the start of the day
    assert "21:45" not in repr(record)


def test_the_expiry_gives_away_the_day_but_not_the_time():
    morning = usage.event_record("download", None, {"kind": "md"}, NOW.replace(hour=0, minute=0, second=1))
    night = usage.skill_stats_record([("python", "must", "matched")], NOW.replace(hour=23, minute=59, second=59))
    assert morning["expires_at"] == night["expires_at"] == 1826668800


def test_an_anonymous_event_record_has_no_visitor_field():
    assert "visitor" not in usage.event_record("page_view", None, {"path": "/"}, NOW)


def test_skill_statistics_carry_skill_names_and_verdicts_only():
    record = usage.skill_stats_record([("python", "must", "matched"), ("kafka", "nice", "gap")], NOW)
    assert set(record) == {"pk", "sk", "day", "skills", "expires_at"}
    assert record["pk"] == "SKILLS#2026-10-16"
    assert record["skills"] == [["python", "must", "matched"], ["kafka", "nice", "gap"]]


def test_a_waitlist_record_is_keyed_by_the_address_and_records_consent():
    assert usage.waitlist_record("jane@example.com", NOW) == {
        "pk": "WAITLIST", "sk": "jane@example.com", "day": "2026-10-16",
        "consent": "v1: email me when careerfit's AI analysis launches"}


def test_a_donated_job_description_is_kept_without_contacts():
    record = usage.donation_record("Python role. Apply: jobs@acme.example, (980) 555-0101.\n", "txt", NOW)
    assert record["text"] == "Python role. Apply: [email removed], [phone removed]."
    assert (record["pk"], record["source_format"], record["chars"]) == ("JD#2026-10-16", "txt", 53)
    assert "visitor" not in record and "expires_at" not in record


def test_a_donation_too_long_or_empty_is_not_kept():
    assert usage.donation_record("x" * 100_001, "pdf", NOW) is None
    assert usage.donation_record("  \n", "pasted", NOW) is None


@pytest.mark.parametrize("text,expected", [
    ("Email jane.doe@example.com today", "Email [email removed] today"),
    ("Call 980-555-0101 or (980) 555 0101", "Call [phone removed] or [phone removed]"),
    ("UK office: +44 20 7946 0958", "UK office: [phone removed]"),
    ("Experience 2024-2026, salary $120,000-150,000, 5+ years", "Experience 2024-2026, salary $120,000-150,000, 5+ years"),
])
def test_contact_scrubbing(text, expected):
    assert usage.scrub_contacts(text) == expected


def test_contact_scrubbing_stays_linear_on_a_long_unbroken_run():
    started = time.perf_counter()
    assert usage.scrub_contacts("x" * 100_000) == "x" * 100_000
    assert time.perf_counter() - started < 1.0  # unbounded patterns took ~30 s here


def test_email_addresses_are_normalised_and_checked():
    assert usage.normalise_email("  Jane.Doe@Example.COM ") == "jane.doe@example.com"
    with pytest.raises(ValueError, match="Enter a valid email address."):
        usage.normalise_email("jane@")
    with pytest.raises(ValueError, match="Enter an email address."):
        usage.normalise_email(None)


def test_days_back_lists_the_window_oldest_first():
    assert usage.days_back(NOW, 3) == ["2026-10-14", "2026-10-15", "2026-10-16"]


# ---- the report ----

def _event(day, event_type, visitor=None, **props):
    return {"day": day, "type": event_type, "props": props, **({"visitor": visitor} if visitor else {})}


def test_the_report_counts_unique_repeat_and_active_visitors():
    events = [
        _event("2026-10-15", "page_view", VISITOR, path="/", ref_host="www.linkedin.com", utm_source="linkedin"),
        _event("2026-10-15", "analysis_completed", VISITOR, skills=12),
        _event("2026-10-16", "page_view", VISITOR, path="/"),
        _event("2026-10-16", "analysis_completed", VISITOR, skills=9),
        _event("2026-10-16", "page_view", OTHER, path="/", ref_host="www.linkedin.com"),
        _event("2026-10-16", "page_view", None, path="/"),
        _event("2026-10-16", "download", OTHER, kind="md"),
        _event("2026-10-16", "analysis_failed", OTHER, status=422),
    ]
    skills = [{"skills": [["python", "must", "matched"], ["kafka", "nice", "gap"]]},
              {"skills": [["python", "must", "gap"]]}]
    report = usage.summarize(events, skills, waitlist=2, donations=1)
    assert report["daily"] == {
        "2026-10-15": {"page_views": 1, "unique_visitors": 1, "anonymous_views": 0, "analyses": 1, "failures": 0},
        "2026-10-16": {"page_views": 3, "unique_visitors": 2, "anonymous_views": 1, "analyses": 1, "failures": 1},
    }
    assert (report["unique_visitors"], report["repeat_visitors"]) == (2, 1)
    assert (report["visitors_with_an_analysis"], report["repeat_analysers"]) == (1, 1)
    assert report["downloads"] == {"md": 1}
    assert report["top_referrers"] == [("www.linkedin.com", 2)]
    assert report["top_utm_sources"] == [("linkedin", 1)]
    assert (report["waitlist"], report["donated_job_descriptions"], report["analyses_with_skill_stats"]) == (2, 1, 2)
    assert report["skills"] == [
        {"skill": "python", "requested": 2, "gap": 1, "unresolvable": 0, "matched": 1},
        {"skill": "kafka", "requested": 1, "gap": 1, "unresolvable": 0, "matched": 0},
    ]


def test_a_visitor_counts_on_every_day_they_did_something_not_only_page_view_days():
    events = [
        _event("2026-10-15", "page_view", VISITOR, path="/"),
        _event("2026-10-16", "analysis_completed", VISITOR, skills=4),  # tab left open past midnight
        _event("2026-10-16", "download", OTHER, kind="json"),  # page view fell outside the window
    ]
    report = usage.summarize(events, [], waitlist=0, donations=0)
    assert report["daily"]["2026-10-16"]["unique_visitors"] == 2
    assert report["daily"]["2026-10-16"]["anonymous_views"] == 0
    assert (report["unique_visitors"], report["repeat_visitors"]) == (2, 1)
    assert report["visitors_with_an_analysis"] == 1


# ---- the in-memory store ----

def test_memory_store_puts_queries_counts_and_deletes():
    store = MemoryStore()
    store.put({"pk": "WAITLIST", "sk": "b@example.com"})
    store.put({"pk": "WAITLIST", "sk": "a@example.com"})
    store.put({"pk": "EVENT#2026-10-16", "sk": "1"})
    assert [r["sk"] for r in store.query("WAITLIST")] == ["a@example.com", "b@example.com"]
    assert store.count("WAITLIST") == 2
    store.delete("WAITLIST", "a@example.com")
    store.delete("WAITLIST", "never-there@example.com")
    assert store.count("WAITLIST") == 1


def test_the_report_script_prints_counts_never_addresses_or_donated_text(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    import boto3

    spec = importlib.util.spec_from_file_location("usage_report", Path(__file__).parent.parent / "scripts" / "usage_report.py")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    store = MemoryStore()
    today = usage.days_back(datetime.now(timezone.utc), 1)[0]
    store.put({"pk": f"EVENT#{today}", "sk": "1", "day": today, "type": "page_view", "visitor": VISITOR, "props": {"path": "/"}})
    store.put({"pk": f"SKILLS#{today}", "sk": "2", "day": today, "skills": [["python", "must", "gap"]]})
    store.put({"pk": "WAITLIST", "sk": "jane.doe@example.com", "day": today})
    store.put({"pk": f"JD#{today}", "sk": "3", "day": today, "text": "Secret donated text"})
    monkeypatch.setattr(boto3.session, "Session", lambda **kwargs: None)  # no AWS profile in tests
    monkeypatch.setattr(report, "DynamoStore", lambda table, session: store)
    assert report.main(["--profile", "careerfit", "--days", "1"]) == 0
    printed = capsys.readouterr().out
    assert "unique visitors        1" in printed
    assert "waitlist (all time)    1" in printed and "donated JDs            1" in printed
    assert "python" in printed
    assert "jane.doe@example.com" not in printed and "Secret donated text" not in printed


def test_the_dynamodb_client_cannot_outlast_the_function_timeout():
    from careerfit.store import DynamoStore

    seen = {}

    class Session:
        def resource(self, name, config):
            seen.update(name=name, connect=config.connect_timeout, read=config.read_timeout, retries=config.retries)
            return type("Resource", (), {"Table": lambda self, table: table})()

    DynamoStore("careerfit-data", session=Session())
    assert seen == {"name": "dynamodb", "connect": 1, "read": 2, "retries": {"total_max_attempts": 2, "mode": "standard"}}


@pytest.mark.parametrize("days", ["0", "-3"])
def test_the_report_refuses_an_empty_window_before_touching_aws(days, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("usage_report", Path(__file__).parent.parent / "scripts" / "usage_report.py")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)

    def no_aws(*args, **kwargs):
        raise AssertionError("AWS was reached")

    monkeypatch.setattr(report, "DynamoStore", no_aws)
    with pytest.raises(SystemExit) as exit_info:
        report.main(["--profile", "careerfit", "--days", days])
    assert exit_info.value.code == 2
    assert "--days must be at least 1" in capsys.readouterr().err
