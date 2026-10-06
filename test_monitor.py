import contextlib
import io
import os
import pathlib
import re
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

import monitor

_patches = []


def setUpModule():
    for target in ("socket.socket.connect", "socket.socket.sendto",
                   "socket.create_connection", "socket.getaddrinfo"):
        p = mock.patch(target, side_effect=RuntimeError("real network in test"))
        p.start()
        _patches.append(p)


def tearDownModule():
    for p in _patches:
        p.stop()
    _patches.clear()


class TempDirCase(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = td.name
        self.path = os.path.join(self.dir, "new", "sub", "checks.db")


class OpenDbTests(TempDirCase):
    def test_creates_folder_file_table_index(self):
        conn = monitor.open_db(self.path)
        self.addCleanup(conn.close)
        self.assertTrue(os.path.isfile(self.path))
        cols = conn.execute("PRAGMA table_info(checks)").fetchall()
        self.assertEqual(
            [(c[1], c[2], c[3], c[5]) for c in cols],
            [("id", "INTEGER", 0, 1),
             ("round_at", "TEXT", 1, 0),
             ("interval_s", "INTEGER", 1, 0),
             ("target", "TEXT", 1, 0),
             ("check_type", "TEXT", 1, 0),
             ("ok", "INTEGER", 1, 0),
             ("latency_ms", "REAL", 0, 0),
             ("error", "TEXT", 0, 0)],
        )
        idx = conn.execute(
            "SELECT tbl_name, sql FROM sqlite_master "
            "WHERE type='index' AND name='checks_round_at'").fetchone()
        self.assertEqual(idx[0], "checks")
        self.assertIn("round_at", idx[1])

    def test_reopen_keeps_rows(self):
        conn = monitor.open_db(self.path)
        monitor.save_result(conn, "2026-10-06T05:41:48+00:00", 30,
                            ("router", "icmp", 1, 3.5, None))
        conn.close()
        conn = monitor.open_db(self.path)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM checks").fetchone()[0], 1)


class SaveResultTests(TempDirCase):
    def test_insert_and_commit_visible_to_second_connection(self):
        conn = monitor.open_db(self.path)
        self.addCleanup(conn.close)
        monitor.save_result(conn, "2026-10-06T05:41:48+00:00", 30,
                            ("dns", "dns", 0, None, "gaierror: boom"))
        other = sqlite3.connect(self.path)
        self.addCleanup(other.close)
        rows = other.execute(
            "SELECT round_at, interval_s, target, check_type, ok, latency_ms, error "
            "FROM checks").fetchall()
        self.assertEqual(
            rows,
            [("2026-10-06T05:41:48+00:00", 30, "dns", "dns", 0, None, "gaierror: boom")])

    def test_ok_outside_0_1_rejected(self):
        conn = monitor.open_db(self.path)
        self.addCleanup(conn.close)
        with self.assertRaises(sqlite3.IntegrityError):
            monitor.save_result(conn, "2026-10-06T05:41:48+00:00", 30,
                                ("router", "icmp", 2, 1.0, None))


class DefaultDbPathTests(unittest.TestCase):
    def test_xdg_data_home(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/xdg/data"}):
            self.assertEqual(str(monitor.default_db_path()),
                             "/xdg/data/internettester/checks.db")

    def test_home_fallback(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_DATA_HOME"}
        env["HOME"] = "/home/someone"
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(str(monitor.default_db_path()),
                             "/home/someone/.local/share/internettester/checks.db")


class SourceScanTests(unittest.TestCase):
    def test_no_destructive_sql(self):
        root = pathlib.Path(__file__).parent
        for name in ("monitor.py", "report.py"):
            text = (root / name).read_text()
            for pat in (r"\bDROP\s+TABLE\b", r"\bDELETE\s+FROM\b"):
                self.assertIsNone(re.search(pat, text, re.IGNORECASE),
                                  f"{name} matches {pat}")


ROUTE_HEADER = "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"


class DefaultGatewayTests(TempDirCase):
    def _route(self, body):
        path = os.path.join(self.dir, "route")
        with open(path, "w") as f:
            f.write(ROUTE_HEADER + body)
        return path

    def test_default_route_gateway(self):
        path = self._route(
            "wlan0\t0000D20A\t00000000\t0001\t0\t0\t600\t0000FFFF\t0\t0\t0\n"
            "wlan0\t00000000\t0100D20A\t0003\t0\t0\t600\t00000000\t0\t0\t0\n")
        self.assertEqual(monitor.default_gateway(path), "10.210.0.1")

    def test_no_default_route(self):
        path = self._route(
            "wlan0\t0000D20A\t00000000\t0001\t0\t0\t600\t0000FFFF\t0\t0\t0\n")
        self.assertIsNone(monitor.default_gateway(path))


def fake_sock(**attrs):
    s = mock.MagicMock()
    s.__enter__.return_value = s
    for k, v in attrs.items():
        getattr(s, k).configure_mock(**v)
    return s


class CheckRouterTests(unittest.TestCase):
    def test_no_route(self):
        with mock.patch("monitor.default_gateway", return_value=None):
            with self.assertRaises(Exception) as cm:
                monitor.check_router(1)
        self.assertEqual(f"{type(cm.exception).__name__}: {cm.exception}",
                         "NoRoute: no default route")

    def _run(self, **recvfrom):
        s = fake_sock(recvfrom=recvfrom)
        with mock.patch("monitor.default_gateway", return_value="10.210.0.1"), \
                mock.patch("socket.socket", return_value=s):
            monitor.check_router(1)
        return s

    def test_echo_reply_succeeds(self):
        s = self._run(return_value=(b"\x00\x00\x00\x00\x00\x01\x00\x01", ("10.210.0.1", 0)))
        self.assertTrue(s.sendto.called)
        self.assertEqual(s.sendto.call_args[0][0][0], 8)
        self.assertEqual(s.sendto.call_args[0][1][0], "10.210.0.1")

    def test_other_type_raises(self):
        with self.assertRaises(Exception) as cm:
            self._run(return_value=(b"\x03\x01\x00\x00", ("10.210.0.1", 0)))
        self.assertNotIsInstance(cm.exception, AttributeError)

    def test_timeout_raises(self):
        with self.assertRaises(TimeoutError):
            self._run(side_effect=TimeoutError("timed out"))


class RunCheckTests(unittest.TestCase):
    def test_success(self):
        r = monitor.run_check("dns", "dns", lambda t: None, 5)
        self.assertEqual(r[:3], ("dns", "dns", 1))
        self.assertGreaterEqual(r[3], 0)
        self.assertIsNone(r[4])

    def test_failure_text(self):
        import socket as sk
        for exc, text in (
                (sk.gaierror(-3, "Temporary failure in name resolution"),
                 "gaierror: [Errno -3] Temporary failure in name resolution"),
                (TimeoutError("timed out"), "TimeoutError: timed out")):
            def fn(t, exc=exc):
                raise exc
            self.assertEqual(monitor.run_check("x", "y", fn, 5),
                             ("x", "y", 0, None, text))


class CheckHttpsTests(unittest.TestCase):
    def _check(self, status, reason=""):
        conn = mock.MagicMock()
        conn.getresponse.return_value = mock.Mock(status=status, reason=reason)
        with mock.patch("http.client.HTTPSConnection", return_value=conn) as cls:
            monitor.check_https("example.com", 3)
        self.assertEqual(cls.call_args[0][0], "example.com")
        self.assertEqual(conn.request.call_args[0][:2], ("HEAD", "/"))

    def test_200_and_301_succeed(self):
        self._check(200, "OK")
        self._check(301, "Moved Permanently")

    def test_503_raises(self):
        with self.assertRaises(Exception) as cm:
            self._check(503, "Service Unavailable")
        self.assertEqual(f"{type(cm.exception).__name__}: {cm.exception}",
                         "HTTPStatus: 503 Service Unavailable")


class CheckSshTests(unittest.TestCase):
    def _check(self, banner):
        s = fake_sock(recv={"return_value": banner})
        with mock.patch("socket.create_connection", return_value=s) as cc:
            monitor.check_ssh(3)
        self.assertEqual(cc.call_args[0][0], ("github.com", 22))

    def test_ssh_banner_succeeds(self):
        self._check(b"SSH-2.0-x\r\n")

    def test_http_banner_raises(self):
        with self.assertRaises(Exception) as cm:
            self._check(b"HTTP/1.1")
        self.assertNotIsInstance(cm.exception, AttributeError)


class CheckDirectDnsTests(unittest.TestCase):
    def test_direct_connects_to_cloudflare(self):
        with mock.patch("socket.create_connection", return_value=fake_sock()) as cc:
            monitor.check_direct(3)
        self.assertEqual(cc.call_args[0][0], ("1.1.1.1", 443))

    def test_dns_resolves_github(self):
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("1.2.3.4", 443))]) as g:
            monitor.check_dns(3)
        self.assertEqual(g.call_args[0][:2], ("github.com", 443))


