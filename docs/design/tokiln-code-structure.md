# Tokiln 代码结构设计 — 2×8 H20 / GLM-5.2 / Dynamo + SGLang + ThunderAgent + HiCache + Mooncake(或 FlexKV)

状态：Draft v0.1 ｜ 对应设计文档：Tokiln Phase 1 ｜ 日期：2026-07-24

---

## 0. 设计目标与总原则

这套代码库不是重新实现推理引擎，而是一层**薄的、声明式的胶水与验证层**。Dynamo、SGLang、HiCache、Mooncake/FlexKV 都是上游组件，我们自己的代码只负责四件事：

1. **把一份声明式配置渲染成可执行的部署产物**（M0 阶段是 docker compose / systemd 脚本，M3 阶段是 K8s + DynamoGraphDeployment）。同一份 `configs/` 是唯一事实来源，换运行时只换渲染后端，不改配置语义。
2. **在部署前后做检查**：preflight（GPU/驱动/RDMA/存储/镜像）和 capability probe（streaming、cancel、tool-call parser、KV event 是否真的工作）。这直接对应设计文档里"兼容性 Spike 不能跳过"的约束——Dynamo 1.2.1 pin 的是 SGLang 0.5.11，GLM-5.2 要求 0.5.13.post1+，所以每一层都要有独立的 Go/No-Go 探针，不能假设组合可用。
3. **压测与报告**：复用 `aa-loadgen`（多轮 agentic）+ SGLang `bench_serving`（单轮基线），把每次运行固化成 run manifest（镜像 digest、模型版本、启动参数、workload seed、原始 JSONL、汇总指标），保证可复现和可交叉定位。
4. **可观测**：Prometheus + Grafana + `agentic-serving-monitor`，统一 request ID / session ID 贯穿 Gateway → Router → Worker。

反过来说，代码库里**不应该出现**的东西：自研调度器、自研 KV 管理、自研 SSE 网关。凡是上游有的，只写配置和探针。

---

## 1. 硬件拓扑与目标部署形态

2 台节点、每台 8×H20（96GB HBM），节点内 NVLink，节点间假定有 RDMA（IB 或 RoCE，Mooncake/跨节点 KV 传输需要，preflight 必须验证）。

**基线拓扑（M1 交付）——aggregated，两个 TP8 worker：**

```
                     ┌──────────────────────────────────────────┐
  aa-loadgen ───────▶│  Dynamo Frontend (OpenAI-compatible SSE) │
  (x-dynamo-         │  thunderagent_router (program-aware +    │
   session-id)       │  KV-aware routing, NATS/etcd 服务发现)    │
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
                                     │ L3 KV store   │ ← mooncake store（RDMA）
                                     │ (可切 flexkv) │    或 flexkv，配置层可换
                                     └──────────────┘
```

两个决策点留给 M0 spike 用数据回答，代码结构对两种结果都兼容：

- **模型是否装得下 TP8×96GB=768GB HBM（含 KV 预算）**。装得下 → 2×TP8 aggregated（上图）；装不下 → 单个 TP16 跨节点 worker（NCCL over RDMA），此时 thunderagent 的价值下降（只剩单 worker 内的 program 调度），HiCache 反而更关键。配置里用 `parallel.tp` 一个字段表达，渲染层自动决定是单机 compose 还是跨机。
- **L3 用 mooncake 还是 flexkv**。两者都收敛为 SGLang HiCache 的 storage backend 配置 + 一个 sidecar/独立部署单元，`configs/serving/l3-*.yaml` 二选一叠加，业务代码零感知。

---

## 2. 仓库总体结构

单 monorepo，名字沿用 `tokiln`。现有两个 repo 以 git submodule 引入（保持独立演进），集成代码放在主仓。

