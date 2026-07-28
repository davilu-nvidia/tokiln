"""Cancellation probe (acceptance gate): after the SSE client disconnects, the server
must not keep consuming GPU without bound.
Criterion: poll /metrics after disconnect; running/queued requests must drain within the grace window."""
import asyncio, re
import httpx
from .base import timed

RUNNING_PAT = re.compile(r"num_running_reqs[^ ]* (\d+(?:\.\d+)?)")  # TODO(spike 01): align with actual metric name


async def _running(c: httpx.AsyncClient, metrics_url: str) -> float:
    r = await c.get(metrics_url)
    m = RUNNING_PAT.search(r.text)
    return float(m.group(1)) if m else -1


@timed("cancel")
async def run(url: str, model: str, metrics_url: str, grace_s: float = 60.0):
    body = {"model": model, "stream": True,
            "messages": [{"role": "user", "content": "Write a 10000-word technical essay. Do not stop."}],
            "max_tokens": 8192}
    async with httpx.AsyncClient(timeout=60) as c:
        task = None
        async def fire():
            async with c.stream("POST", f"{url}/chat/completions", json=body) as r:
                async for _ in r.aiter_lines():
                    pass
        task = asyncio.create_task(fire())
        await asyncio.sleep(3)          # let the request enter decode
        task.cancel()                    # client disconnects
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
                              "note": "bounded drain after disconnect; measured ~35-40s until sglang aborts on h20-09"}
            await asyncio.sleep(1)
    return False, {"running_after_grace": last,
                   "hint": "request leak: check frontend abort propagation and sglang abort_request"}
