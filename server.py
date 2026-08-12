"""Scrum Poker - a tiny real-time planning poker server.

Pure Python standard library (no dependencies).
Run:  python server.py [--port 8000] [--host 0.0.0.0]
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote_plus, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

DECK = ["0.25", "0.5", "1", "2", "3", "5", "8", "13", "21+", "coffee"]
# Cards without a plain number of their own: "coffee" means "skip / I pass" and is
# ignored in the statistics, "21+" counts as 21 so it still shapes the average.
CARD_VALUES = {"21+": 21.0, "coffee": None}
ROLES = ("product_owner", "technical_operations")

MAX_NAME_LENGTH = 24
HEARTBEAT_SECONDS = 15
STALE_USER_SECONDS = 40


def card_value(card: str | None) -> float | None:
    """Numeric weight of a card, or None if it does not count for the statistics."""
    if card is None:
        return None
    if card in CARD_VALUES:
        return CARD_VALUES[card]
    try:
        return float(card)
    except ValueError:
        return None


class Room:
    """In-memory state of the single poker room."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._users: dict[str, dict] = {}
        self._subscribers: dict[str, queue.Queue] = {}
        self._revealed = False
        self._round = 1

    # ---------------------------------------------------------------- users
    def join(self, name: str, role: str) -> str:
        name = (name or "").strip()[:MAX_NAME_LENGTH] or "Anonymous"
        if role not in ROLES:
            role = "technical_operations"
        token = secrets.token_urlsafe(16)
        with self._lock:
            self._users[token] = {
                "id": token[:8],
                "name": name,
                "role": role,
                "vote": None,
                "last_seen": time.time(),
                "joined_at": time.time(),
            }
        self.broadcast()
        return token

    def leave(self, token: str) -> None:
        with self._lock:
            existed = self._users.pop(token, None) is not None
        if existed:
            self.broadcast()

    def remove_participant(self, token: str, participant_id: str) -> bool:
        """Product Owner removes somebody else from the table."""
        if not self.is_product_owner(token):
            return False
        with self._lock:
            target = next(
                (t for t, u in self._users.items() if u["id"] == participant_id),
                None,
            )
            if target is None or target == token:
                return False
            del self._users[target]
        self.broadcast()
        return True

    def touch(self, token: str) -> bool:
        with self._lock:
            user = self._users.get(token)
            if user is None:
                return False
            user["last_seen"] = time.time()
            return True

    def rename(self, token: str, name: str) -> bool:
        name = (name or "").strip()[:MAX_NAME_LENGTH]
        if not name:
            return False
        with self._lock:
            user = self._users.get(token)
            if user is None:
                return False
            user["name"] = name
        self.broadcast()
        return True

    # ---------------------------------------------------------------- votes
    def vote(self, token: str, card: str | None) -> bool:
        with self._lock:
            user = self._users.get(token)
            if user is None:
                return False
            if self._revealed:
                return False
            if card is not None and card not in DECK:
                return False
            user["vote"] = None if user["vote"] == card else card
            user["last_seen"] = time.time()
        self.broadcast()
        return True

    def is_product_owner(self, token: str) -> bool:
        with self._lock:
            user = self._users.get(token)
            return bool(user and user["role"] == "product_owner")

    def reveal(self, token: str) -> bool:
        if not self.is_product_owner(token):
            return False
        with self._lock:
            self._revealed = True
        self.broadcast()
        return True

    def reset(self, token: str) -> bool:
        if not self.is_product_owner(token):
            return False
        with self._lock:
            self._revealed = False
            self._round += 1
            for user in self._users.values():
                user["vote"] = None
        self.broadcast()
        return True

    # ---------------------------------------------------------------- state
    def snapshot(self) -> dict:
        with self._lock:
            participants = [
                {
                    "id": user["id"],
                    "name": user["name"],
                    "role": user["role"],
                    "hasVoted": user["vote"] is not None,
                    "vote": user["vote"] if self._revealed else None,
                }
                for user in sorted(self._users.values(), key=lambda u: u["joined_at"])
            ]
            counted = [
                (card_value(u["vote"]), u["vote"])
                for u in self._users.values()
                if card_value(u["vote"]) is not None
            ]
            stats = None
            if self._revealed and counted:
                numbers = [value for value, _ in counted]
                stats = {
                    "average": round(sum(numbers) / len(numbers), 2),
                    "min": min(counted)[1],
                    "max": max(counted)[1],
                    "consensus": len({card for _, card in counted}) == 1,
                }
            return {
                "deck": DECK,
                "revealed": self._revealed,
                "round": self._round,
                "participants": participants,
                "votedCount": sum(1 for p in participants if p["hasVoted"]),
                "stats": stats,
            }

    def personal_state(self, token: str) -> dict:
        state = self.snapshot()
        with self._lock:
            user = self._users.get(token)
            state["you"] = (
                None
                if user is None
                else {
                    "id": user["id"],
                    "name": user["name"],
                    "role": user["role"],
                    "vote": user["vote"],
                }
            )
        return state

    # ------------------------------------------------------------ broadcast
    def subscribe(self, token: str) -> queue.Queue:
        channel: queue.Queue = queue.Queue(maxsize=32)
        with self._lock:
            self._subscribers[token + ":" + secrets.token_hex(4)] = channel
        return channel

    def unsubscribe(self, channel: queue.Queue) -> None:
        with self._lock:
            for key, value in list(self._subscribers.items()):
                if value is channel:
                    del self._subscribers[key]

    def broadcast(self) -> None:
        with self._lock:
            channels = list(self._subscribers.items())
        for key, channel in channels:
            token = key.split(":", 1)[0]
            try:
                channel.put_nowait(self.personal_state(token))
            except queue.Full:
                pass

    # ---------------------------------------------------------------- reaper
    def drop_stale_users(self) -> None:
        now = time.time()
        removed = False
        with self._lock:
            for token, user in list(self._users.items()):
                if now - user["last_seen"] > STALE_USER_SECONDS:
                    del self._users[token]
                    removed = True
        if removed:
            self.broadcast()


