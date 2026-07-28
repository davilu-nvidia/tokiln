# Tokiln code structure design — 2×8 H20 / GLM-5.2 / Dynamo + SGLang + ThunderAgent + HiCache + Mooncake (or FlexKV)

Status: Draft v0.1 | Companion design doc: Tokiln Phase 1 | Date: 2026-07-24

---

## 0. Design goals and overall principles

This codebase does not re-implement an inference engine; it is a **thin, declarative glue-and-verification layer**. Dynamo, SGLang, HiCache, and Mooncake/FlexKV are upstream components. Our own code is responsible for exactly four things:

1. **Render one declarative config into executable deployment artifacts** (docker compose / systemd scripts in M0, K8s + DynamoGraphDeployment in M3). The same `configs/` tree is the single source of truth; switching runtimes swaps the render backend, never the config semantics.
2. **Check before and after deploying**: preflight (GPU/driver/RDMA/storage/images) and capability probes (does streaming, cancel, the tool-call parser, KV events actually work). This maps directly to the design doc's "compatibility spikes cannot be skipped" constraint — Dynamo 1.2.1 pins SGLang 0.5.11 while GLM-5.2 requires 0.5.13.post1+, so every layer needs an independent Go/No-Go probe; never assume the combination works.
3. **Load testing and reporting**: reuse `aa-loadgen` (multi-turn agentic) + SGLang `bench_serving` (single-turn baseline), and solidify every run into a run manifest (image digests, model revision, launch args, workload seed, raw JSONL, aggregate metrics) for reproducibility and cross-referencing.
4. **Observability**: Prometheus + Grafana + `agentic-serving-monitor`, with unified request ID / session ID threaded through Gateway → Router → Worker.

Conversely, things that must **never appear** in this codebase: a homegrown scheduler, homegrown KV management, a homegrown SSE gateway. Whatever upstream provides, we write config and probes only.

---

## 1. Hardware topology and target deployment shape

Two nodes, 8×H20 each (96GB HBM), NVLink within a node, RDMA assumed between nodes (IB or RoCE; required by Mooncake / cross-node KV transfer; preflight must verify it).

**Baseline topology (M1 deliverable) — aggregated, two TP8 workers:**

```
                     ┌──────────────────────────────────────────┐
  aa-loadgen ───────▶│  Dynamo Frontend (OpenAI-compatible SSE) │
  (x-dynamo-         │  thunderagent_router (program-aware +    │
   session-id)       │  KV-aware routing, NATS/etcd discovery)  │
                     └──────────────┬───────────────┬───────────┘
                                    │               │
                        node1 ┌─────▼─────┐   ┌─────▼─────┐ node2
                              │ SGLang     │   │ SGLang    │
                              │ GLM-5.2    │   │ GLM-5.2   │
                              │ TP8        │   │ TP8       │
                              │ HiCache L2 │   │ HiCache L2│  ← host DRAM offload
                              └─────┬─────┘    └─────┬─────┘
                                    └───────┬────────┘
                                     ┌──────▼───────┐
                                     │ L3 KV store   │ ← mooncake store (RDMA)
                                     │ (or flexkv)   │    swappable at the config layer
                                     └──────────────┘
```

Two decision points are left for the M0 spikes to answer with data; the code structure is compatible with either outcome:

- **Does the model fit in TP8×96GB=768GB HBM (including the KV budget)?** Fits → 2×TP8 aggregated (diagram above); doesn't fit → a single cross-node TP16 worker (NCCL over RDMA), in which case thunderagent's value shrinks (only intra-worker program scheduling remains) and HiCache becomes more critical. Config expresses this with the single field `parallel.tp`; the render layer decides between single-machine compose and cross-machine.
- **Mooncake or FlexKV for L3?** Both converge to an SGLang HiCache storage-backend config + one sidecar/standalone deploy unit; `configs/serving/l3-*.yaml` stack one-of-two, application code stays oblivious.

---

## 2. Repository layout

A single monorepo named `tokiln`. The two existing repos come in as git submodules (independent evolution preserved); integration code lives in the main repo.

