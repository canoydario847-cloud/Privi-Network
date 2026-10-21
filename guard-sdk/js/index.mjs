// Privi Guard client for JavaScript / TypeScript (Node 18+, Deno, Bun, browsers, edge). Zero dependencies.
//
//   import { Guard } from "privi-guard";
//   const guard = new Guard({ apiKey: process.env.PRIVI_API_KEY });
//   const v = await guard.inbound(pageText, { source: url });   // before acting on untrusted content
//   if (v.blocked) throw new Error(v.explain());
//   const out = await guard.outbound(message);                  // before sending
//   send(out.redactedText ?? message);

export const VERSION = "0.1.0";
const DEFAULT_URL = "https://privi-ledger.onrender.com";
const MAX_CHARS = 400_000;

export class GuardError extends Error {}

export class GuardBlocked extends Error {
  constructor(verdict) {
    super(`Privi Guard blocked ${verdict.direction} content (${verdict.findings.map(f => f.code).join(", ") || "policy"})`);
    this.verdict = verdict;
  }
}

export class Verdict {
  constructor(d = {}, extra = {}) {
    this.verdict = d.verdict ?? "allow";
    this.risk = d.risk ?? 0;
    this.direction = d.direction ?? "inbound";
    this.findings = d.findings ?? [];
    this.redactedText = d.redacted_text ?? null;
    this.receipt = d.receipt ?? null;
    this.checked = extra.checked ?? true;
    this.error = extra.error ?? null;
    this.raw = d;
  }
  get blocked() { return this.verdict === "block"; }
  get warned() { return this.verdict === "warn"; }
  get ok() { return this.verdict === "allow"; }
  get receiptId() { return this.receipt?.check_id ?? null; }
  explain() {
    if (!this.checked) return `Not checked by Privi Guard: ${this.error}`;
    if (!this.findings.length) return "Privi Guard: no attack or leak patterns found.";
    return `Privi Guard ${this.verdict}: ` + this.findings.map(f => `${f.code}: ${f.detail}`).join("; ");
  }
}

const toText = v => (typeof v === "string" ? v : (() => { try { return JSON.stringify(v); } catch { return String(v); } })());
const env = k => (typeof process !== "undefined" && process.env ? process.env[k] : undefined);

export class Guard {
  /**
   * @param {{apiKey?: string, baseUrl?: string, timeoutMs?: number, failOpen?: boolean, blockOn?: string[], fetch?: typeof fetch}} [opts]
   */
  constructor(opts = {}) {
    this.apiKey = opts.apiKey ?? env("PRIVI_API_KEY") ?? "";
    this.baseUrl = (opts.baseUrl ?? env("PRIVI_GUARD_URL") ?? DEFAULT_URL).replace(/\/+$/, "");
    this.timeoutMs = opts.timeoutMs ?? 10_000;
    this.failOpen = opts.failOpen ?? true;
    this.blockOn = opts.blockOn ?? ["block"];
    this._fetch = opts.fetch ?? globalThis.fetch.bind(globalThis);
  }

  async _post(path, body) {
    const headers = { "Content-Type": "application/json" };
    if (this.apiKey) headers.Authorization = `Bearer ${this.apiKey}`;
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), this.timeoutMs);
    let r;
    try {
      r = await this._fetch(this.baseUrl + path, { method: "POST", headers, body: JSON.stringify(body), signal: ctl.signal });
    } catch (e) {
      throw new GuardError(`cannot reach Privi Guard: ${e.message ?? e}`);
    } finally {
      clearTimeout(t);
    }
    let data = {};
    try { data = await r.json(); } catch {}
    if (!r.ok) throw new GuardError(`HTTP ${r.status}: ${data.error ?? r.statusText}`);
    return data;
  }

  _unchecked(direction, e) {
    if (!this.failOpen) throw e instanceof GuardError ? e : new GuardError(String(e));
    return new Verdict({ verdict: "allow", direction }, { checked: false, error: String(e.message ?? e) });
  }

  async check(content, direction = "inbound", { source } = {}) {
    const body = { text: toText(content).slice(0, MAX_CHARS), direction };
    if (source) body.source = String(source).slice(0, 300);
    try { return new Verdict(await this._post("/guard/v1/check", body)); } catch (e) { return this._unchecked(direction, e); }
  }
  inbound(content, opts) { return this.check(content, "inbound", opts); }
  outbound(content, opts) { return this.check(content, "outbound", opts); }

  async checkMany(items) {
    const clean = items.map(i => ({ text: toText(i.text).slice(0, MAX_CHARS), direction: i.direction ?? "inbound", ...(i.source ? { source: String(i.source).slice(0, 300) } : {}) }));
    try {
      const out = await this._post("/guard/v1/check_many", { items: clean });
      return out.results.map(r => new Verdict(r));
    } catch (e) {
      return clean.map(c => this._unchecked(c.direction, e));
    }
  }

  /** Wrap an async tool so its result is checked before the agent sees it. */
  wrapTool(fn, { source } = {}) {
    return async (...args) => {
      const out = await fn(...args);
      const v = await this.inbound(out, { source: source ?? fn.name });
      if (this.blockOn.includes(v.verdict)) throw new GuardBlocked(v);
      return out;
    };
  }

  /** Check an outgoing string; returns the redacted text when secrets were found, throws if blocked otherwise. */
  async safeOutbound(text, opts) {
    const v = await this.outbound(text, opts);
    if (v.blocked && v.redactedText != null) return v.redactedText;
    if (this.blockOn.includes(v.verdict)) throw new GuardBlocked(v);
    return text;
  }

  static async signup(organizationName, { baseUrl, fetch: f } = {}) {
    return new Guard({ apiKey: "", baseUrl, failOpen: false, fetch: f })._post("/guard/v1/signup", { organization_name: organizationName });
  }
}

export default Guard;
