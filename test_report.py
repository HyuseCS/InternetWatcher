import contextlib
import csv
import io
import os
import re
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

import monitor
import report
from report import classify

OK = (1, None)
BAD = (0, "OSError: down")
ALL = ("router", "dns", "direct", "web", "github_https", "github_ssh")


def rnd(**kw):
    r = {t: OK for t in ALL}
    for t, v in kw.items():
        if v is None:
            del r[t]
        else:
            r[t] = v
    return r


class ClassifyTest(unittest.TestCase):
    def test_all_ok(self):
        self.assertEqual(classify(rnd()), set())

    def test_local_router_failed(self):
        self.assertEqual(classify(rnd(router=BAD)), {"local"})

    def test_all_six_fail_is_local_only(self):
        self.assertEqual(classify({t: BAD for t in ALL}), {"local"})

    def test_internet_direct_and_web_failed(self):
        r = rnd(direct=BAD, web=BAD)
        self.assertEqual(classify(r), {"internet"})

    def test_internet_with_dns_failed_is_not_dns(self):
        r = rnd(direct=BAD, web=BAD, dns=BAD)
        self.assertEqual(classify(r), {"internet"})

    def test_internet_needs_both_direct_and_web_failed(self):
        self.assertEqual(classify(rnd(direct=BAD)), set())
        self.assertEqual(classify(rnd(web=BAD)), set())

    def test_dns_direct_ok_dns_failed(self):
        self.assertEqual(classify(rnd(dns=BAD)), {"dns"})

    def test_dns_only_outage_is_not_github(self):
        r = rnd(dns=BAD, web=BAD, github_https=BAD, github_ssh=BAD)
        self.assertEqual(classify(r), {"dns"})

    def test_github_https_failed(self):
        self.assertEqual(classify(rnd(github_https=BAD)), {"github"})

    def test_github_ssh_failed_only(self):
        self.assertEqual(classify(rnd(github_ssh=BAD)), {"github"})

    def test_github_with_direct_failed_web_ok(self):
        r = rnd(direct=BAD, github_ssh=BAD)
        self.assertEqual(classify(r), {"github"})

    def test_github_with_web_failed_direct_ok(self):
        r = rnd(web=BAD, github_https=BAD)
        self.assertEqual(classify(r), {"github"})

    def test_github_needs_dns_ok(self):
        r = rnd(dns=None, github_ssh=BAD)
        self.assertEqual(classify(r), set())

    def test_missing_targets_are_unknown(self):
        self.assertEqual(classify(rnd(router=None)), set())
        self.assertEqual(classify(rnd(direct=None, web=None)), set())
        self.assertEqual(classify(rnd(github_https=None, github_ssh=None)), set())

    def test_empty_round(self):
        self.assertEqual(classify({}), set())

T0 = datetime(2026, 10, 6, 5, 0, 0, tzinfo=timezone.utc)
UP = rnd()
ROUTER_DOWN = rnd(router=BAD)
INTERNET_DOWN = rnd(direct=BAD, web=BAD)
GITHUB_DOWN = rnd(github_https=BAD)


def rounds_at(*items, interval=30):
    return [(T0 + timedelta(seconds=s), interval, r) for s, r in items]


def at(s):
    return T0 + timedelta(seconds=s)


