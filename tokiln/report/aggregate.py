"""Aggregation: consume aa-loadgen's JSON output directly (report structure from aaload/core.py);
do not re-implement metrics. Two A/B arms side by side + delta column; collects arms across
multiple run_dirs (bench uses one run_dir per arm).
Parsers for bench_serving/aiperf to be added later."""
import json, pathlib

# Strictly aligned with the output fields of aaload/core.py build_report (contract)
KEYS = ["ttft_p50_s", "ttft_p95_s", "tpot_p50_ms", "tpot_p95_ms",
        "e2e_p50_s", "steps_per_min", "throughput_tok_s",
        "out_speed_median_tok_s", "requests_ok", "requests_err", "total_out_tokens"]

# Lower-is-better metrics, used to annotate the delta direction
LOWER_BETTER = {"ttft_p50_s", "ttft_p95_s", "tpot_p50_ms", "tpot_p95_ms", "e2e_p50_s", "requests_err"}


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
    """Collect all aa_*_arm*.json under the given run_dirs into one comparison table per arm.
    The result is written to report.md in the first run_dir."""
    if isinstance(run_dirs, pathlib.Path):  # backward compat for single-dir calls
        run_dirs = [run_dirs]
    arm_files: dict[str, pathlib.Path] = {}
    for rd in run_dirs:
        for p in sorted(rd.glob("aa_*_arm*.json")):
            arm = p.stem.split("arm")[-1]
            if arm in arm_files:
                raise ValueError(f"arm {arm} appears more than once: {arm_files[arm]} and {p}; "
                                 "pass only the run_dirs under comparison")
            arm_files[arm] = p
    if not arm_files:
        raise FileNotFoundError(f"no aa_*_arm*.json found under {[str(r) for r in run_dirs]}")
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
                d += " ↓ better"
            cells.append(d)
        lines.append("| " + " | ".join(cells) + " |")

    # Contract-drift warning: if every expected metric of an arm is None, list the actual fields
    for arm, v in rows.items():
        if all(v.get(k) is None for k in KEYS):
            lines += ["", f"> ⚠ every expected metric of arm {arm} is missing; loadgen output fields: "
                          f"{', '.join(v['_raw_keys'][:20])} — check KEYS against the aaload/core.py contract"]

    out = run_dirs[0] / "report.md"
    out.write_text("\n".join(lines) + "\n")
    return str(out)
