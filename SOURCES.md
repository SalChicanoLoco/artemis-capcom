# Sources, assumptions and claims

Checked November 1, 2026. No NASA affiliation or endorsement is claimed.

- [NASA Moonquakes](https://science.nasa.gov/moon/moonquakes/): introductory
  background on lunar seismic activity. The project does not ingest its measured
  records or assert that its illustrative site values came from NASA.
- [NASA-hosted ALSEP history](https://www.nasa.gov/wp-content/uploads/static/history/alsj/HamishALSEP.html):
  historical discussion of long-lived impact signals and dry lunar materials.
  This motivates the game; it does not validate our chosen Q, attenuation law,
  1% threshold, simulated duration, or PGA estimate for a real site.
- [Official Twitch IRC](https://dev.twitch.tv/docs/chat/irc/): TLS, authentication,
  PING/PONG and reconnect protocol. IRC is intentionally used for this small
  release; EventSub is not implemented or claimed.
- [Official token validation](https://dev.twitch.tv/docs/authentication/validate-tokens/):
  startup/hourly checks and identity discovery.
- [Hackathon rules](https://twitchcon-codex.devpost.com/rules): interactive Twitch
  experience built during the submission period, code repository, description,
  demo video and main Codex session ID.
- [Final-weekend submission guidance](https://twitchcon-codex.devpost.com/updates/47341-final-weekend-make-your-project-come-alive):
  maximum 3-minute video showing real running Twitch interaction and Codex use;
  check that the entry is Submitted. No submitted artifact changes after deadline.

## Explicit model choices

Q range, frequencies, alpha=.5, threshold=.01, magnitude-energy relation,
fixtures, scoring rules and compressed replay are scenario choices from the
project specification or this game's design. They are not fitted/validated
against Apollo waveforms. Actual lunar propagation is more complex than a
single envelope. PGA assumes spherical radiation, 10km range, density3000kg/m³,
wave speed3000m/s, source duration20s and f1Hz. It neglects attenuation/site
response. It is retained as a legacy telemetry field only; no structural model
or habitability result is available. No forecasting is performed.

## Local Metal evidence

`receipts/metal_coda_verification.json` records a real 256-sample Metal shader
comparison against double precision (tolerance1e-5). This is numerical agreement
for the selected formula, not geophysical validation. The model-assisted scoring
candidate was corrected and independently tested. A second generated test
candidate failed its requested contract and was rejected. Tool admission/static
syntax checks alone are never treated as proof of behavior. Tool-reported power,
energy and monetary estimates are excluded from submission claims.
