#!/usr/bin/env python3
"""Interactive Twitch launcher. Tokens stay in memory and child environment."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
SCOPES = {"chat:read", "chat:edit"}


class LaunchError(Exception):
    pass


def authorize(cli):
    print("Opening Twitch authorization in your browser. Approve the account that will speak as the bot.", flush=True)
    try:
        result = subprocess.run(
            [cli, "token", "--user-token", "--scopes", "chat:read chat:edit"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise LaunchError("Authorization timed out. Run the launcher again when ready.") from None
    # CLI logs may be written to stdout or stderr. Never print either stream.
    match = re.search(r"\bUser Access Token:\s*([A-Za-z0-9]+)\b", result.stdout + "\n" + result.stderr)
    if result.returncode or not match:
        raise LaunchError("Twitch authorization failed. If you changed the Client Secret, run this launcher with --configure first.")
    return match.group(1)


def configure(cli):
    client_id = input("Application Client ID: ").strip()
    secret = getpass.getpass("Application Client Secret (hidden): ").strip()
    if not client_id.isalnum() or not secret.isalnum():
        raise LaunchError("Client ID and Client Secret must be copied without spaces.")
    # Feed the CLI's interactive prompts through stdin, never process arguments.
    result = subprocess.run([cli, "configure"], input=client_id + "\n" + secret + "\n",
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise LaunchError("CLI configuration failed. No configuration output was printed.")
    print("Twitch CLI configured. Its own configuration stores your application credentials locally.")


def validate(token):
    request = urllib.request.Request("https://id.twitch.tv/oauth2/validate",
                                     headers={"Authorization": "OAuth " + token})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            identity = json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        raise LaunchError("Twitch could not validate the token. Check your connection and authorize again.") from None
    login = identity.get("login", "")
    scopes = identity.get("scopes", [])
    expires = identity.get("expires_in", 0)
    if not isinstance(login, str) or not re.fullmatch(r"[a-z0-9_]{1,25}", login):
        raise LaunchError("Twitch did not return a user login; a User Access Token is required.")
    if not isinstance(scopes, list) or not SCOPES.issubset(scopes):
        raise LaunchError("Authorization is missing chat:read or chat:edit.")
    if not isinstance(expires, (int, float)) or expires <= 0:
        raise LaunchError("Token has expired. Authorize again.")
    return login, expires


def choose_channel(login, value):
    value = value or input(f"Channel username [Enter for your own channel: {login}]: ").strip() or login
    value = value.strip().lower().lstrip("#")
    if not re.fullmatch(r"[a-z0-9_]{1,25}", value):
        raise LaunchError("Enter only a Twitch channel username, without a URL or email address.")
    return value


def free_port(preferred):
    for port in range(preferred, min(preferred + 20, 65536)):
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
    raise LaunchError("No available HUD port. Stop your previous demo server and retry.")


def launch(token, login, channel, expires, port, model=False):
    env = dict(os.environ, TWITCH_OAUTH_TOKEN=token, TWITCH_BOT_NICK=login, TWITCH_CHANNEL=channel)
    interpreter = sys.executable
    mlx_python = Path(os.environ.get("COPILOT_MLX_PYTHON", str(Path.home() / "MLX/.venv/bin/python3")))
    if model and mlx_python.is_file():
        interpreter = str(mlx_python)
    command = [interpreter, str(ROOT / "lunar_copilot.py"), "--twitch", "--serve", "--open", "--port", str(port)]
    if not model:
        command.append("--no-model")
    print(f"Authorized account: {login} | Channel: #{channel}")
    print(f"HUD / OBS Browser Source: http://127.0.0.1:{port}")
    print(f"Director: http://127.0.0.1:{port}/control")
    print("Starting bot. Click Start mission in Director, then vote in Twitch chat. Ctrl-C stops it.", flush=True)
    child = subprocess.Popen(command, cwd=ROOT, env=env)
    try:
        while True:
            try:
                return child.wait(timeout=max(1, min(3600, expires)))
            except subprocess.TimeoutExpired:
                # Twitch requires startup and hourly validation; stop if access is revoked.
                refreshed_login, expires = validate(token)
                if refreshed_login != login:
                    raise LaunchError("Authorized account changed; stopping the bot.")
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure", action="store_true", help="Securely enter updated application credentials into Twitch CLI")
    parser.add_argument("--channel", help="Optional channel username; defaults to an interactive prompt")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model", action="store_true", help="Enable the optional local MLX slot")
    args = parser.parse_args()
    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise LaunchError("Run as your normal user, without sudo.")
        cli = shutil.which("twitch")
        if not cli:
            raise LaunchError("Install Twitch CLI first: brew install twitchdev/twitch/twitch-cli")
        if not 1024 <= args.port <= 65535:
            raise LaunchError("Choose a port between 1024 and 65535.")
        if args.configure:
            configure(cli)
        token = authorize(cli)
        login, expires = validate(token)
        print(f"Twitch confirmed your username: {login}")
        channel = choose_channel(login, args.channel)
        port = free_port(args.port)
        if port != args.port:
            print(f"Port {args.port} is occupied; using {port}. The existing server was left running.")
        return launch(token, login, channel, expires, port, model=args.model)
    except (LaunchError, OSError, subprocess.SubprocessError) as exc:
        # Never show a raw exception that could embed a secret or CLI output.
        print(str(exc) if isinstance(exc, LaunchError) else "Launcher failed; check Twitch CLI and your connection.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nLauncher stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
