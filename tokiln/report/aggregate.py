"""汇总: 直接消费 aa-loadgen 的 JSON 输出 (aaload/core.py 的 report 结构), 不重复实现指标。
A/B 两 arm 并排 + 差值; 后续接 bench_serving/aiperf 的解析器。"""
import json, pathlib

KEYS = ["ttft_p95", "out_speed_p25", "out_speed_p50", "tpot_p50",
        "e2e_p50", "steps_per_min", "req_ok", "req_err", "total_out_tokens"]


def load_arm(path: pathlib.Path) -> dict:
    d = json.loads(path.read_text())
    return {k: d.get(k) for k in KEYS} | {"_raw_keys": sorted(d.keys())}


def compare(run_dir: pathlib.Path) -> str:
    arms = sorted(run_dir.glob("aa_*_arm*.json"))
    rows = {p.stem.split("arm")[-1]: load_arm(p) for p in arms}
    lines = [f"# Bench report — {run_dir.name}", ""]
    header = "| metric | " + " | ".join(rows) + " |"
    lines += [header, "|" + "---|" * (len(rows) + 1)]
    for k in KEYS:
        lines.append("| " + k + " | " + " | ".join(str(v.get(k)) for v in rows.values()) + " |")
    out = run_dir / "report.md"
    out.write_text("\n".join(lines) + "\n")
    return str(out)
