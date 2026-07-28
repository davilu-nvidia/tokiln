"""bench 验收判定 + report 字段契约 (回归: KEYS 与 aa-loadgen 输出漂移致报表全 None)。"""
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
    """契约: aggregate.KEYS 的每个字段都必须真实出现在 aa-loadgen 输出里。"""
    d = json.loads(FIXTURE.read_text())
    missing = [k for k in aggregate.KEYS if k not in d]
    assert not missing, f"KEYS 与 aa-loadgen 输出漂移: {missing}"


def test_compare_renders_table(tmp_path):
    rd = tmp_path / "run1"; rd.mkdir()
    shutil.copy(FIXTURE, rd / "aa_smoke_armA.json")
    out = aggregate.compare([rd])
    text = pathlib.Path(out).read_text()
    assert "ttft_p95_s" in text and "None" not in text.split("steps_per_min")[0]
