"""Render contract tests: every profile × overlay combo renders and the artifacts are well-formed.
Issues caught during the 2026-07-28 h20-09 M0 run are pinned here as regressions."""
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
    assert files, "render produced no artifacts"
    for f in files:
        assert f.exists() and f.stat().st_size > 0
        yaml.safe_load(f.read_text())          # at minimum, valid YAML


def test_l3_overlays_mutually_exclusive():
    with pytest.raises(ValueError):
        load_resolved("m1-dynamo-agg-2xtp8", ["hicache-l2", "l3-mooncake", "l3-flexkv"])


def test_model_path_uses_local_dir(tmp_path):
    """Regression: the actual dir name under /raid/model_hub (GLM-5.2-FP8) differs from model.name (glm-5.2)."""
    resolved = load_resolved("m0-sglang-only")
    assert resolved["model"]["local_dir"], "glm-5.2.yaml must declare local_dir"
    files = compose_render.render(resolved, tmp_path)
    text = files[0].read_text()
    assert f"--model-path {resolved['model']['weights_cache']}/{resolved['model']['local_dir']}" in text


def test_tool_call_parser_not_deprecated(tmp_path):
    """Regression: glm45 is deprecated in sglang and cannot parse GLM-5.2's <arg_key>/<arg_value> format."""
    resolved = load_resolved("m0-sglang-only")
    assert resolved["model"]["tool_call_parser"] == "glm47"


def test_gpu_ids_expansion():
    assert compose_render._gpu_ids("0-7") == [str(i) for i in range(8)]
    assert compose_render._gpu_ids("0,2,4") == ["0", "2", "4"]
    assert compose_render._gpu_ids("3") == ["3"]


def test_compose_config_valid(tmp_path):
    """Rendered artifacts must pass docker compose config (when the CI runner has docker)."""
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode:
        pytest.skip("docker compose unavailable")
    resolved = load_resolved("m0-sglang-only")
    files = compose_render.render(resolved, tmp_path)
    r = subprocess.run(["docker", "compose", "-f", str(files[0]), "config", "-q"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
