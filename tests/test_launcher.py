import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

import twitch_launcher as launcher


class LauncherTests(unittest.TestCase):
    def test_cli_token_is_captured_never_printed(self):
        fake = subprocess.CompletedProcess([], 0, "", "User Access Token: MOCKTOKEN\nRefresh Token: MOCKREFRESH\n")
        output = io.StringIO()
        with patch.object(launcher.subprocess, "run", return_value=fake) as run, contextlib.redirect_stdout(output):
            self.assertEqual(launcher.authorize("twitch"), "MOCKTOKEN")
        self.assertNotIn("MOCKTOKEN", output.getvalue())
        self.assertNotIn("MOCKREFRESH", output.getvalue())
        self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_cli_failure_does_not_leak_output(self):
        fake = subprocess.CompletedProcess([], 1, "secret-value", "secret-value")
        with patch.object(launcher.subprocess, "run", return_value=fake):
            with self.assertRaises(launcher.LaunchError) as error:
                launcher.authorize("twitch")
        self.assertNotIn("secret-value", str(error.exception))

    def identity(self, data):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(data).encode()
        return patch.object(launcher.urllib.request, "urlopen", return_value=response)

    def test_validation_derives_login_and_uses_header(self):
        with self.identity({"login": "actual_bot", "scopes": ["chat:edit", "chat:read"], "expires_in": 500}) as urlopen:
            self.assertEqual(launcher.validate("MOCKTOKEN"), ("actual_bot", 500))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://id.twitch.tv/oauth2/validate")
        self.assertEqual(request.get_header("Authorization"), "OAuth MOCKTOKEN")

    def test_invalid_identity_scope_and_expiry_fail_closed(self):
        for data in ({"login": None}, {"login": "actual_bot", "scopes": []},
                     {"login": "actual_bot", "scopes": ["chat:read", "chat:edit"], "expires_in": 0}):
            with self.subTest(data=data), self.identity(data), self.assertRaises(launcher.LaunchError):
                launcher.validate("MOCKTOKEN")

    def test_blank_channel_defaults_to_authorized_login(self):
        with patch("builtins.input", return_value=""):
            self.assertEqual(launcher.choose_channel("actual_bot", None), "actual_bot")
        with self.assertRaises(launcher.LaunchError):
            launcher.choose_channel("actual_bot", "https://twitch.tv/wrong")

    def test_configure_secret_uses_stdin_not_arguments(self):
        with patch("builtins.input", return_value="MOCKID"), patch.object(launcher.getpass, "getpass", return_value="MOCKSECRET"), patch.object(launcher.subprocess, "run", return_value=MagicMock(returncode=0)) as run:
            launcher.configure("twitch")
        self.assertEqual(run.call_args.args[0], ["twitch", "configure"])
        self.assertEqual(run.call_args.kwargs["input"], "MOCKID\nMOCKSECRET\n")

    def test_child_gets_env_and_absolute_script_not_token_arguments(self):
        child = MagicMock()
        child.wait.return_value = 0
        child.poll.return_value = 0
        with patch.object(launcher.subprocess, "Popen", return_value=child) as popen:
            self.assertEqual(launcher.launch("MOCKTOKEN", "actual_bot", "channel", 3600, 8766), 0)
        self.assertNotIn("MOCKTOKEN", str(popen.call_args.args))
        self.assertEqual(popen.call_args.kwargs["env"]["TWITCH_OAUTH_TOKEN"], "MOCKTOKEN")
        self.assertEqual(popen.call_args.kwargs["env"]["TWITCH_BOT_NICK"], "actual_bot")
        self.assertEqual(popen.call_args.kwargs["cwd"], launcher.ROOT)

    def test_revoked_session_stops_child(self):
        child = MagicMock()
        child.wait.side_effect = [subprocess.TimeoutExpired("bot", 1), 0]
        child.poll.return_value = None
        with patch.object(launcher.subprocess, "Popen", return_value=child), patch.object(launcher, "validate", side_effect=launcher.LaunchError("Revoked")):
            with self.assertRaises(launcher.LaunchError):
                launcher.launch("MOCKTOKEN", "actual_bot", "channel", 1, 8766)
        child.terminate.assert_called_once()
