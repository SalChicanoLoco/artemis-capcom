"""Dependency-free fixture and authenticated Twitch TLS IRC transports."""
import os
import re
import socket
import ssl
import threading
import time
from pathlib import Path


class ChatMessage(str):
    """String-compatible command carrying a verified IRC prefix identity."""
    def __new__(cls, text, user="", commander=False):
        obj = super().__new__(cls, text)
        obj.user, obj.commander = user, commander
        return obj


class ChatTransport:
    def lines(self):
        raise NotImplementedError

    def reply(self, text):
        raise NotImplementedError


class FixtureTransport(ChatTransport):
    label = "MOCK"

    def __init__(self, path):
        self.path = Path(path)
        self.replies = []

    def lines(self):
        with self.path.open(encoding="utf-8") as source:
            for line in source:
                line = line.strip()
                if line and not line.startswith("#"):
                    yield line

    def reply(self, text):
        self.replies.append(text)


class TwitchIRCTransport(ChatTransport):
    label = "LIVE IRC"
    host, port = "irc.chat.twitch.tv", 6697

    def __init__(self):
        self.token = os.environ.get("TWITCH_OAUTH_TOKEN", "")
        self.nick = os.environ.get("TWITCH_BOT_NICK", "").lower()
        self.channel = os.environ.get("TWITCH_CHANNEL", "").lstrip("#").lower()
        if (not self.token or any(c.isspace() for c in self.token)
                or not re.fullmatch(r"[a-z0-9_]{1,25}", self.nick)
                or not re.fullmatch(r"[a-z0-9_]{1,25}", self.channel)):
            raise ValueError("Set TWITCH_OAUTH_TOKEN, TWITCH_BOT_NICK and TWITCH_CHANNEL")
        if not self.token.startswith("oauth:"):
            self.token = "oauth:" + self.token
        self._socket = None
        self._send_lock = threading.Lock()
        self._reply_lock = threading.Lock()
        self._last_reply = 0.0
        self.stopped = threading.Event()
        self.status = "offline"

    @staticmethod
    def parse_line(line):
        """Return (command, params, trailing); tolerate optional IRCv3 tags."""
        if line.startswith("@"):
            _, _, line = line.partition(" ")
        if line.startswith(":"):
            _, _, line = line.partition(" ")
        head, sep, trailing = line.partition(" :")
        words = head.split()
        return (words[0].upper(), words[1:], trailing if sep else "") if words else ("", [], "")

    def _send(self, line):
        if "\r" in line or "\n" in line:
            raise ValueError("IRC line injection rejected")
        with self._send_lock:
            if self._socket is None:
                raise ConnectionError("IRC is disconnected")
            self._socket.sendall((line + "\r\n").encode("utf-8"))

    def lines(self):
        """One TLS session; disconnect/auth failure terminates explicitly."""
        self.status = "connecting"
        raw = socket.create_connection((self.host, self.port), timeout=30)
        try:
            self._socket = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
            self._socket.settimeout(300)
            self._send("PASS " + self.token)
            self._send("NICK " + self.nick)
            self._send("JOIN #" + self.channel)
            self.status = "authenticating"
            pending = b""
            while True:
                chunk = self._socket.recv(4096)
                if not chunk:
                    return
                pending += chunk
                if len(pending) > 65536:
                    raise ConnectionError("IRC input exceeded limit")
                while b"\r\n" in pending:
                    packet, pending = pending.split(b"\r\n", 1)
                    decoded = packet.decode("utf-8", "replace")
                    command, params, trailing = self.parse_line(decoded)
                    if command == "001":
                        self.status = "connected"
                    if command == "PING":
                        self._send("PONG :" + (trailing or " ".join(params)))
                    elif command == "RECONNECT":
                        raise ConnectionError("Twitch requested reconnect; restart transport")
                    elif command == "NOTICE" and any(s in trailing.lower() for s in
                            ("authentication failed", "improperly formatted auth", "login unsuccessful")):
                        raise ConnectionError("Twitch authentication failed; check environment credentials")
                    elif command == "PRIVMSG" and params == ["#" + self.channel]:
                        prefix = decoded.split(" ", 1)[1] if decoded.startswith("@") else decoded
                        sender = re.match(r":([a-zA-Z0-9_]+)![^ ]+ ", prefix)
                        user = sender.group(1).lower() if sender else ""
                        # Never accept a display-name/tag as authentication for host controls.
                        yield ChatMessage(trailing, user=user, commander=user == self.channel)
        finally:
            self.status = "disconnected"
            if self._socket is not None:
                self._socket.close()
                self._socket = None
            raw.close()

    def messages(self):
        """Reconnect transient failures with capped, cancellable backoff."""
        delay = 1
        while not self.stopped.is_set():
            try:
                for message in self.lines():
                    delay = 1
                    yield message
            except ConnectionError as exc:
                if "authentication failed" in str(exc):
                    self.status = "authentication failed"
                    return
            except OSError:
                pass
            if not self.stopped.is_set():
                self.status = "reconnecting"
                self.stopped.wait(delay)
                delay = min(30, delay * 2)

    def close(self):
        self.stopped.set()
        with self._send_lock:
            if self._socket:
                try:
                    self._socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def reply(self, text):
        # Conservative 1 message / 1.6s pacing, below the ordinary 20/30s limit.
        text = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
        prefix = "PRIVMSG #" + self.channel + " :"
        budget = min(400, 510 - len(prefix.encode("utf-8")))
        text = text.encode("utf-8")[:budget].decode("utf-8", "ignore")
        with self._reply_lock:
            self.stopped.wait(max(0, 1.6 - (time.monotonic() - self._last_reply)))
            if self.stopped.is_set():
                return
            self._send(prefix + text)
            self._last_reply = time.monotonic()


class TwitchEventSubTransport(ChatTransport):
    def lines(self):
        raise NotImplementedError("EventSub not wired; use TwitchIRCTransport or FixtureTransport")

    def reply(self, text):
        raise NotImplementedError("EventSub not wired; use TwitchIRCTransport or FixtureTransport")
