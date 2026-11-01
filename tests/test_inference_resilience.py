"""Resilience and safety regression tests for background inference and profiler."""
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from inference import BackgroundModelSlot
from mission import Mission

# Ensure tools directory is in sys.path for test imports
TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import profile_local_mlx


class InferenceResilienceTests(unittest.TestCase):
    def test_failure_recovery_after_cooldown(self):
        clock_time = [100.0]
        slot = MagicMock()
        slot.status.return_value = {"disabled": False, "loaded": True, "model_path": "mock"}
        slot.generate.side_effect = RuntimeError("GPU memory spike")

        background = BackgroundModelSlot(
            slot=slot, timeout=5, negative_cooldown=30, clock=lambda: clock_time[0]
        )

        # First attempt fails
        self.assertIsNone(background.generate("Why?", "Moonquake context"))
        background.jobs.join()
        self.assertEqual(slot.generate.call_count, 1)

        # Before cooldown expires (15s elapsed): negative-cache hit, no re-execution
        clock_time[0] = 115.0
        self.assertIsNone(background.generate("Why?", "Moonquake context"))
        self.assertEqual(slot.generate.call_count, 1)

        # After cooldown expires (35s elapsed): retry is allowed
        clock_time[0] = 135.0
        slot.generate.side_effect = None
        slot.generate.return_value = "[INFERRED] Lunar crust lacks water."

        self.assertIsNone(background.generate("Why?", "Moonquake context"))
        background.jobs.join()
        self.assertEqual(slot.generate.call_count, 2)

        # Answer is now cached in results
        self.assertEqual(background.generate("Why?", "Moonquake context"), "[INFERRED] Lunar crust lacks water.")

    def test_stalled_reporting_while_mission_runs(self):
        clock_time = [10.0]
        entered = threading.Event()
        release = threading.Event()
        slot = MagicMock()
        slot.status.return_value = {"disabled": False, "loaded": True, "model_path": "mock"}

        def slow_worker(*_):
            entered.set()
            release.wait(timeout=2)
            return "[INFERRED] late answer"

        slot.generate.side_effect = slow_worker
        background = BackgroundModelSlot(
            slot=slot, timeout=5, negative_cooldown=30, clock=lambda: clock_time[0]
        )

        # Queue slow model job
        background.generate("Slow?", "ctx")
        self.assertTrue(entered.wait(1.0))

        # Check status before timeout
        status_early = background.status()
        self.assertTrue(status_early["busy"])
        self.assertFalse(status_early["stalled"])
        self.assertEqual(status_early["oldest_pending_seconds"], 0.0)

        # Advance clock past timeout: model is now stalled
        clock_time[0] = 20.0
        status_stalled = background.status()
        self.assertTrue(status_stalled["busy"])
        self.assertTrue(status_stalled["stalled"])
        self.assertGreaterEqual(status_stalled["oldest_pending_seconds"], 10.0)

        # Mission and game clock run concurrently without blocking
        mission = Mission(voting_seconds=2, replay_seconds=1, clock=lambda: clock_time[0])
        mission.start()
        mission.vote("alice", "a")
        snapshot = mission.snapshot()
        self.assertEqual(snapshot["round"]["participants"], 1)

        # Release slow worker; late result discarded due to timeout
        release.set()
        background.jobs.join()

        self.assertEqual(background.expired, 1)
        status_done = background.status()
        self.assertFalse(status_done["busy"])
        self.assertFalse(status_done["stalled"])

    def test_duplicate_coalescing(self):
        entered = threading.Event()
        release = threading.Event()
        slot = MagicMock()
        slot.status.return_value = {"disabled": False, "loaded": True, "model_path": "mock"}

        def blocker(*_):
            entered.set()
            release.wait(timeout=2)
            return "ok"

        slot.generate.side_effect = blocker
        background = BackgroundModelSlot(slot=slot)

        try:
            background.generate("dup", "ctx")
            self.assertTrue(entered.wait(1.0))

            # Multiple duplicate requests while pending
            for _ in range(5):
                self.assertIsNone(background.generate("dup", "ctx"))

            # Queue remains at 0 queued items because it is already pending
            self.assertEqual(background.jobs.qsize(), 0)
        finally:
            release.set()
            background.jobs.join()

        self.assertEqual(slot.generate.call_count, 1)

    def test_bounded_lru_and_failure_cache(self):
        slot = MagicMock()
        slot.status.return_value = {"disabled": False, "loaded": True, "model_path": "mock"}
        slot.generate.side_effect = lambda q, _: f"ans_{q}"
        background = BackgroundModelSlot(slot=slot)

        # Populate 25 successful results
        for i in range(25):
            background.generate(f"q_{i}", "ctx")
            background.jobs.join()

        self.assertLessEqual(len(background.results), 16)
        self.assertEqual(len(background.results), 16)

        # Populate 25 failures
        slot.generate.side_effect = RuntimeError("fail")
        for i in range(25):
            background.generate(f"fail_{i}", "ctx")
            background.jobs.join()

        self.assertLessEqual(len(background.failures), 16)
        self.assertEqual(len(background.failures), 16)

    def test_config_and_argument_validation(self):
        with self.assertRaises(ValueError):
            BackgroundModelSlot(timeout=0)
        with self.assertRaises(ValueError):
            BackgroundModelSlot(timeout=-10)
        with self.assertRaises(ValueError):
            BackgroundModelSlot(negative_cooldown=0)
        with self.assertRaises(ValueError):
            BackgroundModelSlot(negative_cooldown=-5)

        slot = BackgroundModelSlot(disabled=True)
        with self.assertRaises(TypeError):
            slot.generate(123, "ctx")
        with self.assertRaises(TypeError):
            slot.generate("q", None)
        self.assertIsNone(slot.generate("   ", "ctx"))

    def test_safe_profiler_inspection(self):
        report = profile_local_mlx.inspect_environment()
        self.assertEqual(report["mode"], "inspection")
        self.assertTrue(report["safe_mode"])
        self.assertIn("system", report["platform"])
        self.assertIn("machine", report["platform"])
        self.assertIsInstance(report["apple_silicon"], bool)
        self.assertIsInstance(report["mlx_installed"], bool)
        self.assertIsInstance(report["model_cached"], bool)

    def test_refusal_to_benchmark_non_apple_hardware(self):
        with patch("platform.system", return_value="Linux"), patch("platform.machine", return_value="x86_64"):
            result = profile_local_mlx.run_benchmark()
            self.assertTrue(result.get("refused"))
            self.assertIn("Apple Silicon", result.get("reason", ""))

    def test_whitespace_normalization_and_deduplication(self):
        slot = MagicMock()
        slot.status.return_value = {"disabled": False, "loaded": True, "model_path": "mock"}
        slot.generate.return_value = "[INFERRED] Normalized response."

        background = BackgroundModelSlot(slot=slot)
        # First query with irregular spacing
        background.generate("  Why   do  moonquakes  ring?  ", "  context text  ")
        background.jobs.join()
        self.assertEqual(slot.generate.call_count, 1)

        # Subsequent query with different whitespace
        cached = background.generate("Why do moonquakes ring?", "context text")
        self.assertEqual(cached, "[INFERRED] Normalized response.")
        # Zero additional GPU calls made
        self.assertEqual(slot.generate.call_count, 1)


if __name__ == "__main__":
    unittest.main()