```
tokiln/
├── Makefile                        # 顶层入口：make preflight / m0 / m1 / bench / report
├── README.md
├── VERSIONS.lock                   # 全局版本锁：镜像 digest、dynamo/sglang/mooncake 版本、模型 revision
│
├── configs/                        # ★ 唯一事实来源，全部声明式 YAML
│   ├── cluster/
│   │   ├── inventory.yaml          # 2 节点：IP、SSH、GPU SKU/数量、RDMA 设备、NVMe 路径
│   │   └── host-contract.yaml      # OS/内核/驱动/CUDA/容器运行时的受支持矩阵
│   ├── models/
│   │   └── glm-5.2.yaml            # 权重 URI、quant(FP8/BF16)、tokenizer、reasoning/tool parser、context 上限
│   ├── serving/
│   │   ├── profiles/
│   │   │   ├── m0-sglang-only.yaml     # 纯 SGLang TP8 单节点（最基础）
│   │   │   ├── m1-dynamo-agg-2xtp8.yaml# Dynamo frontend + thunderagent + 2×TP8
│   │   │   └── m1-alt-tp16.yaml        # 备选：跨节点 TP16
│   │   ├── overlays/
│   │   │   ├── hicache-l2.yaml         # host DRAM offload：hicache_ratio、write policy、page size
│   │   │   ├── l3-mooncake.yaml        # mooncake store 端点、RDMA 设备、副本策略
│   │   │   └── l3-flexkv.yaml          # flexkv 等价配置（与 mooncake 互斥叠加）
│   │   └── router/
│   │       └── thunderagent.yaml       # program-aware 调度参数、session 亲和、pause/resume 阈值
│   └── workloads/
│       ├── smoke.yaml                  # 10 并发 2 分钟，验证正确性
│       ├── steady-highcc.yaml          # 稳态高并发 30 分钟（验收门槛用）
│       └── agentic-prefix.yaml         # aa-loadgen：ISL 5K-131K lognormal、多轮、tool pause、A/B arm
│
├── deploy/
│   ├── docker/
│   │   ├── Dockerfile.sglang-glm52     # SGLang 0.5.13.post1+ + GLM-5.2 依赖，产出锁 digest
│   │   ├── Dockerfile.dynamo           # dynamo + 自建 sglang adapter（若官方 pin 不兼容）
│   │   └── build.sh                    # 构建并把 digest 写回 VERSIONS.lock
│   ├── compose/                        # M0–M2 运行时：每节点一份 systemd/compose
│   │   ├── m0.node1.compose.yaml.j2    # 由 tokiln render 生成，模板受版本控制、产物进 runs/
│   │   ├── m1.node{1,2}.compose.yaml.j2
│   │   └── infra.compose.yaml.j2       # NATS、etcd、prometheus、grafana、mooncake-store
│   └── k8s/                            # M3+：kubeadm bootstrap 之后的清单
│       ├── bootstrap/                  # ansible playbook + kubeadm 配置（入口B）
│       ├── platform/                   # gpu-operator、dcgm-exporter、监控栈
│       └── dgd/                        # DynamoGraphDeployment 模板（同一 profile 渲染）
│
├── tokiln/                             # ★ Python 控制面包（唯一自研主体，~2-3k 行）
│   ├── cli.py                          # tokiln preflight|render|deploy|probe|bench|report|down
│   ├── config/
│   │   ├── schema.py                   # pydantic：Inventory / ModelSpec / ServingProfile / Workload
│   │   └── merge.py                    # profile + overlays 合成 resolved config，并计算 config digest
│   ├── preflight/
│   │   ├── host.py                     # SSH 只读检查：GPU、驱动、CUDA、NVMe 空间、hugepages
│   │   ├── rdma.py                     # ib_write_bw / rping 连通性与带宽，Mooncake 前置门槛
│   │   └── report.py                   # 输出 preflight.json + 人读 markdown
│   ├── render/
│   │   ├── compose.py                  # resolved config → compose 文件（M0-M2 后端）
│   │   └── dgd.py                      # resolved config → K8s DGD（M3 后端，接口相同）
│   ├── probes/                         # ★ 兼容性 Gate 的代码化
│   │   ├── streaming.py                # SSE chat completion、token 时间戳、usage 字段
│   │   ├── cancel.py                   # 断开连接后 GPU 是否停止消耗（验收门槛）
│   │   ├── parser.py                   # GLM-5.2 reasoning/tool-call parser 输出结构断言
│   │   ├── kv_events.py                # Dynamo KV event / SGLang cache report 一致性
│   │   └── hicache.py                  # cold/warm/shared-prefix 三组请求，断言命中率单调关系
│   ├── bench/
│   │   ├── runner.py                   # 驱动 aa-loadgen 与 bench_serving，注入 run_id
│   │   └── scenarios.py                # workloads/*.yaml → 具体命令行与 seed
│   └── report/
│       ├── manifest.py                 # RunManifest：config digest + 镜像 digest + git sha + seed
│       └── aggregate.py                # JSONL → TTFT/ITL/E2E/goodput/cache-hit 汇总表
│
├── third_party/
│   ├── aa-loadgen/                     # git submodule（现有 repo，不改动，只在 bench/runner 里调用）
│   └── agentic-serving-monitor/        # git submodule（私有 repo）
│
├── monitor/
│   ├── prometheus/prometheus.yml.j2    # scrape：dynamo frontend、sglang /metrics、dcgm、node
│   ├── grafana/dashboards/             # 四层：GPU / 引擎 / 请求 / agentic session
│   └── integration.md                  # agentic-serving-monitor 的接入契约（见 §6）
│
├── spikes/                             # Phase 1A：每个 spike 一个目录，一页结论 + 原始证据
│   ├── 01-glm52-sglang-standalone/
│   ├── 02-dynamo-sglang-adapter/
│   ├── 03-hicache-l2/
│   ├── 04-l3-mooncake-vs-flexkv/
│   └── TEMPLATE.md                     # 版本/硬件/命令/证据/失败模式/Go-NoGo
│
├── runs/                               # gitignore；每次 bench 产出 runs/<ts>-<run_id>/
│   └── <run_id>/{manifest.json, resolved-config.yaml, raw/*.jsonl, report.md}
│
└── docs/
    ├── runbook.md                      # 部署/检查/压测/看瓶颈/升级回滚/删除
    └── decisions/                      # ADR：TP8×2 vs TP16、mooncake vs flexkv 等
```

