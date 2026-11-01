#!/usr/bin/env python3
"""Artemis CapCom: a Twitch audience challenge powered by lunar scenario physics."""
import argparse
import importlib  # compatibility for existing model-load fault injection tests
import json
from pathlib import Path
import sys
import threading
import time

from core import CapCom
from model_slot import MLXModelSlot
from physics import finite, radiated_energy, coda_envelope, ringing_minutes, simulate_moonquake
from telemetry import TelemetryServer, ws_frame, read_exact

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--chat', type=Path, help='Replay a labelled MOCK chat fixture and exit unless --serve')
    source.add_argument('--repl', action='store_true')
    source.add_argument('--twitch', action='store_true')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-model', action='store_true')
    parser.add_argument('--open', action='store_true', help='Open the Director console in your browser')
    args = parser.parse_args()
    from twitch_transport import FixtureTransport, TwitchIRCTransport
    if not args.serve and not args.twitch:
        app = CapCom(MLXModelSlot(disabled=args.no_model))
        lines = FixtureTransport(args.chat).lines() if args.chat else (iter(sys.stdin.readline, '') if args.repl else ())
        for line in lines:
            event = app.handle(line, commander=True)
            event['transport'] = 'MOCK' if args.chat else 'LOCAL REPL'
            print(json.dumps(event, allow_nan=False), flush=True)
        return
    from runtime import Runtime
    server = TelemetryServer(args.port)
    transport = TwitchIRCTransport() if args.twitch else None
    runtime = Runtime(server, no_model=args.no_model, transport=transport)
    runtime.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    print(f'Director: {base}/control\nOBS overlay: {base}/\nMode: '+('LIVE TWITCH' if transport else 'REHEARSAL / LOCAL ONLY'), flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(base + '/control')
    def reader():
        lines = FixtureTransport(args.chat).lines() if args.chat else iter(sys.stdin.readline, '')
        for line in lines:
            if line.strip():
                try:
                    runtime.submit(line, source='MOCK' if args.chat else 'LOCAL REPL')
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
    if args.repl or args.chat:
        threading.Thread(target=reader, daemon=True).start()
    try:
        while True:
            time.sleep(.25)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
