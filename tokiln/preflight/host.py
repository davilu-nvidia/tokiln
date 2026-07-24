"""SSH 只读 preflight: GPU/驱动/CUDA/磁盘/端口。绝不修改目标机。
实现方式: ssh <host> <cmd> 采集 → 与 host-contract.yaml 比对。"""
import json, pathlib, shlex, subprocess
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]

CHECKS = {
    "gpu": "nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader",
    "cuda": "nvcc --version 2>/dev/null | tail -1 || cat /usr/local/cuda/version.json 2>/dev/null",
    "docker": "docker version --format '{{.Server.APIVersion}}' 2>/dev/null",
    "disk": "df -BG --output=avail {nvme} | tail -1",
    "rdma": "ibv_devinfo 2>/dev/null | grep -E 'hca_id|state' || echo NO_RDMA",
    "os": "grep -E '^(ID|VERSION_ID)=' /etc/os-release; uname -mr",
}


def _ssh(node: dict, cmd: str, timeout: int = 30) -> tuple[int, str]:
    target = f"{node['ssh']['user']}@{node['host']}"
    full = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-p", str(node["ssh"]["port"]), target, cmd]
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def run(inventory: dict, contract_path: pathlib.Path | None = None) -> dict:
    contract = yaml.safe_load(open(contract_path or ROOT / "configs/cluster/host-contract.yaml"))
    report = {"contract": contract, "nodes": {}}
    for node in inventory["nodes"]:
        res = {}
        for name, cmd in CHECKS.items():
            cmd = cmd.format(nvme=shlex.quote(node.get("nvme", {}).get("path", "/")))
            rc, out = _ssh(node, cmd)
            res[name] = {"rc": rc, "out": out}
        res["verdict"] = {
            "gpu_count_ok": res["gpu"]["out"].count("H20") >= node["gpus"]["count"]
                            if res["gpu"]["rc"] == 0 else False,
            "docker_ok": res["docker"]["rc"] == 0,
            "rdma_present": "NO_RDMA" not in res["rdma"]["out"],
        }
        report["nodes"][node["name"]] = res
    report["go"] = all(n["verdict"]["gpu_count_ok"] and n["verdict"]["docker_ok"]
                       for n in report["nodes"].values())
    return report


def write_report(report: dict, out: pathlib.Path) -> None:
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
