"""tokiln CLI: preflight | render | probe | bench | report | down
deploy 在 M0 阶段 = 打印每节点 scp+docker compose 命令 (人工确认执行), M1 起加 --apply。"""
import argparse, asyncio, pathlib, sys, time, uuid

import yaml

from .config.merge import load_resolved
from .render import compose as compose_render
from .report import manifest as manifest_mod
from .report import aggregate as aggregate_mod

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"


def _new_run_dir(tag: str) -> pathlib.Path:
    rid = f"{time.strftime('%Y%m%d-%H%M%S')}-{tag}-{uuid.uuid4().hex[:6]}"
    d = RUNS / rid
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_preflight(args):
    from .preflight import host
    inv = yaml.safe_load(open(ROOT / "configs/cluster/inventory.yaml"))
    rep = host.run(inv)
    out = pathlib.Path(args.out or f"preflight-{time.strftime('%Y%m%d-%H%M%S')}.json")
    host.write_report(rep, out)
    print(f"preflight: go={rep['go']} → {out}")
    sys.exit(0 if rep["go"] else 2)


def cmd_render(args):
    resolved = load_resolved(args.profile, args.overlay or [])
    run_dir = _new_run_dir(args.profile)
    files = compose_render.render(resolved, run_dir)
    manifest_mod.write(run_dir, resolved)
    print(f"digest={resolved['digest']} run_dir={run_dir}")
    for f in files:
        print(f"  rendered: {f}")


def cmd_probe(args):
    from .probes import streaming, cancel, parser as parser_probe, hicache, stack
    async def _run():
        results = []
        which = args.which
        if which in ("all", "stack"):
            results.append(await stack.run(args.url, args.model, etcd_url=args.etcd))
        if which in ("all", "streaming"):
            results.append(await streaming.run(args.url, args.model))
        if which in ("all", "parser"):
            results.append(await parser_probe.run(args.url, args.model))
        if which in ("all", "hicache"):
            results.append(await hicache.run(args.url, args.model))
        if which in ("all", "cancel"):
            results.append(await cancel.run(args.url, args.model, args.metrics))
        return results
    results = asyncio.run(_run())
    ok = all(r.ok for r in results)
    for r in results:
        print(r.line())
    print(f"probe verdict: {'GO' if ok else 'NO-GO'}")
    sys.exit(0 if ok else 2)


def cmd_bench(args):
    from .bench import runner
    run_dir = _new_run_dir(f"{args.workload}-arm{args.arm}")
    resolved = load_resolved(args.profile, args.overlay or [])
    manifest_mod.write(run_dir, resolved, {"workload": args.workload, "arm": args.arm})
    res = runner.run(args.workload, args.url, args.model, args.arm, run_dir)
    print(yaml.safe_dump(res, allow_unicode=True))
    sys.exit(res["rc"])


def cmd_report(args):
    print(aggregate_mod.compare(pathlib.Path(args.run_dir)))


def main():
    ap = argparse.ArgumentParser(prog="tokiln")
    sub = ap.add_subparsers(required=True)

    p = sub.add_parser("preflight"); p.add_argument("--out"); p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("render")
    p.add_argument("--profile", required=True)
    p.add_argument("--overlay", action="append")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("probe")
    p.add_argument("which", choices=["all", "stack", "streaming", "parser", "cancel", "hicache"])
    p.add_argument("--url", default="http://localhost:8000/v1")
    p.add_argument("--model", default="glm52")
    p.add_argument("--metrics", default="http://localhost:8000/metrics")
    p.add_argument("--etcd", default="")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("bench")
    p.add_argument("--workload", required=True)
    p.add_argument("--profile", default="m1-dynamo-agg-2xtp8")
    p.add_argument("--overlay", action="append")
    p.add_argument("--arm", default="A")
    p.add_argument("--url", default="http://localhost:8000/v1")
    p.add_argument("--model", default="glm52")
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("report"); p.add_argument("run_dir"); p.set_defaults(func=cmd_report)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