```
tokiln/
├── Makefile                        # top-level entry: make preflight / m0 / m1 / bench / report
├── README.md
├── VERSIONS.lock                   # global version lock: image digests, dynamo/sglang/mooncake versions, model revision
│
├── configs/                        # ★ single source of truth, all declarative YAML
│   ├── cluster/
│   │   ├── inventory.yaml          # nodes: IP, SSH, GPU SKU/count, RDMA devices, NVMe paths
│   │   └── host-contract.yaml      # supported matrix: OS/kernel/driver/CUDA/container runtime
│   ├── models/
│   │   └── glm-5.2.yaml            # weight URI, quant(FP8/BF16), tokenizer, reasoning/tool parsers, context limit
│   ├── serving/
│   │   ├── profiles/
│   │   │   ├── m0-sglang-only.yaml     # pure SGLang TP8 single node (most basic)
│   │   │   ├── m1-dynamo-agg-2xtp8.yaml# Dynamo frontend + thunderagent + 2×TP8
│   │   │   └── m1-alt-tp16.yaml        # alternative: cross-node TP16
│   │   ├── overlays/
│   │   │   ├── hicache-l2.yaml         # host DRAM offload: hicache_ratio, write policy, page size
│   │   │   ├── l3-mooncake.yaml        # mooncake store endpoints, RDMA devices, replication policy
│   │   │   └── l3-flexkv.yaml          # flexkv equivalent (mutually exclusive with mooncake)
│   │   └── router/
│   │       └── thunderagent.yaml       # program-aware scheduling params, session affinity, pause/resume watermarks
│   └── workloads/
│       ├── smoke.yaml                  # 10-concurrency 2 minutes, correctness check
│       ├── steady-highcc.yaml          # steady high concurrency 30 minutes (acceptance gate)
│       └── agentic-prefix.yaml         # aa-loadgen: ISL 5K-131K lognormal, multi-turn, tool pauses, A/B arms
│
├── deploy/
│   ├── docker/
│   │   ├── Dockerfile.sglang-glm52     # SGLang 0.5.13.post1+ + GLM-5.2 deps, output digest-locked
│   │   ├── Dockerfile.dynamo           # dynamo + custom sglang adapter (if the official pin is incompatible)
│   │   └── build.sh                    # build and write digests back into VERSIONS.lock
│   ├── compose/                        # M0–M2 runtime: one systemd/compose per node
│   │   ├── m0.node1.compose.yaml.j2    # produced by tokiln render; templates are versioned, artifacts go to runs/
│   │   ├── m1.node{1,2}.compose.yaml.j2
│   │   └── infra.compose.yaml.j2       # NATS, etcd, prometheus, grafana, mooncake-store
│   └── k8s/                            # M3+: manifests after the kubeadm bootstrap
│       ├── bootstrap/                  # ansible playbooks + kubeadm config (entry B)
│       ├── platform/                   # gpu-operator, dcgm-exporter, monitoring stack
│       └── dgd/                        # DynamoGraphDeployment templates (same profile rendered)
│
├── tokiln/                             # ★ Python control-plane package (the only in-house body, ~2-3k lines)
│   ├── cli.py                          # tokiln preflight|render|deploy|probe|bench|report|down
│   ├── config/
│   │   ├── schema.py                   # pydantic: Inventory / ModelSpec / ServingProfile / Workload
│   │   └── merge.py                    # profile + overlays → resolved config, plus the config digest
│   ├── preflight/
│   │   ├── host.py                     # read-only SSH checks: GPU, driver, CUDA, NVMe space, hugepages
│   │   ├── rdma.py                     # ib_write_bw / rping connectivity & bandwidth, Mooncake prerequisite gate
│   │   └── report.py                   # emits preflight.json + human-readable markdown
│   ├── render/
│   │   ├── compose.py                  # resolved config → compose files (M0-M2 backend)
│   │   └── dgd.py                      # resolved config → K8s DGD (M3 backend, same interface)
│   ├── probes/                         # ★ the compatibility gates as code
│   │   ├── streaming.py                # SSE chat completion, token timestamps, usage field
│   │   ├── cancel.py                   # does the GPU stop consuming after disconnect (acceptance gate)
│   │   ├── parser.py                   # GLM-5.2 reasoning/tool-call parser structured-output assertions
│   │   ├── kv_events.py                # Dynamo KV event / SGLang cache report consistency
│   │   └── hicache.py                  # cold/warm/shared-prefix trio, asserting monotonic hit rates
│   ├── bench/
│   │   ├── runner.py                   # drives aa-loadgen and bench_serving, injects run_id
│   │   └── scenarios.py                # workloads/*.yaml → concrete command lines and seeds
│   └── report/
│       ├── manifest.py                 # RunManifest: config digest + image digest + git sha + seed
│       └── aggregate.py                # JSONL → TTFT/ITL/E2E/goodput/cache-hit summary tables
│
├── third_party/
│   ├── aa-loadgen/                     # git submodule (existing repo, unmodified; called from bench/runner)
│   └── agentic-serving-monitor/        # git submodule (private repo)
│
├── monitor/
│   ├── prometheus/prometheus.yml.j2    # scrape: dynamo frontend, sglang /metrics, dcgm, node
│   ├── grafana/dashboards/             # four layers: GPU / engine / request / agentic session
│   └── integration.md                  # integration contract for agentic-serving-monitor (see §6)
│
├── spikes/                             # Phase 1A: one directory per spike, one-page conclusion + raw evidence
│   ├── 01-glm52-sglang-standalone/
│   ├── 02-dynamo-sglang-adapter/
│   ├── 03-hicache-l2/
│   ├── 04-l3-mooncake-vs-flexkv/
│   └── TEMPLATE.md                     # versions/hardware/commands/evidence/failure-modes/Go-NoGo
│
├── runs/                               # gitignored; each bench emits runs/<ts>-<run_id>/
│   └── <run_id>/{manifest.json, resolved-config.yaml, raw/*.jsonl, report.md}
│
└── docs/
    ├── runbook.md                      # deploy / check / bench / bottlenecks / upgrade-rollback / teardown
    └── decisions/                      # ADRs: TP8×2 vs TP16, mooncake vs flexkv, ...
```