class FindOutagesTest(unittest.TestCase):
    def test_local_outage_three_rounds(self):
        errs = [(0, f"OSError: r{i}") for i in range(3)]
        rounds = rounds_at(
            (0, rnd(router=errs[0])),
            (30, rnd(router=errs[1])),
            (60, rnd(router=errs[2])),
            (90, UP),
        )
        outages, blips, gaps = report.find_outages(rounds, at(90))
        self.assertEqual(
            outages,
            [
                {
                    "type": "local",
                    "start": at(0),
                    "end": at(90),
                    "length": 90,
                    "failed_targets": ["router"],
                    "sample_error": "OSError: r0",
                }
            ],
        )
        self.assertEqual(blips, [])
        self.assertEqual(gaps, [])

    def test_internet_outage_failed_targets(self):
        rounds = rounds_at((0, INTERNET_DOWN), (30, INTERNET_DOWN), (60, UP))
        outages, blips, gaps = report.find_outages(rounds, at(60))
        self.assertEqual(len(outages), 1)
        self.assertEqual(outages[0]["type"], "internet")
        self.assertEqual(outages[0]["failed_targets"], ["direct", "web"])
        self.assertEqual(outages[0]["sample_error"], "OSError: down")
        self.assertEqual(blips, [])

    def test_single_down_round_is_blip(self):
        rounds = rounds_at((0, UP), (30, ROUTER_DOWN), (60, UP))
        outages, blips, gaps = report.find_outages(rounds, at(60))
        self.assertEqual(outages, [])
        self.assertEqual(blips, [("local", at(30))])
        self.assertEqual(gaps, [])

    def test_gap_closes_outage_at_last_round(self):
        rounds = rounds_at((0, ROUTER_DOWN), (30, ROUTER_DOWN), (230, UP))
        outages, blips, gaps = report.find_outages(rounds, at(230))
        self.assertEqual(len(outages), 1)
        self.assertEqual(outages[0]["start"], at(0))
        self.assertEqual(outages[0]["end"], at(30))
        self.assertEqual(outages[0]["length"], 30)
        self.assertEqual(blips, [])
        self.assertEqual(gaps, [(at(30), at(230))])

    def test_single_down_round_then_gap_is_blip(self):
        rounds = rounds_at((0, UP), (30, ROUTER_DOWN), (230, UP))
        outages, blips, gaps = report.find_outages(rounds, at(230))
        self.assertEqual(outages, [])
        self.assertEqual(blips, [("local", at(30))])
        self.assertEqual(gaps, [(at(30), at(230))])

    def test_ongoing_outage(self):
        rounds = rounds_at((0, UP), (30, ROUTER_DOWN), (60, ROUTER_DOWN))
        outages, blips, gaps = report.find_outages(rounds, at(90))
        self.assertEqual(len(outages), 1)
        self.assertEqual(outages[0]["start"], at(30))
        self.assertIsNone(outages[0]["end"])
        self.assertEqual(outages[0]["length"], 60)
        self.assertEqual(blips, [])
        self.assertEqual(gaps, [])

    def test_stale_outage_closed_with_trailing_gap(self):
        rounds = rounds_at((0, UP), (30, ROUTER_DOWN), (60, ROUTER_DOWN))
        now = at(60 + 3600)
        outages, blips, gaps = report.find_outages(rounds, now)
        self.assertEqual(len(outages), 1)
        self.assertEqual(outages[0]["end"], at(60))
        self.assertEqual(outages[0]["length"], 30)
        self.assertEqual(gaps, [(at(60), now)])

    def test_back_to_back_github_then_internet(self):
        rounds = rounds_at(
            (0, GITHUB_DOWN),
            (30, GITHUB_DOWN),
            (60, INTERNET_DOWN),
            (90, INTERNET_DOWN),
            (120, INTERNET_DOWN),
            (150, UP),
        )
        outages, blips, gaps = report.find_outages(rounds, at(150))
        self.assertEqual([o["type"] for o in outages], ["github", "internet"])
        self.assertEqual(outages[0]["start"], at(0))
        self.assertEqual(outages[0]["end"], at(60))
        self.assertEqual(outages[1]["start"], at(60))
        self.assertEqual(outages[1]["end"], at(150))
        self.assertEqual(blips, [])

    def test_spacing_within_three_intervals_is_no_gap(self):
        rounds = rounds_at((0, UP), (150, UP), (300, UP), interval=60)
        outages, blips, gaps = report.find_outages(rounds, at(300))
        self.assertEqual((outages, blips, gaps), ([], [], []))


if __name__ == "__main__":
    unittest.main()


UTC = timezone.utc


def utc(*a):
    return datetime(*a, tzinfo=UTC)


class TZCase(unittest.TestCase):
    def setUp(self):
        self.old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "checks.db")

    def tearDown(self):
        if self.old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.old_tz
        time.tzset()

    def save_round(self, conn, at, results, interval=30):
        for t in ALL:
            ok, err = results.get(t, OK)
            monitor.save_result(
                conn, at.isoformat(timespec="seconds"), interval,
                (t, "tcp", ok, 5.0 if ok else None, err),
            )

    def build(self, rounds):
        conn = monitor.open_db(self.path)
        for at, results in rounds:
            self.save_round(conn, at, results)
        conn.close()

    def run_main(self, argv, now):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = report.main(argv, now=now)
        return code, out.getvalue(), err.getvalue()


