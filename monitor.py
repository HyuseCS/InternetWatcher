import functools
import http.client
import os
import pathlib
import socket
import sqlite3
import time

SCHEMA = """
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
"""


def default_db_path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return pathlib.Path(base) / "internettester" / "checks.db"


def open_db(path):
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def save_result(conn, round_at, interval_s, result):
    with conn:
        conn.execute(
            "INSERT INTO checks (round_at, interval_s, target, check_type, ok, latency_ms, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (round_at, interval_s, *result),
        )


class NoRoute(Exception):
    pass


class HTTPStatus(Exception):
    pass


def default_gateway(route_path="/proc/net/route"):
    with open(route_path) as f:
        next(f)
        for line in f:
            fields = line.split()
            if len(fields) > 2 and fields[1] == "00000000":
                return socket.inet_ntoa(int(fields[2], 16).to_bytes(4, "little"))
    return None


def check_router(timeout):
    gw = default_gateway()
    if gw is None:
        raise NoRoute("no default route")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP) as s:
        s.settimeout(timeout)
        s.sendto(b"\x08\x00\x00\x00\x00\x00\x00\x01", (gw, 0))
        data, _ = s.recvfrom(1024)
    if data[0] != 0:
        raise ValueError(f"ICMP type {data[0]} code {data[1]}")


def check_dns(timeout):
    socket.getaddrinfo("github.com", 443, type=socket.SOCK_STREAM)


def check_direct(timeout):
    with socket.create_connection(("1.1.1.1", 443), timeout):
        pass


def check_https(host, timeout):
    conn = http.client.HTTPSConnection(host, timeout=timeout)
    try:
        conn.request("HEAD", "/")
        r = conn.getresponse()
    finally:
        conn.close()
    if r.status >= 400:
        raise HTTPStatus(f"{r.status} {r.reason}")


def check_ssh(timeout):
    with socket.create_connection(("github.com", 22), timeout) as s:
        data = s.recv(64)
    if not data.startswith(b"SSH-"):
        raise ValueError(f"not an SSH banner: {data[:32]!r}")


def run_check(target, check_type, fn, timeout):
    start = time.monotonic()
    try:
        fn(timeout)
    except Exception as e:
        return (target, check_type, 0, None, f"{type(e).__name__}: {e}")
    return (target, check_type, 1, (time.monotonic() - start) * 1000, None)


TARGETS = [
    ("router", "icmp", check_router),
    ("dns", "dns", check_dns),
    ("direct", "tcp", check_direct),
    ("web", "https", functools.partial(check_https, "google.com")),
    ("github_https", "https", functools.partial(check_https, "github.com")),
    ("github_ssh", "ssh", check_ssh),
]