---

## 3. Config model: one profile + stackable overlays

Core idea: **deployment shape = profile ⊕ overlays**; the merge produces a digest-bearing resolved config that goes into the run manifest. Examples:

`configs/models/glm-5.2.yaml`
```yaml
model:
  name: glm-5.2
  source: hf://zai-org/GLM-5.2          # or an internal mirror URI
  revision: <pin-commit>
  quant: fp8                            # fp8/bf16 decided by the M0 spike
  context_len: 131072
  served_model_name: glm-5.2
  chat_template: glm-5.2
  reasoning_parser: glm45               # actual parser name verified by spike
  tool_call_parser: glm45
  weights_cache: /data/models           # local NVMe on each node
```

`configs/serving/profiles/m1-dynamo-agg-2xtp8.yaml`
```yaml
profile:
  runtime: dynamo                       # the m0 profile says sglang-direct
  frontend: {port: 8100, mode: openai}
  router:
    kind: thunderagent                  # alternatives kv-aware / round-robin, used for A/B
    session_header: x-dynamo-session-id
  workers:
    - {node: node1, gpus: [0-7], parallel: {tp: 8}}
    - {node: node2, gpus: [0-7], parallel: {tp: 8}}
  kv:
    l1: radix                           # GPU RadixAttention, always on
  limits: {max_concurrency: 256, queue_size: 128, timeout_s: 600}
```

`configs/serving/overlays/l3-mooncake.yaml` (switching to FlexKV replaces only this file)
```yaml
kv:
  l2:
    enabled: true
    host_mem_gb: 512                    # sized from node DRAM
    write_policy: write_through
  l3:
    backend: mooncake                   # or: flexkv
    endpoints: [node1:port, node2:port]
    transport: rdma
    rdma_devices: [mlx5_0, mlx5_1]
```

Render command and artifacts:

```
tokiln render --profile m1-dynamo-agg-2xtp8 --overlay hicache-l2 --overlay l3-mooncake \
              --out runs/<run_id>/
# outputs: resolved-config.yaml (with digest) + per-node compose files (or DGD yaml for M3)
```

---

## 4. Milestones: start from the most basic (hard acceptance at every step)

Every milestone is "runs + can prove how well it runs"; no advancing until it passes. This mirrors the degradation ladder in design doc §6.1.

### M0 — single node, pure SGLang, GLM-5.2 emits correct tokens (~2-3 days)
- Content: build `Dockerfile.sglang-glm52`; bring up GLM-5.2 TP8 on node1; `tokiln probe streaming|cancel|parser` all green; one single-turn baseline curve via `bench_serving`.
- Key output: the **model memory envelope** (weights + activations + KV budget), which decides TP8×2 vs TP16.
- This is itself the "use the direct-SGLang path if the GLM-5.2 gate fails" gate from the design doc — after M0 passes, even if Dynamo integration later fails, a deliverable fallback shape exists (direct SGLang + a simple gateway).

### M1 — two nodes, Dynamo + thunderagent_router (~1 week)
- Content: infra compose (NATS/etcd) + frontend + 2×TP8 worker registration; `probe kv_events` verifies the KV event stream; first A/B with aa-loadgen, Arm A (thunderagent) vs Arm B (KV-routing-only), `--concurrency 64 --duration 600`.
- The risk is exactly the design doc's key blocker: dynamo 1.2.1 pins SGLang 0.5.11 vs GLM-5.2 needing 0.5.13.post1+. M1's first task is `spikes/02`: build the custom dynamo sglang-adapter container and run the contract test; if it fails, M1 becomes "direct SGLang ×2 + nginx/simple router" and the thunderagent evaluation slips.
- Acceptance: 30-minute steady state with no OOM/NaN/restarts/request leaks; GPU utilization drops after cancel; the A/B report includes P95 TTFT, P25/median output speed, steps/min.

