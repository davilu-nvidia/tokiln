"""RunManifest: 一次运行的完整可复现坐标。"""
import json, pathlib, subprocess, time

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def write(run_dir: pathlib.Path, resolved: dict, extra: dict | None = None) -> pathlib.Path:
    m = {
        "run_id": run_dir.name,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "config_digest": resolved.get("digest"),
        "overlays": resolved.get("overlays"),
        "profile": resolved["profile"]["name"],
        "model": {k: resolved["model"][k] for k in ("name", "revision", "quant")},
        "git": {"sha": _git("rev-parse", "HEAD"),
                "dirty": bool(_git("status", "--porcelain")),
                "submodules": _git("submodule", "status")},
        **(extra or {}),
    }
    p = run_dir / "manifest.json"
    p.write_text(json.dumps(m, indent=2, ensure_ascii=False))
    return p
