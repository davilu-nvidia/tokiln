# Tokiln Runbook (M0–M1)

## Deploy
1. `tokiln preflight` — if go=false, fix the machine per the report; never deploy sick
2. `tokiln render --profile m0-sglang-only` — produces a run_dir with per-node compose files
3. scp the compose files to their nodes, `docker compose up -d`
4. `tokiln probe all --url http://node1:8000/v1 --model glm52`

## Load testing
- smoke: `tokiln bench --workload smoke --arm A`
- A/B: two bench runs differing only in the profile's router.kind (or run_exp-style model-name switch); everything else identical
- Aggregate: single arm `tokiln report runs/<run_id>`; for A/B pass two dirs `tokiln report runs/<armA_run> runs/<armB_run>` (side-by-side table + delta column)

## Watching for bottlenecks
- Live: `make monitor-serve` on the serving node, then `tokiln monitor watch` from any terminal, or open :8100 in a browser
- Quick dashboard: third_party/aa-loadgen/monitor (5s granularity)
- Persistent: Grafana :3000 (GPU / engine / request dashboards)

## Upgrade / rollback
- Upgrades only via VERSIONS.lock changes + rebuild/re-render; no in-place pip/apt inside containers
- Rollback = checkout an older commit and re-render (digests are comparable)

## Teardown
- `docker compose down` per node; keep runs/ archives