### M2 — HiCache L2, then L3 (~1-1.5 weeks, strictly two steps)
- Step one enables **L2 host offload only** (`overlays/hicache-l2.yaml`); run the `probe hicache` cold/warm/shared-prefix trio; confirm hit rates and reused tokens are explainable and the long-context multi-turn TTFT improvement is quantifiable.
- Step two stacks **L3**: try mooncake first (mature RDMA path, public best practices with SGLang HiCache); `spikes/04` compares flexkv under the same workload; both share the overlay schema, so switching costs one `--overlay` argument.
- Acceptance: under the shared-prefix workload, prefill savings from L2/L3 hits are distinguishable in the report (cache hit rate, reused tokens, left-shifted TTFT distribution), and disabling L3 degrades cleanly to L2.

### M3 — Kubernetes + full observability (~1-2 weeks)
- kubeadm bootstrap (entry B) turns the two machines into 1 control plane + 2 GPU workers (control plane may share node1); install gpu-operator, dcgm-exporter, the monitoring stack; `render/dgd.py` renders the same profile into a DynamoGraphDeployment.
- Acceptance = the full design doc §4.3: the same declarative config reaches identical endpoint behavior via both compose and K8s; bootstrap/images/models/config all traceable.

### M4 — (Phase 2 start) capacity reports and regression
- `report/aggregate.py` solidifies capacity curves (concurrency → goodput/TTFT/ITL); every version upgrade re-runs the same scenario as a performance regression; the Rust loadgen decision gate triggers on data here (only if client CPU/connections saturate first).

---

## 5. tokiln CLI surface (the skeleton M0 already needs)

```
tokiln preflight --inventory configs/cluster/inventory.yaml     # read-only, emits preflight.json
tokiln render    --profile <p> [--overlay <o> ...]              # emits resolved config + deploy files
tokiln deploy    --run-id <id> [--backend compose|k8s]          # scp/ssh or kubectl apply
tokiln probe     all|streaming|cancel|parser|kv_events|hicache  # compatibility gates
tokiln bench     --workload agentic-prefix --arm A              # wraps aa-loadgen / bench_serving
tokiln report    --run-id <id>                                  # manifest + aggregates + Grafana snapshot links
tokiln down      --run-id <id>                                  # idempotent cleanup, removes tokiln-owned resources only
```

The Makefile freezes common combinations: `make m0`, `make m1-ab`, `make bench-steady`, etc. — each target is a fixed argument sequence over the CLI above, so everyone reproduces the same thing.

---

## 6. Integration contracts with the two existing repos

**aa-loadgen (submodule, internals untouched)**: `tokiln/bench/runner.py` does three things — translate workload YAML into an `aa_loadgen.py` command line; inject `--out runs/<run_id>/raw/aa_arm{A,B}.json` and the unified run_id; for A/B, guarantee byte-identical parameters (seed, concurrency, duration, nonce policy) apart from the router. Its existing per-session nonce (defeating cross-arm KV reuse) and `x-dynamo-session-id` injection already align with the thunderagent profile — no extra work. If cancellation injection or finer SSE token timestamps are needed later, they go upstream as PRs to its repo, never as a fork here.

**agentic-serving-monitor (submodule, interface per the actual repo)**: the main repo pins only two contracts — (a) metrics contract: `monitor/prometheus/` defines scrape targets and the label discipline (`run_id`, `arm`, `worker` as low-cardinality labels; session_id/prompt never in labels, logs only); (b) event contract: aa-loadgen's per-request JSONL joins serving-side metrics via `run_id + request_id`. The monitor consumes both; it never depends back on the control plane.

---

## 7. Inputs to decide / confirm

1. **Exact H20 SKU and per-node DRAM/NVMe capacity** (96GB or 141GB variant, node memory) — directly decides TP8×2 feasibility and HiCache L2's host_mem_gb.
2. **Inter-node network**: IB/RoCE present? how many NICs, what bandwidth — without RDMA, both Mooncake L3 and cross-node TP16 degrade, and M2 step two becomes FlexKV local tiers or pure L2.
3. **GLM-5.2 weight form**: is an FP8 checkpoint directly available; license/download channel.
4. **Phase-1 target concurrency**: aa-loadgen's 64 concurrency is a starting point; is the acceptance gate hundreds or thousands of sessions?
5. **The actual shape of agentic-serving-monitor** (private repo, no access at the time of writing): exporter, dashboard, or standalone service? The §6 contract adjusts to reality.

