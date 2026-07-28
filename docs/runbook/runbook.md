# Tokiln Runbook (M0–M1)

## 部署
1. `tokiln preflight` — go=false 则按报告修机器, 不带病部署
2. `tokiln render --profile m0-sglang-only` — 得到 run_dir 与每节点 compose
3. 将 run_dir 下 compose scp 至对应节点, `docker compose up -d`
4. `tokiln probe all --url http://node1:8000/v1 --model glm52`

## 压测
- smoke: `tokiln bench --workload smoke --arm A`
- A/B:  两次 bench 仅换 profile 的 router.kind (或 run_exp 风格切模型名), 其余参数不动
- 汇总: 单 arm `tokiln report runs/<run_id>`; A/B 传两个目录 `tokiln report runs/<armA_run> runs/<armB_run>` (自动出并排表 + 差值列)

## 看瓶颈
- 快看板: third_party/aa-loadgen/monitor (5s 粒度)
- 持久: Grafana :3000 (GPU/引擎/请求三层 dashboard)

## 升级/回滚
- 只允许通过改 VERSIONS.lock + 重新 build/render 升级; 禁止容器内就地 pip/apt
- 回滚 = checkout 旧 commit 重新 render (digest 可比对)

## 删除
- `docker compose down` 逐节点; runs/ 归档保留
