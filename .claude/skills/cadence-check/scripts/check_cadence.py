# -*- coding: utf-8 -*-
"""Deterministic cadence analysis for scraper.yml on GitHub Actions.

Fetches the last 20 runs via the GitHub REST API (no `gh` CLI needed —
the repo is public; set GITHUB_TOKEN/GH_TOKEN to raise the rate limit),
computes gaps between scheduled runs, and prints a compact report.
The SKILL.md asks Claude to interpret this output — the arithmetic lives
here so it is never done in-model.
"""
import os
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone

import requests

TARGET_GAP_MIN = 1        # CLAUDE.md rule #1
STALE_WINDOW_MIN = 30     # articles older than this die unprocessed
BROKEN_AFTER_MIN = 120    # no scheduled run for 2h => BROKEN
WORKFLOW = "scraper.yml"


def repo_slug():
    out = subprocess.run(["git", "remote", "get-url", "origin"],
                         capture_output=True, text=True, timeout=15)
    if out.returncode != 0:
        print(f"ERROR: cannot read git remote: {out.stderr.strip()}")
        sys.exit(1)
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", out.stdout.strip())
    if not m:
        print(f"ERROR: origin is not a GitHub remote: {out.stdout.strip()}")
        sys.exit(1)
    return m.group(1)


def fetch_runs(slug):
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{slug}/actions/workflows/{WORKFLOW}/runs"
    resp = requests.get(url, headers=headers, params={"per_page": 20}, timeout=30)
    if resp.status_code != 200:
        print(f"ERROR: GitHub API {resp.status_code} for {slug}: {resp.text[:200]}")
        sys.exit(1)
    return resp.json().get("workflow_runs", [])


def main():
    slug = repo_slug()
    runs = fetch_runs(slug)
    now = datetime.now(timezone.utc)
    print(f"repo: {slug}")
    print(f"now_utc: {now:%Y-%m-%d %H:%M:%S}")
    print(f"total_runs_fetched: {len(runs)}")

    for r in runs:
        r["dt"] = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))

    sched = sorted((r for r in runs if r["event"] == "schedule"), key=lambda r: r["dt"])
    manual = [r for r in runs if r["event"] != "schedule"]
    print(f"scheduled_runs: {len(sched)} | other_event_runs: {len(manual)}")

    failures = [r for r in runs if r["conclusion"] not in ("success", None)]
    if failures:
        print("non_success_runs:")
        for r in failures:
            print(f"  - {r['dt']:%m-%d %H:%M} {r['event']} -> {r['conclusion']}")
    else:
        print("non_success_runs: none")

    if len(sched) < 2:
        print("verdict: CADENCE BROKEN (fewer than 2 scheduled runs in window)")
        return

    gaps = [
        (b["dt"] - a["dt"]).total_seconds() / 60
        for a, b in zip(sched, sched[1:])
    ]
    since_last = (now - sched[-1]["dt"]).total_seconds() / 60
    over_stale = [g for g in gaps if g > STALE_WINDOW_MIN]

    print(f"gap_minutes_median: {statistics.median(gaps):.1f}")
    print(f"gap_minutes_max: {max(gaps):.1f}")
    print(f"gap_minutes_min: {min(gaps):.1f}")
    print(f"gaps_over_stale_window: {len(over_stale)}/{len(gaps)}")
    print(f"minutes_since_last_scheduled_run: {since_last:.1f}")
    # share of timeline NOT covered within the stale window: time beyond the
    # first 30 min of each gap is dead air where articles expire unprocessed
    window = (sched[-1]["dt"] - sched[0]["dt"]).total_seconds() / 60
    dead = sum(max(0.0, g - STALE_WINDOW_MIN) for g in gaps)
    if window > 0:
        print(f"timeline_uncovered_pct: {100 * dead / window:.0f}%")

    if since_last > BROKEN_AFTER_MIN:
        verdict = "CADENCE BROKEN"
    elif over_stale or since_last > STALE_WINDOW_MIN:
        verdict = "CADENCE DEGRADED"
    else:
        verdict = "CADENCE OK"
    print(f"verdict: {verdict} (target={TARGET_GAP_MIN}min, stale_window={STALE_WINDOW_MIN}min)")


if __name__ == "__main__":
    main()
