# November 1 release audit

## Product decision

Retain the verified Twitch connection and lunar identity. The strongest remaining
gap against the official entertainment/design criteria was that chat only queried
a telemetry bot. The release adds one complete audience loop: host starts a
round → viewers choose A/B → independent timer locks ballots → compressed
comparison → deterministic reveal and session scores. A full last-day pivot
would discard working authentication and live-overlay evidence.

## Findings and disposition

| Finding in October 28 build | Release treatment | Evidence |
| --- | --- | --- |
| Physics, inference, CLI and WS mixed in one file | Split along behavior boundaries; compatibility entry point preserved | Original regression suite retained |
| No audience identity/state | Preserve IRC prefix login, one latest vote per account | Host spoofing and repeat-ballot tests |
| Model blocks chat reader | Single background model worker, bounded queue, late result discarded | Slow fake model + actual Metal receipt |
| Reply pacing blocks receive loop | Independent reader and bounded outbox | Runtime separation; IRC PING tests |
| Disconnect terminates session | Capped cancellable retry; bad auth stops retries | Fault-injected reconnect/backoff tests |
| No game clock independent of chat | State loop ticks every50ms | Empty-chat timed reveal test |
| No novice-friendly host controls | Loopback Director buttons, built-in rehearsal, current OBS URL | Browser round/reveal verification |
| Dense scrolling HUD | Fixed1920×1080 stage, separate host console, readable signal cards | OBS-size browser QA |
| Mock terrain could look authoritative | Explicit FIXTURE / schematic labels; no landing verdict | Fixture provenance and screenshot |
| Experimental PGA/hab gauge looked like a safety product | Remove from main overlay; document legacy estimate limitations | No structural assessment advertised |
| Duplicate old project, experiments, no remote configured | Curated source-only release package; retain legacy files outside bundle | Package manifest and reproducibility test |
| Energy/savings figures not physically measured | No product wattage/savings claims; retain schema compatibility only | README / SOURCES and UI |
| Model tool says admitted although behavior can be wrong | Independently test/correct or reject candidates | Saved accepted/rejected candidate receipts |

## Limits that remain explicit

- New game live smoke test PASSED on November1: real browser messages in
  #xavaanes, one accepted voter, changed ballot without duplication, computed
  reveal,100points. See release_live_vote.json and release_live_twitch.json.
  This one-account test does not establish large-audience production capacity.
- OBS Browser Source and80-second live recording VERIFIED. Video publication,
  repository judge access and final Devpost submission remain separate gates.
- Inference deadlines discard late prose; a daemon thread cannot kill an in-flight
  Metal call. One stuck worker consumes its slot, while deterministic game/IRC
  continue. Restart recovers that optional capability.
- IRC join failures/slow mode may prevent replies; the Director reports transport
  state, but successful authorization alone does not prove viewers received text.
- Leaderboards/caches are session-memory only; no persistence or identity beyond
  the authenticated IRC prefix is claimed. Browser rehearsal participants are fake
  labels, clearly separated from live mode.
- Source/fixture validation is scoped to the shipped schema; no authoritative
  terrain, scarp catalog, structural model or Apollo waveform analysis is included.
- Historical credentials pasted into chat were flagged for replacement. This
  release neither republishes nor automatically revokes those historical tokens.

## Reviewer-requested release fixes

The real self-test is one account (xavaanes as broadcaster AND bot), not an
independent second viewer. Receipts establish routing, ballot replacement and
scoring for that account, not audience-scale behavior. Prior70-test outputs are
preserved separately; the suite is now74 with four targeted reviewer regressions.
Repeated deterministic CapCom reference replies are suppressed once per mission
without suppressing HUD receipts. An outbound send failure permits a retry. MLX
chat replies omit the appended reference block. Reveal text now includes Q and
frequency for BOTH signals, the t^-0.5 envelope and1%ofA(1s) threshold; tests
recompute both durations from parsed chat text and check the400byte reply limit.
