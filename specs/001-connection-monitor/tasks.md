---
description: "Tasks for the connection monitor"
---

# Tasks: Connection Monitor

**Input**: `specs/001-connection-monitor/` (plan.md, spec.md, research.md, data-model.md,
contracts/cli.md, quickstart.md)

**Tests**: required (Constitution III). Each test task comes before its build task and MUST fail
first. No test may use the real network.

**Paths**: repo root `/home/hyuse/Desktop/VeentApps/InternetTester/`. All paths below are
relative to it. Run tests with `python3 -m unittest -v`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: touches no file used by tasks that run at the same time. No task carries [P] here.
- Lanes: the monitor lane (`monitor.py`, `test_monitor.py`: US1, US4) and the report lane
  (`report.py`, `test_report.py`: US2, US3) share no file, so the two lanes run in parallel
  after T003. Inside one lane, tasks run in order.

---

## Phase 1: Setup

- [X] T001 Add the line `__pycache__/` to `.gitignore`.

---

## Phase 2: Foundational (blocks all stories)

- [X] T002 Write failing tests in `test_monitor.py` (FR-004, FR-005, FR-016, FR-017):
  - `setUpModule` patches `socket.socket.connect`, `socket.socket.sendto`,
    `socket.create_connection`, and `socket.getaddrinfo` to raise
    `RuntimeError("real network in test")`; `tearDownModule` stops the patches.
  - `open_db(path)` on a path in a new temp folder creates the folder, the file, table `checks`
    and index `checks_round_at` exactly as in data-model.md. Calling it again on the same file
    keeps existing rows (FR-017).
  - `save_result(conn, round_at, interval_s, result)` with
    `result = (target, check_type, ok, latency_ms, error)` inserts one row and commits: a second
    `sqlite3.connect` to the same file sees the row (FR-005).
  - Column rules: `ok` is `CHECK (ok IN (0, 1))`; inserting `ok=2` raises
    `sqlite3.IntegrityError`.
  - `default_db_path()` returns `$XDG_DATA_HOME/internettester/checks.db` when the variable is
    set, else `~/.local/share/internettester/checks.db`.
  - Source scan: neither `monitor.py` nor `report.py` matches `\bDROP\s+TABLE\b` or
    `\bDELETE\s+FROM\b` (`re.IGNORECASE`) (FR-017).
- [X] T003 Implement `default_db_path`, `open_db`, `save_result` in `monitor.py` so T002 passes.
  Schema verbatim from data-model.md. `open_db` does `mkdir(parents=True, exist_ok=True)` on the
  parent folder. Create an empty `report.py` so the source scan can read it.

**Checkpoint**: `python3 -m unittest -v` passes.

---

## Phase 3: User Story 1 - Record every check while left running (P1) MVP

**Goal**: every interval, six checks run and each result is committed.

**Independent Test**: quickstart Q2.

### Tests first, then build

- [ ] T004 [US1] Write failing check tests in `test_monitor.py` (FR-002, FR-004, FR-016). Use
  `unittest.mock.patch` fakes only:
  - `default_gateway(route_path)` on a temp file holding a `/proc/net/route` sample with a
    `00000000` destination and gateway `0100D20A` returns `"10.210.0.1"`; on a sample with no
    `00000000` line returns `None`.
  - `check_router(timeout)` with `default_gateway` returning `None` raises an error whose text
    becomes `NoRoute: no default route`.
  - `check_router(timeout)` with a fake ICMP socket: reply whose first byte (type) is 0 →
    success; reply with another type (for example 3) → raises; `recvfrom` raising
    `TimeoutError` → raises.
  - `run_check(target, check_type, fn, timeout)` returns `(target, check_type, 1, latency_ms, None)`
    when `fn` returns, with `latency_ms >= 0`; returns `(target, check_type, 0, None,
    "<ExceptionClassName>: <message>")` when `fn` raises, for example
    `"gaierror: [Errno -3] Temporary failure in name resolution"` and `"TimeoutError: timed out"`.
  - `check_https(host, timeout)` with a fake `http.client.HTTPSConnection`: status 200 and 301
    succeed, status 503 raises with text `HTTPStatus: 503 Service Unavailable`; the request is
    `HEAD /`.
  - `check_ssh(timeout)` with a fake socket: banner `b"SSH-2.0-x\r\n"` succeeds, `b"HTTP/1.1"`
    raises.
  - `check_direct(timeout)` connects to `("1.1.1.1", 443)`; `check_dns(timeout)` calls
    `getaddrinfo("github.com", 443, ...)`.
  - `TARGETS` holds exactly these `(target, check_type)` pairs in this order:
    `router icmp`, `dns dns`, `direct tcp`, `web https` (google.com), `github_https https`
    (github.com), `github_ssh ssh` (github.com:22). No other host is contacted (FR-016).