---

## 3. 配置模型：一份 profile + 可叠加 overlay

核心思想：**部署形态 = profile ⊕ overlays**，合成后产生一个带 digest 的 resolved config，进 run manifest。示例：

`configs/models/glm-5.2.yaml`
```yaml
model:
  name: glm-5.2
  source: hf://zai-org/GLM-5.2          # 或内部镜像 URI
  revision: <pin-commit>
  quant: fp8                            # M0 spike 决定 fp8/bf16
  context_len: 131072
  served_model_name: glm-5.2
  chat_template: glm-5.2
  reasoning_parser: glm45               # spike 验证实际 parser 名
  tool_call_parser: glm45
  weights_cache: /data/models           # 每节点本地 NVMe
```

`configs/serving/profiles/m1-dynamo-agg-2xtp8.yaml`
```yaml
profile:
  runtime: dynamo                       # m0 profile 里是 sglang-direct
  frontend: {port: 8100, mode: openai}
  router:
    kind: thunderagent                  # 备选 kv-aware / round-robin，A/B 用
    session_header: x-dynamo-session-id
  workers:
    - {node: node1, gpus: [0-7], parallel: {tp: 8}}
    - {node: node2, gpus: [0-7], parallel: {tp: 8}}
  kv:
    l1: radix                           # GPU RadixAttention，永远开
  limits: {max_concurrency: 256, queue_size: 128, timeout_s: 600}
```

`configs/serving/overlays/l3-mooncake.yaml`（换 FlexKV 只换这一个文件）
```yaml
kv:
  l2:
    enabled: true
    host_mem_gb: 512                    # 按节点 DRAM 定
    write_policy: write_through
  l3:
    backend: mooncake                   # or: flexkv
    endpoints: [node1:port, node2:port]
    transport: rdma
    rdma_devices: [mlx5_0, mlx5_1]
```

