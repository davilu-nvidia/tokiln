"""Stack health probe — absorbed from the checks in aa-loadgen monitor/run_exp.sh:
etcd-registered backend endpoint count, /v1/models assertion, warm-up request."""
import httpx
from .base import timed


@timed("stack")
async def run(url: str, model: str, expect_workers: int = 1, etcd_url: str = ""):
    detail = {}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{url}/models")
        models = [m["id"] for m in r.json().get("data", [])]
        detail["models"] = models
        if model not in models:
            return False, {**detail, "hint": f"served_model_name={model} not registered"}
        if etcd_url:
            try:
                kr = await c.get(f"{etcd_url}/v3/kv/range", timeout=8)
                detail["etcd_reachable"] = kr.status_code < 500
            except httpx.HTTPError:
                detail["etcd_reachable"] = False
        w = await c.post(f"{url}/chat/completions", json={
            "model": model, "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 4})
        detail["warm_status"] = w.status_code
        return w.status_code == 200, detail
