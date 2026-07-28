"""resolved config → 每节点 docker compose 文件 (M0–M2 运行时后端)。
M3 的 render/dgd.py 与本模块同接口: render(resolved, out_dir) -> list[Path]。"""
import pathlib
import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = pathlib.Path(__file__).resolve().parents[2]
TPL = ROOT / "deploy" / "compose" / "templates"


def _gpu_ids(spec: str) -> list[str]:
    """'0-7' / '0,2,4' / '3' → 显式 ID 列表。docker compose 的 device_ids 不支持范围语法。"""
    ids: list[str] = []
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            ids += [str(i) for i in range(int(lo), int(hi) + 1)]
        elif part:
            ids.append(part)
    return ids


def _sglang_args(model: dict, worker: dict, kv: dict, extra: dict) -> list[str]:
    """由 resolved config 生成 sglang 启动参数。UNPINNED 项在此集中, 便于 ta-repro 考古后统一替换。"""
    a = [
        f"--model-path {model['weights_cache']}/{model['name']}",
        f"--served-model-name {model['served_model_name']}",
        f"--tp-size {worker['parallel'].get('tp', 8)}",
        f"--mem-fraction-static {worker['mem_fraction']}",
        f"--context-length {model['context_len']}",
        "--enable-metrics",
    ]
    if model.get("reasoning_parser"):
        a.append(f"--reasoning-parser {model['reasoning_parser']}")
    if model.get("tool_call_parser"):
        a.append(f"--tool-call-parser {model['tool_call_parser']}")
    l2 = kv.get("l2") or {}
    if l2.get("enabled"):
        a += ["--enable-hierarchical-cache",
              f"--hicache-ratio {round(l2['host_mem_gb'] / 100, 2)}",  # TODO(spike 03): 换实测换算
              f"--hicache-write-policy {l2.get('write_policy', 'write_through')}"]
    l3 = kv.get("l3") or {}
    if l3:
        a.append(f"--hicache-storage-backend {l3['backend']}")  # TODO(spike 04): backend 具体 flag
    return a


def render(resolved: dict, out_dir: pathlib.Path) -> list[pathlib.Path]:
    env = Environment(loader=FileSystemLoader(str(TPL)), keep_trailing_newline=True)
    prof, model, kv = resolved["profile"], resolved["model"], resolved["profile"]["kv"]
    versions = yaml.safe_load(open(ROOT / "VERSIONS.lock"))
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    if prof["runtime"] == "sglang-direct":
        tpl = env.get_template("m0.compose.yaml.j2")
        w = prof["workers"][0]
        p = out_dir / f"{w['node']}.compose.yaml"
        p.write_text(tpl.render(worker=w, model=model, versions=versions,
                                frontend=prof["frontend"], gpu_ids=_gpu_ids(w["gpus"]),
                                sglang_args=" ".join(_sglang_args(model, w, kv, prof))))
        written.append(p)
    else:  # dynamo
        infra = env.get_template("infra.compose.yaml.j2")
        p = out_dir / "infra.compose.yaml"
        p.write_text(infra.render(versions=versions, profile=prof))
        written.append(p)
        tpl = env.get_template("m1.node.compose.yaml.j2")
        for w in prof["workers"]:
            p = out_dir / f"{w['node']}.compose.yaml"
            p.write_text(tpl.render(worker=w, model=model, versions=versions, profile=prof,
                                    gpu_ids=_gpu_ids(w["gpus"]),
                                    sglang_args=" ".join(_sglang_args(model, w, kv, prof))))
            written.append(p)

    (out_dir / "resolved-config.yaml").write_text(yaml.safe_dump(resolved, allow_unicode=True, sort_keys=False))
    return written
