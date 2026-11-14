"""Regression: missing Coinbase credentials cannot crash the service or allow unpaid work."""
import asyncio
from privi_ledger.config import Settings
from privi_ledger.x402 import Paywall

def test_missing_facilitator_fails_closed(monkeypatch):
    monkeypatch.setenv("LEDGER_NETWORK", "base")
    monkeypatch.setenv("LEDGER_FACILITATOR_URL", "https://api.cdp.coinbase.com/platform/v2/x402")
    monkeypatch.setenv("LEDGER_PAY_TO", "0x" + "1" * 40)
    monkeypatch.setenv("LEDGER_PAYMENTS_ENABLED", "true")
    monkeypatch.delenv("CDP_API_KEY_ID", raising=False)
    monkeypatch.delenv("CDP_API_KEY_SECRET", raising=False)
    setting=Settings.from_env()
    assert setting.payments_enabled and not setting.facilitator_ready
    called=[]
    async def work():
        called.append(True)
        return {"unexpected":"work executed"}
    async def invoke():
        return await Paywall(setting).run("ledger_audit_stream", "Protected tool", None, work)
    result=asyncio.run(invoke())
    assert result.is_error
    assert result.structured_content["error"]=="payment_facilitator_unavailable"
    assert not called

def test_configured_facilitator_remains_paid(monkeypatch):
    monkeypatch.setenv("LEDGER_NETWORK", "base")
    monkeypatch.setenv("LEDGER_FACILITATOR_URL", "https://api.cdp.coinbase.com/platform/v2/x402")
    monkeypatch.setenv("LEDGER_PAY_TO", "0x" + "1" * 40)
    monkeypatch.setenv("LEDGER_PAYMENTS_ENABLED", "true")
    monkeypatch.setenv("CDP_API_KEY_ID", "test-placeholder-id")
    monkeypatch.setenv("CDP_API_KEY_SECRET", "test-placeholder-secret")
    setting=Settings.from_env()
    assert setting.payments_enabled and setting.facilitator_ready