- [ ] T005 [US1] Implement `default_gateway`, `check_router` (unprivileged ICMP
  `SOCK_DGRAM, IPPROTO_ICMP`, echo request type 8, wait for a reply), `check_dns`,
  `check_direct`, `check_https`, `check_ssh`, `run_check`, and `TARGETS` in `monitor.py`
  (research R1-R7) so T004 passes.
- [ ] T006 [US1] Write failing round tests in `test_monitor.py` (FR-003, FR-004, FR-005, FR-006).
  Use fake target lists, not `TARGETS`:
  - `run_round(conn, interval_s, targets, timeout=10, deadline=12)` saves one row per target,
    all with the same `round_at` (UTC, `isoformat(timespec="seconds")`, ends with `+00:00`) and
    the given `interval_s`.
  - A fake check that raises `ValueError("boom")` is saved as `ok=0`,
    `error="ValueError: boom"`, and the other targets are still saved (FR-006).
  - With `deadline=0.2`, a fake check that blocks on a `threading.Event` is saved as `ok=0`,
    `error="TimeoutError: no result in 10s"`, the others are saved, and `run_round` returns in
    under 1 s (FR-003). Set the event in cleanup.
  - Each row is committed before `run_round` returns (read back with a second connection).
  - A `save_result` that raises `sqlite3.OperationalError` for one row: the error is written to
    stderr starting with `write failed:`, the other rows are saved, nothing is raised.
- [ ] T007 [US1] Implement `run_round` in `monitor.py` so T006 passes: one
  `ThreadPoolExecutor(max_workers=len(targets))`, `as_completed(..., timeout=deadline)`, save and
  commit each result as it arrives, save unfinished ones as timeouts, then
  `shutdown(wait=False, cancel_futures=True)` (research R8, R11).
- [ ] T008 [US1] Write failing schedule and CLI tests in `test_monitor.py`
  (FR-001, FR-007):
  - `run_forever(conn, interval_s, rounds, round_fn, clock, sleep)` with a fake clock and
    interval 30 (rule R10: after each round `next_at = max(next_at + interval, now)`):
    three fast rounds start at exactly 0, 30, 60.
  - First round (at 0) takes 45 s on the fake clock, later rounds are fast: rounds start at
    exactly 0, 45, 75 (sleep 0 before the second round). `round_fn` is called exactly `rounds`
    times. No round runs twice for a failed check (FR-007).
  - Parser through `build_parser()`: `parse_args(["run", "--interval", "14"])` raises
    `SystemExit` with code 2; `"--interval", "15"` is accepted; default interval is 30.
  - Every `main(["run", ...])` test passes a temp `--db` and patches `run_forever`.
  - `main(["run", "--db", path])` with `run_forever` patched to raise `KeyboardInterrupt`
    returns 0.
  - Lock: with the data file already `flock`ed by the test, `main(["run", "--db", path])`
    prints `already running: <path>` to stderr and returns 1.
  - Rows saved before a start (first `main` run) still exist after a second `main` run on the
    same file, both with the lock taken and not taken.
- [ ] T009 [US1] Implement `run_forever`, `main` with `run` subcommand (argparse, `--interval`
  int default 30 min 15, `--db` default `default_db_path()`, built by `build_parser()`), the
  lock guard (open the data file with `os.open(path, os.O_RDWR | os.O_CREAT)`, never mode
  `"w"`, then `fcntl.flock(fd, LOCK_EX | LOCK_NB)`), `KeyboardInterrupt` → return 0, and
  `if __name__ == "__main__": sys.exit(main())` in `monitor.py` so T008 passes
  (research R9, R10, R17).
- [ ] T010 [US1] Live check: run quickstart Q2 with `monitor.py`. Record the observed rows in the
  task notes. Also measure the github.com TTL as the system resolver serves it
  (`resolvectl query github.com` twice, a few seconds apart, or `dig github.com`) and write the
  number in `specs/001-connection-monitor/research.md` R3. No code change.

**Checkpoint**: US1 works alone. Data can be read with `sqlite3`.

---

## Phase 4: User Story 2 - See an outage report (P2)

**Goal**: `report.py` prints outages, gaps, and a summary.

**Independent Test**: quickstart Q3, and T013 fixtures.