class TargetsTests(unittest.TestCase):
    def test_exact_targets(self):
        self.assertEqual(
            [(t[0], t[1]) for t in monitor.TARGETS],
            [("router", "icmp"), ("dns", "dns"), ("direct", "tcp"),
             ("web", "https"), ("github_https", "https"), ("github_ssh", "ssh")])


class RunRoundTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.conn = monitor.open_db(self.path)
        self.addCleanup(self.conn.close)

    def _rows(self):
        other = sqlite3.connect(self.path)
        self.addCleanup(other.close)
        return other.execute(
            "SELECT round_at, interval_s, target, check_type, ok, latency_ms, error "
            "FROM checks ORDER BY target").fetchall()

    def test_one_row_per_target_same_round_at(self):
        targets = [("a", "tcp", lambda t: None), ("b", "dns", lambda t: None),
                   ("c", "https", lambda t: None)]
        monitor.run_round(self.conn, 45, targets)
        rows = self._rows()
        self.assertEqual([(r[2], r[3], r[4]) for r in rows],
                         [("a", "tcp", 1), ("b", "dns", 1), ("c", "https", 1)])
        self.assertEqual(len({r[0] for r in rows}), 1)
        self.assertEqual({r[1] for r in rows}, {45})
        round_at = rows[0][0]
        self.assertRegex(round_at, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        parsed = datetime.fromisoformat(round_at)
        self.assertLess(abs((datetime.now(timezone.utc) - parsed).total_seconds()), 30)

    def test_raising_check_saved_as_failure_others_saved(self):
        def boom(t):
            raise ValueError("boom")
        targets = [("a", "tcp", lambda t: None), ("b", "dns", boom),
                   ("c", "https", lambda t: None)]
        monitor.run_round(self.conn, 30, targets)
        rows = {r[2]: r for r in self._rows()}
        self.assertEqual(set(rows), {"a", "b", "c"})
        self.assertEqual((rows["b"][4], rows["b"][5], rows["b"][6]),
                         (0, None, "ValueError: boom"))
        self.assertEqual((rows["a"][4], rows["c"][4]), (1, 1))

    def test_blocking_check_times_out_at_deadline(self):
        release = threading.Event()
        self.addCleanup(release.set)
        targets = [("a", "tcp", lambda t: None),
                   ("b", "dns", lambda t: release.wait(30)),
                   ("c", "https", lambda t: None)]
        start = time.monotonic()
        monitor.run_round(self.conn, 30, targets, timeout=10, deadline=0.2)
        self.assertLess(time.monotonic() - start, 1)
        rows = {r[2]: r for r in self._rows()}
        self.assertEqual(set(rows), {"a", "b", "c"})
        self.assertEqual((rows["b"][4], rows["b"][5], rows["b"][6]),
                         (0, None, "TimeoutError: no result in 10s"))
        self.assertEqual((rows["a"][4], rows["c"][4]), (1, 1))

    def test_rows_committed_before_return(self):
        monitor.run_round(self.conn, 30, [("a", "tcp", lambda t: None)])
        self.assertEqual(len(self._rows()), 1)

    def test_write_failure_goes_to_stderr_others_saved(self):
        real = monitor.save_result

        def flaky(conn, round_at, interval_s, result):
            if result[0] == "b":
                raise sqlite3.OperationalError("disk full")
            return real(conn, round_at, interval_s, result)

        targets = [("a", "tcp", lambda t: None), ("b", "dns", lambda t: None),
                   ("c", "https", lambda t: None)]
        err = io.StringIO()
        with mock.patch("monitor.save_result", side_effect=flaky), \
                contextlib.redirect_stderr(err):
            monitor.run_round(self.conn, 30, targets)
        self.assertTrue(err.getvalue().startswith("write failed:"), err.getvalue())
        self.assertEqual([r[2] for r in self._rows()], ["a", "c"])


if __name__ == "__main__":
    unittest.main()
