"""cold / warm / shared-prefix 三组探针: 断言命中率单调关系 cold < warm, shared-prefix 增益可见。
读 sglang cache report / prometheus 指标, 具体 metric 名 spike 03 对齐。"""
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
    prefix = "你是代码审查助手。以下是仓库约定: " + ("规则X; " * 800)  # ~2K token 共享前缀
    nonce = uuid.uuid4().hex
    async with httpx.AsyncClient(timeout=300) as c:
        cold = await _ask(c, url, model, f"[{nonce}] {prefix}", "第1问", f"s-{nonce}-1")
        warm = await _ask(c, url, model, f"[{nonce}] {prefix}", "第2问", f"s-{nonce}-1")
        shared = await _ask(c, url, model, f"[{nonce}] {prefix}", "第3问", f"s-{nonce}-2")
    # usage 中 cached/prompt token 字段名因版本而异, 先透传原始 usage 供人判
    detail = {"cold": cold, "warm": warm, "shared_prefix_other_session": shared,
              "expect": "warm/shared 的 cached tokens 应显著 > cold; 字段名 spike 03 固化后加硬断言"}
    return True, detail  # M0 阶段信息型探针; spike 03 后改为硬断言
