// Copyright (c) 2026 Privi World Corp — Jose service observability browser client.
const $ = id => document.getElementById(id);
let signedIn = false;
let loadingReport = false;
let latest = null;

async function json(url, options = {}) {
  const r = await fetch(url, { cache: 'no-store', credentials: 'same-origin', ...options });
  if (!r.ok) throw new Error(r.status === 401 ? 'Sign in required' : 'Request failed: HTTP ' + r.status);
  return r.json();
}
function set(id, value) { $(id).textContent = String(value); }
function dateText(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleTimeString();
}
function serviceCard(s) {
  const card = document.createElement('article');
  card.className = 'service';
  const head = document.createElement('div'); head.className = 'service-head';
  const title = document.createElement('h3'); title.textContent = s.name;
  const state = document.createElement('span');
  state.className = 'state ' + (s.status === 'UP' ? 'up' : s.status === 'DOWN' ? 'down' : '');
  state.textContent = s.status;
  head.append(title, state);
  const metrics = document.createElement('div'); metrics.className = 'service-metrics';
  const uptime = document.createElement('div');
  const uptimeValue = document.createElement('strong');
  uptimeValue.textContent = s.uptimePercent === null ? '—' : s.uptimePercent + '%';
  const uptimeCaption = document.createElement('span'); uptimeCaption.className = 'muted'; uptimeCaption.textContent = 'Recent availability';
  uptime.append(uptimeValue, uptimeCaption);
  const latency = document.createElement('div');
  const latencyValue = document.createElement('strong');
  latencyValue.textContent = s.latencyMs === null ? '—' : s.latencyMs + 'ms';
  const latencyCaption = document.createElement('span'); latencyCaption.className = 'muted';
  latencyCaption.textContent = s.lastError ? s.lastError.replaceAll('_',' ') : 'Latest latency';
  latency.append(latencyValue, latencyCaption);
  metrics.append(uptime, latency);
  card.append(head, metrics);
  return card;
}
function showReport(data) {
  latest = data;
  set('grade', data.grade);
  set('grade-state', data.state.replaceAll('_',' '));
  set('score', data.score === null ? '—' : data.score + ' / 100');
  set('responding', data.servicesUp + ' / ' + data.servicesTotal);
  set('checked', dateText(data.checkedAt));
  set('observations', data.sampleCycles + ' cycles · ' + data.observationWindowSeconds + 's observed');
  set('briefing', data.assessment);
  const wrap = $('services'); wrap.replaceChildren(...data.services.map(serviceCard));
  const trend = $('trend'); trend.replaceChildren(...data.lastCycles.map(c => {
    const cell = document.createElement('div');
    cell.className = 'trend-cell ' + (c.up === c.total ? 'up' : c.up === 0 ? 'down' : 'partial');
    cell.title = dateText(c.at) + ' — ' + c.up + '/' + c.total + ' responding';
    return cell;
  }));
}
async function loadReport() {
  if (loadingReport) return;
  loadingReport = true;
  try { showReport(await json('/api/network/report-card')); }
  catch {
    latest = null;
    set('grade','N/A'); set('grade-state','UNAVAILABLE');
    set('score','—'); set('responding','—');
    set('briefing','Jose could not reach its monitoring backend. No health grade is asserted.');
  } finally { loadingReport = false; }
}
function showRewards(data) {
  set('credits', data.totalCredits);
  set('minutes', data.lifetimePresenceMinutes);
  set('inspections', data.lifetimeInspections);
  set('today-minutes', data.todayPresenceMinutes);
  const activity = $('activity');
  activity.replaceChildren(...data.recentActivity.map(a => {
    const li = document.createElement('li');
    li.textContent = dateText(a.at) + ' · ' +
      (a.type === 'qualified_presence' ? 'Connected time (' + a.minutes + ' min)' : 'Network report inspection') +
      ' · +' + a.credits + ' beta credits';
    return li;
  }));
}
async function refreshRewards() {
  try {
    const data = await json('/api/rewards/me');
    signedIn = true;
    $('reward-guest').hidden = true;
    $('reward-member').hidden = false;
    showRewards(data);
  } catch {
    signedIn = false;
    $('reward-guest').hidden = false;
    $('reward-member').hidden = true;
  }
}
async function heartbeat() {
  if (!signedIn || document.visibilityState !== 'visible') return;
  try {
    const data = await json('/api/rewards/heartbeat', { method: 'POST', headers: { 'Content-Type':'application/json' } });
    showRewards(data);
    set('reward-status', data.healthQualified ? 'Presence eligibility: verified by Jose.' :
      'Presence credits paused until at least 5 monitored services pass.');
  } catch { set('reward-status', 'Could not confirm connection; no time credited.'); }
}
$('inspect').addEventListener('click', async () => {
  const btn = $('inspect'); btn.disabled = true;
  try {
    const data = await json('/api/network/inspect', { method: 'POST', headers: { 'Content-Type':'application/json' } });
    showRewards(data.reward);
    set('reward-status', data.credited ? 'Qualified inspection: +2 beta credits.' :
      'Inspection not eligible yet (health, daily cap, or one-minute cooldown).');
  } catch (e) { set('reward-status', e.message); }
  finally { btn.disabled = false; }
});
void loadReport(); void refreshRewards();
setInterval(() => void loadReport(), 5000);
setInterval(() => void heartbeat(), 15000);
setInterval(() => void refreshRewards(), 60000);
