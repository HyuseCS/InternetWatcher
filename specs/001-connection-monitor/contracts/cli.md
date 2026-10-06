# CLI Contract: Connection Monitor

Two scripts in the repo root. Python 3 stdlib only. Run from any folder.

## `python3 monitor.py run [--interval N] [--db PATH]`

- `--interval`: seconds between round starts. Integer, default 30, minimum 15. Lower or
  non-integer → argparse error, exit 2.
- `--db`: data file. Default `$XDG_DATA_HOME/internettester/checks.db`, else
  `~/.local/share/internettester/checks.db`. Folder and file are created if missing.
- Runs until stopped. Ctrl+C → exit 0. SIGTERM uses the Python default (process ends).
- Another monitor holds the data file → stderr `already running: <PATH>`, exit 1.
- Write error on a result → stderr `write failed: <error>`, keeps running.
- Writes nothing to stdout during normal operation.

## `python3 monitor.py install [--interval N] [--db PATH]`

- Writes `~/.config/systemd/user/internettester.service`:

```ini
[Unit]
Description=InternetTester connection monitor

[Service]
ExecStart="<sys.executable>" "<absolute path of monitor.py>" run --interval <N> --db "<absolute PATH>"
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

- Then runs `systemctl --user daemon-reload` and
  `systemctl --user enable --now internettester.service` (argument lists, no shell).
- Prints the unit path. Exit code = the first non-zero `systemctl` exit code, else 0.

## `python3 report.py [--since WHEN] [--db PATH] [--csv FILE]`

- `--since`: `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM[:SS]` (local time), or `<N>h` / `<N>d`.
  Other values → stderr message, exit 2. Shows only outages, blips, and gaps that overlap
  `[since, now]`.
- `--db`: as above. Missing file → stderr `no data file: <PATH>`, exit 1. Opened read-only.
- `--csv FILE`: also write the same outage list to FILE (FR-014). Overwrites FILE.
- Exit 0 on success.

### Report text (stdout)

Times are local, `YYYY-MM-DD HH:MM:SS`. Lengths as `XhYmZs` with leading zero units dropped
(`4m30s`, `1h0m5s`, `45s`). Outages sorted by start.

```text
TYPE      START                END                  LENGTH  FAILED TARGETS           SAMPLE ERROR
github    2026-10-06 14:02:00  2026-10-06 14:06:30  4m30s   github_https github_ssh  TimeoutError: timed out
internet  2026-10-06 15:10:00  ongoing              1m0s    direct web               OSError: [Errno 101] Network is unreachable

NO DATA   2026-10-06 23:00:00  2026-10-07 07:00:00  8h0m0s

Outages: 2 | Down time: local 0s, internet 1m0s, dns 0s, github 4m30s | Blips: 3 | No data: 8h0m0s
```

- No outages → the line `No outages.` replaces the table.
- No gaps → no `NO DATA` lines.
- Column widths may grow to fit values. Fields are separated by at least two spaces.

### CSV (FR-014)

UTF-8, `csv` module defaults (comma, `\r\n`, quoting when needed). Header row:

```text
type,start,end,length_seconds,failed_targets,sample_error
```

- `start`, `end`: local `YYYY-MM-DD HH:MM:SS`. `end` is `ongoing` for an ongoing outage.
- `length_seconds`: integer.
- `failed_targets`: space separated.
- One row per outage, same order and same outages as the report text.
