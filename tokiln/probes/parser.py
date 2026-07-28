"""GLM-5.2 reasoning / tool-call parser probe: assert structured fields, not raw text."""
import httpx
from .base import timed

TOOLS = [{"type": "function", "function": {
    "name": "get_weather",
    "description": "Query the weather for a city",
    "parameters": {"type": "object",
                   "properties": {"city": {"type": "string"}},
                   "required": ["city"]}}}]


@timed("parser")
async def run(url: str, model: str):
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{url}/chat/completions", json={
            "model": model, "stream": False, "tools": TOOLS,
            "messages": [{"role": "user", "content": "What's the weather in Beijing today? Please call the tool."}],
            "max_tokens": 512})
        if r.status_code != 200:
            return False, {"status": r.status_code, "body": r.text[:300]}
        msg = r.json()["choices"][0]["message"]
        tc = msg.get("tool_calls") or []
        ok = bool(tc) and tc[0]["function"]["name"] == "get_weather"
        return ok, {"tool_calls": len(tc),
                    "reasoning_present": bool(msg.get("reasoning_content")),
                    "hint": "" if ok else "check that --tool-call-parser matches the GLM-5.2 chat template"}