渲染命令与产物：

```
tokiln render --profile m1-dynamo-agg-2xtp8 --overlay hicache-l2 --overlay l3-mooncake \
              --out runs/<run_id>/
# 产出：resolved-config.yaml（含 digest）+ 每节点 compose 文件（或 M3 时的 DGD yaml）
```

---

## 4. 里程碑：从最基础做起（每步都有硬验收）

每个里程碑都是"能跑 + 能证明跑得怎样"，不通过不进下一层。这与设计文档 §6.1 的降级顺序一一对应。

### M0 — 单节点、纯 SGLang、GLM-5.2 能正确出 token（约 2-3 天）
- 内容：`Dockerfile.sglang-glm52` 构建镜像；node1 上 TP8 起 GLM-5.2；`tokiln probe streaming|cancel|parser` 全绿；`bench_serving` 跑一条单轮基线曲线。
- 关键产出：**模型显存包络**（权重 + 激活 + KV 预算），据此拍板 TP8×2 还是 TP16。
- 这是设计文档里"未通过 GLM-5.2 Gate 就用 direct-SGLang 路径"的那个 Gate 本身——M0 通过后，即使后面 Dynamo 集成失败，也已经有可交付的降级形态（direct SGLang + 简单 gateway）。

### M1 — 双节点、Dynamo + thunderagent_router（约 1 周）
- 内容：infra compose（NATS/etcd）+ frontend + 2×TP8 worker 注册；`probe kv_events` 验证 KV event 流；aa-loadgen 用 Arm A（thunderagent）vs Arm B（KV-routing-only）做第一次 A/B，`--concurrency 64 --duration 600`。
- 风险点即设计文档的关键阻塞：dynamo 1.2.1 pin SGLang 0.5.11 vs GLM-5.2 要求 0.5.13.post1+。M1 的第一个任务就是 `spikes/02`：自建 dynamo sglang-adapter 容器并跑 contract test，不通过则 M1 改为"direct SGLang ×2 + nginx/简单 router"，thunderagent 评估顺延。
- 验收：30 分钟稳态无 OOM/NaN/重启/请求泄漏；cancel 后 GPU 利用率回落；A/B 报告含 P95 TTFT、P25/median output speed、steps/min。

### M2 — HiCache L2，然后 L3（约 1-1.5 周，严格分两步）
- 第一步只开 **L2 host offload**（`overlays/hicache-l2.yaml`），跑 `probe hicache` 的 cold/warm/shared-prefix 三组，确认命中率与 reused tokens 可解释、长上下文多轮场景 TTFT 改善可量化。
- 第二步再叠 **L3**：默认先试 mooncake（RDMA 路径成熟、与 SGLang HiCache 集成有公开最佳实践），`spikes/04` 里用同一 workload 对 flexkv 做对照；两者共享 overlay schema，切换成本 = 换一个 `--overlay` 参数。
- 验收：shared-prefix workload 下 L2/L3 命中带来的 prefill 节省在报告里可区分（cache hit rate、reused tokens、TTFT 分布左移），且关掉 L3 系统能干净降级到 L2。

### M3 — Kubernetes 化 + 完整可观测（约 1-2 周）
- kubeadm bootstrap（入口B）把这两台机器引导成 1 control-plane + 2 GPU worker（control-plane 可与 node1 复用）；安装 gpu-operator、dcgm-exporter、监控栈；`render/dgd.py` 把同一 profile 渲染成 DynamoGraphDeployment。
- 验收 = 设计文档 §4.3 全套：同一声明式配置从 compose 与 K8s 两条路都能到达同一 endpoint 行为；Bootstrap/镜像/模型/配置全可追溯。

### M4 —（Phase 2 起点）容量报告与回归
- `report/aggregate.py` 固化容量曲线（concurrency → goodput/TTFT/ITL），每次版本升级跑同一 scenario 做性能回归；Rust loadgen 决策门槛在这里用数据触发（客户端 CPU/连接先饱和才立项）。

