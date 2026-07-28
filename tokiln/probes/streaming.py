"""SSE streaming probe: chat completion streams, token timestamps are monotonic, usage field present."""
import json, time
import httpx
from .base import timed


@timed("streaming")
async def run(url: str, model: str):
    body = {"model": model, "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": "Explain KV cache in one sentence."}],
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
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                if delta.get("content") or delta.get("reasoning_content"):
                    ts.append(time.time())
    ok = len(ts) >= 2 and ts == sorted(ts) and usage is not None
    return ok, {"chunks": len(ts), "usage": usage,
                "ttft_note": "first-chunk latency is measured by the bench layer; this probe only checks semantics"}
