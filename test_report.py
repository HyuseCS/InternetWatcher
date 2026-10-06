import unittest

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


if __name__ == "__main__":
    unittest.main()
