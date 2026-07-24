"""压测编排: workload YAML → aa-loadgen (submodule) 命令行, 统一 run_id 归档。
原则: 不 fork aa-loadgen; A/B 两 arm 除 router 外逐字节一致。"""
import pathlib, shlex, subprocess, time
from ..config.merge import load_workload

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOADGEN = ROOT / "third_party" / "aa-loadgen" / "aa_loadgen.py"


def build_cmd(workload_name: str, url: str, model: str, arm: str,
              out_dir: pathlib.Path) -> list[str]:
    w = load_workload(workload_name)
    out = out_dir / f"aa_{w.name}_arm{arm}.json"
    cmd = ["python3", str(LOADGEN), w.mode, "--url", url, "--model", model,
           "--arm", arm, "--out", str(out)]
    p = w.params
    if w.mode == "synth":
        cmd += ["--concurrency", str(p.get("concurrency", 8)),
                "--duration", str(p.get("duration_s", 120))]
        if p.get("seed") is not None:
            cmd += ["--seed", str(p["seed"])]   # 若 loadgen 无 --seed, 以 PR 加回其 repo
    else:  # replay
        cmd += ["--replay", str(ROOT / p["trace"]),
                "--concurrency", str(p.get("concurrency", 32)),
                "--duration", "0"]
        if p.get("agent_context"):
            cmd += ["--agent-context"]
    return cmd


def run(workload_name: str, url: str, model: str, arm: str, run_dir: pathlib.Path) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_cmd(workload_name, url, model, arm, run_dir)
    log = run_dir / f"loadgen_arm{arm}.log"
    t0 = time.time()
    with open(log, "w") as lf:
        rc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT).returncode
    return {"cmd": shlex.join(cmd), "rc": rc, "wall_s": round(time.time() - t0, 1),
            "log": str(log)}
