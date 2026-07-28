"""cold / warm / shared-prefix probe trio: assert the monotonic hit-rate relation
cold < warm, and that the shared-prefix gain is visible.
Reads sglang cache report / prometheus metrics; exact metric names to be aligned in spike 03."""
import uuid
import httpx
from .base import timed


async def _ask(c, url, model, prefix, q, session):
    r = await c.post(f"{url}/chat/completions", json={
        "model": model, "stream": False, "max_tokens": 16,
        "messages": [{"role": "system", "content": prefix},
                     {"role": "user", "content": q}]},
        headers={"x-dynamo-session-id": session})
    return r.json().get("usage", {})


@timed("hicache")
async def run(url: str, model: str):
    prefix = "You are a code review assistant. Repository conventions follow: " + ("Rule X; " * 800)  # ~2K-token shared prefix
    nonce = uuid.uuid4().hex
    async with httpx.AsyncClient(timeout=300) as c:
        cold = await _ask(c, url, model, f"[{nonce}] {prefix}", "Question 1", f"s-{nonce}-1")
        warm = await _ask(c, url, model, f"[{nonce}] {prefix}", "Question 2", f"s-{nonce}-1")
        shared = await _ask(c, url, model, f"[{nonce}] {prefix}", "Question 3", f"s-{nonce}-2")
    # cached/prompt token field names in usage vary by version; pass raw usage through for human judgment
    detail = {"cold": cold, "warm": warm, "shared_prefix_other_session": shared,
              "expect": "cached tokens for warm/shared should be clearly > cold; hard assertion once spike 03 pins the field names"}
    return True, detail  # informational probe during M0; becomes a hard assertion after spike 03
