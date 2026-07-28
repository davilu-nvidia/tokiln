"""Bench pass_criteria checks + report field contract (regression: KEYS drifted from aa-loadgen output, all-None report)."""
import json
import pathlib
import shutil

from tokiln.bench.runner import check_criteria
from tokiln.report import aggregate

FIXTURE = pathlib.Path(__file__).parent / "fixtures_loadgen_result.json"


def test_criteria_pass(tmp_path):
    v = check_criteria(FIXTURE, {"err_rate_max": 0.0, "ttft_p95_s_max": 10})
    assert v["evaluated"] and v["pass"]


def test_criteria_fail_on_ttft():
    v = check_criteria(FIXTURE, {"ttft_p95_s_max": 0.001})
    assert v["evaluated"] and not v["pass"]


def test_criteria_absent():
    assert check_criteria(FIXTURE, {})["evaluated"] is False


def test_report_keys_exist_in_loadgen_output():
    """Contract: every field in aggregate.KEYS must actually exist in aa-loadgen output."""
    d = json.loads(FIXTURE.read_text())
    missing = [k for k in aggregate.KEYS if k not in d]
    assert not missing, f"KEYS drifted from aa-loadgen output: {missing}"


def test_compare_renders_table(tmp_path):
    rd = tmp_path / "run1"; rd.mkdir()
    shutil.copy(FIXTURE, rd / "aa_smoke_armA.json")
    out = aggregate.compare([rd])
    text = pathlib.Path(out).read_text()
    assert "ttft_p95_s" in text and "None" not in text.split("steps_per_min")[0]
