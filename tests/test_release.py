"""Release regressions: game deadlines, viewer integrity, async inference and controls."""
import contextlib
import http.client
import json
import os
import queue
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from core import CapCom
from inference import BackgroundModelSlot
from mission import Mission, award_points
from model_slot import MLXModelSlot
from runtime import Runtime
from telemetry import TelemetryServer
from twitch_transport import ChatMessage, TwitchIRCTransport


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.game = Mission(clock=lambda: self.now, wall=lambda: self.now, voting_seconds=2, replay_seconds=1)

    def finish(self):
        self.now += 2
        self.game.tick()
        self.now += 1
        return self.game.tick()

    def test_answers_hidden_while_voting(self):
        self.game.start()
        snapshot = self.game.snapshot()["round"]
        self.assertIsNone(snapshot["winner"])
        self.assertNotIn("ringing_minutes", snapshot["a"])
        self.assertNotIn("votes", snapshot)

    def test_latest_vote_per_viewer(self):
        self.game.start()
        self.game.vote("alice", "a")
        self.game.vote("alice", "b")
        self.game.vote("bob", "a")
        self.assertEqual(self.game.snapshot()["round"]["counts"], {"a": 1, "b": 1})
        self.assertEqual(self.game.snapshot()["round"]["participants"], 2)

    def test_no_chat_needed_for_timed_reveal(self):
        self.game.start()
        self.game.vote("alice", "b")
        self.assertIn("WINS", self.finish())
        self.assertEqual(self.game.round["winner"], "b")
        self.assertEqual(self.game.scores["alice"], 100)

    def test_late_votes_rejected_at_exact_deadline(self):
        self.game.start()
        self.now += 2
        with self.assertRaises(ValueError):
            self.game.vote("late", "a")

    def test_scores_not_awarded_twice_by_tick(self):
        self.game.start()
        self.game.vote("alice", "b")
        self.finish()
        for _ in range(20):
            self.assertIsNone(self.game.tick())
        self.assertEqual(self.game.scores, {"alice": 100})

    def test_cancel_keeps_prior_scores_but_awards_none(self):
        self.game.scores = {"alice": 100}
        self.game.start()
        self.game.vote("alice", "b")
        self.game.reset()
        self.finish()
        self.assertIsNone(self.game.round)
        self.assertEqual(self.game.scores, {"alice": 100})

    def test_cannot_replace_active_round(self):
        self.game.start()
        with self.assertRaises(ValueError):
            self.game.start()
        self.game.lock()
        with self.assertRaises(ValueError):
            self.game.start()

    def test_multiple_rounds_accumulate_scores(self):
        for _ in range(3):
            self.game.start()
            self.game.vote("alice", "a")
            self.game.vote("bob", "b")
            self.finish()
        self.assertEqual(self.game.scores, {"alice": 100, "bob": 200})

    def test_changed_snapshot_does_not_change_game(self):
        self.game.start()
        self.game.snapshot()["round"]["a"]["q"] = -1
        self.assertEqual(self.game.round["a"]["q"], 3000)

    def test_awards_contract_and_input_immutability(self):
        guesses, scores = {"alice": "a", "bob": "b"}, {"absent": 80, "alice": 20}
        self.assertEqual(award_points(guesses, "a", scores), {"absent": 80, "alice": 120, "bob": 0})
        self.assertEqual(scores, {"absent": 80, "alice": 20})
        self.assertEqual(guesses, {"alice": "a", "bob": "b"})
        self.assertEqual(award_points(guesses, "tie", {}), {"alice": 50, "bob": 50})

    def test_invalid_awards_fail_closed(self):
        for votes, winner in (({"a": "c"}, "a"), ({"": "a"}, "a"), ({1: "a"}, "a"), ({"a": "b"}, "c")):
            with self.subTest(votes=votes, winner=winner), self.assertRaises(ValueError):
                award_points(votes, winner, {})

    def test_host_controls_restricted_and_votes_not_cached(self):
        app = CapCom(MLXModelSlot(disabled=True))
        self.assertFalse(app.handle("!mission", user="viewer")["ok"])
        self.assertTrue(app.handle("!mission", commander=True)["ok"])
        self.assertTrue(app.handle("!vote a", user="alice")["ok"])
        event = app.handle("!vote a", user="bob")
        self.assertFalse(event["cache_hit"])
        self.assertEqual(event["mission"]["round"]["participants"], 2)

    def test_winner_validation_on_local_model_candidate(self):
        from scoring import choose_winner
        self.assertEqual(choose_winner(20, 30), "b")
        self.assertEqual(choose_winner(30, 20), "a")
        self.assertEqual(choose_winner(20, 20), "tie")
        for value in (True, "1", 0, -1, float("nan"), float("inf")):
            for a, b in ((value, 1), (1, value)):
                with self.subTest(a=a, b=b), self.assertRaises(ValueError):
                    choose_winner(a, b)


