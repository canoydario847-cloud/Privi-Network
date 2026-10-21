export declare const VERSION: string;
export interface Finding { severity: "high" | "medium" | "low" | "info"; code: string; detail: string; evidence?: string }
export interface Receipt { check_id: string; receipt_hash: string; signature_ed25519: string; body: Record<string, unknown>; verify: string }
export declare class GuardError extends Error {}
export declare class GuardBlocked extends Error { verdict: Verdict }
export declare class Verdict {
  verdict: "allow" | "warn" | "block"; risk: number; direction: "inbound" | "outbound"; findings: Finding[];
  redactedText: string | null; receipt: Receipt | null; checked: boolean; error: string | null; raw: unknown;
  readonly blocked: boolean; readonly warned: boolean; readonly ok: boolean; readonly receiptId: string | null;
  explain(): string;
}
export interface GuardOptions { apiKey?: string; baseUrl?: string; timeoutMs?: number; failOpen?: boolean; blockOn?: string[]; fetch?: typeof fetch }
export declare class Guard {
  constructor(opts?: GuardOptions);
  check(content: unknown, direction?: "inbound" | "outbound", opts?: { source?: string }): Promise<Verdict>;
  inbound(content: unknown, opts?: { source?: string }): Promise<Verdict>;
  outbound(content: unknown, opts?: { source?: string }): Promise<Verdict>;
  checkMany(items: { text: unknown; direction?: "inbound" | "outbound"; source?: string }[]): Promise<Verdict[]>;
  wrapTool<A extends unknown[], R>(fn: (...a: A) => Promise<R> | R, opts?: { source?: string }): (...a: A) => Promise<R>;
  safeOutbound(text: string, opts?: { source?: string }): Promise<string>;
  static signup(organizationName: string, opts?: { baseUrl?: string; fetch?: typeof fetch }): Promise<{ api_key: string; org_id: string }>;
}
export default Guard;
