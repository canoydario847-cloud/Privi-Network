"""Regression: the quantum service must boot even when x402 CDP secrets are absent.
Paid operations must stay disabled rather than fall back to unpaid execution.
"""
import asyncio
from privi_quantum.payments import PaySettings
from privi_quantum.x402 import Paywall

def test_cdp_missing_starts_fail_closed(monkeypatch):
    monkeypatch.setenv("QUANTUM_PAY_TO", "0x" + "1" * 40)
    monkeypatch.setenv("QUANTUM_PAYMENTS_ENABLED", "true")
    monkeypatch.delenv("CDP_API_KEY_ID", raising=False)
    monkeypatch.delenv("CDP_API_KEY_SECRET", raising=False)
    pay = PaySettings.from_env("/tmp/privi-pay-tests.sqlite")
    assert pay.payments_enabled is True
    assert pay.facilitator_ready is False

    ran = False
    async def work():
        nonlocal ran
        ran = True
        return {"leak": "should never run"}
    response = asyncio.run(Paywall(pay).run("quantum_optimize", "Paid operation", None, work))
    assert response.is_error
    assert response.structured_content["error"] == "payment_facilitator_unavailable"
    assert ran is False

def test_valid_cdp_allows_normal_paid_gate(monkeypatch):
    monkeypatch.setenv("QUANTUM_PAY_TO", "0x" + "1" * 40)
    monkeypatch.setenv("QUANTUM_PAYMENTS_ENABLED", "true")
    monkeypatch.setenv("CDP_API_KEY_ID", "fake-id-test-only")
    monkeypatch.setenv("CDP_API_KEY_SECRET", "fake-secret-test-only")
    pay = PaySettings.from_env("/tmp/privi-pay-tests.sqlite")
    assert pay.payments_enabled is True
    assert pay.facilitator_ready is True
