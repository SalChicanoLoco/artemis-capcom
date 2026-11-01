# Submission draft — Artemis CapCom: The Moonquake Challenge

**Tagline:** Chat is mission control. Pick a signal. Find your crew.

## Description

Artemis CapCom turns a Twitch chat into a small science game that is fun to watch.
The host launches a lunar signal challenge. Viewers type !vote a or !vote b to
choose the synthetic signal they think will ring longest. Twenty seconds later,
ballots lock, an accelerated comparison runs, and the exact model reveals the
answer. Correct picks earn points on the Houston honor roll.

A one-page Director handles hosting and local rehearsal; a1920×1080 browser
overlay goes straight into OBS. Viewers can also ask CapCom science questions
and explore illustrative lunar locations. All scores and physical quantities
come from deterministic local functions. Optional Apple Silicon MLX produces
short explanations in the background without stopping the game or chat heartbeat.

The distinguishing idea is epistemic honesty made playable: this is a simulation,
fixtures are labelled, and the result can be reproduced from the disclosed formula.
There are no earthquake forecasts, landing clearances or unmeasured power claims.

## How Codex was used

This main Codex thread built the clean local implementation, wired/tested real
MLX loading, implemented TLS IRC and private CLI authentication, and guided the
first real Twitch-to-HUD smoke test. The November1 audit separated the monolith,
added audience rounds and stronger tests, designed the OBS overlay and Director,
and prepared the release materials. The local mlx-metal MCP tool generated a
scoring candidate and executed a Metal coda kernel; independent tests corrected
one contract issue and rejected a second candidate rather than trusting tool
admission. The repository includes receipts and the usage log.

Main Codex session ID: `01a184a4-7c17-7392-a960-daccde92d3f7`

## Three-minute recording outline (target 2:40)

- 0:00–0:15: Overlay title. “Chat is mission control. Two lunar signals, one long
  echo. Pick the one that lasts longest.” State this is a simulation.
- 0:15–0:55: Show real Twitch chat beside the live overlay. Host sends !mission;
  real viewers (or your one real test account) send !vote a/b. Do not manufacture
  a crowd; one real viewer proves the integration. Let voting/replay finish.
- 0:55–1:15: Reveal, computed durations and score. Explain how frequency and Q
  change decay; winner derives from the disclosed1% threshold, not an LLM.
- 1:15–1:35: Show Director, start/lock buttons and current OBS URL. Explore a
  site briefly and point out FIXTURE / schematic labels.
- 1:35–1:55: Ask !capcom a question. If showing MLX, use --model and show the
  actual loaded status; never describe deterministic fallback as AI inference.
- 1:55–2:25: Show Codex conversation/session evidence, module boundaries, tests
  and Metal receipt. Explain generated candidates were independently checked.
- 2:25–2:40: Close on the overlay: “A community can learn by making a prediction
  together—and the math gives everyone an answer.”

Record actual running footage in OBS. Do not substitute screenshots or a locally
rehearsed audience for Twitch footage. Avoid displaying any Terminal token output,
client secrets, notifications or unrelated personal windows.

## Completion gates — do not mark until actually done

- [x] New mission !mission/!vote tested through live Twitch chat after this refactor.
- [x] OBS Browser Source uses current overlay URL,1920×1080; actual video recorded (OBS output720p).
- [ ] Video uploaded to YouTube, public or unlisted; link opens for judges; ≤3min.
- [ ] Curated source in a GitHub/GitLab/Bitbucket repo with setup instructions.
- [ ] If private, required judge access granted according to official rules.
- [ ] Repo URL, video URL, description, session ID entered on Devpost.
- [ ] Human reviews entry and accepts any submission terms; page says Submitted.
- [ ] Freeze submitted repo/video/links after deadline; continue only in a copy.

Deadline per official rules: November2,2026 at2:00pm Pacific /3:00pm Denver.
Finish tonight to leave time for video processing. No guarantee of a prize is made.
