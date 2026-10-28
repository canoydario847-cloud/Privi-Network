"""Offline unit tests: no GPU, QPU, model API or external services required."""
import unittest
from dataclasses import replace
from runtime import Node, Workload, NoEligibleNode, place


NOW = 1800000000


def node(name="cpu-a", **overrides):
    defaults = dict(
        node_id=name, device="cpu", supported_models=frozenset({"llama3"}),
        available_ram_gb=16, available_vram_gb=0,
        max_context_tokens=8192, region="us-east",
        trust="verified", load=0.1, cost_per_1000_tokens_usd=0.002,
        p95_latency_ms=500, heartbeat_unix=NOW,
    )
    defaults.update(overrides)
    return Node(**defaults)


def job(**overrides):
    defaults = dict(
        workload_id="job-1", kind="llm_inference", model="llama3",
        context_tokens=1024, min_ram_gb=4, privacy="internal",
    )
    defaults.update(overrides)
    return Workload(**defaults)


class PlacementTests(unittest.TestCase):
    def test_basic_cpu_routing(self):
        result = place([node()], job(), now_unix=NOW)
        self.assertEqual(result.node_id, "cpu-a")
        self.assertFalse(result.executed)
        self.assertEqual(len(result.receipt_digest), 64)

    def test_cost_and_speed_choose_gpu(self):
        gpu = node("gpu-fast", device="gpu", available_vram_gb=24,
                   p95_latency_ms=90, load=0.02)
        result = place([node(), gpu], job(), now_unix=NOW)
        self.assertEqual(result.node_id, "gpu-fast")

    def test_stale_untrusted_and_explicit_opt_in_fail_closed(self):
        for bad in (
            node(heartbeat_unix=NOW - 50),
            node(trust="community"),
            node(enabled=False),
            node(load=1.0),
            node(heartbeat_unix=NOW + 30),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(NoEligibleNode):
                    place([bad], job(), now_unix=NOW)

    def test_restricted_never_routes_to_community(self):
        with self.assertRaises(NoEligibleNode):
            place([node()], job(privacy="restricted"), now_unix=NOW)
        self.assertEqual(place(
            [node(trust="private")], job(privacy="restricted"),
            now_unix=NOW,
        ).node_id, "cpu-a")

    def test_region_memory_and_context_constraints(self):
        for workload in (
            job(required_region="eu-west"),
            job(min_ram_gb=32),
            job(min_vram_gb=8),
            job(context_tokens=20000),
            job(model="unknown-model"),
        ):
            with self.subTest(workload=workload):
                with self.assertRaises(NoEligibleNode):
                    place([node()], workload, now_unix=NOW)

    def test_max_cost_blocks_expensive_route(self):
        with self.assertRaises(NoEligibleNode):
            place([node()], job(max_estimated_cost_usd=0.000001), now_unix=NOW)

    def test_quantum_work_requires_quantum_backend_and_opt_in_simulator(self):
        quantum = job(kind="quantum_optimization", model="qaoa",
                      context_tokens=0)
        sim = node("sim", device="qpu_simulator",
                   supported_models=frozenset({"qaoa"}))
        with self.assertRaises(NoEligibleNode):
            place([sim], quantum, now_unix=NOW)
        selected = place(
            [sim], replace(quantum, allow_quantum_simulator=True),
            now_unix=NOW,
        )
        self.assertEqual(selected.device, "qpu_simulator")
        self.assertFalse(selected.executed)
        with self.assertRaises(NoEligibleNode):
            place([sim], job(), now_unix=NOW)

    def test_invalid_input_fails_closed(self):
        for bad in (job(context_tokens=0), job(min_ram_gb=-1),
                    job(max_estimated_cost_usd=float("nan"))):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    place([node()], bad, now_unix=NOW)

    def test_deterministic_receipt(self):
        first = place([node()], job(), now_unix=NOW)
        second = place([node()], job(), now_unix=NOW)
        self.assertEqual(first.receipt_digest, second.receipt_digest)


if __name__ == "__main__":
    unittest.main()
