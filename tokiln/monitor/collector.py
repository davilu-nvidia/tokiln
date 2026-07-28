"""Metrics collection: sglang /metrics + nvidia-smi + client loadgen progress → snapshot/history.
Contract (monitor/integration.md): single collector instance; nvidia-smi is the source of truth
for GPU state; low-cardinality labels only."""
import glob
import os
import pathlib
import re
import subprocess
import time

import httpx

# sglang metrics (nightly naming, "sglang:" prefix; for per-tp_rank series take the first sample)
_GAUGES = {
    "running": r"sglang:num_running_reqs",
    "queued": r"sglang:num_queue_reqs",
    "token_usage": r"sglang:token_usage",
    "kv_used": r"sglang:kv_used_tokens",
    "kv_max": r"sglang:max_total_num_tokens",
    "gen_throughput": r"sglang:gen_throughput",
    "prompt_tokens_total": r"sglang:prompt_tokens_total",
    "generation_tokens_total": r"sglang:generation_tokens_total",
    "cached_tokens_total": r"sglang:cached_tokens_total",
    "evicted_total": r"sglang:kv_evictable_tokens",
    "aborted_total": r"sglang:num_aborted_requests_total",
    "ttft_sum": r"sglang:time_to_first_token_seconds_sum",
    "ttft_count": r"sglang:time_to_first_token_seconds_count",
    "itl_sum": r"sglang:inter_token_latency_seconds_sum",
    "itl_count": r"sglang:inter_token_latency_seconds_count",
}


def _first_sample(text: str, name: str) -> float | None:
    m = re.search(rf"^{re.escape(name)}(?:{{[^}}]*}})? ([0-9.e+-]+)$", text, re.M)
    return float(m.group(1)) if m else None


def scrape_sglang(base_url: str, timeout: float = 3.0) -> dict:
    out: dict = {"up": False}
    try:
        r = httpx.get(f"{base_url}/metrics", timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        out["error"] = str(e)[:120]
        return out
    text = r.text
    out["up"] = True
    for key, name in _GAUGES.items():
        v = _first_sample(text, name)
        if v is not None:
            out[key] = v
    m = re.search(r'model_name="([^"]+)"', text)
    if m:
        out["model"] = m.group(1)
    p, c = out.get("prompt_tokens_total"), out.get("cached_tokens_total")
    if p:
        out["cache_hit_pct"] = round((c or 0) / p * 100, 1)
    if out.get("ttft_count"):
        out["ttft_avg_s"] = round(out["ttft_sum"] / out["ttft_count"], 3)
    if out.get("itl_count"):
        out["itl_avg_ms"] = round(out["itl_sum"] / out["itl_count"] * 1000, 1)
    return out


def scrape_gpu() -> list[dict]:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used,memory.total,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        rows = []
        for line in r.stdout.strip().splitlines():
            idx, util, mu, mt, pw = [x.strip() for x in line.split(",")]
            rows.append({"idx": int(idx), "util_pct": float(util),
                         "mem_used_gb": round(float(mu) / 1024, 1),
                         "mem_total_gb": round(float(mt) / 1024, 1),
                         "power_w": float(pw)})
        return rows
    except Exception:
        return []


def scrape_client(runs_dir: pathlib.Path, fresh_s: float = 300.0) -> dict:
    """Newest loadgen progress file (both aa-loadgen replay and synth write <out>.progress)."""
    cands = glob.glob(str(runs_dir / "*" / "*.progress"))
    if not cands:
        return {"active": False}
    newest = max(cands, key=os.path.getmtime)
    age = time.time() - os.path.getmtime(newest)
    try:
        line = pathlib.Path(newest).read_text().strip()
    except OSError:
        return {"active": False}
    return {"active": age < fresh_s, "age_s": round(age, 1),
            "run": pathlib.Path(newest).parent.name, "progress": line}


class Collector:
    def __init__(self, sglang_url: str, runs_dir: pathlib.Path,
                 interval: float = 5.0, history_len: int = 720):
        self.sglang_url = sglang_url.rstrip("/").removesuffix("/v1")
        self.runs_dir = runs_dir
        self.interval = interval
        self.history_len = history_len
        self.snapshot: dict = {}
        self.history: list[dict] = []

    def tick(self) -> dict:
        srv = scrape_sglang(self.sglang_url)
        gpus = scrape_gpu()
        snap = {
            "ts": time.time(),
            "time": time.strftime("%H:%M:%S"),
            "host": os.uname().nodename,
            "server": srv,
            "gpu": gpus,
            "client": scrape_client(self.runs_dir),
        }
        self.snapshot = snap
        self.history.append({
            "ts": snap["ts"],
            "running": srv.get("running", 0),
            "queued": srv.get("queued", 0),
            "token_usage": srv.get("token_usage", 0),
            "gen_throughput": srv.get("gen_throughput", 0),
            "gpu_util_avg": round(sum(g["util_pct"] for g in gpus) / len(gpus), 1) if gpus else 0,
            "cache_hit_pct": srv.get("cache_hit_pct", 0),
        })
        if len(self.history) > self.history_len:
            del self.history[: len(self.history) - self.history_len]
        return snap
