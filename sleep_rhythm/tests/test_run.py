import json
import os
import socket
import subprocess
import sys
import unittest
import urllib.request
from pathlib import Path

import run

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never through a proxy


def launch(*args):
    return [sys.executable, "-u", str(ROOT / "run.py"), "--no-browser", *args]


class LauncherTests(unittest.TestCase):
    def test_windows_never_shares_the_port(self):
        # SO_REUSEADDR on Windows would let an older copy and a new copy answer at random.
        self.assertEqual(run.LocalServer.allow_reuse_address, os.name != "nt")

    def test_lan_addresses_are_plain_ipv4(self):
        for ip in run.lan_addresses():
            socket.inet_aton(ip)
            self.assertFalse(ip.startswith(("127.", "0.", "169.254.")), ip)

    def test_busy_port_explains_what_to_do(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            port = busy.getsockname()[1]
            r = subprocess.run(launch("--port", str(port)), cwd=ROOT, env=ENV, capture_output=True,
                               encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("서버를 열 수 없습니다", r.stderr)
        self.assertIn("예전 버전 포함", r.stderr)
        self.assertIn("--port 8001", r.stderr)
        self.assertNotIn("리듬 실행 주소", r.stdout)  # no address is announced for a server that never started

    def test_phone_mode_serves_and_shows_the_phone_address(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        p = subprocess.Popen(launch("--host", "0.0.0.0", "--port", str(port)), cwd=ROOT, env=ENV,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        out, err = p.stdout, p.stderr
        assert out is not None and err is not None
        try:
            lines = []
            while not lines or not lines[-1].startswith("종료"):
                line = out.readline()
                self.assertTrue(line, err.read() if p.poll() is not None else "no output")
                lines.append(line.rstrip("\n"))
            self.assertEqual(lines[0], f"리듬 실행 주소: http://127.0.0.1:{port}")
            phones = run.lan_addresses()
            if phones:
                self.assertEqual(lines[1], f"같은 Wi-Fi의 휴대폰에서 열 주소: http://{phones[0]}:{port}")
            for host in ["127.0.0.1", *phones[:1]]:
                with DIRECT.open(f"http://{host}:{port}/healthz", timeout=10) as r:
                    self.assertEqual(json.load(r)["status"], "ok")
        finally:
            p.terminate()
            p.wait(10)
            out.close()
            err.close()


if __name__ == "__main__":
    unittest.main()
