# Artemis CapCom

**Chat is mission control.** A Twitch audience challenge about an alien world's
long echoes: pick the signal that rings longest, watch the comparison, and earn
points when the disclosed mathematical model reveals the answer.

Built with OpenAI Codex during the Codex x TwitchCon Hackathon, October 2026.
The November 1 release prioritizes a complete viewer interaction over a wall of
mission telemetry. Optional local MLX explains the science; deterministic Python
owns every score and physics result.

## Try it in one command

Python 3.10+; no pip install, Twitch account or model download needed to rehearse.
From this folder:

```sh
bash start_demo.command
```

The Director opens in your browser. Click **Start mission**, pick A for
`observer1`, change the viewer name to `observer2`, and pick B. Voting closes
after 20 seconds; an 8-second comparison reveals the result and honor roll.
Local rehearsals are prominently labelled **REHEARSAL**. They are not live
Twitch evidence. Ctrl-C in Terminal stops the app.

If port 8765 is already occupied, stop your earlier demo or use:

```sh
bash start_demo.command --port 8767
```

Use the URL printed in Terminal. `/control` is the Director; `/` is the overlay.

## Connect Twitch

Install the official CLI with `brew install twitchdev/twitch/twitch-cli` and
register your own Twitch application (Confidential client, Chat Bot category,
redirect `http://localhost:3000`). Run `twitch configure` locally once with its
Client ID and Secret. Then:

```sh
bash start_twitch.command
```

Approve the intended bot account in the browser. The launcher captures CLI token
output privately, validates the user token and scopes, and discovers the real
Twitch username. Press Enter for that account's own channel or enter a different
channel username. No manual token copying, sudo, or credential files in this
project. The Twitch CLI retains its own application credential configuration.
If you rotate its secret, use `bash start_twitch.command --configure`.

The authenticated account posts replies. A dedicated bot account is optional;
using your broadcaster account works too. The account whose login matches the
channel is the only remote host permitted to control rounds. No moderator-tag
or display-name trust is involved.

| Who | Command | Effect |
| --- | --- | --- |
| Host | `!mission` | Start the next scenario, 20 seconds to vote |
| Viewer | `!vote a` or `!vote b` | One ballot per account; latest choice counts |
| Host | `!reveal` | Lock voting early and begin the 8-second comparison |
| Host | `!reset` | Cancel the active round; preserve session scores |
| Anyone | `!capcom Why do moonquakes ring so long?` | Science context, with optional local MLX |
| Anyone | `!landing shackleton` | Inspect a clearly labelled illustrative fixture |
| Anyone | `!moonquake 4.5` | Simulated energy and coda receipt |
| Anyone | `!aoi shackleton` | Draw a schematic bounding polygon |
| Anyone | `!help` | Show commands |

Host buttons also work in the loopback Director. Local rehearsal ballots are
rejected during a live Twitch session. Votes update the overlay without posting
one bot reply per vote. Repeated deterministic CapCom reference context is sent
to chat only once per mission (the HUD retains every receipt). Each reveal gives
both signals' Q, frequency and1% crossing plus the envelope/threshold definition,
so its numbers can be reproduced from chat alone. The reader keeps PING/PONG moving while an independent
outbox conservatively paces replies. Transient disconnects retry with capped
backoff; authentication failure stops retries. The launcher revalidates tokens
at startup and hourly (or sooner at expiry), stopping the bot if validation fails.

