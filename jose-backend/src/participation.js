// Copyright (c) 2026 Privi World Corp. Original prospective proprietary module.
// Nonfinancial, nontransferable beta credits, NOT issued native PRVI or a claim on PRVI.
// Authenticated heartbeats and server-verified network-inspection calls only.
import { createHash, timingSafeEqual } from 'node:crypto';

const DAY = 86_400_000;
const MINUTE = 60_000;
export const POLICY = Object.freeze({
  rewardType: 'NONFINANCIAL_PRVI_PARTICIPATION_CREDITS',
  realPrviIssued: false,
  transferable: false,
  redeemable: false,
  secondsPerMinute: 60,
  presenceCreditsPerMinute: 1,
  inspectionCreditsPerCall: 2,
  maxPresenceMinutesPerUtcDay: 240,
  maxInspectionsPerUtcDay: 30,
  minimumHeartbeatSpacingSeconds: 10,
  maximumHeartbeatGapSeconds: 30,
  minimumInspectionSpacingSeconds: 60,
  note: 'Authenticated beta activity credits only. No PRVI token allocation, wallet balance, or payout is promised.',
});

export function getAgentActor(authorization, config = process.env.JOSE_AGENT_TOKEN_HASHES || '') {
  if (typeof authorization !== 'string' || !/^Bearer [A-Za-z0-9_-]{32,128}$/.test(authorization)) return null;
  const tokenHash = createHash('sha256').update(authorization.slice(7)).digest();
  for (const entry of config.split(',')) {
    const i = entry.indexOf(':');
    const id = entry.slice(0, i);
    const hex = entry.slice(i + 1);
    if (!/^[a-zA-Z0-9_-]{3,48}$/.test(id) || !/^[a-fA-F0-9]{64}$/.test(hex)) continue;
    const expected = Buffer.from(hex, 'hex');
    if (timingSafeEqual(tokenHash, expected)) return 'agent:' + id;
  }
  return null;
}

function qualifiedNetwork(report) {
  return report && report.state === 'OBSERVING' &&
    report.stale === false && report.servicesUp >= Math.ceil(report.servicesTotal * 0.67);
}

export function createParticipationEngine({ store, now = () => Date.now() }) {
  if (!store || typeof store.getRewardState !== 'function' || typeof store.putRewardState !== 'function') {
    throw new Error('Reward engine requires a persistent single-process state store');
  }
  // Ephemeral per-process unique authenticated actors. This is an ecosystem
  // participation signal, NOT validator power, resilience or availability.
  const activeActors = new Map();
  function activeSummary() {
    const t = now();
    for (const [actor, seen] of activeActors) {
      if (t - seen > MINUTE || t < seen) activeActors.delete(actor);
    }
    const actors = [...activeActors.keys()];
    return {
      activeAccountsLast60Seconds: actors.length,
      activeUsers: actors.filter(x => x.startsWith('user:')).length,
      activeAgents: actors.filter(x => x.startsWith('agent:')).length,
      infrastructureGradeContribution: 0,
      note: 'Authenticated participation is an engagement signal, not a consensus-security or uptime metric.',
    };
  }
  function markActive(actor) {
    activeActors.set(actor, now());
    if (activeActors.size > 10000) {
      activeSummary();
      // Bound memory even if an attacker forces many accounts to cycle.
      while (activeActors.size > 10000) activeActors.delete(activeActors.keys().next().value);
    }
  }
  function newState(day) {
    return {
      day, credits: 0, lifetimePresenceMinutes: 0, lifetimeInspections: 0,
      presenceMinutesToday: 0, inspectionsToday: 0, qualifiedMs: 0,
      lastSeenAt: null, lastInspectionAt: null, history: [],
    };
  }
  function account(actor, timestamp) {
    if (typeof actor !== 'string' || !/^(user|agent):[A-Za-z0-9_-]{3,80}$/.test(actor)) {
      throw new Error('Invalid authenticated participation identity');
    }
    const today = Math.floor(timestamp / DAY);
    const saved = store.getRewardState(actor);
    const state = saved && typeof saved.credits === 'number' ? { ...saved } : newState(today);
    if (state.day !== today) {
      state.day = today;
      state.presenceMinutesToday = 0;
      state.inspectionsToday = 0;
      state.qualifiedMs = 0;
      state.lastSeenAt = null;
      state.lastInspectionAt = null;
    }
    return state;
  }
  function appendEvent(state, event) {
    state.history = [...(state.history || []).slice(-29), event];
  }
  function heartbeat(actor, network) {
    const t = now();
    const state = account(actor, t);
    const gap = state.lastSeenAt === null ? 0 : t - state.lastSeenAt;
    // Frequent identical tabs/call bursts do not accelerate the clock.
    if (gap > 0 && gap < 10_000) return summarize(state, network, false);
    const healthy = qualifiedNetwork(network);
    if (healthy) markActive(actor);
    if (healthy && gap >= 10_000 && gap <= 30_000 &&
        state.presenceMinutesToday < POLICY.maxPresenceMinutesPerUtcDay) {
      // No credit for missed/sleeping sessions or unmeasured time.
      state.qualifiedMs += gap;
      const next = Math.min(
        Math.floor(state.qualifiedMs / MINUTE) - state.presenceMinutesToday,
        POLICY.maxPresenceMinutesPerUtcDay - state.presenceMinutesToday,
      );
      if (next > 0) {
        state.credits += next * POLICY.presenceCreditsPerMinute;
        state.presenceMinutesToday += next;
        state.lifetimePresenceMinutes += next;
        appendEvent(state, { at: new Date(t).toISOString(), type: 'qualified_presence',
          minutes: next, credits: next, healthSnapshot: network.checkedAt });
      }
    }
    // On outage or large gaps, do not count unobserved duration.
    state.lastSeenAt = t;
    store.putRewardState(actor, state);
    return summarize(state, network, healthy);
  }
  function inspect(actor, network) {
    const t = now();
    const state = account(actor, t);
    const eligible = qualifiedNetwork(network) &&
      (state.lastInspectionAt === null || t - state.lastInspectionAt >= MINUTE) &&
      state.inspectionsToday < POLICY.maxInspectionsPerUtcDay;
    if (eligible) {
      markActive(actor);
      state.lastInspectionAt = t;
      state.inspectionsToday += 1;
      state.lifetimeInspections += 1;
      state.credits += POLICY.inspectionCreditsPerCall;
      appendEvent(state, { at: new Date(t).toISOString(), type: 'authenticated_network_inspection',
        credits: POLICY.inspectionCreditsPerCall, healthSnapshot: network.checkedAt });
      store.putRewardState(actor, state);
    }
    return { credited: Boolean(eligible), reward: summarize(state, network, eligible) };
  }
  function summarize(state, network, eligible) {
    return {
      ...POLICY,
      totalCredits: state.credits,
      lifetimePresenceMinutes: state.lifetimePresenceMinutes,
      lifetimeInspections: state.lifetimeInspections,
      todayPresenceMinutes: state.presenceMinutesToday,
      todayInspections: state.inspectionsToday,
      pendingPresenceSeconds: Math.min(59, Math.floor((state.qualifiedMs % MINUTE) / 1000)),
      healthQualified: Boolean(eligible),
      recentActivity: [...(state.history || [])].slice(-10).reverse(),
      // Activity is NOT evidence of consensus, operator identity or network resilience.
      networkGrade: network?.grade ?? 'N/A',
    };
  }
  function get(actor, network) {
    const t = now();
    return summarize(account(actor, t), network, qualifiedNetwork(network));
  }
  return { heartbeat, inspect, get, activeSummary };
}
