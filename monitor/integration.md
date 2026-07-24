# 监控分层契约

**快看板 (实验期)**: `third_party/aa-loadgen/monitor/` 三件套原样使用 (5s JSON + monitor.html)。
**持久层**: 本目录 Prometheus/Grafana, 负责历史留存、多 run 对比、告警。

契约:
1. label 规范: `run_id` / `arm` / `worker` 为低基数 label; session_id、prompt 永不进 label, 只进日志。
2. 关联键: aa-loadgen JSONL 与 serving metrics 通过 `run_id + request_id` 交叉定位。
3. 已知坑 (源自 aa-loadgen monitor/README): 采集器必须单实例; 进程判定用
   `ps -eo stat,comm` 而非 `pgrep -f`; GPU 真相以 `nvidia-smi --query-compute-apps=pid` 为准。
   这三条已吸收进 `tokiln probe stack` 的检查逻辑或 runbook。
