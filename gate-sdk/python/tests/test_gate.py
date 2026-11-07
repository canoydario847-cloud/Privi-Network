import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import privi_gate as pg  # noqa: E402

GOOD = {"verification": {"valid": True, "subject": {"org_id": "org_1"}, "issued_score": 700, "issued_grade": "B",
                         "live": {"score": 720, "grade": "B"}}}
REVOKED = {"verification": {"valid": False, "revoked": True, "hash_matches_issued": True, "signature_valid": True,
                            "issued_score": 700, "issued_grade": "B"}}


def fake(table, calls=None):
    def f(url, timeout):
        if calls is not None:
            calls.append(url)
        pid = url.rsplit("/", 1)[1]
        if pid == "pp_boom":
            raise OSError("down")
        return table.get(pid, (404, {"error": "not found"}))
    return f


def test_checker_rules_and_cache():
    calls = []
    c = pg.PassportChecker(fetch=fake({"pp_good": (200, GOOD), "pp_revoked": (200, REVOKED)}, calls))
    assert c.check("pp_good").allow and c.check("pp_good").score == 720
    assert len(calls) == 1                                   # cached
    assert "passport revoked by its organization" in c.check("pp_revoked").reasons
    assert c.check("pp_nope").reasons == ["no such passport"]
    assert not c.check(None).allow and not c.check("drop table").allow
    assert not pg.PassportChecker(min_score=800, fetch=fake({"pp_good": (200, GOOD)})).check("pp_good").allow
    assert not pg.PassportChecker(min_grade="A", fetch=fake({"pp_good": (200, GOOD)})).check("pp_good").allow
    assert not c.check("pp_boom").allow
    assert pg.PassportChecker(on_unreachable="allow", fetch=fake({})).check("pp_boom").allow


def test_headers():
    assert pg.passport_from_headers({"X-Privi-Passport": " pp_abc1 "}) == "pp_abc1"
    assert pg.passport_from_headers({"Authorization": "PriviPassport pp_abc1"}) == "pp_abc1"
    assert pg.passport_from_headers({"Authorization": "Bearer x"}) is None


async def _call(gate, path="/mcp", headers=()):
    sent, called = [], []

    async def app(scope, receive, send):
        called.append(scope.get("state", {}).get("privi_passport"))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    gate.app = app

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(m):
        sent.append(m)
    scope = {"type": "http", "path": path, "method": "POST", "headers": [(k.encode(), v.encode()) for k, v in headers]}
    await gate(scope, receive, send)
    return sent[0]["status"], sent, called


def test_middleware_enforce_monitor_exempt():
    chk = pg.PassportChecker(fetch=fake({"pp_good": (200, GOOD)}))
    gate = pg.PriviGate(None, checker=chk)
    status, sent, called = asyncio.run(_call(gate, headers=[("x-privi-passport", "pp_good")]))
    assert status == 200 and called[0]["allow"]
    status, sent, called = asyncio.run(_call(gate))
    assert status == 401 and not called
    body = json.loads(sent[1]["body"])
    assert body["error"] == "privi_passport_required" and body["how_to_get_one"]["steps"]
    assert any(k == b"www-authenticate" for k, _ in sent[0]["headers"])
    assert asyncio.run(_call(gate, path="/health"))[0] == 200
    mon = pg.PriviGate(None, mode="monitor", checker=chk)
    status, _, called = asyncio.run(_call(mon))
    assert status == 200 and called[0]["allow"] is False
