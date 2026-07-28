"""压测编排: workload YAML → aa-loadgen (submodule) 命令行, 统一 run_id 归档。
原则: 不 fork aa-loadgen; A/B 两 arm 除 router 外逐字节一致。"""
import json, pathlib, shlex, subprocess, time
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


def check_criteria(result_path: pathlib.Path, criteria: dict) -> dict:
    """workload 的 pass_criteria 对照实测结果。声明了标准就必须执行。"""
    if not criteria or not result_path.exists():
        return {"evaluated": False}
    d = json.loads(result_path.read_text())
    checks, ok = {}, True
    if "err_rate_max" in criteria:
        total = d.get("requests_ok", 0) + d.get("requests_err", 0)
        rate = d.get("requests_err", 0) / total if total else 1.0
        good = rate <= criteria["err_rate_max"]
        checks["err_rate"] = {"actual": round(rate, 4), "max": criteria["err_rate_max"], "pass": good}
        ok &= good
    if "ttft_p95_s_max" in criteria:
        v = d.get("ttft_p95_s")
        good = v is not None and v <= criteria["ttft_p95_s_max"]
        checks["ttft_p95_s"] = {"actual": v, "max": criteria["ttft_p95_s_max"], "pass": good}
        ok &= good
    return {"evaluated": True, "pass": bool(ok), "checks": checks}


def run(workload_name: str, url: str, model: str, arm: str, run_dir: pathlib.Path) -> dict:
    if not LOADGEN.exists():
        return {"rc": 3, "error": f"aa-loadgen 未就绪: {LOADGEN} 不存在。"
                                  "请先执行: git submodule update --init (私有仓库需先配置访问权限)",
                "cmd": "", "wall_s": 0.0, "log": ""}
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_cmd(workload_name, url, model, arm, run_dir)
    log = run_dir / f"loadgen_arm{arm}.log"
    t0 = time.time()
    with open(log, "w") as lf:
        rc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT).returncode
    w = load_workload(workload_name)
    out = run_dir / f"aa_{w.name}_arm{arm}.json"
    verdict = check_criteria(out, w.pass_criteria)
    if rc == 0 and verdict.get("evaluated") and not verdict["pass"]:
        rc = 4                    # loadgen 正常结束但未达 pass_criteria
    return {"cmd": shlex.join(cmd), "rc": rc, "wall_s": round(time.time() - t0, 1),
            "log": str(log), "criteria": verdict}
