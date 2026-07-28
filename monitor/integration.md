# Monitoring layering contract

**Quick dashboard (experiment-time)**: use the `third_party/aa-loadgen/monitor/` trio as-is (5s JSON + monitor.html).
**Live terminal**: `tokiln monitor serve` (:8100) + `tokiln monitor watch` (stdlib-only, win/mac/linux).
**Persistent layer**: Prometheus/Grafana in this directory — history retention, multi-run comparison, alerting.

Contract:
1. Label discipline: `run_id` / `arm` / `worker` are low-cardinality labels; session_id and prompts never
   become labels — logs only.
2. Join key: aa-loadgen JSONL and serving metrics cross-reference via `run_id + request_id`.
3. Known pitfalls (from the aa-loadgen monitor/README): the collector must be a single instance; process
   detection uses `ps -eo stat,comm` rather than `pgrep -f`; GPU truth comes from
   `nvidia-smi --query-compute-apps=pid`. All three are absorbed into `tokiln probe stack` checks or the runbook.
