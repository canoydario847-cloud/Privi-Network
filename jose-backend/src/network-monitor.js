// Copyright (c) 2026 Privi World Corp. Original prospective proprietary module.
// Jose service-layer observability; NOT a validator, PoP proof, or financial mainnet attestation.
export const POLL_MS = 5000;
export const TARGETS = Object.freeze([
  { id: 'ledger', name: 'Privi Ledger', url: 'https://privi-ledger.onrender.com/health' },
  { id: 'verify', name: 'Privi Verify', url: 'https://privi-verify.onrender.com/health' },
  { id: 'anchor', name: 'Privi Anchor', url: 'https://privi-anchor.onrender.com/health' },
  { id: 'call', name: 'Privi Call', url: 'https://privi-call.onrender.com/health' },
  { id: 'quantum', name: 'Privi Quantum', url: 'https://privi-quantum.onrender.com/health' },
  { id: 'discovery', name: 'Privi Discovery', url: 'https://privi-discovery.onrender.com/health' },
]);

export function gradeFromScore(score) {
  return score >= 95 ? 'A' : score >= 85 ? 'B' : score >= 70 ? 'C' : score >= 55 ? 'D' : 'F';
}

// All URLs are fixed by this server at build time. Never take probe URLs from public callers.
export function createNetworkMonitor({ targets = TARGETS, fetchImpl = globalThis.fetch,
  now = () => Date.now(), pollMs = POLL_MS, timeoutMs = 3000, maxCycles = 120 } = {}) {
  if (!Array.isArray(targets) || !targets.length ||
      targets.some(t => !t.id || !t.name || !/^https:\/\//.test(t.url))) {
    throw new Error('Monitor needs fixed HTTPS targets');
  }
  let samples = [];
  let pending = false;
  let timer = null;

  async function probe(target) {
    const started = now();
    const ctl = new AbortController();
    const cutoff = setTimeout(() => ctl.abort(), timeoutMs);
    try {
      const response = await fetchImpl(target.url, {
        signal: ctl.signal, redirect: 'error',
        headers: { Accept: 'application/json', 'User-Agent': 'Jose-Privi-Health/1' },
      });
      if (!response.ok) return { id: target.id, name: target.name, ok: false,
        latencyMs: now() - started, reason: 'HTTP_' + response.status };
      const payload = await response.json();
      const good = payload && payload.ok === true;
      return { id: target.id, name: target.name, ok: Boolean(good),
        latencyMs: now() - started, reason: good ? null : 'HEALTH_NOT_OK' };
    } catch {
      return { id: target.id, name: target.name, ok: false,
        latencyMs: now() - started, reason: ctl.signal.aborted ? 'TIMEOUT' : 'NETWORK_ERROR' };
    } finally {
      clearTimeout(cutoff);
    }
  }

  async function poll() {
    if (pending) return false; // never overlap cycles, even during slow responses
    pending = true;
    try {
      const results = await Promise.all(targets.map(probe));
      samples.push({ at: now(), results });
      if (samples.length > maxCycles) samples = samples.slice(-maxCycles);
      return true;
    } finally {
      pending = false;
    }
  }

  function report() {
    const checkedAt = samples.length ? samples[samples.length - 1].at : null;
    const stale = !checkedAt || now() - checkedAt > pollMs * 3;
    const enough = samples.length >= 3 && !stale;
    const last = samples.length ? samples[samples.length - 1].results : [];
    const services = targets.map(target => {
      const history = samples.map(s => s.results.find(r => r.id === target.id)).filter(Boolean);
      const good = history.filter(x => x.ok);
      const recent = last.find(x => x.id === target.id);
      return {
        id: target.id, name: target.name, status: !recent || stale ? 'UNKNOWN' : recent.ok ? 'UP' : 'DOWN',
        uptimePercent: history.length ? Math.round(100 * good.length / history.length) : null,
        latencyMs: recent ? recent.latencyMs : null,
        avgLatencyMs: good.length ? Math.round(good.reduce((a, v) => a + v.latencyMs, 0) / good.length) : null,
        lastError: recent?.reason ?? null,
        samples: history.length,
      };
    });
    const total = services.reduce((sum, s) => sum + s.samples, 0);
    const successes = samples.flatMap(s => s.results).filter(x => x.ok);
    const upNow = !stale ? last.filter(x => x.ok).length : 0;
    const availability = total ? successes.length / total : 0;
    const fastShare = successes.length ? successes.filter(x => x.latencyMs <= 1500).length / successes.length : 0;
    const freshShare = services.length ? upNow / services.length : 0;
    // Observed service health is evidence-driven: participants cannot inflate this score.
    const score = enough ? Math.round(80 * availability + 10 * fastShare + 10 * freshShare) : null;
    let assessment = 'Insufficient fresh measurements';
    if (enough) {
      assessment = upNow === targets.length
        ? 'Jose: all monitored services responded. This does not verify blockchain consensus.'
        : 'Jose: ' + (targets.length - upNow) + ' of ' + targets.length +
          ' services are failing checks. Investigate degraded endpoints.';
    }
    return {
      product: 'Jose AI — Privi Network Report Card',
      monitor: 'SERVER_SIDE_HTTP_HEALTH_PROBES',
      scope: 'Privi service availability only; not native mainnet, PoP consensus, or validator health',
      checkedAt: checkedAt ? new Date(checkedAt).toISOString() : null,
      intervalSeconds: pollMs / 1000,
      observationWindowSeconds: samples.length * pollMs / 1000,
      sampleCycles: samples.length,
      stale,
      state: !checkedAt ? 'STARTING' : stale ? 'STALE' : enough ? 'OBSERVING' : 'WARMING_UP',
      grade: score === null ? 'N/A' : gradeFromScore(score),
      score,
      servicesUp: upNow,
      servicesTotal: targets.length,
      services,
      assessment,
      lastCycles: samples.slice(-24).map(s => ({
        at: new Date(s.at).toISOString(), up: s.results.filter(x => x.ok).length,
        total: s.results.length,
      })),
      realPrviRewardsEnabled: false,
      financialMainnetVerified: false,
    };
  }

  function start() {
    if (timer) return;
    void poll().catch(err => console.error('Jose monitor cycle failed:', err.message));
    timer = setInterval(() => {
      void poll().catch(err => console.error('Jose monitor cycle failed:', err.message));
    }, pollMs);
    timer.unref?.();
  }
  function stop() { if (timer) clearInterval(timer); timer = null; }
  return { poll, report, start, stop };
}
