"""Dynamo KV event vs SGLang cache report consistency probe (enabled from M1).
TODO(spike 02): subscribe to the kv-event subject on NATS and cross-check block counts against worker /metrics."""
from .base import timed


@timed("kv_events")
async def run(nats_url: str):
    return False, {"todo": "implement after spike 02: nats sub kv-events + /metrics reconciliation",
                   "nats": nats_url}