class LoadRoundsTest(TZCase):
    def test_groups_and_sorts_rounds(self):
        t1, t2 = utc(2026, 10, 6, 18, 0, 0), utc(2026, 10, 6, 18, 0, 30)
        conn = monitor.open_db(self.path)
        self.save_round(conn, t2, {"router": (0, "OSError: x")}, interval=15)
        self.save_round(conn, t1, {})
        rounds = report.load_rounds(conn, None)
        self.assertEqual([r[0] for r in rounds], [t1, t2])
        self.assertEqual(rounds[0][1], 30)
        self.assertEqual(rounds[1][1], 15)
        self.assertEqual(set(rounds[0][2]), set(ALL))
        self.assertEqual(rounds[0][2]["router"], (1, None))
        self.assertEqual(rounds[1][2]["router"], (0, "OSError: x"))
        self.assertEqual(rounds[1][2]["dns"], (1, None))

    def test_since_skips_rows_older_than_one_day_before(self):
        since = utc(2026, 10, 6, 12, 0, 0)
        old = since - timedelta(days=1, hours=1)
        kept = since - timedelta(hours=23)
        after = since + timedelta(hours=1)
        conn = monitor.open_db(self.path)
        for at in (old, kept, after):
            self.save_round(conn, at, {})
        rounds = report.load_rounds(conn, since)
        self.assertEqual([r[0] for r in rounds], [kept, after])


class ParseSinceTest(TZCase):
    NOW = utc(2026, 10, 6, 20, 0, 0)

    def test_date_is_local_midnight_as_utc(self):
        self.assertEqual(report.parse_since("2026-10-05", self.NOW), utc(2026, 10, 5, 4, 0, 0))

    def test_datetime_is_local_time_as_utc(self):
        self.assertEqual(report.parse_since("2026-10-05T14:02", self.NOW), utc(2026, 10, 5, 18, 2, 0))

    def test_hours(self):
        self.assertEqual(report.parse_since("6h", self.NOW), utc(2026, 10, 6, 14, 0, 0))

    def test_days(self):
        self.assertEqual(report.parse_since("7d", self.NOW), utc(2026, 9, 29, 20, 0, 0))

    def test_bad_text_raises_value_error(self):
        with self.assertRaises(ValueError):
            report.parse_since("yesterday-ish", self.NOW)


def outage(kind, start, end, length, targets, err):
    return {
        "type": kind, "start": start, "end": end, "length": length,
        "failed_targets": targets, "sample_error": err,
    }


class FormatReportTest(TZCase):
    NOW = utc(2026, 10, 6, 19, 11, 0)

    def sample(self):
        github = outage(
            "github", utc(2026, 10, 6, 18, 2, 0), utc(2026, 10, 6, 18, 6, 30), 270,
            ["github_https", "github_ssh"], "TimeoutError: timed out",
        )
        internet = outage(
            "internet", utc(2026, 10, 6, 19, 10, 0), None, 60,
            ["direct", "web"], "OSError: [Errno 101] Network is unreachable",
        )
        blips = [("dns", utc(2026, 10, 6, 17, 0, 0))] * 3
        gaps = [(utc(2026, 10, 6, 10, 0, 0), utc(2026, 10, 6, 18, 0, 0))]
        return [internet, github], blips, gaps

    def lines(self, text):
        return [l.split() for l in text.splitlines()]

    def test_layout(self):
        text = report.format_report(*self.sample(), self.NOW)
        rows = self.lines(text)
        self.assertEqual(rows[0], ["TYPE", "START", "END", "LENGTH", "FAILED", "TARGETS", "SAMPLE", "ERROR"])
        self.assertEqual(
            rows[1],
            ["github", "2026-10-06", "14:02:00", "2026-10-06", "14:06:30", "4m30s",
             "github_https", "github_ssh", "TimeoutError:", "timed", "out"],
        )
        self.assertEqual(
            rows[2],
            ["internet", "2026-10-06", "15:10:00", "ongoing", "1m0s", "direct", "web",
             "OSError:", "[Errno", "101]", "Network", "is", "unreachable"],
        )
        self.assertIn(
            ["NO", "DATA", "2026-10-06", "06:00:00", "2026-10-06", "14:00:00", "8h0m0s"], rows
        )
        self.assertIn(
            "Outages: 2 | Down time: local 0s, internet 1m0s, dns 0s, github 4m30s"
            " | Blips: 3 | No data: 8h0m0s",
            text.splitlines(),
        )

    def test_length_units(self):
        o = [
            outage("local", utc(2026, 10, 6, 15, 0, 0), utc(2026, 10, 6, 16, 0, 5), 3605, ["router"], "E: a"),
            outage("dns", utc(2026, 10, 6, 17, 0, 0), utc(2026, 10, 6, 17, 0, 45), 45, ["dns"], "E: b"),
        ]
        text = report.format_report(o, [], [], self.NOW)
        self.assertIn("1h0m5s", self.lines(text)[1])
        self.assertIn("45s", self.lines(text)[2])
        self.assertIn("Down time: local 1h0m5s, internet 0s, dns 45s, github 0s", text)

    def test_no_outages_no_gaps(self):
        text = report.format_report([], [], [], self.NOW)
        self.assertIn("No outages.", text.splitlines())
        self.assertNotIn("TYPE", text)
        self.assertNotIn("NO DATA", text)
        self.assertIn("Outages: 0 | Down time: local 0s, internet 0s, dns 0s, github 0s | Blips: 0 | No data: 0s", text)

    def test_non_printable_sample_error_replaced_input_untouched(self):
        o = outage("local", utc(2026, 10, 6, 15, 0, 0), utc(2026, 10, 6, 15, 1, 0), 60, ["router"], "bad\x1b[0m\nnext")
        text = report.format_report([o], [], [], self.NOW)
        self.assertIn("bad?[0m?next", text)
        self.assertNotIn("\x1b", text)
        self.assertEqual(o["sample_error"], "bad\x1b[0m\nnext")


