import argparse
import csv
import itertools
import os
import re
import sqlite3
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

import monitor


def classify(results):
    def ok(t):
        return t in results and bool(results[t][0])

    def failed(t):
        return t in results and not results[t][0]

    down = set()
    if failed("router"):
        down.add("local")
    if ok("router") and failed("direct") and failed("web"):
        down.add("internet")
    if ok("direct") and failed("dns"):
        down.add("dns")
    if (ok("direct") or ok("web")) and ok("dns") and (failed("github_https") or failed("github_ssh")):
        down.add("github")
    return down


TARGETS = {
    "local": ("router",),
    "internet": ("direct", "web"),
    "dns": ("dns",),
    "github": ("github_https", "github_ssh"),
}


def find_outages(rounds, now):
    outages, blips, gaps = [], [], []
    runs = {}

    def close(kind, end):
        run = runs.pop(kind)
        if len(run) == 1:
            blips.append((kind, run[0][0]))
            return
        failed = [t for t in TARGETS[kind] if any(t in r and not r[t][0] for _, r in run)]
        errors = [r[t][1] for _, r in run for t in TARGETS[kind] if t in r and not r[t][0] and r[t][1]]
        start = run[0][0]
        outages.append({
            "type": kind,
            "start": start,
            "end": end,
            "length": int(((end or now) - start).total_seconds()),
            "failed_targets": failed,
            "sample_error": errors[0] if errors else None,
        })

    last = None
    for at, interval, results in rounds:
        if last and (at - last).total_seconds() > 3 * interval:
            gaps.append((last, at))
            for kind in list(runs):
                close(kind, last)
        down = classify(results)
        for kind in list(runs):
            if kind not in down:
                close(kind, at)
        for kind in down:
            runs.setdefault(kind, []).append((at, results))
        last = at
    if rounds:
        stale = (now - last).total_seconds() > 3 * rounds[-1][1]
        if stale:
            gaps.append((last, now))
        for kind in list(runs):
            close(kind, last if stale else None)
    outages.sort(key=lambda o: o["start"])
    blips.sort(key=lambda b: b[1])
    return outages, blips, gaps


def load_rounds(conn, since):
    sql = "SELECT round_at, interval_s, target, ok, error FROM checks"
    args = ()
    if since:
        sql += " WHERE round_at >= ?"
        args = ((since - timedelta(days=1)).astimezone(timezone.utc).isoformat(timespec="seconds"),)
    rows = conn.execute(sql + " ORDER BY round_at", args).fetchall()
    rounds = []
    for at, group in itertools.groupby(rows, key=lambda r: r[0]):
        group = list(group)
        rounds.append((
            datetime.fromisoformat(at).astimezone(timezone.utc),
            group[0][1],
            {t: (ok, err) for _, _, t, ok, err in group},
        ))
    return rounds


def parse_since(text, now):
    m = re.fullmatch(r"(\d+)([hd])", text)
    if m:
        n = int(m.group(1))
        return now - (timedelta(hours=n) if m.group(2) == "h" else timedelta(days=n))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?", text):
        raise ValueError(f"bad --since value: {text}")
    return datetime.fromisoformat(text).astimezone().astimezone(timezone.utc)


def fmt_time(dt):
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def fmt_length(seconds):
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}h{m}m{s}s"
    if m:
        return f"{m}m{s}s"
    return f"{s}s"


def format_report(outages, blips, gaps, now):
    outages = sorted(outages, key=lambda o: o["start"])
    rows = [[
        o["type"],
        fmt_time(o["start"]),
        fmt_time(o["end"]) if o["end"] else "ongoing",
        fmt_length(o["length"]),
        " ".join(o["failed_targets"]),
        "".join(c if c.isprintable() else "?" for c in o["sample_error"] or ""),
    ] for o in outages]
    gap_rows = [["NO DATA", fmt_time(a), fmt_time(b), fmt_length((b - a).total_seconds()), "", ""] for a, b in gaps]
    header = ["TYPE", "START", "END", "LENGTH", "FAILED TARGETS", "SAMPLE ERROR"]
    table = ([header] + rows if rows else []) + gap_rows
    widths = [max(len(r[i]) for r in table) for i in range(6)] if table else []

    def line(r):
        return "  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip()

    out = [line(r) for r in [header] + rows] if rows else ["No outages."]
    if gap_rows:
        out += [""] + [line(r) for r in gap_rows]
    down = {k: sum(o["length"] for o in outages if o["type"] == k) for k in TARGETS}
    no_data = sum((b - a).total_seconds() for a, b in gaps)
    out += ["", (
        f"Outages: {len(outages)} | Down time: "
        + ", ".join(f"{k} {fmt_length(v)}" for k, v in down.items())
        + f" | Blips: {len(blips)} | No data: {fmt_length(no_data)}"
    )]
    return "\n".join(out) + "\n"


def write_csv(outages, path, now):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["type", "start", "end", "length_seconds", "failed_targets", "sample_error"])
        for o in outages:
            w.writerow([
                o["type"],
                fmt_time(o["start"]),
                fmt_time(o["end"]) if o["end"] else "ongoing",
                o["length"],
                " ".join(o["failed_targets"]),
                o["sample_error"] or "",
            ])


def main(argv=None, now=None):
    parser = argparse.ArgumentParser(prog="report.py")
    parser.add_argument("--since")
    parser.add_argument("--db", default=str(monitor.default_db_path()))
    parser.add_argument("--csv")
    args = parser.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    since = None
    if args.since:
        try:
            since = parse_since(args.since, now)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
    if not os.path.exists(args.db):
        print(f"no data file: {args.db}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(f"file:{urllib.parse.quote(args.db)}?mode=ro", uri=True)
    try:
        rounds = load_rounds(conn, since)
    finally:
        conn.close()
    outages, blips, gaps = find_outages(rounds, now)
    if since:
        outages = [o for o in outages if (o["end"] or now) > since]
        blips = [b for b in blips if b[1] >= since]
        gaps = [g for g in gaps if g[1] > since]
    sys.stdout.write(format_report(outages, blips, gaps, now))
    if args.csv:
        write_csv(outages, args.csv, now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
