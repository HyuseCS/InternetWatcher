# Implementation Plan: Connection Monitor

**Branch**: `001-connection-monitor` | **Date**: 2026-10-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-connection-monitor/spec.md`

## Summary

A background monitor runs six fixed checks (router, DNS, direct address, google.com HTTPS,
github.com HTTPS, github.com SSH) every 30 s, in parallel with a 10 s limit each, and commits
each result to a local SQLite file. A report script reads the file, classifies each round into
four down states, derives outages, blips, and no-data gaps, prints them, and can write the same
outage list to CSV. An `install` command adds a systemd user service that starts at login and
restarts after a crash. Details: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11 or later (this machine: 3.14.7)

**Primary Dependencies**: none. stdlib: `socket`, `ssl` (via `http.client`), `http.client`,
`sqlite3`, `concurrent.futures`, `fcntl`, `argparse`, `csv`, `datetime`, `subprocess`,
`unittest`, `unittest.mock`

**Storage**: one SQLite file, one table ([data-model.md](data-model.md))

**Testing**: `unittest`, run with `python3 -m unittest` from the repo root. Network replaced
with `unittest.mock` fakes. A module-level guard makes real socket use fail.

**Target Platform**: one Linux machine, systemd user session

**Project Type**: CLI tool (two scripts)

**Performance Goals**: report over one week of data in under 10 s (SC-002)

**Constraints**: under 1% CPU, under 5 MB data per day (SC-004), round never longer than 12 s

**Scale/Scope**: about 17,280 rows per day, kept forever

## Constitution Check

| Principle | Status | How |
|---|---|---|
| I. Record evidence | Pass | Every check row has UTC time, target, type, ok, latency or exact error text. Exception class in the error text tells DNS, TCP, TLS, HTTP apart (R7). Outages derived with start, end, length. |
| II. Stdlib only | Pass | No third-party import. ICMP through an unprivileged datagram socket (R1). |
| III. Test first | Pass | Every logic task in tasks.md follows a failing test task. Tests use mocks and block real sockets. |
| IV. Light and local | Pass | Fixed small checks: ICMP echo, one lookup, two TCP connects, two `HEAD` requests. `--interval` changeable. No retries (R10). No upload. |
| V. Never stop | Pass | Each check is wrapped, a raised error becomes a failed row (FR-006). Write errors are logged and skipped (R11). |
| Storage: commit per probe | Pass | Insert and commit per result as it completes (R11). |
| Times in UTC | Pass | Stored UTC (R12). Local only for display. |
| Start simple | Pass | Two source files, two test files, no classes beyond stdlib, config = `--interval`, `--db`. |

Post-design re-check: still Pass. No deviations, Complexity Tracking is empty.

## Security Notes

- S1 Data model: new local SQLite file under the user's data folder, default file mode from the
  umask. Rows are never deleted (FR-017). Report opens the file read-only (`mode=ro` URI).
- S2 External services: outbound checks only, to the default gateway, `1.1.1.1`, `google.com`,
  `github.com` (443, 22). No data is sent beyond the check itself. HTTPS keeps certificate
  checks on. The SSH check reads the banner only, no login, no keys.
- S3 Personal data: error text and router address may hold local network details. They stay in
  the local file (FR-016). The CSV export is written only to a path the owner gives.
- S4 Service install: writes one user unit file, runs `systemctl --user` with argument lists,
  no shell. Paths in `ExecStart` are quoted.
- S5 No sign-in, no secrets, no minors' data.

Tasks touching these: T002-T003 (S1), T004-T005 (S2, S3), T017-T018 (S3), T019-T020 (S4).

## Project Structure

### Documentation (this feature)

```text
specs/001-connection-monitor/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/cli.md
└── tasks.md
```

### Source Code (repository root)

```text
monitor.py        # checks, round runner, schedule loop, SQLite writes, run/install CLI
report.py         # read rows, classify rounds, outages/blips/gaps, report text, CSV, CLI
test_monitor.py   # US1, US4 tests + network guard
test_report.py    # US2, US3 tests
```

**Structure Decision**: flat repo root. `python3 -m unittest` finds `test_*.py` there with no
package setup. `report.py` imports `open_db`, `save_result` only in its tests (to build data)
and needs nothing else from `monitor.py`. The two source files share no code, so the US1 lane
(`monitor.py`) and the US2/US3 lane (`report.py`) can be built in parallel after T003.

## Decisions

- D1 (owner, resolved B): GitHub down also needs the dns check to work, so a DNS-only outage is
  reported once, as `dns`. Spec FR-008 updated. Covered by T011, T012.
- D2 (owner): SC-001 tolerance is one round interval plus 15 s (45 s at 30 s). Spec SC-001 and
  quickstart Q3 updated.

No open decisions remain.

## Complexity Tracking

None.
