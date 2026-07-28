"""取消探针 (验收门槛): 断开 SSE 后, 服务端不得继续无界消耗 GPU。
判据: 断开后轮询 /metrics, running/queue 请求数在 grace 期内回落。"""
import asyncio, re
import httpx
from .base import timed

RUNNING_PAT = re.compile(r"num_running_reqs[^ ]* (\d+(?:\.\d+)?)")  # TODO(spike 01): 对齐实际 metric 名


async def _running(c: httpx.AsyncClient, metrics_url: str) -> float:
    r = await c.get(metrics_url)
    m = RUNNING_PAT.search(r.text)
    return float(m.group(1)) if m else -1


@timed("cancel")
async def run(url: str, model: str, metrics_url: str, grace_s: float = 60.0):
    body = {"model": model, "stream": True,
            "messages": [{"role": "user", "content": "写一篇一万字的技术长文, 不要停。"}],
            "max_tokens": 8192}
    async with httpx.AsyncClient(timeout=60) as c:
        task = None
        async def fire():
            async with c.stream("POST", f"{url}/chat/completions", json=body) as r:
                async for _ in r.aiter_lines():
                    pass
        task = asyncio.create_task(fire())
        await asyncio.sleep(3)          # 让请求进入 decode
        task.cancel()                    # 客户端断开
        try:
            await task
        except (asyncio.CancelledError, httpx.HTTPError):
            pass
        t_disc = asyncio.get_event_loop().time()
        deadline = t_disc + grace_s
        last = -1
        while asyncio.get_event_loop().time() < deadline:
            last = await _running(c, metrics_url)
            if last == 0:
                drain = round(asyncio.get_event_loop().time() - t_disc, 1)
                return True, {"drain_s": drain,
                              "note": "断开后请求有界回落; h20-09 实测 sglang 约 35-40s 才 abort"}
            await asyncio.sleep(1)
    return False, {"running_after_grace": last,
                   "hint": "请求泄漏: 检查 frontend abort 传播与 sglang abort_request"}
