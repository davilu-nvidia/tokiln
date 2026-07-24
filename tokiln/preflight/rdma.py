"""RDMA 连通性/带宽 preflight (l3-mooncake / 跨节点 TP 的前置门槛)。
在 node1 起 ib_write_bw server, node2 打流, 比对 host-contract 的 bw_min_gbps。
只在 overlay 含 l3-mooncake 或 parallel 跨节点时强制。"""


def run(inventory: dict) -> dict:
    return {"todo": "M1 前实现: ib_write_bw 双向打流 + 带宽阈值断言",
            "required_by": ["l3-mooncake", "cross-node parallel"]}
