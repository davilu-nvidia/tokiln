# Tokiln Quickstart (M0: 单节点 SGLang)

从零到"服务起来、发压、实时监控"的最短路径。以 h20-09 (8×H20-3e) + GLM-5.2-FP8 为例。

## 0. 前置条件

- 权重在 `configs/models/<model>.yaml` 的 `weights_cache/local_dir` 指向的目录 (例: `/raid/model_hub/GLM-5.2-FP8`)
- `VERSIONS.lock` 里 pin 的 sglang 镜像已 `docker pull`
- 控制机可免密 ssh 到 inventory 里所有 `enabled` 节点 (**包括自己**: `cat ~/.ssh/id_*.pub >> ~/.ssh/authorized_keys`)
- 端口 8000 (frontend) / 8100 (monitor) 空闲

## 1. 安装 → 体检 → 渲染 → 起服务

```bash
make install          # pip install -e . + submodule (pip >= 23 才支持 PEP660 editable)
make preflight        # ssh 只读体检所有 enabled 节点, go=True 才继续
make m0-render        # 渲染 docker compose 产物到 runs/<ts>-m0-sglang-only-<id>/
docker compose -f runs/<run_dir>/node1.compose.yaml up -d
docker logs -f <container>   # 等 "The server is fired up and ready to roll" (首次 DeepGEMM warmup ~5min)
```

## 2. 验收探针 (Go/No-Go)

```bash
make probe            # stack / streaming / parser / hicache / cancel 五连, 全 PASS 输出 GO
```

## 3. 发压 + 实时监控

服务节点起监控端 (采集 sglang /metrics + nvidia-smi + loadgen progress):

```bash
make monitor-serve    # :8100, 也可 nohup 后台跑
```

任意机器的终端看板 (**Windows / macOS / Linux 通用**, 仅 Python 标准库):

```bash
tokiln monitor watch --monitor-url http://10.6.131.9:8100
# 没装 tokiln 的机器: 拷走 tokiln/monitor/watch.py 单文件即可
python watch.py --url http://10.6.131.9:8100
```

浏览器版: 直接开 `http://10.6.131.9:8100/`。

发压 (120s smoke, 8 并发 agentic 合成负载):

```bash
make smoke            # 结束打印 pass_criteria 判定; 未达标 rc=4
python -m tokiln.cli report runs/<run_dir>   # 生成 report.md
```

监控看板效果:

```
┌─ tokiln monitor ── H20-GPU-09 ── 18:46:59 ── server UP ✓ ── model glm52
│ running    8   queued    0   gen    422.2 tok/s   aborted 3
│ KV usage [████████████░░░░░░░░░░░░]  52.0%   cache hit  71.6%   TTFT 1.621s   ITL 35.3ms
│ GPU util% [100 100 100 100 100 100 100 100]  mem 139G/卡  power 2839W
│ tput  ▄▂▇▆▄▄▇▅▂▂▂▂▂▂▂▁▁▁▁▁▁▁▁▁▁▁█▇▄▅▇▅▆█▇▁▇▆▇▃▃▅█▇▆▆█
│ client [20260728-184509-smoke-armA-1150dc] 2 done, ok=78 err=0 ...
└──────────────────────────────────────────────────────────────
```

## 常见坑 (h20-09 实测)

| 症状 | 原因 → 解法 |
|---|---|
| `make install` 报 build_editable | pip 太老 → `pip install -U pip` |
| preflight 全 255 | ssh 不通 (含到自己) → 加 authorized_keys |
| 起服务后 tool_calls 恒为 [] 且 finish_reason=tool_calls | parser 不匹配 → GLM-5.2 用 `glm47` |
| loadgen 大量 err 但服务正常 | reasoning 模型短回复全在 reasoning_content → 升级 aa-loadgen submodule |
| 8000 被占 | 残留旧 frontend → 清进程; GPU 残留看 `nvidia-smi --query-compute-apps=pid` |

完整过程见 [docs/exp/2026-07-28-m0-h20-09.md](exp/2026-07-28-m0-h20-09.md)。
