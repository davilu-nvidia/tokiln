"""profile ⊕ overlays → resolved config (+ digest)。
digest 进 run manifest, 保证 "同一 digest = 同一部署形态"。"""
import copy, hashlib, json, pathlib
import yaml

from .schema import Inventory, ModelSpec, ServingProfile, Workload

ROOT = pathlib.Path(__file__).resolve().parents[2]
CFG = ROOT / "configs"


def _deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _load(p: pathlib.Path) -> dict:
    with open(p) as f:
        return yaml.safe_load(f) or {}


def config_digest(resolved: dict) -> str:
    blob = json.dumps(resolved, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def load_resolved(profile: str, overlays: list[str] | None = None,
                  model: str = "glm-5.2") -> dict:
    """返回 {'inventory','model','profile','digest'} 已通过 schema 校验的 resolved config。"""
    overlays = overlays or []
    inv = _load(CFG / "cluster" / "inventory.yaml")
    mdl = _load(CFG / "models" / f"{model}.yaml")["model"]
    prof = _load(CFG / "serving" / "profiles" / f"{profile}.yaml")["profile"]

    l3_seen = 0
    for ov in overlays:
        patch = _load(CFG / "serving" / "overlays" / f"{ov}.yaml")
        if ov.startswith("l3-"):
            l3_seen += 1
        wp = patch.pop("workers_patch", None)
        prof = _deep_merge(prof, patch)
        if wp:
            prof["workers"] = [{**w, **wp} for w in prof["workers"]]
    if l3_seen > 1:
        raise ValueError("l3-mooncake 与 l3-flexkv 互斥, 只能叠加一个")

    inventory = Inventory(**inv)
    model_spec = ModelSpec(**mdl)
    profile_spec = ServingProfile(**prof)

    # 交叉校验: L2 host_mem 不得超过节点 DRAM 的 70%
    if profile_spec.kv.l2 and profile_spec.kv.l2.get("enabled"):
        need = profile_spec.kv.l2.get("host_mem_gb", 0)
        for w in profile_spec.workers:
            dram = inventory.node(w.node).dram_gb
            if dram and need > dram * 0.7:
                raise ValueError(f"{w.node}: hicache host_mem_gb={need} 超过 DRAM({dram}GB) 的 70%")

    resolved = {
        "inventory": inventory.model_dump(),
        "model": model_spec.model_dump(),
        "profile": profile_spec.model_dump(),
        "overlays": overlays,
    }
    resolved["digest"] = config_digest(resolved)
    return resolved


def load_workload(name: str) -> Workload:
    raw = _load(CFG / "workloads" / f"{name}.yaml")
    return Workload(**{**raw["workload"], "params": raw.get("params", {}),
                       "ab": raw.get("ab"), "pass_criteria": raw.get("pass_criteria", {})})
