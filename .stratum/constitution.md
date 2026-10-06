# InternetTester Constitution

## Core Principles

### I. Record Evidence, Not Guesses
InternetTester is a background monitor that documents intermittent connection loss, such as
GitHub connections that drop and general internet access that goes away and comes back.

- Every probe MUST be stored with a UTC timestamp, the target, the probe type, the result, the
  latency when it succeeded, and the exact error text when it failed.
- Probes MUST be able to tell failure types apart (for example DNS, TCP connect, TLS, HTTP, and
  one host down while others are up). A single "internet down" flag is not enough.
- Outages MUST be derivable from the stored probes with a start time, an end time, and a length.

Rationale: the point of the tool is to prove when and how the connection fails.

### II. Python 3 Standard Library Only
The monitor MUST use Python 3 and its standard library only (`socket`, `ssl`, `urllib`,
`sqlite3`, `logging`, `unittest`, and similar). Adding a third-party dependency requires a
constitution amendment.

Rationale: no install step, no dependency drift, runs on any machine with Python 3.

### III. Test-First for Logic (NON-NEGOTIABLE)
- Each task with logic (probe result parsing, outage detection, storage, scheduling) MUST start
  with a failing `unittest` test, then the code that makes it pass.
- Tests MUST NOT use the real network. Network calls are replaced with fakes.
- Trivial glue with no branches needs no test.

Rationale: intermittent failures cannot be reproduced on demand, so the logic must be proven
with fakes.

### IV. Light and Local
- Probes MUST be small and fixed in size: DNS lookups, TCP connects, TLS handshakes, small HTTP
  requests. No bulk downloads or bandwidth tests.
- All data MUST stay on this machine. No telemetry, no upload to any service.
- The probe interval MUST be configurable, and a failed probe MUST NOT cause a burst of retries.

Rationale: the monitor must not cause or hide the problems it measures.

### V. Never Stop Running
- An error in one probe MUST be recorded as a result and MUST NOT stop the monitor or other
  probes.
- The monitor MUST survive a full loss of connection and keep recording until it comes back.

Rationale: an outage is the moment the monitor matters most.

## Technical Constraints

- Language: Python 3, standard library only.
- Storage: one local SQLite file. Writes MUST be committed per probe so a crash or power loss
  loses at most the probe in progress.
- Times are stored in UTC. Display can convert to local time.
- Start simple. No abstractions, config options, or features beyond what a spec asks for.

## Development Workflow

- Work follows Stratum lanes (Full, Fast, Quick). Specs live in `specs/`.
- Each finished and verified task is its own commit. Commit messages carry no AI attribution.
- Push only when the owner says push.
- Claims of "done" MUST be backed by a test run or a live run, not by reasoning.

## Governance

- This constitution overrides tool defaults and other practice documents for this project.
- Amendments are made with `/stratum:st-constitution`, which updates this file and its version.
- Versioning: MAJOR for removed or redefined principles, MINOR for new principles or sections,
  PATCH for wording fixes.
- Every plan and review MUST check compliance with these principles. Any deviation MUST be named
  and justified in the plan.

**Version**: 1.0.0 | **Ratified**: 2026-10-06 | **Last Amended**: 2026-10-06
