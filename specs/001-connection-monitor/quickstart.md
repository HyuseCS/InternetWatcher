# Quickstart: Connection Monitor

Prerequisites: Linux, Python 3 (3.11 or later), systemd user session. No install step.
Commands run from the repo root. Contract: [contracts/cli.md](contracts/cli.md).
Data: [data-model.md](data-model.md).

## Q1. Unit tests (no network)

```bash
python3 -m unittest -v
```

Expected: all tests pass. The tests block real sockets, so a test that reaches the network
fails.

## Q2. Record while the network drops (US1, SC-001)

```bash
python3 monitor.py run --db /tmp/it-q2.db
```

1. Let it run 2 minutes.
2. Turn Wi-Fi off (or unplug the cable) for 90 seconds. Note the clock times of off and on to
   the second.
3. Turn it back on. Wait 1 minute. Press Ctrl+C.
4. Inspect:

```bash
sqlite3 /tmp/it-q2.db "SELECT round_at, target, ok, latency_ms, error FROM checks ORDER BY id"
```

Expected: 6 rows per round. Success rows have `latency_ms`. During the drop, failed rows have
`error` text (router: `NoRoute: no default route` or an `OSError`). Success rows after it.
The monitor did not stop.

## Q3. Report and filter (US2, SC-001, SC-002)

```bash
python3 report.py --db /tmp/it-q2.db
python3 report.py --db /tmp/it-q2.db --since 1h
python3 report.py --db /tmp/it-q2.db --since 2099-01-01
```

Expected: first command shows one `local` or `internet` outage whose start and end are within
45 s (one interval plus 15 s) of the times noted in Q2. The last command shows `No outages.` Each command returns in
under 10 s.

## Q4. CSV export (US3, SC-005)

```bash
python3 report.py --db /tmp/it-q2.db --csv /tmp/it-q2.csv
```

Expected: `/tmp/it-q2.csv` has the header row and the same outages as the report. It opens in
LibreOffice Calc with one row per outage.

## Q5. Install, login start, crash restart (US4, SC-003, SC-004)

```bash
python3 monitor.py install
systemctl --user status internettester.service
pkill -f "monitor.py run"
sleep 15; systemctl --user status internettester.service
```

Expected: status is `active (running)` again within 1 minute of the kill. Log out and in:
status is `active (running)` without a manual step.

After 1 day:

```bash
ls -l ~/.local/share/internettester/checks.db
systemctl --user show internettester.service -p CPUUsageNSec -p ActiveEnterTimestamp
```

Expected: file grows under 5 MB per day. CPU time divided by run time is under 1%.
SC-003 (7 days with no manual restart) and SC-004 are checked by hand here, not by tests.

Remove: `systemctl --user disable --now internettester.service` and delete
`~/.config/systemd/user/internettester.service`.
