"""GLM-5.2 reasoning / tool-call parser 探针: 断言结构化字段而非裸文本。"""
import httpx
from .base import timed

TOOLS = [{"type": "function", "function": {
    "name": "get_weather",
    "description": "查询城市天气",
    "parameters": {"type": "object",
                   "properties": {"city": {"type": "string"}},
                   "required": ["city"]}}}]


@timed("parser")
async def run(url: str, model: str):
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{url}/chat/completions", json={
            "model": model, "stream": False, "tools": TOOLS,
            "messages": [{"role": "user", "content": "北京今天天气怎么样? 请调用工具。"}],
            "max_tokens": 512})
        if r.status_code != 200:
            return False, {"status": r.status_code, "body": r.text[:300]}
        msg = r.json()["choices"][0]["message"]
        tc = msg.get("tool_calls") or []
        ok = bool(tc) and tc[0]["function"]["name"] == "get_weather"
        return ok, {"tool_calls": len(tc),
                    "reasoning_present": bool(msg.get("reasoning_content")),
                    "hint": "" if ok else "检查 --tool-call-parser 与 chat template 是否匹配 GLM-5.2"}