---

## 5. tokiln CLI 命令面（M0 就要有的骨架）

```
tokiln preflight --inventory configs/cluster/inventory.yaml     # 只读，出 preflight.json
tokiln render    --profile <p> [--overlay <o> ...]              # 出 resolved config + 部署文件
tokiln deploy    --run-id <id> [--backend compose|k8s]          # scp/ssh 或 kubectl apply
tokiln probe     all|streaming|cancel|parser|kv_events|hicache  # 兼容性 Gate
tokiln bench     --workload agentic-prefix --arm A              # 包装 aa-loadgen / bench_serving
tokiln report    --run-id <id>                                  # manifest + 汇总 + Grafana 快照链接
tokiln down      --run-id <id>                                  # 幂等清理，只删 tokiln-owned 资源
```

Makefile 把常用组合固化：`make m0`、`make m1-ab`、`make bench-steady` 等，每个目标背后是上述 CLI 的固定参数序列，保证任何人跑出来的东西一致。

---

## 6. 与现有两个 repo 的集成契约

**aa-loadgen（submodule，不改内部代码）**：`tokiln/bench/runner.py` 负责三件事——把 workload YAML 翻译成 `aa_loadgen.py` 命令行；注入 `--out runs/<run_id>/raw/aa_arm{A,B}.json` 与统一 run_id；A/B 时保证除 router 外一切参数（seed、并发、时长、nonce 策略）逐字节一致。它现有的 per-session nonce 防跨 arm KV 复用、`x-dynamo-session-id` 注入正好和 thunderagent profile 对齐，不需要额外开发。若后续需要 cancellation 注入或更细的 SSE token 时间戳，以 PR 回它自己的 repo，不在主仓 fork。

**agentic-serving-monitor（submodule，接口以实际 repo 为准）**：主仓只约定两个契约——(a) metrics 契约：`monitor/prometheus/` 定义 scrape 目标与 label 规范（`run_id`、`arm`、`worker` 为低基数 label；session_id/prompt 永不进 label，只进日志）；(b) 事件契约：aa-loadgen 的 per-request JSONL 与 serving 侧 metrics 通过 `run_id + request_id` 关联。monitor 作为消费方读这两样东西，不反向依赖控制面。

---

## 7. 先要拍板 / 我需要你确认的输入

1. **H20 具体 SKU 与节点 DRAM/NVMe 容量**（96GB 还是 141GB 版本、单节点内存多少）——直接决定 TP8×2 可行性和 HiCache L2 的 host_mem_gb。
2. **节点间网络**：有没有 IB/RoCE，几张网卡、多少带宽——没有 RDMA 的话 Mooncake L3 与跨节点 TP16 都要降级，M2 第二步改为 FlexKV 本地层或纯 L2。
3. **GLM-5.2 权重形态**：FP8 checkpoint 是否直接可得，license/下载渠道。
4. **一期目标并发**：aa-loadgen 的 64 并发是起点，验收门槛要定在几百还是上千 session。
5. **agentic-serving-monitor 的实际形态**（我访问不到私有 repo）：它是 exporter、dashboard 还是独立服务？§6 的契约需要按实际调整。

---

## 附录 A（v0.2 增补，2026-07-24）：读完 aa-loadgen 实际代码后的修正

本节基于对 `davilu-nvidia/aa-loadgen` 全量源码（`aa_loadgen.py` + `aaload/{core,synth,replay}.py` + `replay/` + `monitor/`，共 686 行）的阅读，修正 v0.1 的三处假设。

### A.1 硬件确认：H20 为 141GB 版本

单节点 8×141GB = 1128GB HBM。结论：**2×TP8 aggregated 定为默认拓扑**，`m1-alt-tp16.yaml` 降级为"仅保留文件、不投入验证"。附带影响：单 worker GPU KV 池非常大，L1 RadixAttention 在中短 trace 下会吃掉大部分命中，**M2 若要证明 L2/L3 增益，workload 必须用长 trace（full300 级别）或人为压缩 GPU KV 预算（`--mem-fraction` 调低）做对照**，否则 HiCache 结论会失真为"没用"。

