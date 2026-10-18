"""Usage records: what careerfit stores about its visitors, and the report built from it.

Pure functions only: no web framework, no AWS, no clock (callers pass `now`). The rules that keep
the records anonymous live here, next to each other, so a reviewer can check them in one place:

- Events come from an allow-list of types and properties. No free text is accepted, so nothing a
  visitor typed or uploaded can end up in an event.
- The visitor ID is a random UUID the browser made. careerfit never stores an IP address with it.
- Every record keeps the day only, never the time, so it can't be lined up with the 14-day access
  logs (which do hold IP addresses).
- Skill statistics and donated job descriptions carry no visitor ID at all.
"""

import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable

RETENTION_DAYS = 400  # usage events and skill statistics: about 13 months, then DynamoDB expires them
MAX_DONATION_CHARS = 100_000  # a DynamoDB item holds 400 KB; a job description is far shorter
CONSENT_WAITLIST = "v1: email me when careerfit's AI analysis launches"

_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")  # utm_* values
_HOST = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")
_VISITOR = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_EMAIL = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@.]{2,63}$")
# Bounded parts: an unbounded "+" makes a long unbroken run of text quadratic to scan.
_EMAIL_IN_TEXT = re.compile(r"[^\s@<>()\[\],;:\"']{1,64}@[^\s@<>()\[\],;:\"']{1,190}\.[A-Za-z]{2,63}")
# North American numbers ("(980) 555-0101", "980.555.0101", "+1 980 555 0101") and "+" international
# ones. Year ranges ("2024-2026") and salaries ("$120,000") don't match.
_PHONE_IN_TEXT = re.compile(
    r"(?<![\w+])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)"
    r"|(?<![\w+])\+\d{1,3}(?:[\s.-]?\d{2,4}){2,5}(?!\w)"
)

STATUSES = ("matched", "partial", "alternative_met", "gap", "unresolvable", "not_assessed")
_COUNT = ("count", 0, 10_000)
_MS = ("count", 0, 600_000)


def _enum(*values: str) -> tuple:
    return ("enum", frozenset(values))


# Every event type careerfit accepts, and the only properties each may carry.
EVENTS: dict[str, dict[str, tuple]] = {
    "page_view": {"path": _enum("/"), "ref_host": ("host",), "utm_source": ("token",),
                  "utm_medium": ("token",), "utm_campaign": ("token",)},
    "analysis_completed": {"perspective": _enum("candidate", "hiring_manager"), "jd_mode": _enum("file", "text"),
                           "resume_type": _enum("pdf", "txt"), "jd_type": _enum("pdf", "txt", "pasted"),
                           "skills": _COUNT, "must": _COUNT, "nice": _COUNT, "matched": _COUNT, "gaps": _COUNT,
                           "ambiguous": _COUNT, "ms": _MS, "donated": _enum("yes", "no")},
    "analysis_failed": {"status": ("count", 0, 599)},
    "download": {"kind": _enum("md", "json")},
    "filter": {"key": _enum("all", "gap", "unresolvable", "matched", "partial", "alternative_met", "not_assessed")},
    "expand": {"kind": _enum("clamp", "repeat")},
    "waitlist_joined": {},
}


def _valid(rule: tuple, value: Any) -> bool:
    kind = rule[0]
    if kind == "enum":
        return isinstance(value, str) and value in rule[1]
    if kind == "count":
        return isinstance(value, int) and not isinstance(value, bool) and rule[1] <= value <= rule[2]
    if kind == "token":
        return isinstance(value, str) and bool(_TOKEN.match(value))
    if kind == "host":
        return isinstance(value, str) and bool(_HOST.match(value))
    raise AssertionError(kind)


def valid_visitor(visitor: Any) -> bool:
    return isinstance(visitor, str) and bool(_VISITOR.match(visitor))


def parse_event(payload: Any) -> tuple[str, str | None, dict[str, Any]]:
    """(type, visitor, props) from a browser event, or ValueError. Unknown fields are refused, not dropped."""
    if not isinstance(payload, dict) or set(payload) - {"type", "visitor", "props"}:
        raise ValueError("An event is an object with type, visitor and props.")
    kind = payload.get("type")
    if not isinstance(kind, str) or kind not in EVENTS:  # a list or object would be unhashable: a 500, not a 400
        raise ValueError("Unknown event type.")
    visitor = payload.get("visitor")
    if visitor is not None and not valid_visitor(visitor):
        raise ValueError("The visitor ID must be a random UUID.")
    props = payload.get("props") or {}
    if not isinstance(props, dict):
        raise ValueError("props must be an object.")
    allowed = EVENTS[kind]
    for key, value in props.items():
        if key not in allowed or not _valid(allowed[key], value):
            raise ValueError(f"Property {key!r} is not allowed for {kind}.")
    return kind, visitor, dict(props)


def normalise_email(email: Any) -> str:
    if not isinstance(email, str):
        raise ValueError("Enter an email address.")
    email = email.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise ValueError("Enter a valid email address.")
    return email


def scrub_contacts(text: str) -> str:
    """Best effort: removes email addresses and phone numbers (a recruiter's, usually) from donated text."""
    return _PHONE_IN_TEXT.sub("[phone removed]", _EMAIL_IN_TEXT.sub("[email removed]", text))


# ---- records ----

def _day(now: datetime) -> str:
    return now.date().isoformat()


