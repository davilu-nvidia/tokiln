"""Bench orchestration: workload YAML → aa-loadgen (submodule) command line, archived under a unified run_id.
Principles: never fork aa-loadgen; the two A/B arms must be byte-identical except for the router."""
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
            cmd += ["--seed", str(p["seed"])]   # if loadgen lacks --seed, add it back via a PR to its repo
    else:  # replay
        cmd += ["--replay", str(ROOT / p["trace"]),
                "--concurrency", str(p.get("concurrency", 32)),
                "--duration", "0"]
        if p.get("agent_context"):
            cmd += ["--agent-context"]
    return cmd


def check_criteria(result_path: pathlib.Path, criteria: dict) -> dict:
    """Compare measured results against the workload's pass_criteria. Declared criteria must be enforced."""
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
        return {"rc": 3, "error": f"aa-loadgen not ready: {LOADGEN} missing. "
                                  "Run: git submodule update --init (private repos need access configured first)",
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
        rc = 4                    # loadgen finished normally but pass_criteria not met
    return {"cmd": shlex.join(cmd), "rc": rc, "wall_s": round(time.time() - t0, 1),
            "log": str(log), "criteria": verdict}