class MainTest(TZCase):
    def test_since_in_future_prints_no_outages(self):
        self.build([(utc(2026, 10, 6, 18, 0, 0), {})])
        code, out, err = self.run_main(
            ["--db", self.path, "--since", "2099-01-01"], utc(2026, 10, 6, 18, 0, 30)
        )
        self.assertEqual(code, 0)
        self.assertIn("No outages.", out.splitlines())

    def local_outage_db(self):
        down = {"router": (0, "OSError: down")}
        rounds = [
            (utc(2026, 10, 6, 18, 2, 0), down),
            (utc(2026, 10, 6, 18, 2, 30), down),
            (utc(2026, 10, 6, 18, 3, 0), down),
            (utc(2026, 10, 6, 18, 3, 30), {}),
            (utc(2026, 10, 6, 18, 4, 0), {}),
            (utc(2026, 10, 6, 18, 4, 30), {}),
        ]
        self.build(rounds)
        return utc(2026, 10, 6, 18, 5, 0)

    def test_outage_overlapping_since_is_shown(self):
        now = self.local_outage_db()
        code, out, err = self.run_main(["--db", self.path, "--since", "2026-10-06T14:03"], now)
        self.assertEqual(code, 0)
        self.assertNotIn("No outages.", out)
        self.assertEqual(out.splitlines()[1].split()[:3], ["local", "2026-10-06", "14:02:00"])

    def test_outage_ended_before_since_is_not_shown(self):
        now = self.local_outage_db()
        code, out, err = self.run_main(["--db", self.path, "--since", "2026-10-06T14:04"], now)
        self.assertEqual(code, 0)
        self.assertIn("No outages.", out.splitlines())

    def blip_gap_db(self):
        down = {"router": (0, "OSError: down")}
        self.build([
            (utc(2026, 10, 6, 17, 0, 0), down),
            (utc(2026, 10, 6, 17, 0, 30), {}),
            (utc(2026, 10, 6, 18, 0, 0), {}),
            (utc(2026, 10, 6, 18, 0, 30), down),
            (utc(2026, 10, 6, 18, 1, 0), {}),
            (utc(2026, 10, 6, 18, 1, 30), {}),
        ])
        return utc(2026, 10, 6, 18, 2, 0)

    def blips(self, out):
        return int(re.search(r"Blips: (\d+)", out).group(1))

    def test_since_before_everything_counts_all(self):
        now = self.blip_gap_db()
        code, out, err = self.run_main(["--db", self.path, "--since", "2026-10-06T12:00"], now)
        self.assertEqual(self.blips(out), 2)
        self.assertIn("NO DATA", out)

    def test_gap_starting_before_since_and_ending_after_is_shown_old_blip_dropped(self):
        now = self.blip_gap_db()
        code, out, err = self.run_main(["--db", self.path, "--since", "2026-10-06T13:30"], now)
        self.assertEqual(self.blips(out), 1)
        self.assertIn("NO DATA", out)

    def test_gap_ended_before_since_and_older_blips_dropped(self):
        now = self.blip_gap_db()
        code, out, err = self.run_main(["--db", self.path, "--since", "2026-10-06T14:00:45"], now)
        self.assertEqual(self.blips(out), 0)
        self.assertNotIn("NO DATA", out)

    def test_missing_db(self):
        missing = os.path.join(self.tmp.name, "nope.db")
        code, out, err = self.run_main(["--db", missing], utc(2026, 10, 6, 18, 0, 0))
        self.assertEqual(code, 1)
        self.assertIn("no data file: " + missing, err)
        self.assertFalse(os.path.exists(missing))

    def test_bad_since_returns_2(self):
        code, out, err = self.run_main(["--since", "bad"], utc(2026, 10, 6, 18, 0, 0))
        self.assertEqual(code, 2)


