# -*- coding: utf-8 -*-
"""Deterministic cadence analysis for the TWO-SHIFT CryptoSentinel production.

Day shift  = local Task Scheduler loop (storage/local_cron.log).
Night shift = GH Actions scraper.yml, one run = a ~5h30 internal loop ("shift").

Old versions measured gaps between *creation times* of scheduled GH runs —
meaningless under the shift model (one run covers up to 350 min) and blind to
the local shift. This version measures timeline COVERAGE: every activity
interval [start, end] from either shift serves price-move signals observed from
start - STALE_WINDOW up to end. Dead air = timeline outside that reach.

The SKILL.md asks Claude to interpret this output — the arithmetic lives
here so it is never done in-model.
"""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

STALE_WINDOW_MIN = 30     # signals older than this expire unsent
BROKEN_AFTER_MIN = 120    # no activity from EITHER shift for 2h => BROKEN
WINDOW_HOURS = 24         # analysis window
VERDICT_RECENT_HOURS = 6  # gaps older than this are history, not the verdict
WORKFLOW = "scraper.yml"

LOCAL_DONE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} - INFO - === Pipeline .*?"
    r"(\d+(?:\.\d+)?)s ==="
)


def repo_root():
    # cwd khi skill chạy là repo root; fallback theo vị trí file
    for cand in (Path.cwd(), Path(__file__).resolve().parents[4]):
        if (cand / ".git").exists():
            return cand
    return Path.cwd()


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
    resp = requests.get(url, headers=headers, params={"per_page": 30}, timeout=30)
    if resp.status_code != 200:
        print(f"ERROR: GitHub API {resp.status_code} for {slug}: {resp.text[:200]}")
        sys.exit(1)
    return resp.json().get("workflow_runs", [])


def iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def gh_intervals(runs, now):
    """[(start, end, label)] — in-progress run is open-ended: end = now."""
    out = []
    for r in runs:
        start = iso(r.get("run_started_at") or r["created_at"])
        if r["status"] == "completed":
            end = iso(r["updated_at"])
        else:
            end = now
        out.append((start, end, f"gh/{r['event']}"))
    return out


def local_intervals(root, now):
    """Parse completion lines; each cycle covers [end - duration, end].
    Timestamps in the log are machine-local time -> convert to UTC."""
    log = root / "storage" / "local_cron.log"
    if not log.exists():
        return None, []
    out = []
    with open(log, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LOCAL_DONE_RE.match(line)
            if not m:
                continue
            end_local = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            end = end_local.astimezone(timezone.utc)  # naive => system local tz
            start = end - timedelta(seconds=float(m.group(2)))
            out.append((start, end, "local"))
    return log, out


def merge(intervals):
    merged = []
    for s, e, _ in sorted(intervals):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def main():
    slug = repo_slug()
    root = repo_root()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=WINDOW_HOURS)
    runs = fetch_runs(slug)

    print(f"repo: {slug}")
    print(f"now_utc: {now:%Y-%m-%d %H:%M:%S}")
    print(f"window_hours: {WINDOW_HOURS}")

    sched = [r for r in runs if r["event"] == "schedule"]
    print(f"gh_runs_fetched: {len(runs)} (schedule: {len(sched)}, "
          f"other: {len(runs) - len(sched)})")

    active = [r for r in runs if r["status"] != "completed"]
    if active:
        r = active[0]
        elapsed = (now - iso(r["run_started_at"])).total_seconds() / 60
        print(f"gh_shift_active: yes - {r['event']} run started "
              f"{iso(r['run_started_at']):%H:%M} UTC, elapsed {elapsed:.0f} min "
              f"(cap 350)")
    else:
        print("gh_shift_active: no")

    log, loc = local_intervals(root, now)
    loc_window = [iv for iv in loc if iv[1] >= window_start]
    if log is None:
        print("local_log: NOT FOUND (storage/local_cron.log) - day shift invisible")
    else:
        print(f"local_log: {len(loc_window)} completed cycles in window")
        if loc:
            last_end = max(iv[1] for iv in loc)
            print(f"local_last_cycle_end: {last_end:%Y-%m-%d %H:%M} UTC "
                  f"({(now - last_end).total_seconds() / 60:.1f} min ago)")

    intervals = [iv for iv in gh_intervals(runs, now) + loc if iv[1] >= window_start]
    if not intervals:
        print("verdict: CADENCE BROKEN (no activity from either shift in window)")
        return

    merged = merge(intervals)
    last_end = max(e for _, e in merged)
    since_last = max(0.0, (now - last_end).total_seconds() / 60)
    print(f"minutes_since_last_activity: {since_last:.1f}"
          + (" (shift running now)" if since_last == 0 else ""))

    # Dead air: a publish at time t is served if activity starts within
    # [t, t+stale]; so each merged interval reaches stale-window back in time.
    stale = timedelta(minutes=STALE_WINDOW_MIN)
    reach = merge([(max(s - stale, window_start), e, "") for s, e in merged])
    gaps, cursor = [], window_start
    for s, e in reach:
        if s > cursor:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if now > cursor and (now - cursor) > stale:
        # tail beyond reach: only the part older than the stale window is lost
        gaps.append((cursor, now - stale))

    dead = sum((e - s).total_seconds() / 60 for s, e in gaps)
    total = (now - window_start).total_seconds() / 60
    coverage = 100 * (1 - dead / total)
    print(f"coverage_pct_window: {coverage:.0f}%")
    if gaps:
        print(f"dead_air_gaps ({len(gaps)}, signals observed here died stale):")
        for s, e in gaps:
            print(f"  - {s:%m-%d %H:%M} -> {e:%m-%d %H:%M} UTC "
                  f"({(e - s).total_seconds() / 60:.0f} min)")
    else:
        print("dead_air_gaps: none")

    failures = [r for r in runs if r["conclusion"] not in ("success", None)]
    if failures:
        print("non_success_runs:")
        for r in failures:
            print(f"  - {iso(r['created_at']):%m-%d %H:%M} {r['event']} "
                  f"-> {r['conclusion']}")
    else:
        print("non_success_runs: none")

    recent_cut = now - timedelta(hours=VERDICT_RECENT_HOURS)
    recent_gaps = [g for g in gaps if g[1] > recent_cut]
    if since_last > BROKEN_AFTER_MIN:
        verdict = "CADENCE BROKEN"
    elif since_last > STALE_WINDOW_MIN or recent_gaps:
        verdict = "CADENCE DEGRADED"
    else:
        verdict = "CADENCE OK"
    # Verdict = "bây giờ có đang chạy không" (scope hẹp). "Hôm nay có miss
    # không" là câu hỏi KHÁC — phải in kèm ngay trên cùng một dòng để người
    # chỉ đọc dòng cuối không bị verdict OK ru ngủ khi coverage 24h thấp.
    miss_note = (f"{len(gaps)} miss-window(s), {dead:.0f} min dead air"
                 if gaps else "no miss windows")
    print(f"verdict: {verdict} (scope=last {VERDICT_RECENT_HOURS}h) | "
          f"last {WINDOW_HOURS}h: coverage {coverage:.0f}%, {miss_note}")


if __name__ == "__main__":
    main()
