import base64
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

from lunar_copilot import (CapCom, MLXModelSlot, ROOT, TelemetryServer,
                           coda_envelope, radiated_energy, read_exact,
                           ringing_minutes, simulate_moonquake)
from twitch_transport import FixtureTransport, TwitchEventSubTransport, TwitchIRCTransport


class PhysicsTests(unittest.TestCase):
    def test_energy_reference_values(self):
        self.assertAlmostEqual(radiated_energy(4.8) / 1e12, 1.0, places=12)
        self.assertAlmostEqual(radiated_energy(4.5) / 1e11, 3.5481338923, places=9)

    def test_energy_magnitude_scaling(self):
        self.assertAlmostEqual(radiated_energy(5) / radiated_energy(4), 10**1.5)

    def test_invalid_magnitudes(self):
        for bad in (0, -1, 7.01, 9.9, "nan", "inf", "abc"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                radiated_energy(bad)
        self.assertGreater(radiated_energy(7), 0)

    def test_coda_formula(self):
        self.assertAlmostEqual(coda_envelope(100), .1 * math.exp(-math.pi * 100 / 4200))

    def test_coda_decays_and_high_q_rings_longer(self):
        self.assertGreater(coda_envelope(10), coda_envelope(100))
        self.assertGreater(ringing_minutes(5000), ringing_minutes(3000))

    def test_ringing_threshold(self):
        end = ringing_minutes() * 60
        self.assertAlmostEqual(coda_envelope(end) / coda_envelope(1), .01, places=10)

    def test_invalid_coda_inputs(self):
        for kwargs in ({"t": 0}, {"t": 1, "q": 2999}, {"t": 1, "frequency": 0}, {"t": 1, "alpha": -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                coda_envelope(**kwargs)

    def test_pga_is_explicit_scenario(self):
        event = simulate_moonquake(4.5)
        self.assertGreater(event["pga_lunar_g"], 0)
        self.assertEqual(event["pga_assumptions"]["distance_m"], 10000)
        self.assertIn("UNASSESSED", event["hab_status"])
        self.assertIn("[INFERRED]", event["message"])


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.app = CapCom(MLXModelSlot(disabled=True), clock=lambda: self.now)

    def test_sites_have_epistemic_tags(self):
        for site in ("shackleton", "malapert", "amundsen", "de_gerlache"):
            event = self.app.handle("!landing " + site)
            self.assertTrue(event["ok"])
            for tag in ("[REFERENCE]", "[COMPUTED]", "[INFERRED]"):
                self.assertIn(tag, event["message"])
            self.assertIn("ILLUSTRATIVE", event["message"])

    def test_scarp_gate_and_slope(self):
        self.assertTrue(self.app.handle("!landing shackleton")["data"]["elevated_slip_risk"])
        self.assertFalse(self.app.handle("!landing malapert")["data"]["elevated_slip_risk"])
        self.assertTrue(self.app.handle("!landing amundsen")["data"]["slope_flag"])

    def test_cache_hit_and_expiry(self):
        first = self.app.handle("!landing shackleton")
        self.now += 29.999
        hit = self.app.handle("!landing shackleton")
        self.assertTrue(hit["cache_hit"])
        self.assertEqual(hit["modelled_energy"], 0.0)
        self.assertEqual(hit["counters"]["calls_avoided"], 1)
        self.assertEqual(hit["counters"]["computations"], 1)
        self.now = 130
        self.assertFalse(self.app.handle("!landing shackleton")["cache_hit"])
        self.assertIsNone(first["modelled_energy"])

    def test_cached_result_cannot_be_mutated_by_consumer(self):
        event = self.app.handle("!landing shackleton")
        event["data"]["name"] = "CORRUPTED"
        self.assertEqual(self.app.handle("!landing shackleton")["data"]["name"], "Shackleton Rim")

    def test_fail_closed_and_counted(self):
        for line in ("!landing nowhere", "!moonquake 9.9", "!moonquake nan", "!moonquake inf", "!aoi nowhere", "!unknown x", "!capcom"):
            event = self.app.handle(line)
            self.assertFalse(event["ok"])
            self.assertEqual(event["data"], {})
        self.assertEqual(self.app.counters["errors"], 7)
        self.assertEqual(self.app.counters["computations"], 0)

    def test_aoi_is_closed_valid_lon_lat_polygon(self):
        event = self.app.handle("!aoi shackleton")
        points = event["data"]["polygon_lon_lat"]
        self.assertEqual(points[0], points[-1])
        self.assertEqual(len(points), 5)
        self.assertTrue(all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon, lat in points))

    def test_capcom_fallback_context_and_cache(self):
        self.app.handle("!moonquake 4.5")
        first = self.app.handle("!capcom Why ring?")
        self.assertEqual(first["data"]["answer_source"], "deterministic")
        self.assertIn("3.548134e+11", first["message"])
        self.assertTrue(self.app.handle("!capcom Why ring?")["cache_hit"])
        self.app.handle("!moonquake 5")
        self.assertFalse(self.app.handle("!capcom Why ring?")["cache_hit"])

    def test_fixture_end_to_end(self):
        events = [self.app.handle(line) for line in FixtureTransport(ROOT / "fixtures/chat_log.txt").lines()]
        self.assertEqual(len(events), 8)
        self.assertEqual(self.app.counters, {"computations": 4, "cache_hits": 2, "calls_avoided": 2, "errors": 2})
        json.dumps(events, allow_nan=False)

    def test_cache_is_bounded(self):
        for i in range(300):
            self.app.handle(f"!capcom query {i}")
        self.assertEqual(len(self.app.cache), 256)

    def test_reconnect_snapshot_retains_physics_after_rejected_input(self):
        self.app.handle("!landing shackleton")
        self.app.handle("!moonquake 4.5")
        self.app.handle("!aoi shackleton")
        rejected = self.app.handle("!moonquake 9.9")
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["state"]["quake"]["energy_j"], radiated_energy(4.5))
        self.assertEqual(rejected["state"]["site"]["name"], "Shackleton Rim")
        self.assertEqual(len(rejected["state"]["aoi"]["polygon_lon_lat"]), 5)


class ModelTests(unittest.TestCase):
    def test_import_and_disabled_mode_need_no_mlx(self):
        script = '''
import sys
class BlockMLX:
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in ('mlx', 'mlx_lm'):
            raise AssertionError('Unexpected MLX import')
sys.meta_path.insert(0, BlockMLX())
from lunar_copilot import MLXModelSlot, CapCom
assert not MLXModelSlot(disabled=True).status()['loaded']
assert CapCom(MLXModelSlot(disabled=True)).handle('!capcom Why ring?')['ok']
assert not any(k == 'mlx' or k.startswith('mlx.') or k == 'mlx_lm' for k in sys.modules)
'''
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_env_disables_slot_without_import(self):
        with patch.dict(os.environ, {"COPILOT_DISABLE_MLX": "1"}), patch("lunar_copilot.importlib.import_module") as imp:
            slot = MLXModelSlot()
            self.assertIsNone(slot.generate("q", "context"))
            self.assertFalse(slot.status()["loaded"])
            imp.assert_not_called()

    def test_missing_weights_falls_back(self):
        with patch.dict(os.environ, {"COPILOT_DISABLE_MLX": "0"}), patch.object(MLXModelSlot, "_local_path", side_effect=FileNotFoundError):
            slot = MLXModelSlot()
            event = CapCom(slot).handle("!capcom Why ring?")
            self.assertFalse(event["model"]["loaded"])
            self.assertIsNone(event["model"]["model_path"])
            self.assertEqual(event["data"]["answer_source"], "deterministic")

    def test_real_references_required_for_loaded_and_cached_generation(self):
        fake = MagicMock()
        fake.load.return_value = (object(), MagicMock())
        fake.generate.return_value = "[REFERENCE] Dry crust has low attenuation."
        with patch.dict(os.environ, {"COPILOT_DISABLE_MLX": "0"}), patch.object(MLXModelSlot, "_local_path", return_value="/mock/weights"), patch("lunar_copilot.importlib.import_module", return_value=fake):
            slot = MLXModelSlot()
            self.assertFalse(slot.status()["loaded"])
            app = CapCom(slot)
            event = app.handle("!capcom Why ring?")
            self.assertTrue(event["model"]["loaded"])
            self.assertEqual(event["model"]["model_path"], "/mock/weights")
            self.assertEqual(event["data"]["answer_source"], "mlx")
            self.assertIn("[INFERRED] Local model", event["message"])
            self.assertTrue(app.handle("!capcom Why ring?")["cache_hit"])
            fake.load.assert_called_once()
            fake.generate.assert_called_once()

    def test_failed_load_does_not_report_loaded(self):
        fake = MagicMock()
        fake.load.return_value = (None, None)
        with patch.dict(os.environ, {"COPILOT_DISABLE_MLX": "0"}), patch.object(MLXModelSlot, "_local_path", return_value="/mock"), patch("lunar_copilot.importlib.import_module", return_value=fake):
            slot = MLXModelSlot()
            self.assertFalse(slot.load())
            self.assertIsNone(slot.status()["model_path"])

    def test_generation_failure_uses_physics(self):
        fake = MagicMock()
        fake.load.return_value = (object(), MagicMock())
        fake.generate.side_effect = RuntimeError("offline")
        with patch.dict(os.environ, {"COPILOT_DISABLE_MLX": "0"}), patch.object(MLXModelSlot, "_local_path", return_value="/mock"), patch("lunar_copilot.importlib.import_module", return_value=fake):
            event = CapCom(MLXModelSlot()).handle("!capcom Why ring?")
            self.assertEqual(event["data"]["answer_source"], "deterministic")
            self.assertTrue(event["model"]["loaded"])
            self.assertEqual(event["model"]["error"], "RuntimeError")


ENV = {"TWITCH_OAUTH_TOKEN": "test-only-token", "TWITCH_BOT_NICK": "test_bot", "TWITCH_CHANNEL": "#test_channel"}


class TransportTests(unittest.TestCase):
    def test_fixture_mock_and_reply(self):
        transport = FixtureTransport(ROOT / "fixtures/chat_log.txt")
        self.assertEqual(transport.label, "MOCK")
        self.assertEqual(next(transport.lines()), "!landing shackleton")
        transport.reply("receipt")
        self.assertEqual(transport.replies, ["receipt"])

    def test_eventsub_stub(self):
        for operation in (lambda: TwitchEventSubTransport().lines(), lambda: TwitchEventSubTransport().reply("x")):
            with self.assertRaisesRegex(NotImplementedError, "EventSub not wired; use TwitchIRCTransport or FixtureTransport"):
                operation()

    def test_missing_env_fails_before_connection(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "TWITCH_OAUTH_TOKEN"):
            TwitchIRCTransport()

    def test_env_injection_rejected(self):
        for field in ENV:
            with patch.dict(os.environ, {**ENV, field: "bad\r\nJOIN #injected"}, clear=True):
                with self.assertRaises(ValueError):
                    TwitchIRCTransport()

    def test_tagged_irc_line_parser(self):
        result = TwitchIRCTransport.parse_line("@badge-info=;mod=0 :viewer!v@host PRIVMSG #test_channel :!moonquake 4.5")
        self.assertEqual(result, ("PRIVMSG", ["#test_channel"], "!moonquake 4.5"))

    def test_tls_ping_fragmentation_and_channel_filter(self):
        tls = MagicMock()
        tls.recv.side_effect = [b"PING :server\r", b"\n:v!x PRIVMSG #other :ignore\r\n@mod=0 :v!x PRIVMSG #test_channel :!landing shack", b"leton\r\n", b""]
        raw = MagicMock()
        context = MagicMock()
        context.wrap_socket.return_value = tls
        with patch.dict(os.environ, ENV, clear=True), patch("twitch_transport.socket.create_connection", return_value=raw) as connect, patch("twitch_transport.ssl.create_default_context", return_value=context):
            transport = TwitchIRCTransport()
            self.assertEqual(list(transport.lines()), ["!landing shackleton"])
            connect.assert_called_once_with(("irc.chat.twitch.tv", 6697), timeout=30)
            context.wrap_socket.assert_called_once_with(raw, server_hostname="irc.chat.twitch.tv")
            packets = [call.args[0] for call in tls.sendall.call_args_list]
            self.assertIn(b"PONG :server\r\n", packets)
            self.assertIn(b"NICK test_bot\r\n", packets)
            self.assertIn(b"JOIN #test_channel\r\n", packets)
            tls.close.assert_called_once()

    def test_auth_failure_is_explicit(self):
        tls = MagicMock()
        tls.recv.return_value = b":tmi NOTICE * :Login authentication failed\r\n"
        context = MagicMock()
        context.wrap_socket.return_value = tls
        with patch.dict(os.environ, ENV, clear=True), patch("twitch_transport.socket.create_connection"), patch("twitch_transport.ssl.create_default_context", return_value=context):
            with self.assertRaisesRegex(ConnectionError, "authentication failed"):
                list(TwitchIRCTransport().lines())

    def test_reply_sanitizes_and_bounds_utf8(self):
        with patch.dict(os.environ, ENV, clear=True), patch("twitch_transport.time.sleep"):
            transport = TwitchIRCTransport()
            transport._socket = MagicMock()
            transport.reply("test\r\nJOIN #evil " + "🌕" * 500)
            wire = transport._socket.sendall.call_args.args[0]
            self.assertLessEqual(len(wire), 512)
            self.assertEqual(wire.count(b"\r\n"), 1)
            self.assertTrue(wire.startswith(b"PRIVMSG #test_channel :"))
            wire.decode("utf-8")


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.server = TelemetryServer(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def http(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def handshake(self, origin=None):
        sock = socket.create_connection(self.server.server_address, timeout=2)
        self.addCleanup(sock.close)
        key = base64.b64encode(b"0123456789abcdef").decode()
        request = f"GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n"
        if origin:
            request += "Origin: " + origin + "\r\n"
        sock.sendall((request + "\r\n").encode())
        response = b""
        while not response.endswith(b"\r\n\r\n"):
            response += read_exact(sock, 1)
        return sock, response

    @staticmethod
    def receive(sock):
        first, size = read_exact(sock, 2)
        if size == 126:
            size = struct.unpack("!H", read_exact(sock, 2))[0]
        elif size == 127:
            size = struct.unpack("!Q", read_exact(sock, 8))[0]
        return first & 15, read_exact(sock, size)

    def test_http_hud_and_no_data(self):
        status, body = self.http("/")
        self.assertEqual(status, 200)
        self.assertIn(b"NO DATA / DISCONNECTED", body)
        self.assertEqual(self.http("/telemetry"), (200, b"null"))
        self.assertEqual(self.http("/absent")[0], 404)

    def test_websocket_upgrade_broadcast_ping_and_close(self):
        sock, response = self.handshake()
        self.assertIn(b"101 Switching Protocols", response)
        expected = base64.b64encode(hashlib.sha1(b"MDEyMzQ1Njc4OWFiY2RlZg==258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        self.assertIn(expected, response)
        event = CapCom(MLXModelSlot(disabled=True)).handle("!moonquake 4.5")
        self.server.broadcast(event)
        opcode, payload = self.receive(sock)
        self.assertEqual(opcode, 1)
        self.assertEqual(json.loads(payload)["data"]["energy_j"], radiated_energy(4.5))
        self.assertEqual(json.loads(self.http("/telemetry")[1])["kind"], "moonquake")
        sock.sendall(b"\x89\x82abcd" + bytes([ord('h') ^ ord('a'), ord('i') ^ ord('b')]))
        self.assertEqual(self.receive(sock), (10, b"hi"))
        sock.sendall(b"\x88\x80abcd")
        self.assertEqual(self.receive(sock), (8, b""))

    def test_replay_and_untrusted_origin_rejection(self):
        self.server.broadcast({"ok": True, "sequence": 42})
        sock, response = self.handshake()
        self.assertIn(b"101", response)
        self.assertEqual(json.loads(self.receive(sock)[1])["sequence"], 42)
        _, denied = self.handshake("https://untrusted.invalid")
        self.assertIn(b"403", denied)


if __name__ == "__main__":
    unittest.main()