class WriteCsvTest(TZCase):
    def read(self, path):
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.reader(f))

    def test_header_rows_ongoing_and_comma_round_trip(self):
        closed = outage(
            "github", utc(2026, 10, 6, 18, 2, 0), utc(2026, 10, 6, 18, 6, 30), 270,
            ["github_https", "github_ssh"], "TimeoutError: a, b \"c\"",
        )
        ongoing = outage(
            "internet", utc(2026, 10, 6, 19, 10, 0), None, 60, ["direct", "web"], None,
        )
        path = os.path.join(self.tmp.name, "out.csv")
        report.write_csv([closed, ongoing], path, utc(2026, 10, 6, 19, 11, 0))
        self.assertEqual(
            self.read(path),
            [
                ["type", "start", "end", "length_seconds", "failed_targets", "sample_error"],
                ["github", "2026-10-06 14:02:00", "2026-10-06 14:06:30", "270",
                 "github_https github_ssh", "TimeoutError: a, b \"c\""],
                ["internet", "2026-10-06 15:10:00", "ongoing", "60", "direct web", ""],
            ],
        )

    def test_overwrites_existing_file(self):
        path = os.path.join(self.tmp.name, "out.csv")
        with open(path, "w") as f:
            f.write("stale,content\n" * 10)
        report.write_csv([], path, utc(2026, 10, 6, 19, 11, 0))
        self.assertEqual(
            self.read(path),
            [["type", "start", "end", "length_seconds", "failed_targets", "sample_error"]],
        )


class MainCsvTest(TZCase):
    def two_outage_db(self):
        down = {"router": (0, "OSError: down, hard")}
        net = {"direct": (0, "OSError: net"), "web": (0, "OSError: net")}
        self.build(
            [(utc(2026, 10, 6, 18, 2, 0) + timedelta(seconds=30 * i), down) for i in range(3)]
            + [(utc(2026, 10, 6, 18, 3, 30) + timedelta(seconds=30 * i), {}) for i in range(3)]
            + [(utc(2026, 10, 6, 18, 5, 0) + timedelta(seconds=30 * i), net) for i in range(3)]
        )
        return utc(2026, 10, 6, 18, 6, 30)

    def check(self, since_args, expected_types):
        now = self.two_outage_db()
        csv_path = os.path.join(self.tmp.name, "out.csv")
        code, out, err = self.run_main(
            ["--db", self.path, *since_args, "--csv", csv_path], now
        )
        self.assertEqual(code, 0, err)
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0][0], "type")
        printed = []
        for line in out.splitlines()[1:]:
            if not line:
                break
            printed.append(line.split()[:3])
        self.assertEqual([r[0] for r in rows[1:]], expected_types)
        self.assertEqual(
            [[r[0], *r[1].split()] for r in rows[1:]], printed
        )
        return rows

    def test_csv_matches_printed_report(self):
        rows = self.check([], ["local", "internet"])
        self.assertEqual(rows[1][2], "2026-10-06 14:03:30")
        self.assertEqual(rows[2][2], "ongoing")
        self.assertEqual(rows[1][5], "OSError: down, hard")

    def test_csv_respects_since(self):
        self.check(["--since", "2026-10-06T14:04"], ["internet"])


if __name__ == "__main__":
    unittest.main()
