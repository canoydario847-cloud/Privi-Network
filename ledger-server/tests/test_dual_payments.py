"""Safety boundaries for PRVI_TEST simulation; no blockchain or network dependency."""
import pytest

from privi_ledger.dual_payments import ACKNOWLEDGEMENT, DualPayments, PaymentSimulationError


PRICES = {"ledger_upgrade_pro": "29", "ledger_audit_stream": "0.02", "guard_check": "0.01"}


def router(*, network="base-sepolia", enabled=True, clock=None):
    return DualPayments(network_key=network, payments_enabled=True,
                        prices_usd=PRICES, enable_test=enabled, clock=clock)


def test_usdc_path_is_advertised_and_untouched():
    opts = router(enabled=False).options()
    assert opts["payments"][0]["method"] == "USDC_X402"
    assert opts["payments"][0]["enabled"] is True
    assert opts["payments"][1]["enabled"] is False
    assert opts["native_prvi_mainnet_payments_enabled"] is False


def test_testing_disabled_by_default():
    with pytest.raises(PaymentSimulationError, match="disabled"):
        router(enabled=False).quote("org_valid", "ledger_upgrade_pro")


def test_test_payment_never_enabled_on_base_mainnet():
    r = router(network="base", enabled=True)
    assert not r.options()["payments"][1]["enabled"]
    with pytest.raises(PaymentSimulationError, match="disabled"):
        r.quote("org_valid", "ledger_upgrade_pro")


def test_any_other_network_disables_simulation():
    with pytest.raises(PaymentSimulationError):
        router(network="local-4221", enabled=True).quote("org_valid", "ledger_upgrade_pro")


def test_quote_requires_org_and_whitelisted_sku():
    r = router()
    for org, sku in [("", "guard_check"), ("org_valid", "unpriced"),
                     ("org_valid", "__dict__"), ("x", "ledger_upgrade_pro")]:
        with pytest.raises(PaymentSimulationError):
            r.quote(org, sku)


def test_simulated_receipt_no_entitlement_no_settlement():
    r = router()
    quote = r.quote("org_valid", "ledger_upgrade_pro")
    assert quote["economic_value"] == "none"
    assert quote["paid"] is False
    assert quote["service_unlocked"] is False
    receipt = r.simulate("org_valid", quote["quote_id"], ACKNOWLEDGEMENT)
    assert receipt["status"] == "SIMULATED_NOT_PAID"
    assert receipt["paid"] is False and receipt["settled"] is False
    assert receipt["on_chain"] is False
    assert receipt["service_unlocked"] is False and receipt["grants_entitlements"] is False
    assert receipt["real_transaction_hash"] is None


def test_replay_is_refused():
    r = router()
    quote_id = r.quote("org_valid", "guard_check")["quote_id"]
    r.simulate("org_valid", quote_id, ACKNOWLEDGEMENT)
    with pytest.raises(PaymentSimulationError, match="replay"):
        r.simulate("org_valid", quote_id, ACKNOWLEDGEMENT)


def test_wrong_organization_and_missing_acknowledgement_fail():
    r = router()
    quote_id = r.quote("org_a", "guard_check")["quote_id"]
    for org, ack in [("org_b", ACKNOWLEDGEMENT), ("org_a", "yes")]:
        with pytest.raises(PaymentSimulationError):
            r.simulate(org, quote_id, ack)
    assert r.simulate("org_a", quote_id, ACKNOWLEDGEMENT)["paid"] is False


def test_expiration_fails_closed():
    now = [0.0]
    r = router(clock=lambda: now[0])
    qid = r.quote("org_valid", "ledger_upgrade_pro")["quote_id"]
    now[0] = 601.0
    with pytest.raises(PaymentSimulationError, match="expired"):
        r.simulate("org_valid", qid, ACKNOWLEDGEMENT)


def test_quotes_are_not_money_or_exchange_rates():
    r = router()
    for sku in PRICES:
        q = r.quote("org_valid", sku)
        assert q["asset"] == "PRVI_TEST" and q["simulation_units"] == 1
        assert q["conversion_rate"] is None
        assert q["on_chain"] is False


def test_mcp_registration_requires_org_and_never_grants_pro(monkeypatch):
    """Integration of the additive MCP-tool layer with a fake MCP decorator."""
    import sys
    import types
    from types import SimpleNamespace
    from privi_ledger import dual_payments

    fake_mcp = types.ModuleType("mcp")
    fake_mcp_server = types.ModuleType("mcp.server")
    fake_mcpserver = types.ModuleType("mcp.server.mcpserver")
    fake_mcpserver.Context = type("Context", (), {})
    fake_types = types.ModuleType("mcp_types")
    fake_types.ToolAnnotations = lambda **kw: kw
    for name, mod in (("mcp", fake_mcp), ("mcp.server", fake_mcp_server),
                      ("mcp.server.mcpserver", fake_mcpserver), ("mcp_types", fake_types)):
        monkeypatch.setitem(sys.modules, name, mod)

    class FakeMCP:
        def __init__(self):
            self.tools = {}
        def tool(self, **kwargs):
            def decorator(fn):
                self.tools[fn.__name__] = fn
                return fn
            return decorator

    m = FakeMCP()
    st = SimpleNamespace(network_key="base-sepolia", payments_enabled=True, prices_usd=PRICES)
    monkeypatch.setenv("PRVI_TEST_PAYMENT_MODE", "1")
    dual_payments.register(m, st, org_from=lambda ctx: getattr(ctx, "org", None),
                           result=lambda obj, is_error=False: {**obj, "is_error": is_error},
                           unauthorized={"is_error": True, "error": "unauthorized"})
    assert m.tools["privi_payment_options"]()["payments"][0]["method"] == "USDC_X402"
    bad = m.tools["privi_test_payment_quote"](SimpleNamespace(org=None), "ledger_upgrade_pro")
    assert bad["is_error"] is True
    ctx = SimpleNamespace(org={"org_id": "org_valid"})
    q = m.tools["privi_test_payment_quote"](ctx, "ledger_upgrade_pro")
    assert not q["is_error"]
    receipt = m.tools["privi_test_payment_simulate"](ctx, q["quote_id"], ACKNOWLEDGEMENT)
    assert receipt["paid"] is False and receipt["service_unlocked"] is False
