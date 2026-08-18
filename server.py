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

DECK = ["0.125", "0.25", "0.5", "1", "2", "3", "5", "8", "13", "21+", "coffee"]
# Cards without a plain number of their own: "coffee" means "skip / I pass" and is
# ignored in the statistics, "21+" counts as 21 so it still shapes the average.
CARD_VALUES = {"21+": 21.0, "coffee": None}
ROLES = ("product_owner", "technical_operations")

MAX_NAME_LENGTH = 24
MAX_ROOM_CODE_LENGTH = 16
HEARTBEAT_SECONDS = 15
STALE_USER_SECONDS = 40

# The room code travels in the URL, so keep it to characters that survive that.
ROOM_CODE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
TOKEN_SEPARATOR = "~"


def normalize_room_code(raw: str | None) -> str:
    """Room codes are case-insensitive: 'team42' and 'TEAM42' are one table."""
    cleaned = "".join(c for c in (raw or "").strip().upper() if c in ROOM_CODE_CHARS)
    return cleaned[:MAX_ROOM_CODE_LENGTH]


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
    """In-memory state of one poker table."""

    def __init__(self, code: str = "TABLE") -> None:
        self.code = code
        self._lock = threading.RLock()
        self._users: dict[str, dict] = {}
        self._subscribers: dict[str, queue.Queue] = {}
        self._revealed = False
        self._round = 1

    @property
    def empty(self) -> bool:
        with self._lock:
            return not self._users

    # ---------------------------------------------------------------- users
    def join(self, name: str, role: str) -> str:
        name = (name or "").strip()[:MAX_NAME_LENGTH] or "Anonymous"
        if role not in ROLES:
            role = "technical_operations"
        # The room code is part of the token, so any request identifies its table.
        token = f"{self.code}{TOKEN_SEPARATOR}{secrets.token_urlsafe(16)}"
        with self._lock:
            self._users[token] = {
                "id": secrets.token_hex(4),
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
                self._reset_if_empty()
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
            self._reset_if_empty()
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
            if user["role"] == "product_owner":
                return False  # the Product Owner facilitates, they do not estimate
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

    def restart(self, token: str) -> bool:
        """Product Owner starts the whole session over: back to round 1."""
        if not self.is_product_owner(token):
            return False
        with self._lock:
            self._revealed = False
            self._round = 1
            for user in self._users.values():
                user["vote"] = None
        self.broadcast()
        return True

    def _reset_if_empty(self) -> None:
        """Nobody left at the table -> the next arrival starts at round 1.

        Must be called while holding the lock.
        """
        if not self._users:
            self._revealed = False
            self._round = 1

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
                    # 3 decimals so an average of 0.125 cards does not collapse to 0.12
                    "average": round(sum(numbers) / len(numbers), 3),
                    "min": min(counted)[1],
                    "max": max(counted)[1],
                    "consensus": len({card for _, card in counted}) == 1,
                }
            return {
                "room": self.code,
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
                self._reset_if_empty()
        if removed:
            self.broadcast()


class Rooms:
    """Every team gets its own table, addressed by a short code like TEAM42."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rooms: dict[str, Room] = {}

    def join(self, code: str, name: str, role: str) -> str | None:
        """Create the table if needed and seat somebody, in one atomic step.

        Doing both under the lock keeps the reaper from deleting a brand new
        table before its first participant has arrived.
        """
        code = normalize_room_code(code)
        if not code:
            return None
        with self._lock:
            room = self._rooms.get(code)
            if room is None:
                room = Room(code)
                self._rooms[code] = room
            return room.join(name, role)

    def get(self, code: str) -> Room | None:
        code = normalize_room_code(code)
        with self._lock:
            return self._rooms.get(code) if code else None

    def for_token(self, token: str) -> Room | None:
        if not token or TOKEN_SEPARATOR not in token:
            return None
        return self.get(token.split(TOKEN_SEPARATOR, 1)[0])

    def codes(self) -> list[str]:
        with self._lock:
            return sorted(self._rooms)

    def drop_stale_users(self) -> None:
        with self._lock:
            rooms = list(self._rooms.items())
        for _, room in rooms:
            room.drop_stale_users()
        with self._lock:
            for code, room in rooms:
                if room.empty and self._rooms.get(code) is room:
                    del self._rooms[code]


ROOMS = Rooms()

# Everything below needs a seat at a table (the token says which one).
TABLE_ENDPOINTS = frozenset(
    {"/api/rename", "/api/vote", "/api/reveal", "/api/reset", "/api/restart", "/api/remove"}
)


def empty_state(code: str) -> dict:
    """State for somebody who is not seated yet - the deck, and nothing else."""
    room = ROOMS.get(code)
    if room is not None:
        state = room.personal_state("")
        state["exists"] = True
        return state
    state = Room(normalize_room_code(code)).personal_state("")
    state["exists"] = False
    return state


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
            token = self._token()
            room = ROOMS.for_token(token)
            if room is None:
                self._send_json(empty_state(self._query().get("room", "")))
            else:
                self._send_json(room.personal_state(token))
        elif path == "/api/events":
            self._serve_events()
        else:
            self._serve_static(path)

    def _serve_static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"
        # /table/TEAM42 is a shareable link, not a file - the app reads the code
        # from the URL and joins that table.
        if path == "/table" or path.startswith("/table/"):
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
        room = ROOMS.for_token(token)
        if room is None:
            self._send_json({"error": "unknown table"}, 404)
            return
        channel = room.subscribe(token)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self._write_event(room.personal_state(token))
            while True:
                try:
                    state = channel.get(timeout=HEARTBEAT_SECONDS)
                    self._write_event(state)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                room.touch(token)
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            pass
        finally:
            room.unsubscribe(channel)

    def _write_event(self, state: dict) -> None:
        payload = json.dumps(state)
        self.wfile.write(f"data: {payload}\n\n".encode())
        self.wfile.flush()

    # ---------------------------------------------------------------- POST
    def do_POST(self) -> None:
        path = urlparse(self.path).path
        data = self._read_json()
        token = self._token()

        if path == "/api/join":
            code = normalize_room_code(data.get("room", ""))
            if not code:
                self._send_json({"error": "a team ID is required"}, 400)
                return
            new_token = ROOMS.join(code, data.get("name", ""), data.get("role", ""))
            room = ROOMS.for_token(new_token)
            if room is None:
                self._send_json({"error": "could not open the table"}, 500)
                return
            self._send_json({"token": new_token, "state": room.personal_state(new_token)})
            return

        if path == "/api/leave":
            room = ROOMS.for_token(token)
            if room is not None:
                room.leave(token)
            self._send_json({"ok": True})
            return

        room = ROOMS.for_token(token)
        if path not in TABLE_ENDPOINTS:
            self._send_json({"error": "not found"}, 404)
            return
        if room is None:
            self._send_json({"error": "unknown session"}, 401)
            return

        if path == "/api/rename":
            ok = room.rename(token, data.get("name", ""))
            self._send_json({"ok": ok, "state": room.personal_state(token)}, 200 if ok else 400)
        elif path == "/api/vote":
            if not room.touch(token):
                self._send_json({"error": "unknown session"}, 401)
                return
            ok = room.vote(token, data.get("card"))
            self._send_json({"ok": ok, "state": room.personal_state(token)})
        elif path == "/api/reveal":
            ok = room.reveal(token)
            self._send_json({"ok": ok, "state": room.personal_state(token)}, 200 if ok else 403)
        elif path == "/api/reset":
            ok = room.reset(token)
            self._send_json({"ok": ok, "state": room.personal_state(token)}, 200 if ok else 403)
        elif path == "/api/restart":
            ok = room.restart(token)
            self._send_json({"ok": ok, "state": room.personal_state(token)}, 200 if ok else 403)
        elif path == "/api/remove":
            ok = room.remove_participant(token, str(data.get("id", "")))
            self._send_json({"ok": ok}, 200 if ok else 403)
        else:
            self._send_json({"error": "not found"}, 404)


def _reaper_loop() -> None:
    while True:
        time.sleep(10)
        ROOMS.drop_stale_users()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrum Poker server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8000))
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