- [ ] T011 [US2] Write failing tests in `test_report.py` for `classify(results)` (FR-008).
  `results` maps target → `(ok, error)`; missing targets are unknown. One case per row of the
  "Down states per round" table in data-model.md, plus:
  - all six fail → `{"local"}` only (router failed, so internet is not down).
  - router ok, direct fail, web fail, dns fail → `{"internet"}` (not dns).
  - router ok, direct ok, dns fail, web fail, github_https fail, github_ssh fail → `{"dns"}`
    only, not `github` (FR-008, plan D1).
  - router ok, direct ok, web ok, dns ok, github_ssh fail → `{"github"}`.
  - empty dict (crash mid-round) → `set()`.
- [ ] T012 [US2] Implement `classify` in `report.py` so T011 passes. The github rule is
  `(direct ok or web ok) and dns ok and (github_https failed or github_ssh failed)`, where "ok" and
  "failed" both require the target to be present in `results`.
- [ ] T013 [US2] Write failing tests in `test_report.py` for
  `find_outages(rounds, now)` → `(outages, blips, gaps)` (FR-009, FR-010, FR-011, edge cases).
  `rounds` is a time-sorted list of `(round_at_utc_datetime, interval_s, results)`. Outage =
  dict with `type, start, end (None if ongoing), length, failed_targets, sample_error`.
  `blips` = list of `(type, round_at)`. `gaps` = list of `(start, end)`.
  - 3 rounds router failed then 1 ok → one `local` outage, start = round 1, end = round 4,
    length = 90 s, `failed_targets == ["router"]`, sample error = first router error.
  - 2 rounds internet down then ok → one `internet` outage, failed targets `["direct", "web"]`.
  - ok, 1 down, ok → no outage, one blip (FR-010).
  - 2 down rounds, then a 200 s gap (interval 30), then ok → outage ends at round 2, one gap
    `(round 2, round 3)` (FR-011).
  - 1 down round then a gap → blip, no outage.
  - last 2 rounds down, `now` = last round + 30 s → ongoing outage, `end is None`,
    length = now − start.
  - last 2 rounds down, `now` = last round + 1 h → outage ends at last round, trailing gap
    `(last round, now)`.
  - github down rounds 1-2, then internet down rounds 3-5, then ok → two outages back to back:
    `github` ends at round 3, `internet` starts at round 3, sorted by start.
  - interval 60 rows with 150 s spacing → no gap (150 ≤ 180).
- [ ] T014 [US2] Implement `find_outages` in `report.py` so T013 passes (data-model.md state
  table, research R15).
- [ ] T015 [US2] Write failing tests in `test_report.py` (FR-012, FR-013). `setUp` sets
  `os.environ["TZ"] = "America/New_York"` and calls `time.tzset()`; `tearDown` restores the old
  value and calls `time.tzset()` again:
  - `load_rounds(conn, since)` on a DB built with `monitor.open_db` + `monitor.save_result`
    groups rows into rounds sorted by `round_at`; with `since` it skips rows older than
    `since - 1 day`.
  - `parse_since(text, now)`: `"2026-10-05"` → local midnight as UTC; `"2026-10-05T14:02"` →
    that local time as UTC; `"6h"` → now − 6 h; `"7d"` → now − 7 days; `"yesterday-ish"` raises
    `ValueError`.
  - `format_report(outages, blips, gaps, now)` matches the layout in contracts/cli.md: header,
    one line per outage sorted by start, `ongoing` end, lengths like `4m30s`, local times,
    `NO DATA` lines, summary line with outage count, down time per type for all four types,
    blip count, total no-data time. No outages → `No outages.`
  - `main(["--db", path, "--since", "2099-01-01"], now=...)` prints `No outages.` and returns
    0. An outage that started before `since` and ended after it is shown (overlap rule).
  - `--since` filters blips and gaps by the same rule: a blip before `since` is not counted; a
    gap that ends before `since` is not shown; a gap that starts before `since` and ends after
    it is shown.
  - `format_report` replaces non-printable characters in `sample_error` (for example `\x1b`,
    `\n`) with `?`; the outage dict passed in is not changed.
  - `main(["--db", missing_path])` prints `no data file: <path>` to stderr, returns 1, and does
    not create the file.
  - `main(["--since", "bad"])` returns 2.
- [ ] T016 [US2] Implement `load_rounds`, `parse_since`, `format_report`, `main` and
  `if __name__ == "__main__": sys.exit(main())` in `report.py` so T015 passes. Open the DB with
  `sqlite3.connect(f"file:{urllib.parse.quote(path)}?mode=ro", uri=True)` after an
  `os.path.exists` check. Default `--db` from `monitor.default_db_path` by import. Non-printable
  characters in `sample_error` become `?` in the text output only.

**Checkpoint**: report works on a DB written by US1.

---

## Phase 5: User Story 3 - Export outages to a spreadsheet (P3)

**Goal**: `report.py --csv FILE` writes the report's outage list.

**Independent Test**: quickstart Q4.

