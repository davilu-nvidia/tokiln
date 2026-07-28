"""render 契约测试: 所有 profile × overlay 组合渲染成功且产物结构正确。
今天 (2026-07-28) h20-09 M0 实测抓到的问题在此固化为回归项。"""
import pathlib
import subprocess

import pytest
import yaml

from tokiln.config.merge import load_resolved
from tokiln.render import compose as compose_render

COMBOS = [
    ("m0-sglang-only", []),
    ("m1-dynamo-agg-2xtp8", []),
    ("m1-dynamo-agg-2xtp8", ["hicache-l2"]),
    ("m1-dynamo-agg-2xtp8", ["hicache-l2", "l3-mooncake"]),
]


@pytest.mark.parametrize("profile,overlays", COMBOS)
def test_render_all_profiles(tmp_path, profile, overlays):
    resolved = load_resolved(profile, overlays)
    files = compose_render.render(resolved, tmp_path)
    assert files, "渲染无产物"
    for f in files:
        assert f.exists() and f.stat().st_size > 0
        yaml.safe_load(f.read_text())          # 至少是合法 YAML


def test_l3_overlays_mutually_exclusive():
    with pytest.raises(ValueError):
        load_resolved("m1-dynamo-agg-2xtp8", ["hicache-l2", "l3-mooncake", "l3-flexkv"])


def test_model_path_uses_local_dir(tmp_path):
    """回归: /raid/model_hub 实际目录名 (GLM-5.2-FP8) 与 model.name (glm-5.2) 不同。"""
    resolved = load_resolved("m0-sglang-only")
    assert resolved["model"]["local_dir"], "glm-5.2.yaml 应声明 local_dir"
    files = compose_render.render(resolved, tmp_path)
    text = files[0].read_text()
    assert f"--model-path {resolved['model']['weights_cache']}/{resolved['model']['local_dir']}" in text


def test_tool_call_parser_not_deprecated(tmp_path):
    """回归: glm45 已被 sglang 废弃且解析不了 GLM-5.2 的 <arg_key>/<arg_value> 格式。"""
    resolved = load_resolved("m0-sglang-only")
    assert resolved["model"]["tool_call_parser"] == "glm47"


def test_gpu_ids_expansion():
    assert compose_render._gpu_ids("0-7") == [str(i) for i in range(8)]
    assert compose_render._gpu_ids("0,2,4") == ["0", "2", "4"]
    assert compose_render._gpu_ids("3") == ["3"]


def test_compose_config_valid(tmp_path):
    """渲染产物能过 docker compose config (CI runner 有 docker 时)。"""
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode:
        pytest.skip("docker compose 不可用")
    resolved = load_resolved("m0-sglang-only")
    files = compose_render.render(resolved, tmp_path)
    r = subprocess.run(["docker", "compose", "-f", str(files[0]), "config", "-q"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
