"""End-to-end tests: start the real server and talk HTTP to it.

Standard library only - run with:  python -m unittest discover -s tests -v
"""

import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ServerTests(unittest.TestCase):
    process = None
    base = ""

    @classmethod
    def setUpClass(cls):
        port = free_port()
        cls.base = f"http://127.0.0.1:{port}"
        cls.process = subprocess.Popen(
            [sys.executable, "server.py", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        # Proxies must not swallow requests to our own loopback server.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        urllib.request.install_opener(opener)

        deadline = time.time() + 30
        while time.time() < deadline:
            if cls.process.poll() is not None:
                raise RuntimeError("server exited during startup")
            try:
                urllib.request.urlopen(cls.base + "/api/state", timeout=2).read()
                return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError("server did not start in time")

    @classmethod
    def tearDownClass(cls):
        if cls.process:
            cls.process.terminate()
            try:
                cls.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.process.kill()

    # ------------------------------------------------------------- helpers
    def get(self, path, token=""):
        request = urllib.request.Request(self.base + path)
        if token:
            request.add_header("X-Poker-Token", token)
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def post(self, path, payload=None, token=""):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        if token:
            request.add_header("X-Poker-Token", token)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8") or "{}")

    def join(self, name, role):
        status, data = self.post("/api/join", {"name": name, "role": role})
        self.assertEqual(status, 200)
        return data["token"]

    # --------------------------------------------------------------- tests
    def test_index_page_is_served(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as response:
            body = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Scrum Poker", body)

    def test_static_assets_are_served(self):
        for path, needle in (("/app.js", "STORAGE_KEY"), ("/style.css", ".seat")):
            with urllib.request.urlopen(self.base + path, timeout=10) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(needle, response.read().decode("utf-8"))

    def test_directory_traversal_is_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + "/../server.py", timeout=10)
        self.assertEqual(caught.exception.code, 404)

    def test_deck_is_exposed(self):
        self.assertEqual(
            self.get("/api/state")["deck"],
            ["0.25", "0.5", "1", "2", "3", "5", "8", "13", "21+", "coffee"],
        )

    def test_full_round(self):
        po = self.join("PO", "product_owner")
        dev = self.join("Dev", "technical_operations")

        status, _ = self.post("/api/vote", {"card": "5"}, token=dev)
        self.assertEqual(status, 200)

        # A Technical Operations member must not be able to reveal.
        status, _ = self.post("/api/reveal", token=dev)
        self.assertEqual(status, 403)

        status, _ = self.post("/api/reveal", token=po)
        self.assertEqual(status, 200)

        state = self.get("/api/state", token=po)
        self.assertTrue(state["revealed"])
        voted = next(p for p in state["participants"] if p["name"] == "Dev")
        self.assertEqual(voted["vote"], "5")

        self.post("/api/reset", token=po)
        self.post("/api/leave", token=po)
        self.post("/api/leave", token=dev)

    def test_vote_with_unknown_token_is_rejected(self):
        status, _ = self.post("/api/vote", {"card": "5"}, token="bogus")
        self.assertEqual(status, 401)

    def test_restart_is_product_owner_only_and_empties_the_room(self):
        po = self.join("PO", "product_owner")
        dev = self.join("Dev", "technical_operations")

        self.post("/api/reset", token=po)
        self.assertEqual(self.get("/api/state", token=po)["round"], 2)

        status, _ = self.post("/api/restart", token=dev)
        self.assertEqual(status, 403)

        status, _ = self.post("/api/restart", token=po)
        self.assertEqual(status, 200)
        self.assertEqual(self.get("/api/state", token=po)["round"], 1)

        # Everybody leaving must bring the room back to a clean round 1.
        self.post("/api/reset", token=po)
        self.post("/api/leave", token=po)
        self.post("/api/leave", token=dev)

        state = self.get("/api/state")
        self.assertEqual(state["participants"], [])
        self.assertEqual(state["round"], 1)
        self.assertFalse(state["revealed"])

    def test_unknown_endpoint_returns_404(self):
        status, _ = self.post("/api/does-not-exist")
        self.assertEqual(status, 404)

    def test_event_stream_sends_initial_state(self):
        token = self.join("Streamer", "technical_operations")
        request = urllib.request.Request(f"{self.base}/api/events?token={token}")
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertIn("text/event-stream", response.headers["Content-Type"])
            for raw in response:
                line = raw.decode("utf-8").strip()
                if line.startswith("data:"):
                    payload = json.loads(line[5:])
                    self.assertEqual(payload["you"]["name"], "Streamer")
                    break
        self.post("/api/leave", token=token)


if __name__ == "__main__":
    unittest.main()
