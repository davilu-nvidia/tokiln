"""RDMA connectivity / bandwidth preflight (prerequisite gate for l3-mooncake / cross-node TP).
Start an ib_write_bw server on node1, drive traffic from node2, compare against bw_min_gbps
from the host contract. Only enforced when overlays include l3-mooncake or parallelism spans nodes."""


def run(inventory: dict) -> dict:
    return {"todo": "implement before M1: bidirectional ib_write_bw + bandwidth threshold assertion",
            "required_by": ["l3-mooncake", "cross-node parallel"]}
