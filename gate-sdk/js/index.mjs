// Copyright (c) 2026 Privi World Co. All rights reserved.
// Privi Gate: let only AI agents with a valid Privi Passport call your API or MCP server.
// Works as Express/Connect middleware (privGate) or standalone (new PassportChecker().check(id)). No dependencies.

export const VERSION = "0.1.0";
export const LEDGER_URL = "https://privi-ledger.onrender.com";
const GRADES = ["A", "B", "C", "D", "E"];
const ID = /^pp_[A-Za-z0-9_-]{4,64}$/;

export function howToGetOne(ledgerUrl = LEDGER_URL) {
  return {
    what: "This service only accepts AI agents carrying a valid Privi Passport (a signed, on-chain-anchored " +
      "trust credential built from the agent's tamper-evident audit log).",
    steps: [
      `Create a free Privi Ledger organization: MCP tool ledger_signup at ${ledgerUrl}/mcp`,
      "Record your agent's actions with ledger_record (this history is what the passport scores)",
      "Issue a passport: MCP tool passport_issue (free on Pro; $1 USDC via x402 on the free plan)",
      "Send it on every request: header 'X-Privi-Passport: pp_...'",
    ],
    verify_yourself: `${ledgerUrl}/passports/<passport_id>`,
    docs: "https://github.com/canoydario847-cloud/Privi-Network/tree/main/gate-sdk",
  };
}

export function decide(doc, passportId, minScore, minGrade) {
  const v = (doc && doc.verification) || {};
  const reasons = [];
  if (!v.valid) {
    if (v.hash_matches_issued === false) reasons.push("passport content does not match what was issued");
    if (v.signature_valid === false) reasons.push("signature is not from Privi Ledger");
    if (v.expired) reasons.push("passport expired");
    if (v.revoked) reasons.push("passport revoked by its organization");
    if (v.history_still_intact === false) reasons.push("the agent's history no longer verifies (tampering detected since issue)");
    if (!reasons.length) reasons.push("passport did not verify");
  }
  const live = v.live || {};
  const score = live.score ?? v.issued_score ?? null;
  const grade = live.grade ?? v.issued_grade ?? null;
  if (score === null || score < minScore) reasons.push(`current score ${score} is below the required ${minScore}`);
  if (minGrade && GRADES.includes(grade) && GRADES.indexOf(grade) > GRADES.indexOf(minGrade.toUpperCase()))
    reasons.push(`current grade ${grade} is below the required ${minGrade.toUpperCase()}`);
  return { allow: reasons.length === 0, passport_id: passportId, reasons, score, grade, subject: v.subject ?? null };
}

export class PassportChecker {
  constructor({ minScore = 550, minGrade = null, ledgerUrl = LEDGER_URL, cacheSeconds = 300, timeoutMs = 8000,
                onUnreachable = "deny", fetchImpl = globalThis.fetch } = {}) {
    if (!["deny", "allow"].includes(onUnreachable)) throw new Error("onUnreachable must be 'deny' or 'allow'");
    Object.assign(this, { minScore, minGrade, ledgerUrl: ledgerUrl.replace(/\/+$/, ""), cacheSeconds, timeoutMs,
                          onUnreachable, fetchImpl });
    this.cache = new Map();
  }

  async check(passportId) {
    if (!passportId) return { allow: false, passport_id: null, reasons: ["no Privi Passport presented (send header X-Privi-Passport)"] };
    passportId = String(passportId).trim();
    if (!ID.test(passportId)) return { allow: false, passport_id: passportId, reasons: ["malformed passport id"] };
    const hit = this.cache.get(passportId);
    if (hit && Date.now() - hit.at < this.cacheSeconds * 1000) return hit.d;
    const soft = (why) => ({ allow: this.onUnreachable === "allow", passport_id: passportId,
                             reasons: this.onUnreachable === "allow" ? [] : [why] });
    let res;
    try {
      res = await this.fetchImpl(`${this.ledgerUrl}/passports/${passportId}`, {
        headers: { accept: "application/json", "user-agent": `privi-gate/${VERSION}` },
        signal: AbortSignal.timeout(this.timeoutMs) });
    } catch (e) { return soft(`Privi Ledger unreachable: ${e.name || "error"}`); }
    let d;
    if (res.status === 404) d = { allow: false, passport_id: passportId, reasons: ["no such passport"] };
    else if (res.status !== 200) return soft(`Privi Ledger answered HTTP ${res.status}`);
    else d = decide(await res.json(), passportId, this.minScore, this.minGrade);
    this.cache.set(passportId, { at: Date.now(), d });
    return d;
  }
}

export function passportFromHeaders(headers) {
  const get = (k) => (typeof headers.get === "function" ? headers.get(k) : headers[k] ?? headers[k.toLowerCase()]);
  const p = get("x-privi-passport");
  if (p) return String(p).trim();
  const auth = String(get("authorization") || "");
  return /^privipassport\s+/i.test(auth) ? auth.split(/\s+/, 2)[1].trim() : null;
}

/** Express/Connect middleware. mode: "enforce" (default) or "monitor". Sets req.priviPassport. */
export function priviGate({ mode = "enforce", exempt = ["/health", "/healthz", "/.well-known/", "/robots.txt"],
                            onDecision = null, checker = null, ...opts } = {}) {
  if (!["enforce", "monitor"].includes(mode)) throw new Error("mode must be 'enforce' or 'monitor'");
  const chk = checker || new PassportChecker(opts);
  return async function priviGateMiddleware(req, res, next) {
    const path = req.path || (req.url || "").split("?")[0];
    if (req.method === "OPTIONS" || exempt.some((p) => path.startsWith(p))) return next();
    const d = await chk.check(passportFromHeaders(req.headers || {}));
    req.priviPassport = d;
    if (onDecision) { try { onDecision(d, req); } catch (_) {} }
    if (d.allow || mode === "monitor") return next();
    const body = JSON.stringify({ error: "privi_passport_required", decision: d, how_to_get_one: howToGetOne(chk.ledgerUrl) });
    res.statusCode = 401;
    res.setHeader("content-type", "application/json");
    res.setHeader("www-authenticate", `PriviPassport realm="privi", get="${chk.ledgerUrl}/mcp"`);
    res.setHeader("access-control-allow-origin", "*");
    res.end(body);
  };
}
