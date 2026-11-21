"""Offline enterprise decision-gateway policy regressions, no provider credentials."""
import unittest

from privi_quantum.enterprise_gateway import triage_workload


class EnterpriseGatewayTests(unittest.TestCase):
    def test_small_optimization_chooses_classical_exact_and_stable_receipt(self):
        req = {"kind": "binary_optimization", "variables": 8}
        first = triage_workload(req)
        self.assertEqual(first, triage_workload(dict(reversed(list(req.items())))))
        self.assertEqual(first["recommended_path"], "classical_exact_baseline")
        self.assertEqual(first["complexity"]["search_space_size"], 256)
        self.assertFalse(first["execution_performed"])
        self.assertFalse(first["proven_quantum_advantage"])
        self.assertEqual(len(first["receipt_sha256"]), 64)

    def test_large_optimization_is_classical_first_not_hardware(self):
        plan = triage_workload({"kind": "binary_optimization", "variables": 16,
                               "hardware_requested": True,
                               "max_budget_usd": 100})
        self.assertEqual(plan["recommended_path"], "classical_first_research")
        self.assertTrue(plan["hardware_review_required"])
        self.assertFalse(plan["paid_hardware_authorized"])
        self.assertEqual(plan["financial_commitment_usd"], 0)
        self.assertIsNone(plan["estimated_cost_usd"])

    def test_simulation_route_matches_bounded_cloud(self):
        plan = triage_workload({"kind": "circuit_simulation",
                                "qubits": 12, "gates": 500, "shots": 4096})
        self.assertEqual(plan["recommended_path"], "local_statevector_simulator")
        self.assertEqual(plan["complexity"]["statevector_amplitudes"], 4096)
        self.assertFalse(plan["physical_qpu_used"])

    def test_different_request_has_different_digest(self):
        a = triage_workload({"kind": "binary_optimization", "variables": 7})
        b = triage_workload({"kind": "binary_optimization", "variables": 8})
        self.assertNotEqual(a["receipt_sha256"], b["receipt_sha256"])

    def test_unsafe_or_unbounded_requests_fail_closed(self):
        failures = [
            None, [], {},
            {"kind": "backend"},
            {"kind": "binary_optimization", "variables": True},
            {"kind": "binary_optimization", "variables": 0},
            {"kind": "binary_optimization", "variables": 17},
            {"kind": "binary_optimization", "variables": 5, "qubits": 3},
            {"kind": "binary_optimization", "variables": 5,
             "max_budget_usd": float("nan")},
            {"kind": "binary_optimization", "variables": 5,
             "max_budget_usd": -1},
            {"kind": "binary_optimization", "variables": 5,
             "hardware_requested": "yes"},
            {"kind": "binary_optimization", "variables": 5, "api_key": "secret"},
            {"kind": "circuit_simulation", "qubits": 13, "gates": 4},
            {"kind": "circuit_simulation", "qubits": 2, "gates": 501},
            {"kind": "circuit_simulation", "qubits": 2, "gates": 4, "shots": 4097},
            {"kind": "circuit_simulation", "qubits": 2, "gates": 2.5},
            {"kind": "circuit_simulation", "qubits": 2, "gates": 1,
             "variables": 2},
        ]
        for request in failures:
            with self.subTest(request=str(request)):
                with self.assertRaises(ValueError):
                    triage_workload(request)


if __name__ == "__main__":
    unittest.main()
