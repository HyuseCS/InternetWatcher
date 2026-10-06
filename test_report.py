import unittest
from datetime import datetime, timedelta, timezone

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
