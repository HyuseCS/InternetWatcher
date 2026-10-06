# Feature Specification: Connection Monitor

**Feature Branch**: `001-connection-monitor`

**Created**: 2026-10-06

**Status**: Draft

**Input**: User description: "Background monitor that we can leave running that documents
intermittent internet connection. Cases noticed so far: connections to GitHub disconnect, and
internet access in general is sometimes lost for a period of time and then comes back."

Grilling summary: fixed target set (router, DNS, general internet, GitHub HTTPS and SSH); one
check round every 30 seconds; an outage is 2 or more failed rounds in a row; data kept forever;
results shown as a terminal report plus a CSV export; starts automatically at login and restarts
after a crash.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Record every check while left running (Priority: P1)

The owner starts the monitor once and forgets it. Every 30 seconds it checks the router, name
lookup, the general internet, and GitHub, and saves each result with the time, the target, the
result, the response time, and the exact error text on failure.

**Why this priority**: without the saved record, nothing else can work. This alone already gives
evidence that can be read by hand.

**Independent Test**: run the monitor for 2 minutes, unplug the network for 1 minute, plug it
back in, and confirm the saved record shows successes, then failures with error text, then
successes again.

**Acceptance Scenarios**:

1. **Given** the network is up, **When** a check round runs, **Then** one success result per
   target is saved with its response time.
2. **Given** the network is down, **When** a check round runs, **Then** one failed result per
   target is saved with the error text, and the monitor keeps running.
3. **Given** one target check hangs, **When** its time limit passes, **Then** it is saved as a
   timeout and the other targets in the round are still checked and saved.

---

### User Story 2 - See an outage report (Priority: P2)

The owner runs a report command and sees a list of outages: the type, the start time, the end
time (or "ongoing"), the length, and which targets failed with a sample error.

