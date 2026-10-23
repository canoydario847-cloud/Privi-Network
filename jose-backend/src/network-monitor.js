// Copyright (c) 2026 Privi World Corp. New original source licensed under repository LICENSE.
// Jose's five-second APPLICATION SERVICE health checks, never consensus/mainnet certification.
export const MONITOR_INTERVAL_MS = 5000;
export const TARGETS = Object.freeze([
  { id: 'privi-ledger', name: 'Privi Ledger', url: 'https://privi-ledger.onrender.com/health' },
  { id: 'privi-verify', name: 'Privi Verify', url: 'https://privi-verify.onrender.com/health' },
  { id: 'privi-anchor', name: 'Privi Anchor', url: 'https://privi-anchor.onrender.com/health' },
  { id: 'privi-call', name: 'Privi Call', url: 'https://privi-call.onrender.com/health' },
  { id: 'privi-quantum', name: 'Privi Quantum', url: 'https://privi-quantum.onrender.com/health' },
]);

export function gradeForScore(score) {
  if (!Number.isFinite(score)) return 'N/A';
  return score >= 90 ? 'A' : score >= 80 ? 'B' : score >= 70 ? 'C'
    : score >= 60 ? 'D' : 'F';
}

export function createNetworkMonitor({
  fetchImpl = globalThis.fetch,
  targets = TARGETS,
  intervalMs = MONITOR_INTERVAL_MS,
  timeoutMs = 2500,
  clock = () => Date.now(),
} = {}) {
  if (typeof fetchImpl !== 'function') throw new TypeError('fetch required');
  if (!Array.isArray(targets) || targets.length < 1 || targets.length > 12) {
    throw new TypeError('1 to 12 fixed service targets required');
  }
  if (!Number.isInteger(intervalMs) || intervalMs < 5000) {
    throw new TypeError('Minimum polling interval is five seconds');
  }
  const endpoints = targets.map((target) => {
    const url = new URL(target.url);
    if (url.protocol !== 'https:' || url.username || url.password ||
        url.search || url.hash || url.pathname !== '/health' ||
        !url.hostname.endsWith('.onrender.com') ||
        !/^privi-[a-z-]{2,32}$/.test(target.id)) {
      throw new TypeError('Unapproved Jose health probe target');
    }
    return Object.freeze({ id: target.id, name: target.name, url: target.url });
  });
  let interval = null;
  let last = null;
  let running = false;
  const history = [];

  async function probe(target) {
    const started = clock();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(target.url, {
        method: 'GET', redirect: 'error',
        headers: { accept: 'application/json' }, signal: controller.signal,
      });
      // The native health routes use exact {ok: true, service: "privi-*"}.
      // HTTP 200 or an HTML fallback page by itself is NOT a healthy probe.
      const payload = response.status === 200 ? await response.json() : null;
      const healthy = response.status === 200 && payload?.ok === true &&
        payload?.service === target.id;
      return {
        id: target.id, name: target.name, healthy,
        latencyMs: Math.max(0, Math.round(clock() - started)),
        status: healthy ? 'UP' : 'DOWN',
        detail: healthy ? 'Verified service health response' : 'Missing or invalid health response',
      };
    } catch {
      return {
        id: target.id, name: target.name, healthy: false, latencyMs: null,
        status: 'DOWN', detail: 'Health request failed or timed out',
      };
    } finally {
      clearTimeout(timeout);
    }
  }

  async function checkNow() {
    if (running) return getReport();
    running = true;
    try {
      const services = await Promise.all(endpoints.map((target) => probe(target)));
      const available = services.filter((service) => service.healthy);
      const fraction = available.length / services.length;
      const meanLatencyMs = available.length
        ? Math.round(available.reduce((sum, service) => sum + service.latencyMs, 0) / available.length)
        : null;
      // Availability dominates; responsiveness is scored ONLY for up services.
      const latencyBonus = meanLatencyMs === null ? 0 : Math.max(0, 20 - meanLatencyMs / 125);
      const score = Math.max(0, Math.min(100, Math.round(fraction * (80 + latencyBonus))));
      const checkedAtMs = clock();
      last = {
        checkedAt: new Date(checkedAtMs).toISOString(), checkedAtMs,
        score, grade: gradeForScore(score), available: available.length,
        total: services.length, meanLatencyMs, services,
      };
      history.push({ checkedAt: last.checkedAt, score, grade: last.grade, available: available.length });
      if (history.length > 120) history.shift();
      return getReport();
    } finally {
      running = false;
    }
  }

  function getReport() {
    const ageMs = last ? Math.max(0, clock() - last.checkedAtMs) : null;
    const fresh = last !== null && ageMs <= 15_000;
    const prior = history.slice(-12);
    const summary = !last ? 'Jose has not completed a service check yet.'
      : !fresh ? 'Jose monitoring is stale; no current network grade is available.'
      : last.available === last.total ? 'All monitored Privi application services responded.'
      : last.available === 0 ? 'All monitored Privi application services failed health checks.'
      : last.available + ' of ' + last.total + ' Privi application services are responding.';
    return {
      monitor: 'Jose AI automated service observer',
      checkedEverySeconds: intervalMs / 1000,
      monitoringScope: 'APPLICATION_SERVICES_ONLY',
      consensusHealthVerified: false, financialMainnetActivated: false,
      grade: fresh ? last.grade : 'N/A',
      score: fresh ? last.score : null,
      fresh, checkedAt: last?.checkedAt ?? null,
      ageSeconds: ageMs === null ? null : Math.round(ageMs / 1000),
      available: last?.available ?? 0,
      total: endpoints.length,
      services: last?.services ?? endpoints.map((target) => ({
        id: target.id, name: target.name, healthy: false, status: 'PENDING',
        latencyMs: null, detail: 'Awaiting the first check',
      })),
      history: prior, summary,
      financialRewardClaimsAllowed: false,
    };
  }

  function start() {
    if (interval !== null) return;
    void checkNow().catch((error) => {
      // Never leak external response bodies, URLs, or secrets to public logs.
      console.error('Jose monitor check failed:', error?.name || 'unknown');
    });
    interval = setInterval(() => {
      void checkNow().catch((error) => {
        console.error('Jose monitor check failed:', error?.name || 'unknown');
      });
    }, intervalMs);
  }

  function stop() {
    if (interval !== null) clearInterval(interval);
    interval = null;
  }

  return Object.freeze({ start, stop, checkNow, getReport });
}