---

## Appendix A (v0.2 addendum, 2026-07-24): corrections after reading the actual aa-loadgen code

Based on a full read of `davilu-nvidia/aa-loadgen` (`aa_loadgen.py` + `aaload/{core,synth,replay}.py` + `replay/` + `monitor/`, 686 lines), three v0.1 assumptions are corrected.

### A.1 Hardware confirmed: H20 is the 141GB variant

8×141GB = 1128GB HBM per node. Conclusion: **2×TP8 aggregated becomes the default topology**; `m1-alt-tp16.yaml` is demoted to "file kept, not validated". Side effect: a single worker's GPU KV pool is huge, so L1 RadixAttention absorbs most hits on short/medium traces — **to prove L2/L3 gains in M2, workloads must use long traces (full300-scale) or artificially squeeze the GPU KV budget (lower `--mem-fraction`) as a control**, otherwise HiCache conclusions will falsely read as "useless".

### A.2 aa-loadgen has two modes; replay is primary from M1

- `synth`: AA-AgentPerf-distribution synthesis (ISL lognormal mean 27K, range 5K–131K; OSL 60% short tool-call / 40% long reasoning; median tool delay 1s; 6–40 turns per session; per-session nonce defeats cross-arm KV reuse). Good for smoke and capacity curves.
- `replay`: replays real trajectories recorded from mini-SWE-agent + SWE-bench. `recording_hook` records verbatim messages / real OSL / real tool gaps → `convert_to_dag.py` emits `dag.jsonl` → closed-loop concurrent replay with `ignore_eos` pinning OSL. **Strongest A/B fairness; formal thunderagent and HiCache conclusions come from replay**, synth is supplementary.
- Correction to `configs/workloads/`: `agentic-prefix.yaml` splits into `agentic-synth.yaml` and `agentic-replay.yaml`; the latter references a trace path + tokenizer + concurrency. As the README states: replaying DSV4 trajectories on GLM-5.2 is a legitimate **load test** but does not represent GLM's own agent behavior — for GLM behavioral conclusions, re-record traces with GLM-5.2 after M1 (a pre-M2 task).
- The metrics contract follows `aaload/core.py`: TTFT / out_speed (tok/s) / TPOT (ms) / session E2E / steps; token counting prefers server-side usage from `stream_options.include_usage`, falling back to delta counting. `tokiln/report/aggregate.py` consumes its JSON output directly; nothing is re-implemented.

### A.3 monitor/ is the lightweight experiment dashboard, layered alongside Prometheus

The `monitor/` trio (`collect_metrics.sh` 5s collection→JSON, `monitor.html` local dashboard, `run_exp.sh` one-shot experiment runner) already covers: TA pause/resume/still_paused counters, measured GPU util vs TA-estimated util dual lines, HiCache host_used/host_total, TTFT/TPOT/E2E P50. Positioning correction:

- **Experiment-time quick dashboard**: keep as-is; do not convert into a Prometheus exporter (its value is zero dependencies and 5-second visibility).
- **Persistent layer**: build Prometheus/Grafana per v0.1 §6, scraping the same sources (dynamo/sglang /metrics + DCGM), owning history retention, multi-run comparison, and alerting.
- The two layers join on `run_id`; the three "known pitfalls" in `monitor/README.md` (single collector instance, pgrep false positives, sed extraction) are absorbed as pre-checks in `tokiln probe`.

### A.4 The real starting point: declaratize the ta-repro container

`run_exp.sh` reveals an existing hand-built single-container experiment environment: docker container `ta-repro`, etcd discovery, frontend :8000, model names `glm52ta` (TA on) / `glm52` (no TA), traces under `/workspace/davilu/full300_traj/`. M0's task therefore changes from "bring up SGLang from scratch" to:

1. **Archaeology and solidification**: extract the actual versions inside ta-repro (dynamo/sglang/driver/launch args) into `VERSIONS.lock` and `configs/serving/profiles/`, rebuild the image and lock digests — this simultaneously answers spikes 01/02;
2. **Health checks as code**: absorb run_exp.sh's stack health checks (etcd endpoint count, /v1/models assertion, file-based warm-up) into `tokiln probe stack`;
3. **Then extend to two nodes**: only after the declarative config reproduces ta-repro behavior (single-node regression passes) does node2 join for M1.

Risk note: ta-repro is living proof of a "combination that runs", but hand-built container drift (in-place apt/pip upgrades, unrecorded flags) is the biggest reproducibility risk — do not stack more experiment variables on it before solidifying.
