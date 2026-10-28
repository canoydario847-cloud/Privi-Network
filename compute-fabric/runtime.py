"""Privi Compute Fabric: deterministic, fail-closed workload placement.

This module NEVER executes jobs, probes endpoints, signs receipts, or accesses
a quantum device. Nodes must be explicitly registered by an operator. Only
an inference or optimization adapter may execute a placed job after auth.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Literal

Device = Literal["cpu", "gpu", "npu", "qpu", "qpu_simulator"]
Privacy = Literal["public", "internal", "restricted"]
Kind = Literal["llm_inference", "quantum_optimization"]
Trust = Literal["community", "verified", "private"]

MAX_HEARTBEAT_AGE_S = 45
MAX_FUTURE_SKEW_S = 5
TRUST_RANK = {"community": 0, "verified": 1, "private": 2}
REQUIRED_TRUST = {"public": 0, "internal": 1, "restricted": 2}


class NoEligibleNode(RuntimeError):
    """No opt-in node meets the workload's hard requirements."""


@dataclass(frozen=True)
class Node:
    node_id: str
    device: Device
    supported_models: frozenset[str]
    available_ram_gb: float
    available_vram_gb: float
    max_context_tokens: int
    region: str
    trust: Trust
    load: float
    cost_per_1000_tokens_usd: float
    p95_latency_ms: int
    heartbeat_unix: int
    enabled: bool = True


@dataclass(frozen=True)
class Workload:
    workload_id: str
    kind: Kind
    model: str
    context_tokens: int
    min_ram_gb: float = 0
    min_vram_gb: float = 0
    privacy: Privacy = "internal"
    required_region: str | None = None
    max_estimated_cost_usd: float | None = None
    allow_quantum_simulator: bool = False


@dataclass(frozen=True)
class Placement:
    workload_id: str
    node_id: str
    device: Device
    estimated_cost_usd: float
    estimate_is_guaranteed: bool
    receipt_digest: str
    executed: bool = False


def _valid_node(node: Node, now_unix: int) -> bool:
    if not node.enabled or not node.node_id or not node.region:
        return False
    if node.device not in {"cpu", "gpu", "npu", "qpu", "qpu_simulator"}:
        return False
    if node.trust not in TRUST_RANK:
        return False
    if any(not math.isfinite(v) or v < 0 for v in (
        node.available_ram_gb, node.available_vram_gb,
        node.cost_per_1000_tokens_usd,
    )):
        return False
    if not math.isfinite(node.load) or not 0 <= node.load < 1:
        return False
    if node.max_context_tokens < 0 or node.p95_latency_ms < 0:
        return False
    age = now_unix - node.heartbeat_unix
    return -MAX_FUTURE_SKEW_S <= age <= MAX_HEARTBEAT_AGE_S


def _validate_workload(job: Workload) -> None:
    if not job.workload_id or not job.model:
        raise ValueError("workload ID and model/algorithm ID are required")
    if job.kind not in {"llm_inference", "quantum_optimization"}:
        raise ValueError("unsupported workload kind")
    if job.privacy not in REQUIRED_TRUST:
        raise ValueError("unsupported privacy classification")
    if job.context_tokens < 0:
        raise ValueError("negative context tokens")
    for name in ("min_ram_gb", "min_vram_gb"):
        v = getattr(job, name)
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"invalid {name}")
    if job.max_estimated_cost_usd is not None and (
        not math.isfinite(job.max_estimated_cost_usd)
        or job.max_estimated_cost_usd < 0
    ):
        raise ValueError("invalid cost cap")
    if job.kind == "llm_inference" and job.context_tokens == 0:
        raise ValueError("LLM requests need a positive token estimate")
    if job.kind == "quantum_optimization" and job.context_tokens:
        raise ValueError("quantum work is not billed by estimated LLM tokens")


def _eligible(node: Node, job: Workload, now_unix: int) -> bool:
    if not _valid_node(node, now_unix):
        return False
    if TRUST_RANK[node.trust] < REQUIRED_TRUST[job.privacy]:
        return False
    if job.required_region is not None and node.region != job.required_region:
        return False
    if job.model not in node.supported_models:
        return False
    if job.kind == "llm_inference":
        if node.device not in {"cpu", "gpu", "npu"}:
            return False  # Never invent an LLM speed-up on QPUs.
        if job.context_tokens > node.max_context_tokens:
            return False
    else:
        if node.device != "qpu" and not (
            job.allow_quantum_simulator and node.device == "qpu_simulator"
        ):
            return False
    if (node.available_ram_gb < job.min_ram_gb
            or node.available_vram_gb < job.min_vram_gb):
        return False
    if job.max_estimated_cost_usd is not None and (
        node.cost_per_1000_tokens_usd * job.context_tokens / 1000
        > job.max_estimated_cost_usd
    ):
        return False
    return True


def place(nodes: list[Node], job: Workload, *, now_unix: int) -> Placement:
    """Choose only verified compatible nodes; never fallback across privacy boundaries.

    Cost is a *rough operator-advertised estimate*, not a payment quote.
    No quantum cost guarantee: QPU providers have their own shot/job pricing.
    """
    _validate_workload(job)
    eligible = [n for n in nodes if _eligible(n, job, now_unix)]
    if not eligible:
        raise NoEligibleNode("No healthy, compatible, trusted opt-in node")
    # Prefer lower latency, lower estimated price and lower utilization.
    selected = min(eligible, key=lambda n: (
        n.p95_latency_ms / 1000 + 2 * n.load
        + n.cost_per_1000_tokens_usd * job.context_tokens / 1000,
        n.node_id,
    ))
    cost = selected.cost_per_1000_tokens_usd * job.context_tokens / 1000
    public_receipt = {
        "workload_id": job.workload_id,
        "model": job.model,
        "kind": job.kind,
        "node_id": selected.node_id,
        "device": selected.device,
        "estimated_cost_usd": round(cost, 8),
    }
    digest = sha256(json.dumps(public_receipt, sort_keys=True,
                               separators=(",", ":")).encode()).hexdigest()
    return Placement(
        workload_id=job.workload_id, node_id=selected.node_id,
        device=selected.device, estimated_cost_usd=round(cost, 8),
        estimate_is_guaranteed=False, receipt_digest=digest,
    )
