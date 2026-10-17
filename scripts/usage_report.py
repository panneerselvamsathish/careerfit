"""Traffic, activation and skill demand from careerfit's DynamoDB table.

Runs with your own AWS credentials (the function's role can't read the table):

    uv run python scripts/usage_report.py --profile careerfit --region us-east-2 --days 30

Prints counts only. It never prints waitlist addresses or donated text; export those deliberately
with the AWS console or CLI when you need them.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from careerfit import usage
from careerfit.store import DynamoStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", required=True, help="your personal AWS profile, e.g. careerfit")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--table", default="careerfit-data")
    parser.add_argument("--days", type=int, default=30, help="how many days back, including today")
    parser.add_argument("--json", action="store_true", help="print the raw report as JSON")
    args = parser.parse_args(argv)
    if args.days < 1:  # before touching AWS: an empty window has nothing to report
        parser.error("--days must be at least 1")

    import boto3  # the report is owner tooling; only store.py and this script touch AWS

    store = DynamoStore(args.table, session=boto3.session.Session(profile_name=args.profile, region_name=args.region))
    days = usage.days_back(datetime.now(timezone.utc), args.days)
    events = [e for day in days for e in store.query(f"EVENT#{day}")]
    skills = [r for day in days for r in store.query(f"SKILLS#{day}")]
    donations = sum(store.count(f"JD#{day}") for day in days)
    report = usage.summarize(events, skills, waitlist=store.count("WAITLIST"), donations=donations)

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
        return 0
    print(f"careerfit usage, {days[0]} to {days[-1]} ({args.days} days)\n")
    print(f"{'day':<12}{'views':>7}{'unique':>8}{'anon':>6}{'analyses':>10}{'failed':>8}")
    for day, row in report["daily"].items():
        print(f"{day:<12}{row['page_views']:>7}{row['unique_visitors']:>8}{row['anonymous_views']:>6}"
              f"{row['analyses']:>10}{row['failures']:>8}")
    visitors = report["unique_visitors"]
    print(f"\nunique visitors        {visitors}")
    print(f"repeat visitors        {report['repeat_visitors']} (seen on 2 or more days)")
    active = report["visitors_with_an_analysis"]
    rate = f" ({active / visitors:.0%} of visitors)" if visitors else ""
    print(f"ran an analysis        {active}{rate}")
    print(f"ran 2 or more          {report['repeat_analysers']}")
    print(f"downloads              {report['downloads'] or 'none'}")
    print(f"waitlist (all time)    {report['waitlist']}")
    print(f"donated JDs            {report['donated_job_descriptions']}")
    if report["top_referrers"]:
        print("\nreferrers              " + ", ".join(f"{h} {n}" for h, n in report["top_referrers"]))
    if report["top_utm_sources"]:
        print("utm_source             " + ", ".join(f"{s} {n}" for s, n in report["top_utm_sources"]))
    if report["skills"]:
        print(f"\nmost requested skills ({report['analyses_with_skill_stats']} analyses)")
        print(f"{'skill':<28}{'asked':>6}{'gap':>6}{'ambig':>7}{'match':>7}")
        for row in report["skills"]:
            print(f"{row['skill']:<28}{row['requested']:>6}{row['gap']:>6}{row['unresolvable']:>7}{row['matched']:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
