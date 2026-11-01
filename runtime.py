"""Single-owner state loop, independent IRC reader, outbox, inference and clock."""
import queue
import threading
import time
from core import CapCom
from inference import BackgroundModelSlot


class Runtime:
    def __init__(self, server, no_model=True, transport=None):
        self.app = CapCom(BackgroundModelSlot(disabled=no_model))
        self.server, self.transport = server, transport
        self.inbox = queue.Queue(maxsize=256)
        self.outbox = queue.Queue(maxsize=32)
        self.stop = threading.Event()
        self.dropped = 0
        self.cooldowns = {}
        self.reference_queued_for = None
        self.reply_lock = threading.Lock()
        self.suppressed_replies = 0
        self.thread = threading.Thread(target=self._loop, daemon=True, name="capcom-state")
        server.runtime = self

    def status(self):
        return {"mode": "LIVE IRC" if self.transport else "REHEARSAL",
                "connection": self.transport.status if self.transport else "local",
                "channel": self.transport.channel if self.transport else None,
                "dropped": self.dropped, "queued": self.inbox.qsize(),
                "suppressed_replies": self.suppressed_replies}

    def submit(self, text, user="director", commander=True, source="LOCAL DIRECTOR"):
        text = str(text).strip()
        if len(text) > 600 or not text.startswith("!"):
            raise ValueError("Enter a command beginning with ! (maximum 600 characters)")
        if source == "LOCAL DIRECTOR" and self.transport and text.lower().startswith("!vote"):
            raise ValueError("Rehearsal votes are disabled during live Twitch; vote in chat")
        try:
            self.inbox.put_nowait((text, user, commander, source))
        except queue.Full:
            self.dropped += 1
            raise ValueError("Command queue full; please retry") from None

    def start(self):
        self.thread.start()
        if self.transport:
            threading.Thread(target=self._read, daemon=True, name="capcom-irc").start()
            threading.Thread(target=self._send, daemon=True, name="capcom-outbox").start()

    def _read(self):
        for message in self.transport.messages():
            if self.stop.is_set():
                return
            if not message.startswith("!") or not message.user:
                continue
            now = time.monotonic()
            command = message.split()[0].lower()
            key = (message.user, "vote" if command == "!vote" else "command")
            if now - self.cooldowns.get(key, -10) < (.15 if command == "!vote" else .6):
                self.dropped += 1
                continue
            if len(self.cooldowns) > 5000:
                self.cooldowns = {k: t for k, t in self.cooldowns.items() if now-t < 30}
            self.cooldowns[key] = now
            try:
                self.submit(message, message.user, message.commander, "LIVE IRC")
            except ValueError:
                pass

    def _send(self):
        while not self.stop.is_set():
            try:
                text, reference_round = self.outbox.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                self.transport.reply(text)
            except OSError:
                self.dropped += 1
                if reference_round is not None:
                    with self.reply_lock:
                        if self.reference_queued_for == reference_round:
                            self.reference_queued_for = None

    def publish(self, event, reply=True):
        event["transport"] = self.status()["mode"]
        event["runtime"] = self.status()
        self.server.broadcast(event)
        # A voting flood updates the overlay but never floods the Twitch reply queue.
        if self.transport and reply and event["kind"] != "vote":
            reference_round = (self.app.mission.round_id if event["kind"] == "capcom" and
                               event["data"].get("answer_source") == "deterministic" else None)
            text = event["data"].get("chat_message", event["message"])
            with self.reply_lock:
                if reference_round is not None and self.reference_queued_for == reference_round:
                    self.suppressed_replies += 1
                    return
                try:
                    self.outbox.put_nowait((text, reference_round))
                except queue.Full:
                    self.dropped += 1
                else:
                    if reference_round is not None:
                        self.reference_queued_for = reference_round

    def _loop(self):
        while not self.stop.is_set():
            try:
                text, user, commander, source = self.inbox.get(timeout=.05)
            except queue.Empty:
                pass
            else:
                event = self.app.handle(text, user=user, commander=commander)
                event["source"] = source
                self.publish(event)
            message = self.app.mission.tick()
            if message:
                self.publish(self.app.system_event("mission", message))
            try:
                question, context = self.app.model.ready.get_nowait()
            except queue.Empty:
                pass
            else:
                if context == self.app.context():
                    self.publish(self.app.handle("!capcom " + question))

    def close(self):
        self.stop.set()
        if self.transport:
            self.transport.close()
        self.thread.join(timeout=2)
