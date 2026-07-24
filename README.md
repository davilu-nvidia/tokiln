# Tokiln

把 2×8 H20(141GB) 变成可部署、可调用、可观察、可压测的 GLM-5.2 Token 服务。
栈: NVIDIA Dynamo + SGLang + ThunderAgent router + HiCache (L2 host offload, L3 mooncake/flexkv 可切)。

- 设计文档: [docs/design/tokiln-code-structure.md](docs/design/tokiln-code-structure.md)
- 压测器: [third_party/aa-loadgen](https://github.com/davilu-nvidia/aa-loadgen) (submodule; synth + 真实轨迹 replay)
- 里程碑: M0 单节点纯 SGLang → M1 Dynamo+TA 双节点 A/B → M2 HiCache L2→L3 → M3 K8s 化

```bash
make install
make preflight            # SSH 只读检查 2 节点
make m0-render            # 声明式配置 → compose (带 config digest)
make probe                # streaming/cancel/parser/hicache/stack 五探针 Go/No-Go
make smoke && make bench-ab
```

原则: 自研代码只做 渲染/探针/编排/归档 四件事; 调度、KV、网关全部来自上游, 只写配置不写实现。
每次运行落 `runs/<run_id>/manifest.json` (git sha + config digest + 镜像 digest + seed), 保证可复现。

**当前状态**: M0 脚手架。所有 `TODO(spike NN)` 标记处等待 ta-repro 考古与四个兼容性 spike 回填。