[Official CLI instructions](https://dev.twitch.tv/docs/cli/) ·
[IRC authentication](https://dev.twitch.tv/docs/chat/irc/) ·
[Token validation](https://dev.twitch.tv/docs/authentication/validate-tokens/)

## Put it in OBS

Sources → + → Browser. Paste the launcher's printed **overlay** URL, for example
`http://127.0.0.1:8766/`, and set width **1920**, height **1080**. Use the URL
from the current run: the live launcher chooses another port when needed. Do
not use an old tab or the `/control` URL as the broadcast source. The entire
overlay scales as a 16:9 canvas. There are no external fonts, image assets, npm
build steps, or cloud inference requirements.

## Local Apple Metal / MLX

```sh
bash start_twitch.command --model
```

On this Mac, the launcher selects `~/MLX/.venv/bin/python3` if present. Set
`COPILOT_MLX_PYTHON` for another interpreter. Model weights must already be in
the local Hugging Face cache: `mlx-community/Qwen2.5-Coder-7B-Instruct-4bit`.
No weights are downloaded by the app. The optional slot imports MLX only in a
bounded background worker. The first question returns deterministic context
immediately; a completed explanation is published separately if its context is
still current. Responses completing after 20 seconds are discarded. The Python
thread cannot forcibly cancel a running GPU call, but it cannot block voting,
physics, IRC PING/PONG or the mission clock. At most two jobs wait behind it.

Missing GPU/model or `COPILOT_DISABLE_MLX=1` preserves the offline experience.
`loaded` means model/tokenizer references have actually loaded; busy/loaded are
separate states. A 30-second, 256-entry query cache avoids repeated work.
Generated prose is labelled `[INFERRED]`; it never sets game answers or scores.
No LoRA adapter is enabled or needed. No measured wattage, carbon reduction,
credit savings or power-efficiency claim is made.

## What is computed, and what is a fixture?

The challenge compares `A(t) = t^-0.5 * exp(-pi*f*t/Q)` for t≥1 second, using
scenario Q=3000..5000 and frequency=0.5..2Hz. Ringing ends at 1% of the envelope
at t=1s, found by bisection. The replay compresses **80 simulated minutes** into
**8 display seconds** and uses a log-amplitude comparison; it is not a live
seismometer. Correct votes earn 100 points; ties earn 50 each. Session scores
are in memory only and capped; deadlines use a monotonic clock.

`!moonquake` uses the requested scenario magnitude-energy scaling
`E_R=10**(4.8+1.5*Mw)` J, with `0 < Mw <= 7`. This is not a conversion of an
Apollo body-wave magnitude catalog into measured lunar energy. The legacy PGA
field remains an explicitly unvalidated spherical-wave estimate for compatibility
and is not presented as a habitat assessment. See [SOURCES.md](SOURCES.md).

All site slopes, scarp distances and volatile flags in `fixtures/sites.json` are
invented demonstration inputs; coordinates are approximate feature locations.
The schematic does not supply a terrain survey or landing clearance. Unknown
sites, non-finite values and out-of-range magnitudes fail closed. The old
15° slope and 10km scarp gates are demo heuristics, not mission requirements.

## Architecture and verification

- `physics.py`: pure, deterministic model functions.
- `mission.py`: timed rounds, ballots, scoring and snapshots.
- `core.py`: validation, cache, receipts, mission commands.
- `model_slot.py` / `inference.py`: optional local-only weights and background worker.
- `twitch_transport.py`: TLS IRC, sender identity, reconnect, mock transport.
- `runtime.py`: single state owner, independent reader/outbox/model work.
- `telemetry.py`: loopback HTTP, WebSocket snapshots and token-protected Director POST.
- `lunar_copilot.py`: thin CLI entry point and compatibility exports.
- `lunar_hud.html` / `director.html`: standalone frontend files.
- `twitch_launcher.py`: private authorization and credential validation.

```sh
python3 -m unittest discover -s tests -v
python3 lunar_copilot.py --no-model --chat fixtures/chat_log.txt
```

The release suite covers equations, cache expiry, rejected inputs, model fallback,
background inference, per-viewer scores, late ballots, host controls, frame
handshakes, replay, TLS/PING, reconnect, queue limits and cross-origin controls.
See [AUDIT.md](AUDIT.md) for evidence boundaries, [CODEX_USAGE_LOG.md](CODEX_USAGE_LOG.md)
for build provenance and [SUBMISSION.md](SUBMISSION.md) for the demo/submission draft.
