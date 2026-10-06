import os
import pathlib
import re
import socket
import sqlite3
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
