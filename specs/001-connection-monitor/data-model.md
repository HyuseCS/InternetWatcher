# Data Model: Connection Monitor

One SQLite file. Default path: `$XDG_DATA_HOME/internettester/checks.db`, else
`~/.local/share/internettester/checks.db`. Created with its folder on first start.
Rows are never deleted or changed (FR-017).

## Table `checks` (stored)

```sql
CREATE TABLE IF NOT EXISTS checks (
  id         INTEGER PRIMARY KEY,
  round_at   TEXT    NOT NULL,
  interval_s INTEGER NOT NULL,
  target     TEXT    NOT NULL,
  check_type TEXT    NOT NULL,
  ok         INTEGER NOT NULL CHECK (ok IN (0, 1)),
  latency_ms REAL,
  error      TEXT
);
CREATE INDEX IF NOT EXISTS checks_round_at ON checks (round_at);
```

| Field | Rule |
|---|---|
| `round_at` | UTC round start, `isoformat(timespec="seconds")`, for example `2026-10-06T05:41:48+00:00`. Same value for all checks of one round. It is the round id. |
| `interval_s` | Interval the monitor ran with, integer ≥ 15. |
| `target` | One of `router`, `dns`, `direct`, `web`, `github_https`, `github_ssh`. |
| `check_type` | `icmp` (router), `dns` (dns), `tcp` (direct), `https` (web, github_https), `ssh` (github_ssh). |
| `ok` | 1 = success, 0 = failure. |
| `latency_ms` | Set when `ok = 1`, NULL when `ok = 0`. |
| `error` | NULL when `ok = 1`. When `ok = 0`: `<ExceptionClassName>: <message>`, never empty. |

## Fixed targets (FR-002)

| target | check_type | What | Success |
|---|---|---|---|
| router | icmp | echo to the default gateway from `/proc/net/route` | echo reply |
| dns | dns | `getaddrinfo("github.com", 443)` | at least one address |
| direct | tcp | connect `1.1.1.1:443` | connected |
| web | https | `HEAD /` on `google.com` | status < 400 |
| github_https | https | `HEAD /` on `github.com` | status < 400 |
| github_ssh | ssh | connect `github.com:22`, read banner | data starts with `SSH-` |

## Round (derived, not stored)

All rows with the same `round_at`. A target missing from a round (crash mid-round) is unknown:
it counts as neither failed nor working.

## Down states per round (derived, FR-008)

| Type | Down when |
|---|---|
| local | router failed |
| internet | router worked, direct failed, web failed |
| dns | direct worked, dns failed |
| github | (direct worked or web worked) and dns worked and (github_https failed or github_ssh failed) |

## Outage (derived, FR-009, FR-012)

Fields: `type`, `start` (UTC datetime), `end` (UTC datetime or None = ongoing), `length`
(seconds), `failed_targets` (list), `sample_error` (text).

State per type, walking rounds in time order:

```text
not down --down round--> run(1)
run(1)   --down round--> run(2+)          (outage)
run(1)   --not down----> not down          blip +1
run(2+)  --not down----> not down          outage ends at this round's time
any run  --gap > 3 x interval_s--> closed  outage ends at last saved round (run 2+) or blip (run 1)
end of data, last round within 3 x interval_s of now: run(2+) = ongoing, run(1) = blip
end of data, older: closed as for a gap
```

## No-data gap (derived, FR-011)

Fields: `start` (last round before the gap), `end` (next round, or now for a trailing gap),
`length`. A gap exists when the time between two rounds, or between the last round and now,
is greater than 3 × `interval_s` of the earlier round for the trailing case and of the later
round otherwise.
