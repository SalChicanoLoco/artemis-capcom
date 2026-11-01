# Artemis CapCom / Twitch_Codex — RESUMED WORK DONE

Checkpoint: 2026-11-01 · isolated continuation from the verified curated source ZIP.
Status: **local owner-review candidate, unpublished/unsubmitted**.

## Verified baseline

- Original November 1 package had 41 manifest-listed source files and passed **74** Python unittest cases in this isolated Linux environment.
- Canonical code is the `ArtemisCapCom/` directory extracted from `release/ArtemisCapCom-source.zip`; the legacy root experiments are not the current release.
- Previous live Twitch, OBS and native-MLX evidence is **historical**, not independently replicated here. Prior source archive and raw demo were not altered.

## Changes in this continuation

1. **`inference.py`**: Replaced indefinite caching of a failed optional MLX generation with a bounded **30-second negative-cache cooldown**. A future identical question/context may retry after cooldown; successful generated explanations retain the existing bounded 16-entry LRU and `ready` notification.
2. **`inference.py`**: Adds `stalled` and `oldest_pending_seconds` to model status. A native model call exceeding the 20-second configured deadline remains non-cancellable; it is **observable**, and its late answer is rejected when it finishes. Mission clock/voting/physics still run in the separate deterministic loop.
3. **`inference.py`**: Keeps at most two queued MLX jobs; identical pending requests are coalesced. Bounded failure registry and argument validation prevent unbounded status/cache growth. No new MLX dependency is introduced for the normal disabled/rehearsal path.
4. **`tests/test_inference_resilience.py`**: Adds 7 new regression tests (failure recovery, stalled reporting while mission runs, duplicate coalescing, bounded LRU, config validation, safe profiler inspection, refusal to benchmark non-Apple hardware).
5. **`tools/profile_local_mlx.py`**: Adds safe opt-in profiler. Inspection mode is stdlib-only. `--run` requires macOS arm64, locally cached model, installed `mlx`/`mlx-lm`; forces Hugging Face offline mode. Reports cold-load time, per-run first-token latency, prefill and generation tokens/sec, observed MLX peak memory and p50/p95 wall latency. Suppresses prompt text, generated prose, file paths and credentials.
6. **`tools/package_release.py`**: Explicit release allowlist includes this checkpoint, new benchmark tool, and new tests. Rebuild generates a fresh digest manifest, without rewriting the previous `Archive.zip` or earlier release.

## Verification completed here

- `python3 -m unittest discover -s tests -q`: **81 tests, OK (0 failures)**, Linux x86-64 / Python 3.13.5.
- `python3 tools/profile_local_mlx.py`: returns valid offline inspection JSON and does not try importing/loading MLX weights.
- `python3 tools/profile_local_mlx.py --run`: refused on Linux (expected); no benchmark or model download ran.
- The newly built continuation ZIP has its own independently checked SHA-256 manifest. Do **not** use the historical original manifest to validate modified source.

## On the M4 Mac — NEXT ACTIONS

Extract this new source ZIP into a **new directory**; compare it with the active `/Users/xavasena/Documents/ChatGPT/Twitch_Codex/copilot` worktree and `git status` before merging any changes. Do not copy over unseen post-export local modifications.

```sh
cd ArtemisCapCom
python3 -m unittest discover -s tests -q
python3 tools/profile_local_mlx.py
# Run only if the currently active Python environment has mlx and mlx-lm
# installed and the documented model snapshot already exists locally:
python3 tools/profile_local_mlx.py --run --warmups 1 --runs 5 --max-tokens 64 \
    > mlx_profile_local.json
bash start_demo.command
```

For the owner's known local MLX environment, use the appropriate virtualenv Python (historically `~/MLX/.venv/bin/python3`) instead of `python3` on the third command. `--run` does **not** start Twitch or publish anything.

Record machine memory, local package versions, p50/p95 inference latency, peak memory and whether the stream stayed responsive under voting load. Only change quantization, prompt caching, prefill batch size or model selection *after* obtaining that baseline and confirming version-specific APIs. Separate **computed** signal physics from **inferred** model prose.

## Constraints / remaining gates

- This runtime is Linux x86-64 with **no Apple Metal device or owner's local MLX model cache**, so actual GPU speed/memory/energy improvement is **unmeasured**.
- There is no actual persisted session state across process restart; cache/leaderboard remains in RAM.
- Timeout is **discard-on-completion**, not preemption: a hung native GPU call requires a process restart for full recovery. The new status flag does not claim to kill GPU work.
- The model loader currently attempts one load per process. Newly installed weights may require restart if load previously failed.
- Live Twitch, OBS, independent viewer, authentication freshness, and native Safari/Chrome behavior are unverified in this new session.
- Source release and demo remain unpublished. Do not push a public repository, reveal tokens, stream, upload video, or submit a contest entry without owner's explicit approval.
- Historical contest handoff reported a deadline of November 2, 2026 at 3 PM Denver; verify at the official site before submission.

## Antigravity / GPT-Codex prompt

Continue from `ArtemisCapCom/` in the new resume ZIP. First read `RESUME_WORK_DONE.md`, `AUDIT.md`, `SUBMISSION.md` and existing receipts. Compare against the live local worktree; do not overwrite local work. Run the 81-test baseline and the offline MLX inspection. Use the existing isolated inference worker, deterministic lunar signal model, Twitch identity controls and local protected Director. If on Apple Silicon, run the opt-in MLX benchmark, then report measured prefill/generation token throughput, first-token latency, p50/p95 latency, peak GPU memory and state-loop p95 during active voting. Propose one bounded optimization backed by before/after timings and regression tests. Do not fabricate native Metal results, rewrite core physics with LLMs, or publish anything. Every change must be diff-reviewed, tested and recorded in a WORK DONE update.
