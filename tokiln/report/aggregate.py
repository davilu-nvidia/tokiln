"""汇总: 直接消费 aa-loadgen 的 JSON 输出 (aaload/core.py 的 report 结构), 不重复实现指标。
A/B 两 arm 并排 + 差值; 支持跨多个 run_dir 收集 arm (bench 每个 arm 一个 run_dir)。
后续接 bench_serving/aiperf 的解析器。"""
import json, pathlib

KEYS = ["ttft_p95", "out_speed_p25", "out_speed_p50", "tpot_p50",
        "e2e_p50", "steps_per_min", "req_ok", "req_err", "total_out_tokens"]

# 差值中 "越低越好" 的指标, 用于标注方向
LOWER_BETTER = {"ttft_p95", "tpot_p50", "e2e_p50", "req_err"}


def load_arm(path: pathlib.Path) -> dict:
    d = json.loads(path.read_text())
    return {k: d.get(k) for k in KEYS} | {"_raw_keys": sorted(d.keys())}


def _fmt_delta(a, b, key: str) -> str:
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return ""
    diff = b - a
    pct = f" ({diff / a * 100:+.1f}%)" if a else ""
    return f"{diff:+g}{pct}"


def compare(run_dirs: list[pathlib.Path]) -> str:
    """收集所有 run_dir 下的 aa_*_arm*.json, 按 arm 汇总成一张对比表。
    结果写入第一个 run_dir 的 report.md。"""
    if isinstance(run_dirs, pathlib.Path):  # 向后兼容单目录调用
        run_dirs = [run_dirs]
    arm_files: dict[str, pathlib.Path] = {}
    for rd in run_dirs:
        for p in sorted(rd.glob("aa_*_arm*.json")):
            arm = p.stem.split("arm")[-1]
            if arm in arm_files:
                raise ValueError(f"arm {arm} 出现多次: {arm_files[arm]} 与 {p}; 请只传入待对比的 run_dir")
            arm_files[arm] = p
    if not arm_files:
        raise FileNotFoundError(f"未在 {[str(r) for r in run_dirs]} 找到 aa_*_arm*.json")
    rows = {arm: load_arm(p) for arm, p in sorted(arm_files.items())}
    arms = list(rows)

    lines = [f"# Bench report — {' vs '.join(rd.name for rd in run_dirs)}", ""]
    two = len(arms) == 2
    header_cells = ["metric", *arms] + ([f"Δ {arms[1]}−{arms[0]}"] if two else [])
    lines += ["| " + " | ".join(header_cells) + " |",
              "|" + "---|" * len(header_cells)]
    for k in KEYS:
        cells = [k] + [str(v.get(k)) for v in rows.values()]
        if two:
            d = _fmt_delta(rows[arms[0]].get(k), rows[arms[1]].get(k), k)
            if d and k in LOWER_BETTER:
                d += " ↓更优"
            cells.append(d)
        lines.append("| " + " | ".join(cells) + " |")

    # 契约漂移预警: 若某 arm 的 KEYS 全为 None, 提示实际可用字段
    for arm, v in rows.items():
        if all(v.get(k) is None for k in KEYS):
            lines += ["", f"> ⚠ arm {arm} 的所有预期指标均缺失, loadgen 输出字段为: "
                          f"{', '.join(v['_raw_keys'][:20])} — 请核对 KEYS 与 aaload/core.py 的契约"]

    out = run_dirs[0] / "report.md"
    out.write_text("\n".join(lines) + "\n")
    return str(out)
