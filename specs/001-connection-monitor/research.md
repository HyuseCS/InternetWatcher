# Research: Connection Monitor

Each item: Decision, Rationale, Alternatives. Facts marked "verified" were run on this machine
(Python 3.14.7, SQLite 3.53.4, systemd 262, Linux) on 2026-10-06.

## R1. Router check method

- Decision: ICMP echo through an unprivileged datagram socket
  (`socket.socket(AF_INET, SOCK_DGRAM, IPPROTO_ICMP)`), sent to the default gateway.
- Rationale: stdlib only, no root, no subprocess. Verified: `ping_group_range` is
  `0 2147483647`, and an echo to the router `10.210.0.1` came back in 3 ms. The kernel fills
  the ID and checksum.
- Alternatives: `subprocess` + `ping` (external binary, output parsing). TCP connect to the
  router (many routers drop closed ports silently, which gives a false "down").
- Ceiling: if a machine forbids unprivileged ICMP, every router check fails with
  `PermissionError`. Out of scope (one Linux machine).

## R2. Router address and the no-router case (CHK004)

- Decision: read `/proc/net/route` at each round. The default route is the line with
  Destination `00000000`. The gateway is little-endian hex (`0100D20A` = `10.210.0.1`, verified).
  If there is no default route, the router check fails with error
  `NoRoute: no default route`.
- Rationale: follows network changes without a restart (spec assumption). No route means the
  machine is off the network, so "local network down" is the correct result.
- Alternatives: `ip route` subprocess (extra process every round).

## R3. Name lookup check (CHK002)

- Decision: `socket.getaddrinfo("github.com", 443, type=SOCK_STREAM)` through the system resolver.
- Rationale: measures what apps see. github.com is the host the owner cares about.
- Ceiling: this machine uses systemd-resolved (`nameserver 127.0.0.53`, verified), which caches.
  An upstream DNS loss can stay hidden until the cached record expires. Accepted by the owner
  (F7). TTL of github.com as served by the system resolver: not measured yet, T010 measures it
  and writes the number here.
- Alternatives: hand-built DNS query to a fixed server (does not measure the system resolver,
  more code).

## R4. Direct-address check

- Decision: TCP connect to `1.1.1.1:443`. Success = connect completes.
- Rationale: no name lookup, small, fixed size.

## R5. HTTPS checks and success codes (CHK003)

- Decision: `http.client.HTTPSConnection(host, timeout=10)`, `HEAD /`, default SSL context
  (certificate checks on). Success = any status below 400. Redirects are not followed.
  Status 400 and above is a failure with error `HTTPStatus: <code> <reason>`.
- Rationale: one small request, no redirect chain. Verified: github.com gives 200,
  google.com gives 301. Certificate checks stay on so a TLS interception shows as a TLS error.
- Alternatives: `urllib.request.urlopen` (follows redirects, which means more requests).

## R6. GitHub SSH check

- Decision: TCP connect to `github.com:22`, read up to 64 bytes. Success = data starts with
  `SSH-`. Verified banner: `SSH-2.0-...`.
- Rationale: proves the SSH service answers, not only that a port opened. No login, no keys.

## R7. Error text (Constitution I)

- Decision: error text = `<ExceptionClassName>: <str(exception)>`, for example
  `gaierror: [Errno -3] Temporary failure in name resolution`,
  `SSLCertVerificationError: ...`, `TimeoutError: timed out`.
- Rationale: the exception class tells DNS, TCP, TLS, and HTTP failures apart without an extra
  column, and the message is the exact text.

## R8. Per-check time limit and round deadline (CHK001, FR-003)

- Decision: socket timeout 10 s per check. All six checks of a round run at the same time in a
  `ThreadPoolExecutor(max_workers=6)`. The round waits at most 12 s. A check that has not
  finished is saved as `TimeoutError: no result in 10s`. The executor is shut down with
  `wait=False, cancel_futures=True`.
- Rationale: `getaddrinfo` has no timeout parameter, so a socket timeout alone cannot bound a
  check. The thread deadline bounds the round. A round never takes longer than 12 s.
- Alternatives: run checks one after another (worst case 60 s, longer than the interval).
- Ceiling: a hung `getaddrinfo` thread lives on until the resolver gives up.
- On Ctrl+C during a resolver hang, exit can be delayed by up to one check timeout (10 s).

## R9. Lowest interval (CHK005)

