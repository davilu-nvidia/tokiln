"""Dynamo KV event 与 SGLang cache report 一致性探针 (M1 起启用)。
TODO(spike 02): 订阅 NATS 上的 kv event 主题, 与 worker /metrics 的 block 计数交叉校验。"""
from .base import timed


@timed("kv_events")
async def run(nats_url: str):
    return False, {"todo": "spike 02 完成后实现: nats sub kv-events + /metrics 对账",
                   "nats": nats_url}
