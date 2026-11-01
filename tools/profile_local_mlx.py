#!/usr/bin/env python3
"""Safe opt-in profiler for local MLX model execution on Apple Silicon.

Inspection mode is stdlib-only and safe to run in any environment (including CI
and Linux). The --run flag requires macOS arm64, locally cached model weights,
and mlx/mlx-lm installed. It forces offline mode and suppresses generated prose,
prompts, paths, and credentials from output.
"""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import sys
import time

MODEL_ID = "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
BENCHMARK_PROMPT = "Why do moonquakes ring for minutes instead of seconds?"


def get_cache_root():
    cache_env = os.environ.get("HF_HUB_CACHE")
    if cache_env:
        return Path(cache_env)
    return Path.home() / ".cache" / "huggingface" / "hub"


def resolve_local_model_path():
    root = get_cache_root() / ("models--" + MODEL_ID.replace("/", "--"))
    ref = root / "refs" / "main"
    candidates = []
    if ref.is_file():
        try:
            candidates.append(root / "snapshots" / ref.read_text(encoding="utf-8").strip())
        except Exception:
            pass
    snapshots_dir = root / "snapshots"
    if snapshots_dir.is_dir():
        candidates += sorted(snapshots_dir.glob("*"), reverse=True)
    for candidate in candidates:
        if (candidate / "config.json").is_file() and any(candidate.glob("*.safetensors")):
            return candidate
    return None


def inspect_environment():
    sys_name = platform.system()
    machine = platform.machine()
    is_apple_silicon = (sys_name == "Darwin" and machine in ("arm64", "aarch64"))
    mlx_spec = importlib.util.find_spec("mlx") is not None
    mlx_lm_spec = importlib.util.find_spec("mlx_lm") is not None
    cached_path = resolve_local_model_path()

    return {
        "mode": "inspection",
        "platform": {
            "system": sys_name,
            "machine": machine,
        },
        "apple_silicon": is_apple_silicon,
        "mlx_installed": bool(mlx_spec and mlx_lm_spec),
        "model_id": MODEL_ID,
        "model_cached": cached_path is not None,
        "safe_mode": True,
    }


def percentile(data, p):
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[int(f)] * (c - k) + sorted_data[int(c)] * (k - f)


def run_benchmark(warmups=1, runs=5, max_tokens=64):
    inspection = inspect_environment()
    if not inspection["apple_silicon"]:
        return {
            "refused": True,
            "reason": "MLX native benchmarking requires Apple Silicon (Darwin arm64).",
            "platform": inspection["platform"],
        }
    if not inspection["mlx_installed"]:
        return {
            "refused": True,
            "reason": "mlx and mlx-lm packages must be installed.",
        }
    model_path = resolve_local_model_path()
    if not model_path:
        return {
            "refused": True,
            "reason": f"Model {MODEL_ID} is not cached locally.",
        }

    # Enforce strictly offline execution
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    import mlx.core as mx
    import mlx_lm

    # Cold load measurement
    t0 = time.perf_counter()
    model, tokenizer = mlx_lm.load(str(model_path))
    mx.eval(model.parameters())
    cold_load_seconds = round(time.perf_counter() - t0, 4)

    # Warmups
    for _ in range(max(0, warmups)):
        for _ in mlx_lm.stream_generate(model, tokenizer, BENCHMARK_PROMPT, max_tokens=max_tokens):
            pass

    # Measured runs
    run_records = []
    wall_latencies = []
    first_token_latencies = []
    prefill_rates = []
    generation_rates = []
    peak_memories = []

    for run_idx in range(runs):
        t_start = time.perf_counter()
        t_first = None
        last_resp = None
        gen = mlx_lm.stream_generate(model, tokenizer, BENCHMARK_PROMPT, max_tokens=max_tokens)
        for resp in gen:
            if t_first is None:
                t_first = time.perf_counter()
            last_resp = resp
        t_end = time.perf_counter()

        wall_sec = round(t_end - t_start, 4)
        first_token_sec = round((t_first - t_start) if t_first else wall_sec, 4)
        prefill_tps = round(last_resp.prompt_tps, 2) if last_resp and hasattr(last_resp, "prompt_tps") else 0.0
        gen_tps = round(last_resp.generation_tps, 2) if last_resp and hasattr(last_resp, "generation_tps") else 0.0
        peak_mb = round(last_resp.peak_memory * 1024, 2) if last_resp and hasattr(last_resp, "peak_memory") else 0.0

        wall_latencies.append(wall_sec)
        first_token_latencies.append(first_token_sec)
        prefill_rates.append(prefill_tps)
        generation_rates.append(gen_tps)
        peak_memories.append(peak_mb)

        run_records.append({
            "run": run_idx + 1,
            "first_token_latency_seconds": first_token_sec,
            "prefill_tokens_per_second": prefill_tps,
            "generation_tokens_per_second": gen_tps,
            "peak_memory_mb": peak_mb,
            "wall_latency_seconds": wall_sec,
        })

    summary = {
        "model_id": MODEL_ID,
        "runs_count": runs,
        "warmups_count": warmups,
        "max_tokens": max_tokens,
        "cold_load_seconds": cold_load_seconds,
        "p50_wall_latency_seconds": round(percentile(wall_latencies, 50), 4),
        "p95_wall_latency_seconds": round(percentile(wall_latencies, 95), 4),
        "p50_first_token_seconds": round(percentile(first_token_latencies, 50), 4),
        "p95_first_token_seconds": round(percentile(first_token_latencies, 95), 4),
        "mean_prefill_tokens_per_second": round(sum(prefill_rates) / len(prefill_rates), 2) if prefill_rates else 0.0,
        "mean_generation_tokens_per_second": round(sum(generation_rates) / len(generation_rates), 2) if generation_rates else 0.0,
        "peak_gpu_memory_mb": round(max(peak_memories), 2) if peak_memories else 0.0,
    }

    return {
        "mode": "benchmark",
        "platform": inspection["platform"],
        "summary": summary,
        "runs": run_records,
    }


def main():
    parser = argparse.ArgumentParser(description="Profile local MLX model execution safely.")
    parser.add_argument("--run", action="store_true", help="Execute native MLX inference benchmark (requires Apple Silicon).")
    parser.add_argument("--warmups", type=int, default=1, help="Warmup iterations before timing (default: 1).")
    parser.add_argument("--runs", type=int, default=5, help="Number of measured runs (default: 5).")
    parser.add_argument("--max-tokens", type=int, default=64, help="Maximum generated tokens per run (default: 64).")
    args = parser.parse_args()

    if not args.run:
        result = inspect_environment()
        print(json.dumps(result, indent=2))
        return 0

    result = run_benchmark(warmups=args.warmups, runs=args.runs, max_tokens=args.max_tokens)
    print(json.dumps(result, indent=2))
    if result.get("refused"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