- [ ] T017 [US3] Write failing tests in `test_report.py` (FR-014). Same `TZ` =
  `America/New_York` setUp/tearDown as T015:
  - `write_csv(outages, path, now)` writes header
    `type,start,end,length_seconds,failed_targets,sample_error` and one row per outage, `end`
    = `ongoing` for an ongoing outage, local `YYYY-MM-DD HH:MM:SS` times, integer seconds,
    space-separated targets; a sample error with a comma round-trips through `csv.reader`.
  - `main(["--db", path, "--since", X, "--csv", out])` writes the same outages (same order,
    same count) that the printed report lists for the same `--since`.
- [ ] T018 [US3] Implement `write_csv` and the `--csv` option in `report.py` so T017 passes.

---

## Phase 6: User Story 4 - Runs on its own at login (P4)

**Goal**: `monitor.py install` sets up a systemd user service.

**Independent Test**: quickstart Q5.

- [ ] T019 [US4] Write failing tests in `test_monitor.py` (FR-015):
  - `unit_text(python, script, interval, db)` equals the unit in contracts/cli.md with the
    given values: `ExecStart` quoted absolute paths, `Restart=always`, `RestartSec=10`,
    `WantedBy=default.target`.
  - `main(["install", "--db", path])` with `HOME` set to a temp folder and `subprocess.run`
    patched: writes `<HOME>/.config/systemd/user/internettester.service`, calls
    `["systemctl", "--user", "daemon-reload"]` then
    `["systemctl", "--user", "enable", "--now", "internettester.service"]`, returns 0; returns
    the non-zero code when a call fails.
- [ ] T020 [US4] Implement `unit_text` and the `install` subcommand in `monitor.py` so T019
  passes (research R18). Use `sys.executable` and `os.path.abspath(__file__)`.
- [ ] T021 [US4] Live check: run quickstart Q5 (install, kill, restart within 1 minute, login
  start). Record results in the task notes. Not a code change.

---

## Phase 7: Polish

- [ ] T022 Negative control for the network guard: add a temporary test to `test_monitor.py`
  that calls `monitor.check_direct(1)` under the guard, run it, and confirm it fails with
  `RuntimeError: real network in test`. Remove the temporary test. Then run
  `python3 -m unittest -v` (all pass) and quickstart Q3, Q4. Record output.
- [ ] T023 SC-002 timing (measurement, no test pair): in a heredoc script, create
  `/tmp/it-week.db` with `monitor.open_db` and insert one week of fake rows ending now
  (6 targets × 2880 rounds/day × 7 days ≈ 121k rows, interval 30, mix of ok and failed rows)
  with `executemany` and one commit. Then run
  `time python3 report.py --db /tmp/it-week.db --since 7d`. Must finish in under 10 s.
  Record the time in the task notes. Delete `/tmp/it-week.db`. No repo file is added.

---

## Dependencies & Execution Order

- T001 → T002 → T003 → both lanes.
- Monitor lane (in order): T004 → T005 → T006 → T007 → T008 → T009 → T010 → T019 → T020 → T021.
- Report lane (in order, parallel to the monitor lane): T011 → T012 → T013 → T014 → T015 → T016
  → T017 → T018.
- T022 after both lanes. T023 after T016.
- US2 needs data to be useful live (Q3 uses the Q2 file), but its tests need only T003.

## Parallel Example

```text
After T003:
  Agent A: T004..T010 (monitor.py, test_monitor.py)
  Agent B: T011..T018 (report.py, test_report.py)
```

## Implementation Strategy

1. MVP: T001-T010. The monitor records evidence that can be read with `sqlite3`.
2. Add US2 (report), then US3 (CSV), then US4 (install). Each ends with its quickstart step.

## FR → test → build

| FR | Test | Build |
|---|---|---|
| FR-001 | T008 | T009 |
| FR-002 | T004 | T005 |
| FR-003 | T006 | T007 |
| FR-004 | T002, T004, T006 | T003, T005, T007 |
| FR-005 | T002, T006 | T003, T007 |
| FR-006 | T006 | T007 |
| FR-007 | T008 | T009 |
| FR-008 | T011 | T012 |
| FR-009 | T013 | T014 |
| FR-010 | T013 | T014 |
| FR-011 | T013 | T014 |
| FR-012 | T015 | T016 |
| FR-013 | T015 | T016 |
| FR-014 | T017 | T018 |
| FR-015 | T019 | T020 |
| FR-016 | T002, T004 | T003, T005 |
| FR-017 | T002 | T003 |

SC-002 is measured by T023. SC-001 by T010 + T022 (Q2, Q3). SC-003, SC-004 are manual (Q5, T021).
