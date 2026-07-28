# Tokiln Quickstart (M0: single-node SGLang)

Shortest path from zero to "service up, load applied, live monitoring". Example: h20-09 (8×H20-3e) + GLM-5.2-FP8.

## 0. Prerequisites

- Weights present at the directory `configs/models/<model>.yaml` points to via `weights_cache/local_dir` (e.g. `/raid/model_hub/GLM-5.2-FP8`)
- The sglang image pinned in `VERSIONS.lock` already pulled (`docker pull`)
- The control node can ssh password-free to every `enabled` node in the inventory (**including itself**: `cat ~/.ssh/id_*.pub >> ~/.ssh/authorized_keys`)
- Ports 8000 (frontend) and 8100 (monitor) free

## 1. Install → preflight → render → launch

```bash
make install          # pip install -e . + submodules (PEP 660 editable needs pip >= 23)
make preflight        # read-only ssh checks on all enabled nodes; continue only on go=True
make m0-render        # renders docker compose artifacts into runs/<ts>-m0-sglang-only-<id>/
docker compose -f runs/<run_dir>/node1.compose.yaml up -d
docker logs -f <container>   # wait for "The server is fired up and ready to roll" (first DeepGEMM warmup ~5min)
```

## 2. Acceptance probes (Go/No-Go)

```bash
make probe            # stack / streaming / parser / hicache / cancel; all PASS prints GO
```

## 3. Load + live monitoring

Start the monitor on the serving node (scrapes sglang /metrics + nvidia-smi + loadgen progress):

```bash
make monitor-serve    # :8100, can run under nohup
```

Terminal dashboard from any machine (**Windows / macOS / Linux**, Python stdlib only):

```bash
tokiln monitor watch --monitor-url http://10.6.131.9:8100
# machines without tokiln installed: just copy the single file tokiln/monitor/watch.py
python watch.py --url http://10.6.131.9:8100
```

Browser GUI: open `http://10.6.131.9:8100/` — live KPI tiles, throughput/requests/utilization
time-series charts, per-GPU bars, and a **load-client panel that can start/stop a bench in either
of the two primary modes: synthetic (AA-AgentPerf) or real-trajectory SWE-bench replay**.

Persistent layer (Prometheus :9091 + Grafana :3000, provisioned dashboard included):

```bash
docker compose -f monitor/grafana/compose.yaml up -d
# open http://10.6.131.9:3000/d/tokiln-sglang  (anonymous viewer enabled)
```

Apply load (120s smoke, 8-concurrency agentic synthetic workload):

```bash
make smoke            # prints the pass_criteria verdict at the end; unmet criteria → rc=4
python -m tokiln.cli report runs/<run_dir>   # produces report.md
```

Dashboard during load:

```
┌─ tokiln monitor ── H20-GPU-09 ── 18:46:59 ── server UP ✓ ── model glm52
│ running    8   queued    0   gen    422.2 tok/s   aborted 3
│ KV usage [████████████░░░░░░░░░░░░]  52.0%   cache hit  71.6%   TTFT 1.621s   ITL 35.3ms
│ GPU util% [100 100 100 100 100 100 100 100]  mem 139G/gpu  power 2839W
│ tput  ▄▂▇▆▄▄▇▅▂▂▂▂▂▂▂▁▁▁▁▁▁▁▁▁▁▁█▇▄▅▇▅▆█▇▁▇▆▇▃▃▅█▇▆▆█
│ client [20260728-184509-smoke-armA-1150dc] 2 done, ok=78 err=0 ...
└──────────────────────────────────────────────────────────────
```

## Common pitfalls (measured on h20-09)

| Symptom | Cause → fix |
|---|---|
| `make install` fails on build_editable | pip too old → `pip install -U pip` |
| preflight all rc=255 | ssh unreachable (including to itself) → add the key to authorized_keys |
| tool_calls always [] though finish_reason=tool_calls | parser mismatch → GLM-5.2 needs `glm47` |
| loadgen reports many errs while the server looks fine | reasoning models put short replies entirely in reasoning_content → update the aa-loadgen submodule |
| port 8000 occupied | stale old frontend → kill it; check GPU leftovers via `nvidia-smi --query-compute-apps=pid` |

Full walkthrough: [docs/exp/2026-07-28-m0-h20-09.md](exp/2026-07-28-m0-h20-09.md).
