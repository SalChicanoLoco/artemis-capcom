"""One bounded daemon worker keeps local inference away from IRC and game clocks."""
from collections import OrderedDict
import queue
import threading
import time
from model_slot import MLXModelSlot


class BackgroundModelSlot:
    def __init__(self, disabled=False, slot=None, timeout=20, negative_cooldown=30, clock=time.monotonic):
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be a positive number")
        if not isinstance(negative_cooldown, (int, float)) or negative_cooldown <= 0:
            raise ValueError("negative_cooldown must be a positive number")
        self.slot = slot or MLXModelSlot(disabled=disabled)
        self.clock = clock
        self.timeout = timeout
        self.negative_cooldown = negative_cooldown
        self.jobs = queue.Queue(maxsize=2)
        self.ready = queue.Queue(maxsize=16)
        self.results = OrderedDict()
        self.failures = OrderedDict()
        self.pending = {}
        self.lock = threading.Lock()
        self.revision = 0
        self.thread = None
        self.expired = 0

    def status(self):
        with self.lock:
            now = self.clock()
            oldest_pending_seconds = 0.0
            if self.pending:
                oldest_pending_seconds = max(0.0, now - min(self.pending.values()))
            stalled = oldest_pending_seconds > self.timeout
            base = self.slot.status()
            return dict(
                base,
                busy=bool(self.pending),
                revision=self.revision,
                pending=len(self.pending),
                expired=self.expired,
                stalled=stalled,
                oldest_pending_seconds=round(oldest_pending_seconds, 3),
            )

    def generate(self, question, context):
        if not isinstance(question, str) or not isinstance(context, str):
            raise TypeError("question and context must be strings")
        if self.slot.status()["disabled"]:
            return None
        norm_q = " ".join(question.strip().split())
        norm_ctx = context.strip()
        if not norm_q:
            return None
        key = (norm_q, norm_ctx)
        with self.lock:
            if key in self.results:
                return self.results[key]
            now = self.clock()
            if key in self.failures:
                if now < self.failures[key]:
                    return None
                del self.failures[key]
            if key in self.pending or self.jobs.full():
                return None
            self.pending[key] = now
            self.jobs.put_nowait(key)
            if self.thread is None:
                self.thread = threading.Thread(target=self._work, daemon=True, name="capcom-mlx")
                self.thread.start()
        return None

    def _work(self):
        while True:
            key = self.jobs.get()
            try:
                answer = self.slot.generate(*key)
            except Exception:
                answer = None
            with self.lock:
                started = self.pending.pop(key, None)
                now = self.clock()
                if started is not None and (now - started > self.timeout):
                    answer = None
                    self.expired += 1
                if answer:
                    self.results[key] = answer
                    self.failures.pop(key, None)
                    self.revision += 1
                    while len(self.results) > 16:
                        self.results.popitem(last=False)
                else:
                    self.failures[key] = now + self.negative_cooldown
                    self.revision += 1
                    while len(self.failures) > 16:
                        self.failures.popitem(last=False)
            if answer:
                try:
                    self.ready.put_nowait(key)
                except queue.Full:
                    pass
            self.jobs.task_done()