ROOM = Room()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ScrumPoker/1.0"

    def log_message(self, fmt: str, *args) -> None:  # keep the console readable
        pass

    # ------------------------------------------------------------- helpers
    def _token(self) -> str:
        header = self.headers.get("X-Poker-Token", "")
        if header:
            return header
        # sendBeacon() cannot set headers, so allow ?token=... as a fallback.
        return self._query().get("token", "")

    def _query(self) -> dict[str, str]:
        raw = urlparse(self.path).query
        return {
            key: unquote_plus(value)
            for key, value in (
                part.split("=", 1) for part in raw.split("&") if "=" in part
            )
        }

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")) or {}
        except (ValueError, UnicodeDecodeError):
            return {}

    # ----------------------------------------------------------------- GET
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/state":
            self._send_json(ROOM.personal_state(self._token()))
        elif path == "/api/events":
            self._serve_events()
        else:
            self._serve_static(path)

    def _serve_static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"
        relative = os.path.normpath(path.lstrip("/")).replace("\\", "/")
        if relative.startswith("..") or os.path.isabs(relative):
            self._send_json({"error": "not found"}, 404)
            return
        file_path = os.path.join(STATIC_DIR, relative)
        if not os.path.isfile(file_path):
            self._send_json({"error": "not found"}, 404)
            return
        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        with open(file_path, "rb") as handle:
            body = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _serve_events(self) -> None:
        token = self._query().get("token", "")
        channel = ROOM.subscribe(token)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self._write_event(ROOM.personal_state(token))
            while True:
                try:
                    state = channel.get(timeout=HEARTBEAT_SECONDS)
                    self._write_event(state)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                ROOM.touch(token)
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            pass
        finally:
            ROOM.unsubscribe(channel)

    def _write_event(self, state: dict) -> None:
        payload = json.dumps(state)
        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()

    # ---------------------------------------------------------------- POST
    def do_POST(self) -> None:
        path = urlparse(self.path).path
        data = self._read_json()
        token = self._token()

        if path == "/api/join":
            new_token = ROOM.join(data.get("name", ""), data.get("role", ""))
            self._send_json({"token": new_token, "state": ROOM.personal_state(new_token)})
        elif path == "/api/rename":
            ok = ROOM.rename(token, data.get("name", ""))
            self._send_json({"ok": ok, "state": ROOM.personal_state(token)}, 200 if ok else 400)
        elif path == "/api/vote":
            if not ROOM.touch(token):
                self._send_json({"error": "unknown session"}, 401)
                return
            ok = ROOM.vote(token, data.get("card"))
            self._send_json({"ok": ok, "state": ROOM.personal_state(token)})
        elif path == "/api/reveal":
            ok = ROOM.reveal(token)
            self._send_json({"ok": ok, "state": ROOM.personal_state(token)}, 200 if ok else 403)
        elif path == "/api/reset":
            ok = ROOM.reset(token)
            self._send_json({"ok": ok, "state": ROOM.personal_state(token)}, 200 if ok else 403)
        elif path == "/api/leave":
            ROOM.leave(token)
            self._send_json({"ok": True})
        elif path == "/api/remove":
            ok = ROOM.remove_participant(token, str(data.get("id", "")))
            self._send_json({"ok": ok}, 200 if ok else 403)
        else:
            self._send_json({"error": "not found"}, 404)


def _reaper_loop() -> None:
    while True:
        time.sleep(10)
        ROOM.drop_stale_users()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrum Poker server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    args = parser.parse_args()

    threading.Thread(target=_reaper_loop, daemon=True).start()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"Scrum Poker running on http://localhost:{args.port}  (bound to {args.host})")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
