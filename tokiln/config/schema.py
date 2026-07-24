"""Pydantic schema: configs/ 下 YAML 的强类型定义。
校验失败即部署失败 —— 这是 "在部署前明确失败" 原则的第一道门。"""
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator


class SSH(BaseModel):
    user: str = "root"
    port: int = 22


class GPUSpec(BaseModel):
    sku: str
    count: int
    hbm_gb: int


class Node(BaseModel):
    name: str
    host: str
    ssh: SSH = SSH()
    roles: list[str] = ["worker"]
    gpus: GPUSpec
    dram_gb: int = 0
    nvme: dict = {}
    rdma: dict = {}


class Inventory(BaseModel):
    cluster: dict
    nodes: list[Node]

    def node(self, name: str) -> Node:
        for n in self.nodes:
            if n.name == name:
                return n
        raise KeyError(f"node {name} not in inventory")


class ModelSpec(BaseModel):
    name: str
    source: str = ""
    revision: str = ""
    quant: Literal["fp8", "bf16"] = "fp8"
    context_len: int = 131072
    served_model_name: str
    chat_template: str = ""
    reasoning_parser: str = ""
    tool_call_parser: str = ""
    weights_cache: str = "/raid/model_hub"


class WorkerSpec(BaseModel):
    node: str
    gpus: str = "0-7"
    parallel: dict = {"tp": 8}
    mem_fraction: float = 0.9


class RouterSpec(BaseModel):
    kind: Literal["thunderagent", "kv-aware", "round-robin"] = "kv-aware"
    session_header: str = "x-dynamo-session-id"


class KVSpec(BaseModel):
    l1: Literal["radix"] = "radix"
    l2: Optional[dict] = None
    l3: Optional[dict] = None

    @model_validator(mode="after")
    def _l3_requires_l2(self):
        if self.l3 and not (self.l2 and self.l2.get("enabled")):
            raise ValueError("L3 KV 需要先启用 L2 (hicache-l2 overlay); 分层不可跳级")
        return self


class ServingProfile(BaseModel):
    name: str
    runtime: Literal["sglang-direct", "dynamo"]
    frontend: dict
    router: Optional[RouterSpec] = None
    infra: dict = {}
    workers: list[WorkerSpec] = Field(min_length=1)
    kv: KVSpec = KVSpec()
    limits: dict = {}

    @model_validator(mode="after")
    def _dynamo_needs_router(self):
        if self.runtime == "dynamo" and self.router is None:
            raise ValueError("runtime=dynamo 必须声明 router")
        return self


class Workload(BaseModel):
    name: str
    tool: Literal["aa-loadgen", "bench_serving"] = "aa-loadgen"
    mode: Literal["synth", "replay"] = "synth"
    params: dict = {}
    ab: Optional[dict] = None
    pass_criteria: dict = {}
