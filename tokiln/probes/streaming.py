"""SSE streaming 探针: chat completion 流式返回、token 时间戳单调、usage 字段存在。"""
import json, time
import httpx
from .base import timed


@timed("streaming")
async def run(url: str, model: str):
    body = {"model": model, "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": "用一句话解释 KV cache。"}],
            "max_tokens": 64}
    ts, usage = [], None
    async with httpx.AsyncClient(timeout=120) as c:
        async with c.stream("POST", f"{url}/chat/completions", json=body) as r:
            if r.status_code != 200:
                return False, {"status": r.status_code}
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                chunk = json.loads(payload)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                if chunk.get("choices") and chunk["choices"][0].get("delta", {}).get("content"):
                    ts.append(time.time())
    ok = len(ts) >= 2 and ts == sorted(ts) and usage is not None
    return ok, {"chunks": len(ts), "usage": usage,
                "ttft_note": "首 chunk 时间由 bench 层测, 本探针只验语义"}