class InferenceTests(unittest.TestCase):
    def test_slow_model_does_not_block_physics_or_game(self):
        entered, release = threading.Event(), threading.Event()
        slot = MagicMock()
        slot.status.return_value = {"disabled": False, "loaded": False, "model_path": None}
        def slow(*_):
            entered.set()
            release.wait(3)
            return "[INFERRED] local explanation"
        slot.generate.side_effect = slow
        background = BackgroundModelSlot(slot=slot)
        app = CapCom(background)
        started = time.monotonic()
        first = app.handle("!capcom Why ring?")
        self.assertLess(time.monotonic()-started, .5)
        self.assertTrue(entered.wait(1))
        try:
            self.assertTrue(app.handle("!moonquake 4.5")["ok"])
            self.assertTrue(app.handle("!mission", commander=True)["ok"])
            self.assertTrue(app.handle("!vote b", user="alice")["ok"])
            self.assertTrue(first["model"]["busy"])
        finally:
            release.set()
            background.jobs.join()

    def test_finished_answer_invalidates_cached_fallback(self):
        slot = MagicMock()
        slot.status.return_value = {"disabled": False, "loaded": True, "model_path": "mock"}
        slot.generate.return_value = "[INFERRED] Lower attenuation sustains the coda."
        background = BackgroundModelSlot(slot=slot)
        app = CapCom(background)
        app.handle("!capcom Why ring?")
        background.jobs.join()
        result = app.handle("!capcom Why ring?")
        self.assertEqual(result["data"]["answer_source"], "mlx")
        self.assertFalse(result["cache_hit"])
        slot.generate.assert_called_once()

    def test_missed_inference_deadline_discards_generated_answer(self):
        now = [0]
        slot = MagicMock()
        slot.status.return_value = {"disabled": False, "loaded": True}
        def slow(*_):
            now[0] = 30
            return "late"
        slot.generate.side_effect = slow
        background = BackgroundModelSlot(slot=slot, timeout=10, clock=lambda: now[0])
        background.generate("q", "context")
        background.jobs.join()
        self.assertIsNone(background.generate("q", "context"))
        self.assertEqual(background.expired, 1)

    def test_disabled_does_not_start_inference(self):
        slot = BackgroundModelSlot(disabled=True)
        self.assertIsNone(slot.generate("q", "context"))
        self.assertIsNone(slot.thread)


class ReviewerFixTests(unittest.TestCase):
    def runtime(self):
        return Runtime(MagicMock(), no_model=True,
                       transport=MagicMock(status="connected", channel="host"))

    def test_reference_once_per_mission_hud_keeps_all_receipts(self):
        runtime = self.runtime()
        for i in range(5):
            runtime.publish(runtime.app.handle(f"!capcom question {i}"))
        self.assertEqual(runtime.outbox.qsize(), 1)
        self.assertEqual(runtime.suppressed_replies, 4)
        self.assertEqual(runtime.server.broadcast.call_count, 5)
        runtime.app.handle("!mission", commander=True)
        runtime.publish(runtime.app.handle("!capcom new mission question"))
        self.assertEqual(runtime.outbox.qsize(), 2)

    def test_failed_send_allows_reference_retry(self):
        runtime = self.runtime()
        event = runtime.app.handle("!capcom why")
        runtime.publish(event)
        def failed(_):
            runtime.stop.set()
            raise OSError("test disconnect")
        runtime.transport.reply.side_effect = failed
        runtime._send()
        self.assertIsNone(runtime.reference_queued_for)
        runtime.stop.clear()
        runtime.publish(event)
        self.assertEqual(runtime.outbox.qsize(), 1)

    def test_mlx_chat_does_not_append_repeated_reference_paragraph(self):
        model = MagicMock()
        model.status.return_value = {"loaded": True}
        model.generate.return_value = "[INFERRED] Short local explanation."
        event = CapCom(model).handle("!capcom why")
        self.assertEqual(event["data"]["chat_message"], "[INFERRED] Short local explanation.")
        self.assertIn("[REFERENCE]", event["message"])

    def test_each_reveal_is_reproducible_from_chat_and_fits_irc(self):
        import re
        from physics import ringing_minutes
        now = [0]
        mission = Mission(clock=lambda: now[0])
        for _ in range(3):
            mission.start()
            mission.lock()
            now[0] += 9
            reveal = mission.tick()
            values = re.findall(r"([AB]): Q=([\d.]+), f=([\d.]+)Hz, 1% at ([\d.]+)min", reveal)
            self.assertEqual(len(values), 2)
            for label, q, f, minutes in values:
                self.assertAlmostEqual(ringing_minutes(float(q), float(f)), float(minutes), delta=.005)
            self.assertIn("t^-0.5", reveal)
            self.assertIn("1% of A(1s)", reveal)
            self.assertLessEqual(len(reveal.encode()), 400)