def _expires(now: datetime) -> int:
    # From the start of the day, not from `now`: an expiry exactly 400 days after the write would give
    # the write's time back to the second, and with it a way to line records up with the access logs.
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((day_start + timedelta(days=RETENTION_DAYS)).timestamp())


def event_record(kind: str, visitor: str | None, props: dict[str, Any], now: datetime) -> dict[str, Any]:
    record = {"pk": f"EVENT#{_day(now)}", "sk": str(uuid.uuid4()), "type": kind, "day": _day(now),
              "props": props, "expires_at": _expires(now)}
    if visitor:
        record["visitor"] = visitor
    return record


def skill_stats_record(observations: Iterable[tuple[str, str, str]], now: datetime) -> dict[str, Any]:
    """One analysis as (skill, must|nice, status) triples: careerfit's own skill names, no visitor ID."""
    return {"pk": f"SKILLS#{_day(now)}", "sk": str(uuid.uuid4()), "day": _day(now),
            "skills": [list(t) for t in observations], "expires_at": _expires(now)}


def waitlist_record(email: str, now: datetime) -> dict[str, Any]:
    return {"pk": "WAITLIST", "sk": email, "day": _day(now), "consent": CONSENT_WAITLIST}


def donation_record(text: str, source_format: str, now: datetime) -> dict[str, Any] | None:
    """A donated job description, contacts removed. None when it is too long to keep in one record."""
    if len(text) > MAX_DONATION_CHARS:  # checked first, so an oversized text is never scanned
        return None
    scrubbed = scrub_contacts(text).strip()
    if not scrubbed or len(scrubbed) > MAX_DONATION_CHARS:
        return None
    return {"pk": f"JD#{_day(now)}", "sk": str(uuid.uuid4()), "day": _day(now),
            "source_format": source_format, "chars": len(scrubbed), "text": scrubbed}


def days_back(now: datetime, days: int) -> list[str]:
    return [(now.date() - timedelta(days=n)).isoformat() for n in range(days - 1, -1, -1)]


# ---- the report ----

def summarize(events: Iterable[dict], skill_records: Iterable[dict], waitlist: int, donations: int) -> dict[str, Any]:
    """Traffic, activation and skill demand from stored records. Unique and repeat counts use visitor IDs
    from any event, not only page views; page views sent without one (Global Privacy Control, Do Not
    Track) are counted as anonymous views."""
    events = list(events)
    per_day: dict[str, Counter] = defaultdict(Counter)
    days_seen: dict[str, set] = defaultdict(set)
    analyses: Counter = Counter()
    referrers: Counter = Counter()
    sources: Counter = Counter()
    downloads: Counter = Counter()
    for e in events:
        day, kind, visitor, props = e["day"], e["type"], e.get("visitor"), e.get("props") or {}
        per_day[day][kind] += 1
        # Any identified event shows the visitor was there that day: a tab left open past midnight
        # sends analyses and downloads without a new page view.
        if visitor:
            days_seen[visitor].add(day)
        if kind == "page_view":
            if not visitor:
                per_day[day]["anonymous_views"] += 1
            if props.get("ref_host"):
                referrers[props["ref_host"]] += 1
            if props.get("utm_source"):
                sources[props["utm_source"]] += 1
        elif kind == "analysis_completed" and visitor:
            analyses[visitor] += 1
        elif kind == "download":
            downloads[props.get("kind", "?")] += 1
    daily = {}
    for day in sorted(per_day):
        visitors = {v for v, seen in days_seen.items() if day in seen}
        daily[day] = {"page_views": per_day[day]["page_view"], "unique_visitors": len(visitors),
                      "anonymous_views": per_day[day]["anonymous_views"],
                      "analyses": per_day[day]["analysis_completed"], "failures": per_day[day]["analysis_failed"]}
    visitors = set(days_seen)
    active = [v for v in visitors if analyses[v] > 0]
    skill_counts: dict[str, Counter] = defaultdict(Counter)
    total_analyses_with_stats = 0
    for record in skill_records:
        total_analyses_with_stats += 1
        for skill, _level, status in record["skills"]:
            skill_counts[skill]["requested"] += 1
            skill_counts[skill][status] += 1
    top = sorted(skill_counts.items(), key=lambda kv: (-kv[1]["requested"], kv[0]))
    return {
        "daily": daily,
        "unique_visitors": len(visitors),
        "repeat_visitors": sum(1 for v in visitors if len(days_seen.get(v, ())) >= 2),
        "visitors_with_an_analysis": len(active),
        "repeat_analysers": sum(1 for v in active if analyses[v] >= 2),
        "analyses_by_known_visitors": sum(analyses.values()),
        "downloads": dict(sorted(downloads.items())),
        "top_referrers": referrers.most_common(10),
        "top_utm_sources": sources.most_common(10),
        "waitlist": waitlist,
        "donated_job_descriptions": donations,
        "analyses_with_skill_stats": total_analyses_with_stats,
        # alternative_met: the JD accepted another skill the resume showed, so "requested" can be more
        # than gap + unresolvable + matched (partial and not_assessed are counted in requested only).
        "skills": [{"skill": s, "requested": c["requested"], "gap": c["gap"], "unresolvable": c["unresolvable"],
                    "matched": c["matched"], "alternative_met": c["alternative_met"]} for s, c in top[:25]],
    }