**Why this priority**: this turns raw results into the answer the owner needs ("GitHub dropped
for 4 minutes at 14:02 while the rest of the internet worked").

**Independent Test**: load a known set of saved results and confirm the report lists exactly
the expected outages with correct types, times, and lengths.

**Acceptance Scenarios**:

1. **Given** the router check fails for 3 rounds in a row, **When** the report runs, **Then** it
   shows one "local network" outage from the first failed round to the first success after it.
2. **Given** the router works but the general internet targets all fail for 2 or more rounds,
   **When** the report runs, **Then** it shows one "internet" outage.
3. **Given** the general internet works but a GitHub check fails for 2 or more rounds, **When**
   the report runs, **Then** it shows one "GitHub" outage.
4. **Given** the direct-address check works but name lookup fails for 2 or more rounds, **When**
   the report runs, **Then** it shows one "DNS" outage.
5. **Given** a single failed round between successes, **When** the report runs, **Then** no
   outage is shown, and the round is counted as a blip in the report summary.
6. **Given** a time filter such as "since yesterday", **When** the report runs, **Then** only
   outages that overlap that window are shown.

---

### User Story 3 - Export outages to a spreadsheet (Priority: P3)

The owner exports the same outage list to a CSV file to open in a spreadsheet or send to the
internet provider.

**Why this priority**: useful for sharing, but the terminal report already answers the question.

**Independent Test**: export a known set of outages and confirm the file opens in a spreadsheet
with one row per outage and the same values the report shows.

**Acceptance Scenarios**:

1. **Given** saved outages, **When** the owner exports with a file path, **Then** a CSV file is
   written with a header row and one row per outage.
2. **Given** the same time filter as the report, **When** the owner exports, **Then** the file
   holds the same outages the report shows.

---

### User Story 4 - Runs on its own at login (Priority: P4)

The owner installs the monitor once. It starts by itself at login and starts again by itself if
it crashes.

**Why this priority**: removes the need to remember to start it, but the monitor works without it.

**Independent Test**: install, log out and in, and confirm checks are being saved. Kill the
process and confirm it comes back within 1 minute.

**Acceptance Scenarios**:

1. **Given** the monitor is installed, **When** the owner logs in, **Then** checks start without
   any manual step.
2. **Given** the monitor is running, **When** its process is killed, **Then** it restarts and
   saving resumes within 1 minute.

### Edge Cases

- The computer sleeps or the monitor is stopped: the time with no saved rounds is shown as a
  "no data" gap, never as an outage and never as uptime.
- An outage is still going on when the report runs: it is shown with end "ongoing" and its
  length so far.
- Several outage types overlap (for example GitHub fails, then the whole internet fails): each
  type is tracked and reported on its own.
- A check takes longer than the round interval: each check has a time limit shorter than the
  interval, so rounds do not pile up.
- The computer clock changes: times are saved in UTC so daylight saving changes do not break
  lengths.
- The monitor crashes or power is lost: at most the round in progress is lost.
- The data file does not exist yet: it is created on first start.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The monitor MUST run one check round every 30 seconds, with the interval
  changeable at start.
- **FR-002**: Each round MUST check these targets: the default router (gateway), name lookup of
  a public host, a direct-address check of a public internet host (1.1.1.1), a general website
  (google.com over HTTPS), github.com over HTTPS, and GitHub's git SSH port (github.com port 22).
- **FR-003**: Each check MUST have a time limit shorter than the round interval and MUST save a
  timeout as a failed result.
- **FR-004**: Each result MUST be saved with the UTC time, target, check type, success or failure,
  response time on success, and the exact error text on failure.
- **FR-005**: Each result MUST be saved before the next round starts, so a crash loses at most
  the round in progress.
- **FR-006**: An error in one check MUST NOT stop other checks in the round or stop the monitor.
- **FR-007**: A failed check MUST NOT trigger extra retries outside the normal round schedule.
- **FR-008**: The report MUST classify each round into these states per type:
  - local network down: the router check fails;
  - internet down: the router works and both general internet checks fail;
  - DNS down: the direct-address check works and name lookup fails;
  - GitHub down: at least one general internet check works, the DNS check works, and a GitHub
    check fails.
- **FR-009**: An outage of a type MUST be 2 or more rounds in a row in that down state. It starts
  at the first such round and ends at the first round after it where that state is gone.
- **FR-010**: A single down round between non-down rounds MUST be counted as a blip, not an
  outage.
- **FR-011**: A gap between saved rounds longer than 3 intervals MUST be shown as "no data" and
  MUST end any open outage at the last saved round.
- **FR-012**: The report MUST list each outage with type, start, end or "ongoing", length, failed
  targets, and one sample error text, sorted by start time, then a summary with outage count,
  total down time per type, blip count, and no-data time.
- **FR-013**: The report MUST accept a start time filter and show only outages that overlap it.
- **FR-014**: The export MUST write the same outage list as the report to a CSV file at a path
  the owner gives, with a header row.
- **FR-015**: The monitor MUST be installable so that it starts at login and restarts within
  1 minute after a crash.
- **FR-016**: All data MUST stay on this computer. Nothing is sent anywhere except the checks
  themselves.
- **FR-017**: Saved results MUST be kept with no automatic deletion.

### Key Entities

- **Check result**: one check of one target in one round. Time (UTC), round id, target, check
  type, success, response time, error text.
- **Outage**: derived from check results, not saved. Type, start, end or ongoing, length, failed
  targets, sample error.
- **No-data gap**: derived from check results. Start, end, length.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After a 1-minute unplug test, the report shows exactly one "local network" or
  "internet" outage whose start and end are within one round interval plus 15 seconds (45
  seconds at the default 30-second interval) of the real times.
- **SC-002**: The owner can answer "when did GitHub fail this week, and for how long?" with one
  command in under 10 seconds.
- **SC-003**: The monitor runs for 7 days with no manual restart and no gaps except sleep or
  shutdown.
- **SC-004**: The monitor uses under 1% CPU on average and its data grows by under 5 MB per day.
- **SC-005**: An exported CSV opens in a common spreadsheet app with one correct row per outage.

## Assumptions

- One owner, one Linux computer, one user login. No sign-in, no multi-user access.
- The data file lives in the owner's user data folder (for example
  `~/.local/share/internettester/`).
- Target list is fixed in this version. Editing targets is out of scope.
- Alerts, notifications, dashboards, charts, and speed or bandwidth tests are out of scope.
- The "login start and crash restart" feature relies on the Linux user service manager. Other
  operating systems are out of scope.
- The router address is found from the system's default route at each round, so a network change
  (for example a new Wi-Fi) is followed without a restart.