- Decision: `--interval` default 30, minimum 15 seconds. Lower values are rejected at start.
- Rationale: must stay above the 12 s round deadline so rounds never overlap.

## R10. Schedule and no-burst rule (FR-001, FR-007)

- Decision: round start times use `time.monotonic()`. After each round:
  `next_at = max(next_at + interval, now)`, then sleep until `next_at`. Missed rounds are
  skipped, never caught up. Failed checks are never retried.
- Rationale: a slow round or a resume from sleep gives one round at once, not a burst.

## R11. Saving (FR-005, Constitution storage rule)

- Decision: each result is inserted and committed as soon as its check finishes
  (`as_completed`), from the main thread only.
- Rationale: the constitution asks for a commit per probe. One connection, one thread, no lock.
- Write error (disk full, file locked, CHK015): the error is printed to stderr and the monitor
  continues with the next result and the next round.

## R12. Time format (CHK009)

- Decision: stored as UTC ISO 8601 text, seconds precision,
  `datetime.now(timezone.utc).isoformat(timespec="seconds")` → `2026-10-06T05:41:48+00:00`
  (verified). Report and CSV show local time as `YYYY-MM-DD HH:MM:SS`.
- Rationale: readable in the `sqlite3` shell, sorts as text, no time zone mistakes in storage.

## R13. Report time filter (CHK008)

- Decision: `--since` accepts `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM[:SS]` (local time), or a relative
  `<N>h` / `<N>d`. Anything else exits with code 2 and a message. Parsed with
  `datetime.fromisoformat` (accepts date-only, verified) and `.astimezone()`.
- "since yesterday" = `--since <yesterday's date>` or `--since 1d`.
- To keep the report fast, rows are loaded from `since - 1 day`.
  Ceiling: an outage that began more than 1 day before `since` shows a later start.

## R14. Interval stored per row (FR-011)

- Decision: each row stores the `interval_s` the monitor ran with.
- Gap rule: two saved rounds are a no-data gap when the later round's time minus the earlier
  round's time is greater than 3 × `interval_s` of the later round. After the last saved round,
  the time to now is a no-data gap when it is greater than 3 × `interval_s` of the last round.
- Rationale: the report needs no `--interval` flag and stays correct if the interval changes.

## R15. Outage details (CHK006, CHK007, CHK017)

- Length = end − start. End = time of the first round where the state is gone. Ongoing
  length = now − start.
- Failed targets = the targets that define the type and that failed in any round of the outage:
  local → router; internet → direct, web; dns → dns; github → github_https, github_ssh.
  Sample error = the first error text among them.
- Crash during an outage: after restart, if the gap is ≤ 3 intervals the outage continues,
  otherwise it ends at the last saved round and a no-data gap is shown.
- A single down round as the last saved round of an ongoing run is counted as a blip.

## R16. Overlapping rules (CHK010, CHK011)

- Internet down needs direct to fail. DNS down needs direct to work. So they never both apply.
- GitHub down also needs the dns check to work (owner decision D1, spec FR-008 updated). A
  DNS-only outage is reported as `dns` only, not also as `github`.

## R17. Single instance (CHK016)

- Decision: open the data file with `os.open(path, os.O_RDWR | os.O_CREAT)` (never mode `"w"`,
  which would empty it) and take `fcntl.flock(fd, LOCK_EX | LOCK_NB)` at start. If the lock is
  taken, print `already running: <path>` and exit 1.
- Rationale: two monitors writing the same file would mix two round streams. SQLite uses
  `fcntl` record locks, which are separate from `flock` on Linux, so there is no conflict.

## R18. Start at login and restart (FR-015)

- Decision: `monitor.py install` writes `~/.config/systemd/user/internettester.service`
  (`Restart=always`, `RestartSec=10`, `WantedBy=default.target`, `ExecStart` with the absolute
  Python and script paths), then runs `systemctl --user daemon-reload` and
  `systemctl --user enable --now internettester.service`.
- Rationale: restart in 10 s meets "within 1 minute". 10 s also stays clear of the default
  start limit (5 starts in 10 s).
- Alternatives: ship a unit file and tell the owner to edit paths by hand (more error-prone).

## R19. Data growth (SC-004)

- 6 rows every 30 s = 17,280 rows a day. At about 100 bytes per row plus index, about 2-3 MB a
  day. Below 5 MB. Measure in quickstart step Q5.

## R20. Privacy (CHK018)

- Error text and the router address can contain local network details. They stay in the local
  file. Nothing is uploaded (FR-016).