class TransportReleaseTests(unittest.TestCase):
    ENV = {"TWITCH_OAUTH_TOKEN": "MOCK", "TWITCH_BOT_NICK": "bot", "TWITCH_CHANNEL": "host"}

    def test_chat_message_keeps_identity_and_string_compatibility(self):
        message = ChatMessage("!vote b", "alice")
        self.assertEqual(message, "!vote b")
        self.assertEqual(message.user, "alice")
        self.assertFalse(message.commander)

    def test_display_name_cannot_impersonate_host(self):
        tls = MagicMock()
        tls.recv.side_effect = [b"@display-name=host :viewer!v@host PRIVMSG #host :!mission\r\n:host!h@host PRIVMSG #host :!mission\r\n", b""]
        ctx = MagicMock()
        ctx.wrap_socket.return_value = tls
        with patch.dict(os.environ, self.ENV, clear=True), patch("twitch_transport.socket.create_connection"), patch("twitch_transport.ssl.create_default_context", return_value=ctx):
            messages = list(TwitchIRCTransport().lines())
        self.assertFalse(messages[0].commander)
        self.assertTrue(messages[1].commander)
        self.assertEqual(messages[0].user, "viewer")

    def test_reconnect_backoff_is_capped_and_cancellable(self):
        with patch.dict(os.environ, self.ENV, clear=True):
            transport = TwitchIRCTransport()
        calls = []
        def wait(seconds):
            calls.append(seconds)
            if len(calls) == 8:
                transport.stopped.set()
        transport.stopped.wait = wait
        with patch.object(transport, "lines", side_effect=OSError):
            self.assertEqual(list(transport.messages()), [])
        self.assertEqual(calls, [1, 2, 4, 8, 16, 30, 30, 30])

    def test_bad_auth_does_not_loop_retries(self):
        with patch.dict(os.environ, self.ENV, clear=True):
            transport = TwitchIRCTransport()
        with patch.object(transport, "lines", side_effect=ConnectionError("Twitch authentication failed")) as lines:
            self.assertEqual(list(transport.messages()), [])
        lines.assert_called_once()
        self.assertEqual(transport.status, "authentication failed")


class DirectorTests(unittest.TestCase):
    def setUp(self):
        self.server = TelemetryServer(0)
        self.runtime = Runtime(self.server, no_model=True)
        self.runtime.app.mission = Mission(voting_seconds=.15, replay_seconds=.15)
        self.runtime.start()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.runtime.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def post(self, command, token=None, origin=None):
        headers = {"Content-Type": "application/json", "X-CapCom-Control": token or self.server.control_token}
        if origin:
            headers["Origin"] = origin
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            connection.request("POST", "/command", json.dumps({"command": command, "viewer": "observer1"}), headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_director_round_reaches_reveal_without_more_requests(self):
        self.assertEqual(self.post("!mission")[0], 202)
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            if self.runtime.app.mission.round and self.runtime.app.mission.round["phase"] == "revealed":
                break
            self.runtime.stop.wait(.02)
        self.assertEqual(self.runtime.app.mission.round["phase"], "revealed")
        self.assertEqual(json.loads(self.server.latest)["mission"]["round"]["winner"], "b")

    def test_control_requires_session_token(self):
        self.assertEqual(self.post("!mission", token="wrong")[0], 403)
        self.assertIsNone(self.runtime.app.mission.round)

    def test_cross_origin_control_rejected(self):
        self.assertEqual(self.post("!mission", origin="https://untrusted.invalid")[0], 403)

    def test_bad_command_cannot_enter_queue(self):
        self.assertEqual(self.post("x"*700)[0], 400)
        self.assertEqual(self.post("not a command")[0], 400)

    def test_rehearsal_votes_disabled_in_live_mode(self):
        self.runtime.transport = MagicMock(status="connected", channel="host")
        with self.assertRaisesRegex(ValueError, "disabled during live"):
            self.runtime.submit("!vote a")
        self.runtime.transport = None

    def test_queue_limit_rejects_instead_of_blocking(self):
        runtime = Runtime(TelemetryServer(0), no_model=True)
        try:
            for _ in range(256):
                runtime.submit("!help")
            with self.assertRaisesRegex(ValueError, "queue full"):
                runtime.submit("!help")
        finally:
            runtime.server.server_close()