### A.2 aa-loadgen 有两种模式，M1 起以 replay 为主

- `synth`：AA-AgentPerf 分布合成（ISL lognormal mean 27K、区间 5K–131K；OSL 60% 短 tool-call / 40% 长 reasoning；tool delay 中位 1s；每 session 6–40 轮；per-session nonce 防跨 arm KV 复用）。适合 smoke 和容量曲线。
- `replay`：mini-SWE-agent + SWE-bench 录制的真实轨迹回放。`recording_hook` 录 verbatim messages / 真实 OSL / 真实 tool 间隔 → `convert_to_dag.py` 出 `dag.jsonl` → 闭环并发回放，`ignore_eos` 钉死 OSL。**A/B 公平性最强，thunderagent 与 HiCache 的正式结论以 replay 结果为准**，synth 结果只做补充。
- 对 `configs/workloads/` 的修正：`agentic-prefix.yaml` 拆成 `agentic-synth.yaml` 与 `agentic-replay.yaml`，后者引用 trace 文件路径 + tokenizer + 并发。注意 README 明示：回放 DSV4 轨迹在 GLM-5.2 上是合法**负载测试**，但不代表 GLM 自身 agent 行为——若要 GLM 行为学结论，需在 M1 完成后用 GLM-5.2 重录一批 trace（列入 M2 前置任务）。
- metrics 契约以 `aaload/core.py` 为准：TTFT / out_speed(tok/s) / TPOT(ms) / session E2E / steps；token 计数优先 `stream_options.include_usage` 的服务端 usage，回退 delta 计数。`tokiln/report/aggregate.py` 直接消费其 JSON 输出，不重复实现。

### A.3 monitor/ 即轻量实验看板，与 Prometheus 分层共存

`monitor/` 三件套（`collect_metrics.sh` 5s 采集→JSON、`monitor.html` 本地看板、`run_exp.sh` 一键实验器）已覆盖：TA pause/resume/still_paused 计数、GPU 实测 util vs TA 预估 util 双线、HiCache host_used/host_total、TTFT/TPOT/E2E P50。定位修正：

- **实验期快看板**：保留原样使用，不改造成 Prometheus exporter（它的价值就是零依赖、5 秒可见）。
- **持久层**：Prometheus/Grafana 按 v0.1 §6 建设，采集同源指标（dynamo/sglang /metrics + DCGM），负责历史留存、多 run 对比与告警。
- 两层通过 `run_id` 关联；`monitor/README.md` 里的三个"已知坑"（采集器单实例、pgrep 误报、sed 提取）作为 `tokiln probe` 的前置检查项吸收进代码。

### A.4 真实起点：把 ta-repro 容器声明式化

`run_exp.sh` 表明现存一个手工搭建的单容器实验环境：docker 容器 `ta-repro`、etcd 服务发现、frontend :8000、模型名 `glm52ta`（TA on）/ `glm52`（no TA）、trace 位于 `/workspace/davilu/full300_traj/`。因此 M0 的任务从"从零起 SGLang"改为：

1. **考古固化**：提取 ta-repro 内的实际版本（dynamo/sglang/驱动/启动参数）写入 `VERSIONS.lock` 与 `configs/serving/profiles/`，镜像重建并锁 digest——这一步同时就是 spike 01/02 的答案来源；
2. **健康检查代码化**：`run_exp.sh` 的栈健康检查（etcd endpoint 计数、/v1/models 断言、文件方式预热）吸收为 `tokiln probe stack`；
3. **再扩双节点**：在声明式配置下复现 ta-repro 行为（单节点回归通过）后，才加 node2 worker 进入 M1。

风险提示：ta-repro 是"能跑的组合"的活证据，但手工容器的漂移（apt/pip 就地升级、未记录的 flag）是最大的复现风险——固化前不要在其上继续叠加实验变量。
