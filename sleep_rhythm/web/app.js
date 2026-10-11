import {AGE, KSS, MIN_PERIODS, MAX_PERIODS, esc, uid, defaultData, hoursLabel, minutesLabel, zoneLocal, timeLabel, dayLabel, addDay,
  isoInZone, hhmm, toMs, localToMs, nextWake, periodTargets, validateTimetable, timetableRows, sameTimetable, upgradeTimetable,
  addPeriod, removePeriod, defaultTimetable, nearestOccurrence, latestBefore, latestAtOrBefore,
  defaultKind, historyStatus, recordProblem, validateImport, datasetProblem, canonicalZone, csv, demoData, candidateRangeText,
  chartScale} from './utils.js';

const $ = id => document.getElementById(id);
const KEY = 'rhythm-data-v1', PREFS = 'rhythm-prefs-v1', SESSION = 'rhythm-sleep-session-v1', RESULT = 'rhythm-last-result-v1';
const RESCUE = 'rhythm-data-unreadable', INTRO_HIDDEN = 'rhythm-intro-hidden';
const WAKE_PROMPT_MINUTES = 60;   // a screen unlock this long after "잠자러 가기" asks about waking up
const SNOOZE_MINUTES = 30;        // after "아직 자는 중이에요"
const LONG_SESSION_HOURS = 16;    // older sessions ask for the wake-up date as well
const LATENCIES = [[0, '바로'], [15, '15분'], [30, '30분'], [60, '1시간']];
const GLOSSARY = [
  ['수면압 (S)', '깨어 있을수록 쌓이고 자면 줄어드는 ‘졸음의 양’이에요.'],
  ['일주기 기준 (C)', '몸시계에 따라 하루 동안 오르내리는 ‘버틸 수 있는 졸음의 한계’예요.'],
  ['각성 지표 (AL)', 'C − S. 0 이상이면 모형상 깨어 있기 괜찮고, 0보다 작으면 ‘잠이 필요한데 깨어 있는’ 상태예요.'],
  ['모형 각성도 높음·낮음', '고른 교시 내내 AL이 0 이상이면 ‘높음’, 한 번이라도 0 아래로 내려가면 ‘낮음’이에요. 실제 집중력 점수는 아니에요.'],
  ['필요 수면', '잠든 뒤 수면압이 일주기 기준 아래로 내려가 그대로 머무를 때까지의 잠이에요. 그 전에 일어나면 모형상 ‘필요한 잠을 덜 잔’ 상태예요.'],
  ['권장 취침 구간', '조건을 모두 지키면서 평소 취침 시각을 가장 적게 바꾸는 30분이에요. ‘늦어도’ 시각까지 잠드는 것이 목표예요.'],
  ['준비 기간', '처음 4일은 모형이 내 기록에 맞춰지는 기간이에요. 연속 5일째부터 계산해요.']
];

let data = defaultData(), personal = null, prefs = defaultPrefs(), session = null, saved = null;
let analysisCache = null, researchCache = null, sheetState = null, calcError = null, calcBusy = false, analysisRuns = 0;
let storageWorks = true, storedUnreadable = false, recordLimit = 30, currentTab = 'home', obsRev = 0;
let ttDraft = null;  // timetable edits not saved yet (kept while the app is open)
let toastTimer, installPrompt, sleepTimer, resizeTimer;

// ---------- storage: everything stays in this browser
function defaultPrefs() { return {wake: '07:00', periods: ['p1'], timetable: defaultTimetable(), latency: 15, rev: 0}; }
function read(key) { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; } }
function write(key, value) {
  try { value == null ? localStorage.removeItem(key) : localStorage.setItem(key, JSON.stringify(value)); storageWorks = true; }
  catch { storageWorks = false; }
  $('storage-banner').hidden = storageWorks;
}
function loadData() {
  let raw = null;
  try { raw = localStorage.getItem(KEY); } catch { storageWorks = false; return; }
  if (!raw) return;
  try {
    const next = validateImport(JSON.parse(raw)), z = next.profile.timezone;
    zoneLocal(Date.now(), z);
    if (![...next.records.flatMap(r => [r.start, r.end]), ...next.observations.map(o => o.at)].every(v => Number.isFinite(toMs(v, z)))) throw new Error('unreadable time');
    data = next;
  } catch {
    data = defaultData(); storedUnreadable = true;
    try { if (!localStorage.getItem(RESCUE)) localStorage.setItem(RESCUE, raw); } catch { /* storage full */ }
  }
}
function loadPrefs() {
  const raw = read(PREFS), p = defaultPrefs();
  if (raw && typeof raw === 'object') {
    if (/^([01]\d|2[0-3]):[0-5]\d$/.test(raw.wake)) p.wake = raw.wake;
    try { p.timetable = validateTimetable(upgradeTimetable(raw.timetable)); } catch { /* keep defaults */ }
    if (Array.isArray(raw.periods)) p.periods = raw.periods.filter(id => p.timetable.some(t => t.id === id));
    if (LATENCIES.some(([m]) => m === raw.latency)) p.latency = raw.latency;
    if (Number.isInteger(raw.rev)) p.rev = raw.rev;
  }
  prefs = p;
}
function loadSession() { const s = read(SESSION); session = s && Number.isFinite(s.start) && s.start <= Date.now() + 6e4 ? s : null; }
function loadSaved() { const s = read(RESULT); saved = s?.result && s.request ? s : null; }
const savePrefs = () => write(PREFS, prefs);
const saveSession = () => write(SESSION, session);
function persist() { if (!demo()) write(KEY, data); }
// Records, profile and timetable feed the calculation and the analysis; activity sleepiness only the model comparison.
function changed(scope = 'records') {
  researchCache = null;
  if (scope === 'observations') { obsRev++; return; }
  prefs.rev = (prefs.rev || 0) + 1; savePrefs(); analysisCache = null;
}

const zone = () => data.profile.timezone;
const demo = () => data.data_kind === 'demo';
const clone = () => structuredClone(data);
const serverData = () => ({schema_version: 1, data_kind: data.data_kind, profile: data.profile, records: data.records, observations: data.observations});
const tl = (v, withDate = false) => esc(timeLabel(v, zone(), withDate));
const profileInfo = () => { const [label, min, max, eligible, searchMax] = AGE[data.profile.age_group]; return {label, min, max, eligible: eligible && data.profile.schedule === 'day', searchMax}; };

function toast(message, ms = 4500) { const t = $('toast'); t.textContent = message; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, ms); }
function showError(id, message) { $(id).textContent = message || ''; $(id).hidden = !message; }
function hm(hours) {
  if (hours == null || !Number.isFinite(hours)) return '—';
  const m = Math.round(hours * 60), h = Math.floor(m / 60), r = m % 60;
  return `<b>${h}</b>시간${r ? ` <b>${r}</b>분` : ''}`;
}

async function api(path, payload) {
  // A free hosting plan may be asleep: waking it can take about a minute.
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 75000);
  const slow = setTimeout(() => toast('서버를 깨우는 중이에요. 무료 서버는 처음 응답까지 1분쯤 걸릴 수 있어요.', 9000), 5000);
  try {
    const r = await fetch('/api/' + path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload), signal: controller.signal, cache: 'no-store'});
    let body;
    try { body = await r.json(); } catch { throw new Error('서버 응답을 읽을 수 없어요. 앱 주소가 맞는지 확인해 주세요.'); }
    if (!r.ok) throw new Error(body.error || '요청을 처리할 수 없어요.');
    return body;
  } catch (e) {
    if (e.name === 'AbortError' || e instanceof TypeError) throw Object.assign(new Error('서버에 연결할 수 없어요. 인터넷 연결을 확인하고 다시 시도해 주세요. 기록은 이 휴대폰에 그대로 있어요.'), {offline: true});
    throw e;
  } finally { clearTimeout(timer); clearTimeout(slow); }
}

// ---------- home
function wakeInfo(now = Date.now()) { return nextWake(now, zone(), prefs.wake); }
function relativeDay(day) {
  const today = zoneLocal(Date.now(), zone()).slice(0, 10);
  return day === today ? '오늘' : day === addDay(today, 1) ? '내일' : '';
}
function currentRequest(now = Date.now()) {
  const w = wakeInfo(now);
  if (!w) return null;
  const {targets, skipped} = periodTargets(w.ms, zone(), prefs.timetable, prefs.periods);
  const labels = prefs.timetable.filter(p => prefs.periods.includes(p.id) && !skipped.includes(p.id)).map(p => p.label);
  return {wake: isoInZone(w.ms, zone()), targets, skipped, labels, rev: prefs.rev, profile: JSON.stringify(data.profile), kind: data.data_kind};
}
function resultFresh() {
  const req = currentRequest();
  return !!(saved && req && saved.request.wake === req.wake && JSON.stringify(saved.request.targets) === JSON.stringify(req.targets)
    && saved.request.rev === req.rev && saved.request.profile === req.profile && saved.request.kind === req.kind);
}
const resultLive = () => !!saved && saved.request.kind === data.data_kind && Date.parse(saved.result.wake) > Date.now();

function renderHome() {
  const now = Date.now();
  $('today-date').textContent = new Intl.DateTimeFormat('ko-KR', {timeZone: zone(), month: 'long', day: 'numeric', weekday: 'short'}).format(now);
  renderStatus(now); renderPeriods(now); renderWake(now); renderCalc();
}

function renderStatus(now) {
  const h = historyStatus(data.records, zone(), now);
  $('stat-days').innerHTML = `<b>${h.days}</b>일`;
  $('stat-avg').innerHTML = hm(h.mean);
  $('stat-last').innerHTML = hm(h.last?.hours);
  let tag = '기록 충분', cls = 'tag ok', note = '';
  const empty = !data.records.length;
  $('status-badge').hidden = empty; $('status-demo').hidden = !empty;
  if (empty) tag = '기록 없음';
  else if (h.duplicate) { tag = '확인 필요'; cls = 'tag warn'; note = '밤잠이 2개인 날을 기록 탭에서 고쳐 주세요.'; }
  else if (h.stale) { tag = '기록 끊김'; cls = 'tag warn'; note = '빠진 날은 기록 탭에서 추가해 주세요.'; }
  else if (h.days < 5) { tag = `준비 중 ${h.days}/5`; cls = 'tag'; note = h.missing ? `${dayLabel(h.missing)} 기록을 추가하면 이어져요.` : `${5 - h.days}일 더 기록하면 계산할 수 있어요.`; }
  else if (h.days < 10) tag = '계산 가능';
  $('status-badge').className = cls; $('status-badge').textContent = tag;
  $('status-note').textContent = note; $('status-note').hidden = !note;
}

function renderPeriods(now) {
  const w = wakeInfo(now), focused = document.activeElement?.dataset?.period;
  let disabledAny = false, count = 0;
  // Periods before the wake-up time stay pressable (aria-disabled) so a press can explain why they are off.
  $('period-chips').innerHTML = prefs.timetable.map(p => {
    const disabled = !w || localToMs(`${w.day}T${p.start}`, zone()) < w.ms;
    const on = prefs.periods.includes(p.id) && !disabled;
    disabledAny ||= disabled; count += on;
    return `<button type="button" class="chip" data-period="${p.id}" aria-pressed="${on}"${disabled ? ' aria-disabled="true"' : ''} aria-label="${esc(p.label)} ${p.start}–${p.end}${disabled ? ', 기상 시각보다 이른 교시' : ''}">${esc(p.label)}</button>`;
  }).join('');
  $('period-chips').classList.toggle('five', prefs.timetable.length > 8);
  if (focused) $('period-chips').querySelector(`[data-period="${focused}"]`)?.focus({preventScroll: true});
  $('focus-meta').textContent = disabledAny ? '이른 교시 제외' : count ? `${count}개 선택` : '선택 없음';
}

function renderWake(now) {
  const w = wakeInfo(now);
  if (document.activeElement !== $('wake-time')) $('wake-time').value = prefs.wake;
  $('wake-day').textContent = w ? `${dayLabel(w.day)} ${relativeDay(w.day)} 아침`.replace('  ', ' ') : '';
}

function summarize(r) {
  const t = v => timeLabel(v, zone());
  if (r.status === 'ready' || r.status === 'partial') {
    const keep = r.mode === 'keep';
    let sub = keep ? (r.baseline?.source === 'habitual' ? '평소처럼 자면 돼요' : '지금 계획대로 괜찮아요')
      : r.mode === 'advance' && r.advance_minutes ? `평소보다 ${minutesLabel(r.advance_minutes)} 일찍`
      : r.mode === 'earliest' ? '가능한 한 빨리' : '이 구간에 잠들기';
    sub = `늦어도 ${t(r.deadline.bed)} · ${sub}`;
    if (r.status === 'partial') sub += r.partial_reason === 'large_shift' ? ' · 오늘은 60분까지만 앞당겨요' : ' · 집중 시간 조건은 일부 미충족';
    return {main: keep ? t(r.best.bed) : candidateRangeText(r, zone()), sub, cls: ''};
  }
  if (r.status === 'warmup') return r.history_days >= 5
    ? {main: '최근 기록을 먼저 채워 주세요', sub: '마지막 밤잠 기록이 36시간보다 오래됐어요.', cls: 'message'}
    : {main: `기록이 ${5 - r.history_days}일 더 필요해요`, sub: `연속 5일째부터 계산해요 (지금 ${r.history_days}일)`, cls: 'message'};
  if (r.status === 'infeasible') {
    if (r.infeasible_reason === 'minimum_unreachable') {
      const left = (Date.parse(r.wake) - Date.now()) / 36e5;
      return {main: `${r.minimum_hours}시간을 채우기 어려워요`, sub: `지금 자도 ${t(r.wake)}까지 ${hoursLabel(Math.max(0, left))}이에요. 기상 시각을 늦출 수 있는지 확인해 보세요.`, cls: 'message'};
    }
    return {main: '조건에 맞는 시각이 없어요', sub: r.message, cls: 'message'};
  }
  if (r.status === 'irregular') return {main: '리듬을 더 살펴볼게요', sub: '수면 시각이 들쭉날쭉해 이번 계산은 쉬어요. 기록은 계속 쌓여요.', cls: 'message'};
  return {main: '지금은 기록만 해요', sub: r.message || '', cls: 'message'};
}

function renderCalc() {
  const card = $('calc-card');
  const live = resultLive(), fresh = live && resultFresh();
  let main = '몇 시에 자면 좋을까요?', sub = '', cls = 'idle';
  if (live) ({main, sub, cls} = summarize(saved.result));
  if (live && !fresh) sub = '바뀐 내용이 있어요 · 다시 계산해 주세요';
  if (calcError) { main = calcError.main; sub = calcError.sub; cls = 'message'; }
  $('calc-main').textContent = main; $('calc-main').className = `calc-main ${cls}`.trim();
  $('calc-sub').textContent = sub;
  card.classList.toggle('has-result', !!(live && fresh && !calcError));
  $('calc-detail').hidden = !live;
  $('calc-button').textContent = calcBusy ? '계산 중…' : live && fresh ? '다시 계산하기' : '최근 기록으로 취침 시각 계산하기';
  $('calc-button').disabled = calcBusy;
}

async function calculate() {
  if (calcBusy) return;
  calcError = null;
  const req = currentRequest();
  if (!req) { calcError = {main: '기상 시각을 확인해 주세요', sub: '꼭 일어나야 하는 시각을 다시 골라 주세요.'}; renderCalc(); return; }
  if (!req.targets.length) {
    calcError = prefs.periods.length ? {main: '교시를 다시 골라 주세요', sub: '고른 교시가 모두 기상 시각보다 일러요.'}
      : {main: '교시를 골라 주세요', sub: '아래에서 교시를 하나 이상 눌러 주세요.'};
    renderCalc(); return;
  }
  calcBusy = true; renderCalc();
  try {
    const result = await api('recommend', {...serverData(), plan: {wake: req.wake, targets: req.targets}});
    if (req.rev !== prefs.rev || req.kind !== data.data_kind) { toast('계산하는 동안 기록이 바뀌었어요. 다시 눌러 주세요.'); return; }
    saved = {result, request: req, at: Date.now()};
    if (!demo()) write(RESULT, saved);
    if (currentTab === 'basis') renderBasis();
    toast(result.status === 'ready' ? '오늘 밤 취침 시각을 계산했어요.' : result.status === 'partial' ? '계산했어요. 모형 조건 일부는 만족하지 못해요.' : '계산 결과를 확인해 주세요.');
  } catch (e) {
    calcError = e.offline ? {main: '서버에 연결하지 못했어요', sub: '인터넷을 확인하고 다시 눌러 주세요.'} : {main: '계산하지 못했어요', sub: e.message};
  } finally {
    calcBusy = false; renderCalc();
    // The home card shows at most two lines; a longer explanation is shown in full once.
    const sub = $('calc-sub');
    if (sub.scrollHeight > sub.clientHeight + 1) toast(sub.textContent, 9000);
  }
}

// ---------- sleep session
function startSleep() {
  if (demo()) { toast('예시를 보는 중에는 수면 기록을 시작할 수 없어요. 위의 ‘예시 보는 중 · 끝내기’를 누른 뒤 다시 눌러 주세요.', 6000); return; }
  if (!session) { session = {start: Date.now()}; saveSession(); }
  showSleep();
}
function showSleep() {
  $('sleep-screen').hidden = false; $('app').inert = true;
  updateSleep(); clearInterval(sleepTimer); sleepTimer = setInterval(updateSleep, 30000);
  $('wake-button').focus({preventScroll: true});
}
function hideSleep() { $('sleep-screen').hidden = true; $('app').inert = false; clearInterval(sleepTimer); }
function updateSleep() {
  if (!session) return;
  const z = zone(), now = Date.now(), minutes = Math.max(0, (now - session.start) / 6e4);
  $('sleep-since').textContent = `${timeLabel(session.start, z)}에 잠자리에 들었어요 · ${minutes < 1 ? '방금' : `${minutesLabel(minutes)}째`}`;
  const w = nextWake(session.start, z, prefs.wake, .5), info = profileInfo();
  const mins = w ? Math.round((w.ms - session.start) / 6e4) : null;  // whole minutes, as shown
  let plan = '';
  if (mins != null && mins >= 180 && mins <= 840) {
    plan = `${timeLabel(w.ms, z)}에 일어나면 약 ${minutesLabel(mins)}`;
    if (info.eligible) plan += mins >= info.min * 60 ? ` · 최소 ${info.min}시간 충족` : ` · 최소 ${info.min}시간보다 ${minutesLabel(info.min * 60 - mins)} 짧아요`;
    if (resultLive() && saved.result.deadline && saved.result.wake === isoInZone(w.ms, z)) {
      const deadline = Date.parse(saved.result.deadline.bed);
      plan += session.start <= deadline + 6e4 ? ' · 권장 마감 전에 누웠어요' : ` · 권장 마감(${timeLabel(deadline, z)})보다 ${minutesLabel((session.start - deadline) / 6e4)} 늦었어요`;
    }
  }
  $('sleep-plan').textContent = plan;
}
function maybeAskWake() {
  if (!session || $('sheet').open) return;
  const now = Date.now();
  if (now - session.start < WAKE_PROMPT_MINUTES * 6e4 || (session.snooze && now < session.snooze)) return;
  openSheet('wake', {detected: now, auto: true});
}
function endSession(message) { session = null; saveSession(); hideSleep(); renderHome(); if (message) toast(message); }

// ---------- record sheet (wake-up, manual add, edit)
function openSheet(mode, opts = {}) {
  const z = zone(), now = Date.now();
  sheetState = {mode, id: opts.id || null, kind: 'main', kindTouched: false, kss: null, latency: null, detected: null, light: null};
  showError('sheet-error', '');
  $('sheet-note').hidden = true;
  $('sheet-day-row').hidden = mode === 'wake'; $('latency-row').hidden = mode !== 'wake';
  $('sheet-still').hidden = mode !== 'wake'; $('sheet-discard').hidden = mode !== 'wake'; $('sheet-delete').hidden = mode !== 'edit';
  $('sheet-day').max = zoneLocal(now, z).slice(0, 10);
  if (mode === 'wake') {
    const detected = Math.max(opts.detected ?? now, session.start + 6e4);
    const long = detected - session.start > LONG_SESSION_HOURS * 36e5;
    Object.assign(sheetState, {detected, long, latency: prefs.latency});
    $('sheet-title').textContent = opts.auto ? '일어나셨나요?' : '잘 잤어요?';
    let end = detected;
    if (long) {
      // the button was pressed long ago: offer the planned wake-up time on the morning after
      const planned = nextWake(session.start, z, prefs.wake, 1);
      if (planned && planned.ms <= now) end = planned.ms;
      $('sheet-day-row').hidden = false;
      $('sheet-day').value = zoneLocal(end, z).slice(0, 10);
      $('sheet-note').textContent = `잠자러 간 지 ${LONG_SESSION_HOURS}시간이 넘었어요. 실제로 일어난 날짜와 시각으로 고쳐 주세요.`;
      $('sheet-note').hidden = false;
    }
    $('sheet-start').value = hhmm(Math.min(session.start + prefs.latency * 6e4, end - 6e4), z);
    $('sheet-end').value = hhmm(end, z);
  } else if (mode === 'edit') {
    const r = data.records.find(x => x.id === opts.id);
    if (!r) return;
    const s = toMs(r.start, z), e = toMs(r.end, z);
    Object.assign(sheetState, {kind: r.kind, kindTouched: true, kss: r.sleepiness_wake ?? null, light: r.light_minutes ?? null});
    $('sheet-title').textContent = '수면 기록 고치기';
    $('sheet-day').value = zoneLocal(e, z).slice(0, 10); $('sheet-start').value = hhmm(s, z); $('sheet-end').value = hhmm(e, z);
  } else {
    const last = historyStatus(data.records, z, now).last, local = zoneLocal(now, z), today = local.slice(0, 10);
    $('sheet-title').textContent = '수면 기록 추가';
    $('sheet-start').value = last ? hhmm(toMs(last.start, z), z) : '23:00';
    $('sheet-end').value = last ? hhmm(toMs(last.end, z), z) : '07:00';
    const recorded = new Set(data.records.filter(r => r.kind === 'main').map(r => zoneLocal(toMs(r.end, z), z).slice(0, 10)));
    let day = $('sheet-end').value <= local.slice(11) ? today : addDay(today, -1);
    for (let i = 0; i < 14 && recorded.has(day); i++) day = addDay(day, -1);
    $('sheet-day').value = recorded.has(day) ? today : day;
  }
  renderSheetChoices(); updateSheet();
  if (!$('sheet').open) $('sheet').showModal();
}
function sheetTimes() {
  const z = zone(), s = $('sheet-start').value, e = $('sheet-end').value;
  if (!/^\d\d:\d\d$/.test(s) || !/^\d\d:\d\d$/.test(e)) return null;
  const day = $('sheet-day').value, wake = sheetState.mode === 'wake' && !sheetState.long;
  if (!wake && !/^\d{4}-\d\d-\d\d$/.test(day)) return null;
  // wake-up: the latest such clock time up to now; the onset: the one nearest the button press
  const end = wake ? latestAtOrBefore(e, sheetState.detected + 2 * 6e4, z) : localToMs(`${day}T${e}`, z);
  const start = sheetState.mode === 'wake' ? nearestOccurrence(s, session.start, z) : latestBefore(s, end, z);
  return Number.isFinite(start) && Number.isFinite(end) ? {start, end} : null;
}
function renderSheetChoices() {
  document.querySelectorAll('#latency-chips [data-latency]').forEach(b => b.setAttribute('aria-pressed', String(sheetState.latency === Number(b.dataset.latency))));
  document.querySelectorAll('#sheet .seg').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.kind === sheetState.kind)));
  document.querySelectorAll('#sheet-kss [data-kss]').forEach(b => b.setAttribute('aria-pressed', String(sheetState.kss === Number(b.dataset.kss))));
}
function updateSheet() {
  const t = sheetTimes();
  if (!t) { $('sheet-summary').textContent = ''; return; }
  const minutes = (t.end - t.start) / 6e4;
  if (!sheetState.kindTouched) {
    sheetState.kind = defaultKind(minutes);
    document.querySelectorAll('#sheet .seg').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.kind === sheetState.kind)));
  }
  const z = zone();
  $('sheet-summary').textContent = minutes >= 1 && minutes <= 1200
    ? `${timeLabel(t.start, z, true)} → ${timeLabel(t.end, z, true)} · ${minutesLabel(minutes)}` : '시각을 확인해 주세요.';
}
function saveSheet(e) {
  e.preventDefault();
  const t = sheetTimes(), z = zone();
  if (!t) { showError('sheet-error', '시각을 확인해 주세요.'); return; }
  if (sheetState.mode === 'wake' && t.end <= session.start) {
    showError('sheet-error', `일어난 시각은 잠자러 간 시각(${timeLabel(session.start, z)})보다 늦어야 하고, 지금보다 늦을 수 없어요.`);
    return;
  }
  const rec = {id: sheetState.id || uid(), start: isoInZone(t.start, z), end: isoInZone(t.end, z), kind: sheetState.kind, sleepiness_wake: sheetState.kss, light_minutes: sheetState.light};
  const problem = recordProblem(data.records, rec, z, Date.now());
  if (problem) { showError('sheet-error', problem); return; }
  const next = clone();
  next.records = next.records.filter(r => r.id !== rec.id);
  next.records.push(rec);
  commit(next);
  const mode = sheetState.mode;
  $('sheet').close();
  const summary = `${timeLabel(t.start, z)} → ${timeLabel(t.end, z)} (${minutesLabel((t.end - t.start) / 6e4)})`;
  if (mode === 'wake') endSession(`기록했어요: ${summary}`);
  else toast(mode === 'edit' ? `고쳤어요: ${summary}` : `추가했어요: ${summary}`);
}
function commit(next, scope = 'records') { data = next; persist(); changed(scope); renderAll(); }

// ---------- records tab
function renderRecords() {
  const z = zone(), list = $('record-list');
  const rows = [...data.records].sort((a, b) => toMs(b.end, z) - toMs(a.end, z));
  if (!rows.length) { list.innerHTML = '<li class="empty">아직 기록이 없어요.<br>오늘 밤 홈에서 ‘잠자러 가기’를 눌러 보세요.</li>'; $('more-records').hidden = true; return; }
  list.innerHTML = rows.slice(0, recordLimit).map(r => {
    const s = toMs(r.start, z), e = toMs(r.end, z), day = zoneLocal(e, z).slice(0, 10), nap = r.kind === 'nap';
    const label = dayLabel(day), extra = [minutesLabel((e - s) / 6e4), nap ? '낮잠' : '밤잠', r.sleepiness_wake ? `졸림 ${r.sleepiness_wake}` : ''].filter(Boolean).join(' · ');
    return `<li class="record${nap ? ' nap' : ''}"><div class="rec-date"><b>${esc(label.slice(0, -3))}</b><small>${esc(label.slice(-3))}</small></div><div class="rec-main"><b>${tl(s)} → ${tl(e)}</b><small>${esc(extra)}</small></div><button type="button" class="rec-edit" data-edit="${esc(r.id)}" aria-label="${esc(label)} ${tl(s)}부터의 기록 고치기">고치기</button></li>`;
  }).join('');
  $('more-records').hidden = rows.length <= recordLimit;
}

// ---------- analysis tab
function analysisBusy(delta) {
  analysisRuns += delta;
  $('analysis-refresh').disabled = analysisRuns > 0; $('analysis-refresh').textContent = analysisRuns > 0 ? '분석 중…' : '새로 분석';
}
async function refreshAnalysis(force = false) {
  renderObsLast();
  if (!force && analysisCache?.rev === prefs.rev && analysisCache.kind === data.data_kind) { renderAnalysis(analysisCache.result); return; }
  const rev = prefs.rev, kind = data.data_kind;
  $('analysis-tiles').innerHTML = '<div class="tile"><small>분석 중…</small><b>—</b></div>';
  analysisBusy(1);
  try {
    const result = await api('analysis', serverData());
    if (rev !== prefs.rev || kind !== data.data_kind) return;
    analysisCache = {result, rev, kind};
    if (currentTab === 'analysis') renderAnalysis(result);
    if (force) toast('기록을 새로 분석했어요.');
  } catch (e) {
    $('analysis-tiles').innerHTML = '';
    $('analysis-comments').innerHTML = `<li class="comment warn"><b>분석하지 못했어요</b><p>${esc(e.message)}</p></li>`;
  } finally { analysisBusy(-1); }
}
function clock(h) { const m = Math.round(h * 60) % 1440; return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`; }
function renderAnalysis(r) {
  const s = r.stats || {}, min = r.profile.minimum, eligible = r.profile.eligible;
  $('analysis-range').textContent = r.range
    ? `${dayLabel(r.range.first.slice(0, 10))} ~ ${dayLabel(r.range.last.slice(0, 10))} · 기록 ${r.range.records}개 (밤잠 ${r.range.mains}, 낮잠 ${r.range.naps})`
    : '기록을 바탕으로 수면시간·규칙성·필요 수면을 살펴보고 풀어서 설명해요.';
  const tile = (label, value, note) => `<div class="tile"><small>${esc(label)}</small><b>${value}</b><span>${esc(note)}</span></div>`;
  const tiles = [];
  if (r.status === 'ready') {
    tiles.push(tile('최근 7일 평균', s.avg7 != null ? esc(hoursLabel(s.avg7)) : '—', `${eligible ? '밤잠' : '낮잠 포함'} · 권장 ${min}시간 이상`));
    tiles.push(tile('권장 시간 채운 날', s.nights7 ? `${s.meets7} / ${s.nights7}일` : '—', '최근 7일 중 기록한 날'));
    if (s.bed_sd_minutes != null) tiles.push(tile('잠드는 시각', `±${s.bed_sd_minutes}분`, `평균 ${clock(s.bed_mean)}`));
    if (eligible) tiles.push(tile('필요 수면 채운 날', s.necessary_nights ? `${s.necessary_ok} / ${s.necessary_nights}일` : '준비 중', '모형 계산 · 준비 기간 제외'));
    else tiles.push(tile('기록한 날', `${s.nights14}일`, '최근 14일 중'));
  }
  $('analysis-tiles').innerHTML = tiles.join('');
  $('analysis-comments').innerHTML = r.comments.map(c => `<li class="comment ${esc(c.tone)}"><b>${esc(c.title)}</b><p>${esc(c.text)}</p></li>`).join('');
  $('analysis-disclaimer').textContent = r.message || '';
  drawTimeline(r);
}
function drawTimeline(r) {
  const box = $('timeline'), nights = r.nights || [];
  if (!nights.length) { box.innerHTML = '<p class="card-note">기록이 쌓이면 14일 동안 언제 잤는지 막대로 보여 줘요.</p>'; return; }
  const z = zone(), W = Math.max(280, Math.round(box.clientWidth || 300)), L = 46, R = 62, top = 20, row = 20, H = top + nights.length * row + 4;
  const span = 24 * 36e5, x = v => L + v / span * (W - L - R);
  const grid = [0, 6, 12, 18, 24].map(k => { const px = x(k * 36e5); return `<line x1="${px.toFixed(1)}" y1="${top - 4}" x2="${px.toFixed(1)}" y2="${H - 2}" class="tl-grid"/><text x="${px.toFixed(1)}" y="${top - 7}" text-anchor="${k === 24 ? 'end' : k === 0 ? 'start' : 'middle'}" class="tl-hour">${(18 + k) % 24}시</text>`; }).join('');
  const episodes = data.records.map(rec => ({s: toMs(rec.start, z), e: toMs(rec.end, z), nap: rec.kind === 'nap'}));
  const rows = nights.map((n, i) => {
    const y = top + i * row, from = localToMs(`${addDay(n.date, -1)}T18:00`, z), to = localToMs(`${n.date}T18:00`, z);
    const bars = episodes.filter(ep => ep.e > from && ep.s < to).map(ep => {
      const a = x(Math.max(0, ep.s - from) * span / (to - from)), b = x(Math.min(to - from, ep.e - from) * span / (to - from));
      const cls = ep.nap ? 'tl-nap' : n.meets_minimum === false ? 'tl-short' : 'tl-main';
      return `<rect x="${a.toFixed(1)}" y="${y + 4}" width="${Math.max(2, b - a).toFixed(1)}" height="${row - 8}" rx="3" class="${cls}"/>`;
    }).join('');
    const label = dayLabel(n.date);
    const value = n.hours != null ? hoursLabel(n.hours).replace('시간 ', '시간') : '기록 없음';
    return `<text x="0" y="${y + row - 6}" class="tl-label">${esc(label.slice(0, -3))} ${esc(label.slice(-2, -1))}</text>${bars}<text x="${W}" y="${y + row - 6}" text-anchor="end" class="${n.hours != null ? 'tl-value' : 'tl-label'}">${esc(value)}</text>`;
  }).join('');
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="최근 14일 동안 잠든 시각부터 일어난 시각까지를 막대로 나타낸 그래프. 각 줄 오른쪽에 그날의 수면시간이 있어요."><title>최근 14일 수면 막대 그래프</title>${grid}${rows}</svg>`;
}

async function refreshResearch() {
  const key = `${prefs.rev}:${obsRev}:${data.data_kind}`;
  renderObservations();
  try {
    const r = researchCache?.key === key ? researchCache.result : await api('research', serverData());
    if (key !== `${prefs.rev}:${obsRev}:${data.data_kind}`) return;
    researchCache = {result: r, key};
    const desc = {A: ['수면량만', '측정 전 24시간 총수면시간'], B: ['평소 시각과의 일치', '전날 취침·기상 시각과 그 이전 평균의 차이'], C: ['수면압 + 일주기', '측정 시각의 AL = C − S']};
    $('research-results').innerHTML = (r.metrics || []).map(m => `<div class="metric"><div><b>모델 ${m.model} · ${desc[m.model][0]}</b><small>${desc[m.model][1]}</small></div><strong>${m.rho_with_alertness == null ? '—' : m.rho_with_alertness.toFixed(2)}</strong></div>`).join('')
      + `<p class="card-note">비교 ${r.rows.length}회 / ${r.daily.length}일 · 제외 ${r.excluded}회. 5일 이상 모이면 값이 나와요. 양수일수록 ‘모형 값이 높은 날 덜 졸렸다’는 뜻이고, 어느 모형이 낫다고 미리 정하지 않아요.${demo() ? ' 지금은 합성한 예시 자료예요.' : ''}</p><p class="card-note">${esc(r.message || '')}</p>`;
    $('export-research').setAttribute('aria-disabled', String(!r.rows.length));
  } catch (e) { $('research-results').innerHTML = `<p class="form-error">${esc(e.message)}</p>`; }
}
function renderObservations() {
  const rows = [...data.observations].sort((a, b) => toMs(b.at, zone()) - toMs(a.at, zone())).slice(0, 20);
  $('observations-list').innerHTML = rows.length ? `<ul class="obs-list">${rows.map(o => `<li><span>${tl(toMs(o.at, zone()), true)} · 졸림 ${esc(o.sleepiness)}</span><button type="button" data-delete-ob="${esc(o.id)}" aria-label="${tl(toMs(o.at, zone()), true)} 졸림 기록 지우기">지우기</button></li>`).join('')}</ul>` : '';
}
// The latest sleepiness tap stays on screen under the buttons.
function renderObsLast() {
  const z = zone(), last = data.observations.reduce((a, o) => !a || toMs(o.at, z) > toMs(a.at, z) ? o : a, null);
  const word = last && KSS.find(k => k[0] === last.sleepiness)?.[1];
  $('obs-last').textContent = last ? `마지막 기록: ${timeLabel(toMs(last.at, z), z, true)} · 졸림 ${last.sleepiness}${word ? `(${word})` : ''} · 모두 ${data.observations.length}번` : '아직 기록이 없어요.';
}
function addObservation(value) {
  if (!Number.isInteger(value)) return;
  const next = clone();
  next.observations.push({id: uid(), at: isoInZone(Date.now(), zone()), sleepiness: value});
  if (next.observations.length > 400) { toast('졸림 기록은 400개까지 보관해요. 오래된 기록을 지운 뒤 다시 눌러 주세요.'); return; }
  commit(next, 'observations'); renderObsLast();
  toast(`지금 졸림 ${value}(${KSS.find(k => k[0] === value)[1]})을 기록했어요.`);
  if ($('research-results').closest('details').open) refreshResearch();
}

// ---------- basis tab (details of the latest calculation)
function renderBasis() {
  const box = $('basis-result');
  if (!resultLive()) {
    box.innerHTML = '<h2>최근 계산</h2><p class="card-note">홈에서 ‘최근 기록으로 취침 시각 계산하기’를 누르면 여기에서 계산 과정과 그래프를 볼 수 있어요.</p>';
    return;
  }
  const r = saved.result, req = saved.request, z = zone(), t = v => esc(timeLabel(v, z));
  const head = `<h2>최근 계산</h2><p class="card-note">${tl(saved.at, true)} 계산 · ${t(r.wake)} 기상 · ${esc(req.labels.join('·') || '고른 교시')} 기준${resultFresh() ? '' : ' · <b>그 뒤 조건이나 기록이 바뀌었어요</b>'}</p>`;
  const warnings = (r.warnings || []).length ? `<ul class="warn-list">${r.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : '';
  if (r.status !== 'ready' && r.status !== 'partial') {
    const s = summarize(r);
    box.innerHTML = `${head}<p class="result-big">${esc(s.main)}</p><p class="result-line">${esc(r.message || s.sub)}</p>${warnings}`;
    return;
  }
  const b = r.best, d = r.deadline, base = r.baseline, min = r.profile.minimum, keep = r.mode === 'keep';
  const hoursOf = at => (Date.parse(r.wake) - Date.parse(at)) / 36e5;
  const [shortest, longest] = keep ? [b.hours, b.hours] : [hoursOf(r.window.end), hoursOf(r.window.start)];
  const deadlineText = (at, none) => at == null ? `<b>${none}</b>` : `늦어도 <b>${t(at)}</b>`;
  let message = '';
  if (r.partial_reason === 'large_shift') message = `<p class="result-msg warn">${esc(r.message)} 모형 기준 목표는 <b>${t(r.deadlines.overall)}</b> 전 취침이에요. 하루에 15분 이상씩 며칠에 걸쳐 앞당기면 닿을 수 있어요.</p>`;
  else if (r.status === 'partial') message = `<p class="result-msg warn">${esc(r.message)}</p>`;
  else if (keep) message = `<p class="result-msg">${base?.source === 'habitual' ? '평소 취침 시각(최근 평균)' : '지금 계획'}이 이미 두 조건을 만족해요. 바꾸지 않아도 돼요.</p>`;
  else if (r.mode === 'advance' && base) message = `<p class="result-msg">평소 취침(${t(base.bed)})보다 <b>${esc(minutesLabel(r.advance_minutes))} 이상</b> 일찍 잠드는 것을 권해요.</p>`;
  else if (r.mode === 'earliest') message = '<p class="result-msg">비교할 평소 취침 시각이 이미 지나서, 지금부터 잠들 수 있는 가장 이른 시각을 기준으로 계산했어요.</p>';
  const checks = [
    {ok: true, label: `연령별 최소 수면 ${min}시간 이상`, when: deadlineText(r.deadlines.minimum, '불가'), note: `${r.profile.label} 권장 수면시간의 최솟값`},
    {ok: r.deadlines.target != null, label: '고른 교시 내내 각성 지표 AL ≥ 0', when: deadlineText(r.deadlines.target, '연령별 범위 안에서는 불가'), note: '집중할 시간에 모형상 ‘잠이 필요한데 깨어 있는’ 때가 없어야 해요'},
    {ok: null, label: `필요 수면이 ${t(r.wake)} 전에 끝남 (참고)`, when: deadlineText(r.deadlines.necessary, '연령별 범위 안에서는 불가'), note: '기상 시각에서 거꾸로 계산한 참고 정보예요. 이것만으로 결정을 바꾸지는 않아요'}
  ];
  const checkList = `<ul class="checks">${checks.map(c => `<li class="${c.ok === null ? 'info' : c.ok ? 'ok' : 'bad'}"><span class="mark" aria-hidden="true">${c.ok === null ? 'i' : c.ok ? '✓' : '✗'}</span><span>${c.label} · ${c.when}</span><small>${c.note}</small></li>`).join('')}</ul>`;
  let compare = '';
  if (base) {
    const short = Math.round((min - base.hours) * 60);
    let necessary;
    if (base.necessary_ok) necessary = `필요 수면이 ${t(base.necessary_end)}에 끝나서 ${t(r.wake)}에 일어나도 괜찮아요(모형).`;
    else if (base.necessary_end) necessary = `필요 수면이 ${t(base.necessary_end)}에 끝나서, ${t(r.wake)}에 일어나면 <b>필요한 잠이 끝나기 전에 깨요</b>(모형). ` + (r.necessary_advance_minutes ? `연령별 수면시간을 지키면서 기상 전에 끝나게 하려면 약 <b>${esc(minutesLabel(r.necessary_advance_minutes))}</b> 일찍 자야 해요.` : '연령별 수면시간 범위 안에서는 앞당겨도 기상 전에 끝나지 않아요.');
    else necessary = '모형상 16시간 안에 필요 수면이 끝나지 않아요.';
    compare = `<h3 class="sub-title">${base.source === 'habitual' ? `평소처럼 ${t(base.bed)}에 자면` : `${t(base.bed)}에 자면`}</h3><p class="card-note">수면 ${esc(hoursLabel(base.hours))} · ${short > 0 ? `<b>최소 ${min}시간보다 ${esc(minutesLabel(short))} 부족</b>` : `최소 ${min}시간 충족`} · 집중 시간 모형 각성도 <b>${base.target_ok ? '높음' : '낮음'}</b></p><p class="card-note">${necessary}</p>`;
  }
  const s = r.sensitivity;
  const sens = s ? `<p class="fold-text">일주기 위상 ±1시간, 시간상수 ±20%로 바꾼 ${s.scenarios}가지 가정에서 다시 계산한 마감: <b>${s.overall_earliest ? `${t(s.overall_earliest)}~${t(s.overall_latest)}` : '없음'}</b>${s.overall_unresolved ? ` (${s.overall_unresolved}가지 가정에서는 조건을 모두 만족하는 시각 없음)` : ''}. 필요 수면 기준 마감: <b>${s.necessary_earliest ? `${t(s.necessary_earliest)}~${t(s.necessary_latest)}` : '없음'}</b>. 통계적 신뢰구간이 아니에요.</p>` : '';
  const mark = v => v ? '✓' : '✗';
  const candidates = `<ul class="cand-list">${r.candidates.map(c => `<li class="${c.bed === b.bed ? 'best' : ''}"><span><b>${t(c.bed)}</b> · ${esc(hoursLabel(c.hours))}${base && c.bed === base.bed ? ' (평소)' : ''}</span><small>최소${mark(c.meets_minimum && c.within_maximum)} 집중${mark(c.target_ok)} 필요수면${mark(c.necessary_ok)}</small></li>`).join('')}</ul>`;
  const table = `<table class="num-table"><thead><tr><th scope="col">시각</th><th scope="col">S</th><th scope="col">C</th><th scope="col">AL</th>${r.chart.some(q => q.baseline_AL != null) ? '<th scope="col">평소 AL</th>' : ''}</tr></thead><tbody>${r.chart.filter((_, i) => i % 2 === 0).map(q => `<tr><td>${t(q.at)}</td><td>${q.S.toFixed(2)}</td><td>${q.C.toFixed(2)}</td><td>${q.AL.toFixed(2)}</td>${q.baseline_AL != null ? `<td>${q.baseline_AL.toFixed(2)}</td>` : r.chart.some(x => x.baseline_AL != null) ? '<td>—</td>' : ''}</tr>`).join('')}</tbody></table>`;
  box.innerHTML = `${head}<p class="result-big">${esc(keep ? timeLabel(b.bed, z) : candidateRangeText(r, z))}</p><p class="result-line">${deadlineText(d.bed)} · 예상 수면 ${esc(shortest === longest ? hoursLabel(shortest) : `${hoursLabel(shortest)}~${hoursLabel(longest)}`)} · 모형 각성도 ${b.target_ok ? '높음' : '낮음'}</p>${message}${checkList}${compare}
    <h3 class="sub-title">24시간 모형 흐름</h3><div class="chart-legend"><span class="legend s">수면압 S</span><span class="legend c">일주기 기준 C</span><span class="legend al">각성 지표 AL</span>${r.chart.some(q => q.baseline_AL != null) ? '<span class="legend base">평소대로 잘 때 AL</span>' : ''}<span class="legend dead">취침 마감</span></div><div class="chart"></div><p class="card-note">보라 음영: 권장 구간 시작에 잠들 때의 수면 · 초록 음영: 고른 교시. AL이 0보다 작으면 ‘잠이 필요한데 깨어 있는’ 상태예요. 세로축은 단위 없는 모형 값이에요.</p>
    <details class="fold"><summary>모든 후보 보기 (${r.candidates.length}개)</summary>${candidates}</details>
    <details class="fold"><summary>그래프 숫자 표 (30분 간격)</summary>${table}</details>
    <details class="fold"><summary>가정을 바꾸면?</summary>${sens}</details>
    ${warnings}<button id="export-result" class="pill-button ghost" type="button">계산 결과 CSV 저장</button>`;
  drawChart(r);
}
function drawChart(r) {
  const box = $('basis-result').querySelector('.chart'), rows = r.chart;
  if (!box || !rows?.length || box.offsetParent === null) return;
  const W = Math.max(280, Math.round(box.clientWidth || 320)), H = 220, L = 36, R = 8, T = 16, B = 26;
  const {lo, hi, step, ticks} = chartScale(rows);
  const first = Date.parse(rows[0].at), last = Date.parse(rows.at(-1).at);
  const x = at => L + (Date.parse(at) - first) / (last - first) * (W - L - R);
  const y = v => T + (hi - v) / (hi - lo) * (H - T - B);
  const line = key => rows.filter(q => q[key] != null).map((q, i) => `${i ? 'L' : 'M'}${x(q.at).toFixed(1)},${y(q[key]).toFixed(1)}`).join(' ');
  const shade = (a, b, cls) => { const aa = Math.max(L, x(a)), bb = Math.min(W - R, x(b)); return bb > aa ? `<rect x="${aa.toFixed(1)}" y="${T}" width="${(bb - aa).toFixed(1)}" height="${H - T - B}" class="${cls}"/>` : ''; };
  const grid = ticks.map(v => `<line x1="${L}" y1="${y(v).toFixed(1)}" x2="${W - R}" y2="${y(v).toFixed(1)}" class="${v === 0 ? 'chart-zero' : 'chart-grid'}"/><text x="${L - 5}" y="${(y(v) + 4).toFixed(1)}" class="chart-label" text-anchor="end">${v.toFixed(step < .5 ? 2 : 1)}</text>`).join('');
  const ticksX = rows.filter((_, i) => i % 24 === 0).map(q => { const px = x(q.at); return `<text x="${px.toFixed(1)}" y="${H - 8}" class="chart-label" text-anchor="${px > W - 30 ? 'end' : px < L + 20 ? 'start' : 'middle'}">${esc(timeLabel(q.at, zone()))}</text>`; }).join('');
  const dl = r.deadline?.bed, inRange = dl && Date.parse(dl) >= first && Date.parse(dl) <= last;
  const marker = inRange ? `<line x1="${x(dl).toFixed(1)}" y1="${T}" x2="${x(dl).toFixed(1)}" y2="${H - B}" class="chart-deadline"/>` : '';
  const targets = (r.targets || [[r.target_start, r.target_end]]).map(([a, b]) => shade(a, b, 'chart-target')).join('');
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="권장안의 수면압, 일주기 기준, 각성 지표 24시간 그래프. 값은 아래 숫자 표에 있어요."><title>24시간 모형 흐름</title>${shade(r.best.bed, r.wake, 'chart-sleep')}${targets}${grid}<path d="${line('S')}" class="line-s"/><path d="${line('C')}" class="line-c"/><path d="${line('baseline_AL')}" class="line-base"/><path d="${line('AL')}" class="line-al"/>${marker}${ticksX}</svg>`;
}

// ---------- settings
function ageGuidance() {
  const [label, lo, hi, eligible, searchMax] = AGE[$('age-group').value];
  const amount = hi == null ? `${lo}시간 이상` : `${lo}~${hi}시간`;
  $('age-guidance').textContent = `${label} · 권장 수면 하루 ${amount}. ` + (eligible
    ? `추천은 ${lo}~${searchMax}시간${hi == null ? '(9시간은 앱 탐색 상한이며 의학적 상한이 아님)' : ''}의 밤잠에서 찾고, 평소 수면이 더 길어도 줄이라고 하지 않아요. 낮잠은 최소 수면시간에 넣지 않아요.`
    : '밤잠 추천 없이 기록과 낮잠을 포함한 수면량 요약만 제공해요.');
}
function renderSettings() {
  // unsaved profile edits survive a redraw (for example after 시간표 저장)
  if ($('profile-dirty').hidden) { $('age-group').value = data.profile.age_group; $('schedule').value = data.profile.schedule || 'day'; $('timezone').value = zone(); }
  ageGuidance(); showError('profile-error', ''); profileDirty(); renderTimetable();
  $('demo-button').textContent = demo() ? '예시 끝내고 내 기록으로' : '14일 예시로 둘러보기';
  let rescue = null; try { rescue = localStorage.getItem(RESCUE); } catch { /* unavailable */ }
  $('export-rescue').hidden = !rescue;
}
// Unsaved changes stay visible: a note under the fields and a glowing save button.
function profileDirty() {
  const typed = $('timezone').value.trim();
  const dirty = $('age-group').value !== data.profile.age_group || $('schedule').value !== (data.profile.schedule || 'day')
    || (canonicalZone(typed) || typed) !== zone();
  $('profile-dirty').hidden = !dirty; $('save-profile').classList.toggle('needs-save', dirty);
}
function saveProfile() {
  const tz = canonicalZone($('timezone').value);
  if (!tz) { showError('profile-error', '시간대 이름을 확인해 주세요. 예: Asia/Seoul, America/New_York'); return; }
  const next = clone();
  next.profile = {age_group: $('age-group').value, timezone: tz, schedule: $('schedule').value === 'shift' ? 'shift' : 'day'};
  const problem = tz === zone() ? '' : datasetProblem(next, Date.now());
  if (problem) { showError('profile-error', `이 시간대로 바꾸면 기존 기록을 읽을 수 없어요. ${problem}`); return; }
  commit(next); $('timezone').value = tz; profileDirty(); toast('설정을 저장했어요.');
}

// ---------- settings: school timetable (edits, added and removed periods stay a draft until 시간표 저장)
const timetableInputs = () => [...$('timetable-rows').querySelectorAll('.tt-row')].map(row => ({
  start: row.querySelector('[data-edge=start]').value, end: row.querySelector('[data-edge=end]').value}));
function renderTimetable() {
  const rows = timetableRows(ttDraft || prefs.timetable), n = rows.length - 1;
  $('timetable-rows').innerHTML = rows.map(p => {
    const old = prefs.timetable.find(s => s.id === p.id);
    const input = (edge, word) => `<input type="time" data-tt="${p.id}" data-edge="${edge}" value="${esc(p[edge])}"${old?.[edge] === p[edge] ? '' : ' class="changed"'} aria-label="${esc(p.label)} ${word}">`;
    return `<div class="tt-row${old ? '' : ' tt-new'}"><span>${esc(p.label)}</span>${input('start', '시작')}<i aria-hidden="true">–</i>${input('end', '끝')}</div>`;
  }).join('');
  $('add-period').hidden = n >= MAX_PERIODS; $('add-period').textContent = `＋ ${n + 1}교시 추가하기`;
  $('remove-period').hidden = n <= MIN_PERIODS; $('remove-period').textContent = `− ${n}교시 빼기`;
  $('period-limit').hidden = n < MAX_PERIODS;
  timetableDirty();
}
function timetableDirty() {
  if (ttDraft && sameTimetable(ttDraft, prefs.timetable)) ttDraft = null;
  $('timetable-dirty').hidden = !ttDraft; $('save-timetable').classList.toggle('needs-save', !!ttDraft);
}
function editTimetable(next, message) {
  ttDraft = next; showError('timetable-error', ''); renderTimetable();
  toast(ttDraft ? `${message} ‘시간표 저장’을 눌러야 적용돼요.` : '저장된 시간표와 같아요.', 6000);
}
function saveTimetable() {
  try {
    const rows = validateTimetable(timetableInputs());
    prefs.timetable = rows; prefs.periods = prefs.periods.filter(id => rows.some(r => r.id === id));
    ttDraft = null; changed(); renderAll(); toast('시간표를 저장했어요. 홈의 교시 버튼에 바로 반영돼요.');
  } catch (e) { showError('timetable-error', e.message); }
}

function download(name, body, type, what) {
  const blob = new Blob([body], {type}), url = URL.createObjectURL(blob), a = document.createElement('a');
  a.href = url; a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
  toast(`${what} 저장했어요(${name}). 다운로드 폴더에서 확인할 수 있어요.`, 6000);
}
const stamp = () => zoneLocal(Date.now(), zone()).slice(0, 10);
function enterDemo() {
  if (!demo()) personal = clone();
  data = demoData(); analysisCache = researchCache = null; renderAll(); navigate('home');
  toast('14일 예시 기록을 불러왔어요. 계산·분석을 눌러 보세요.');
}
function exitDemo() {
  data = personal || defaultData(); personal = null; analysisCache = researchCache = null; loadSaved(); renderAll();
  toast('예시를 끝내고 내 기록으로 돌아왔어요.');
}
async function importBackup(file) {
  if (file.size > 524288) throw new Error('512KB 이하의 백업 파일만 불러올 수 있어요.');
  let parsed;
  try { parsed = JSON.parse(await file.text()); } catch { throw new Error('백업 파일(JSON)을 읽을 수 없어요.'); }
  const next = validateImport(parsed), problem = datasetProblem(next, Date.now());
  if (problem) throw new Error(problem);
  if (!confirm(`${next.data_kind === 'demo' ? '예시' : '내'} 기록 ${next.records.length}개를 불러올까요? 지금 이 기기의 기록을 바꿔요. 필요하면 먼저 백업 파일을 저장하세요.`)) return;
  if (next.data_kind === 'demo' && !demo()) personal = clone();
  if (next.data_kind === 'personal') personal = null;
  commit(next); toast('백업을 불러왔어요.');
}

// ---------- intro (shown at every launch unless hidden for this session)
function introHidden() { try { return sessionStorage.getItem(INTRO_HIDDEN) === '1'; } catch { return false; } }
function openIntro() { if (!$('intro-dialog').open) $('intro-dialog').showModal(); $('intro-close').focus({preventScroll: true}); }

// ---------- navigation and rendering
const TABS = ['home', 'records', 'analysis', 'basis', 'settings'];
function navigate(tab) {
  if (!TABS.includes(tab)) tab = 'home';
  currentTab = tab;
  for (const t of TABS) $('tab-' + t).hidden = t !== tab;
  document.querySelectorAll('.tab').forEach(b => b.dataset.tab === tab ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current'));
  if (location.hash.slice(1) !== tab) history.replaceState(null, '', '#' + tab);
  window.scrollTo(0, 0);
  if (tab === 'home') renderHome();
  if (tab === 'records') renderRecords();
  if (tab === 'analysis') refreshAnalysis();
  if (tab === 'basis') renderBasis();
  if (tab === 'settings') renderSettings();
}
function renderAll() {
  $('exit-demo').hidden = !demo(); $('today-date').hidden = demo(); $('storage-banner').hidden = storageWorks;
  renderHome();
  if (currentTab === 'records') renderRecords();
  if (currentTab === 'analysis') refreshAnalysis();
  if (currentTab === 'basis') renderBasis();
  if (currentTab === 'settings') renderSettings();
}

// ---------- events
document.querySelectorAll('.tab').forEach(b => b.addEventListener('click', () => navigate(b.dataset.tab)));
window.addEventListener('hashchange', () => navigate(location.hash.slice(1)));
$('calc-button').addEventListener('click', calculate);
$('calc-detail').addEventListener('click', () => navigate('basis'));
$('period-chips').addEventListener('click', e => {
  const b = e.target.closest('[data-period]');
  if (!b) return;
  if (b.getAttribute('aria-disabled') === 'true') {
    const p = prefs.timetable.find(x => x.id === b.dataset.period);
    toast(`${p ? p.label : '이 교시'}는 꼭 일어나야 하는 시각(${prefs.wake})보다 일러서 고를 수 없어요. 기상 시각을 바꾸면 고를 수 있어요.`);
    return;
  }
  const id = b.dataset.period;
  prefs.periods = prefs.periods.includes(id) ? prefs.periods.filter(p => p !== id) : [...prefs.periods, id];
  calcError = null; savePrefs(); renderPeriods(Date.now()); renderCalc();
});
$('wake-time').addEventListener('change', e => {
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(e.target.value)) { e.target.value = prefs.wake; return; }
  prefs.wake = e.target.value; calcError = null; savePrefs(); renderHome(); flash($('wake-time').closest('.wake-row'));
});
$('status-demo').addEventListener('click', enterDemo);
$('sleep-button').addEventListener('click', startSleep);
$('wake-button').addEventListener('click', () => { if (session) openSheet('wake', {detected: Date.now()}); });
$('sleep-cancel').addEventListener('click', () => { if (confirm('이번 수면 기록을 취소할까요? 잠자러 간 시각이 지워져요.')) endSession('수면 기록을 취소했어요.'); });
$('sleep-screen').addEventListener('pointerdown', e => { if (!e.target.closest('button')) maybeAskWake(); });
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') {
    if ($('sheet').open && sheetState?.mode === 'wake') $('sheet').close();
    return;
  }
  if (session) { updateSleep(); maybeAskWake(); }
  if (currentTab === 'home') renderHome();
});
window.addEventListener('pageshow', () => { if (session) maybeAskWake(); });

$('sheet-form').addEventListener('submit', saveSheet);
$('sheet-form').addEventListener('input', e => {
  if (e.target.id === 'sheet-start' && sheetState.latency != null) { sheetState.latency = null; renderSheetChoices(); }
  showError('sheet-error', ''); updateSheet();
});
$('sheet-form').addEventListener('click', e => {
  const lat = e.target.closest('[data-latency]'), kind = e.target.closest('[data-kind]'), kss = e.target.closest('[data-kss]');
  if (lat && session) {
    const m = Number(lat.dataset.latency);
    sheetState.latency = m; prefs.latency = m; savePrefs();
    const t = sheetTimes();
    $('sheet-start').value = hhmm(Math.min(session.start + m * 6e4, (t?.end ?? sheetState.detected) - 6e4), zone());
    renderSheetChoices(); updateSheet();
  }
  if (kind) { sheetState.kind = kind.dataset.kind; sheetState.kindTouched = true; renderSheetChoices(); }
  if (kss) { const v = Number(kss.dataset.kss); sheetState.kss = sheetState.kss === v ? null : v; renderSheetChoices(); }
});
$('sheet-x').addEventListener('click', () => $('sheet').close());
$('sheet').addEventListener('close', () => {
  // closing the wake-up question without an answer: ask again after a short pause
  if (sheetState?.mode === 'wake' && session) { session.snooze = Math.max(session.snooze || 0, Date.now() + 5 * 6e4); saveSession(); }
});
$('sheet-still').addEventListener('click', () => { if (session) { session.snooze = Date.now() + SNOOZE_MINUTES * 6e4; saveSession(); } sheetState = null; $('sheet').close(); toast('계속 기록할게요. 다시 주무세요.'); });
$('sheet-discard').addEventListener('click', () => { if (confirm('이번 수면 기록을 취소할까요? 잠자러 간 시각이 지워져요.')) { sheetState = null; $('sheet').close(); endSession('수면 기록을 취소했어요.'); } });
$('sheet-delete').addEventListener('click', () => {
  if (!sheetState?.id || !confirm('이 수면 기록을 지울까요?')) return;
  const next = clone(); next.records = next.records.filter(r => r.id !== sheetState.id);
  $('sheet').close(); commit(next); toast('기록을 지웠어요.');
});
$('add-record').addEventListener('click', () => openSheet('add'));
$('record-list').addEventListener('click', e => { const b = e.target.closest('[data-edit]'); if (b) openSheet('edit', {id: b.dataset.edit}); });
$('more-records').addEventListener('click', () => { recordLimit += 30; renderRecords(); });

$('analysis-refresh').addEventListener('click', () => refreshAnalysis(true));
$('obs-buttons').innerHTML = KSS.map(([v, label]) => `<button type="button" class="kss" data-obs="${v}" aria-label="지금 졸림 ${v}(${label}) 기록하기"><b>${v}</b><small>${label}</small></button>`).join('');
$('obs-buttons').addEventListener('click', e => { const b = e.target.closest('[data-obs]'); if (b) addObservation(Number(b.dataset.obs)); });
$('research-results').closest('details').addEventListener('toggle', e => { if (e.target.open) refreshResearch(); });
$('observations-list').addEventListener('click', e => {
  const b = e.target.closest('[data-delete-ob]');
  if (!b || !confirm('이 졸림 기록을 지울까요?')) return;
  const next = clone(); next.observations = next.observations.filter(o => o.id !== b.dataset.deleteOb); commit(next, 'observations');
  renderObsLast(); refreshResearch(); toast('졸림 기록을 지웠어요.');
});
$('export-research').addEventListener('click', () => {
  const r = researchCache?.result;
  if (!r || !r.rows.length) { toast('아직 내보낼 비교 결과가 없어요. 수업 중에 ‘지금 얼마나 졸린가요?’를 눌러 두면 생겨요.'); return; }
  download(`rhythm-comparison-${demo() ? 'DEMO-' : ''}${stamp()}.csv`, csv(r.rows.map(x => ({...x, data_kind: data.data_kind})), ['data_kind', 'at', 'sleepiness', 'A', 'B', 'C', 'history_days']), 'text/csv;charset=utf-8', '비교 결과 CSV를');
});
$('basis-result').addEventListener('click', e => {
  if (!e.target.closest('#export-result') || !saved) return;
  download(`rhythm-model-${demo() ? 'DEMO-' : ''}${stamp()}.csv`, csv(saved.result.chart.map(r => ({...r, data_kind: data.data_kind, model_version: saved.result.model_version})), ['data_kind', 'model_version', 'at', 'S', 'C', 'AL', 'baseline_AL', 'asleep', 'target']), 'text/csv;charset=utf-8', '계산 결과 CSV를');
});

$('age-group').addEventListener('change', ageGuidance);
for (const id of ['age-group', 'schedule', 'timezone']) for (const type of ['input', 'change']) $(id).addEventListener(type, profileDirty);
$('save-profile').addEventListener('click', saveProfile);
$('timetable-rows').addEventListener('input', () => {
  ttDraft = timetableInputs();
  for (const el of $('timetable-rows').querySelectorAll('input')) {
    el.classList.toggle('changed', prefs.timetable.find(s => s.id === el.dataset.tt)?.[el.dataset.edge] !== el.value);
  }
  showError('timetable-error', ''); timetableDirty();
});
$('add-period').addEventListener('click', () => {
  const before = timetableInputs(), next = addPeriod(before), n = next.length - 1;
  if (next.length === before.length) { toast(`${MAX_PERIODS}교시까지 추가할 수 있어요.`); return; }
  editTimetable(next, `${n}교시를 추가했어요${before.at(-1).start !== next.at(-1).start ? '(방과후는 그 뒤로 옮겼어요)' : ''}. 시각을 확인하고`);
  $('timetable-rows').querySelector(`[data-tt="p${n}"]`)?.scrollIntoView({block: 'nearest'});
});
$('remove-period').addEventListener('click', () => {
  const before = timetableInputs(), next = removePeriod(before);
  if (next.length === before.length) return;
  editTimetable(next, `${before.length - 1}교시를 뺐어요.`);
});
$('reset-timetable').addEventListener('click', () => editTimetable(defaultTimetable(timetableInputs().length - 1), '기본 시각으로 바꿨어요.'));
$('save-timetable').addEventListener('click', saveTimetable);
$('export-json').addEventListener('click', () => download(`rhythm-backup-${demo() ? 'DEMO-' : ''}${stamp()}.json`, JSON.stringify(serverData(), null, 2), 'application/json', '백업 파일을'));
$('export-csv').addEventListener('click', () => download(`rhythm-sleep-${demo() ? 'DEMO-' : ''}${stamp()}.csv`, csv(data.records.map(r => ({...r, data_kind: data.data_kind, timezone: zone(), hours: ((toMs(r.end, zone()) - toMs(r.start, zone())) / 36e5).toFixed(4)})), ['data_kind', 'id', 'start', 'end', 'timezone', 'kind', 'hours', 'sleepiness_wake', 'light_minutes']), 'text/csv;charset=utf-8', '기록 CSV를'));
$('export-rescue').addEventListener('click', () => { let raw = null; try { raw = localStorage.getItem(RESCUE); } catch { /* unavailable */ } if (raw) download(`rhythm-unreadable-original-${stamp()}.json`, raw, 'application/json', '읽지 못한 원본을'); });
$('import-button').addEventListener('click', () => $('import-file').click());
$('import-file').addEventListener('change', async e => { const file = e.target.files[0]; e.target.value = ''; if (!file) return; try { await importBackup(file); } catch (err) { toast(err.message, 7000); } });
$('clear-data').addEventListener('click', () => {
  if (!confirm(demo() ? '예시 기록을 모두 비울까요? 내 기록은 그대로 있어요.' : '이 기기의 수면·졸림 기록을 모두 지울까요? 필요하면 먼저 백업 파일을 저장하세요.')) return;
  if (!demo()) { try { localStorage.removeItem(RESCUE); } catch { /* unavailable */ } write(RESULT, null); saved = null; }
  const next = clone(); next.records = []; next.observations = []; commit(next); toast('기록을 지웠어요.');
});
$('demo-button').addEventListener('click', () => demo() ? (exitDemo(), navigate('home')) : enterDemo());
$('exit-demo').addEventListener('click', exitDemo);
$('show-intro').addEventListener('click', openIntro);
$('help-button').addEventListener('click', openIntro);
$('intro-close').addEventListener('click', () => $('intro-dialog').close());
$('intro-hide').addEventListener('click', () => {
  try { sessionStorage.setItem(INTRO_HIDDEN, '1'); } catch { /* private mode */ }
  $('intro-dialog').close(); toast('앱을 다시 열 때까지 이 안내는 나오지 않아요. 오른쪽 위 ? 버튼으로 언제든 볼 수 있어요.');
});
window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); installPrompt = e; $('install-button').hidden = false; });
$('install-button').addEventListener('click', async () => { if (installPrompt) { await installPrompt.prompt(); installPrompt = null; $('install-button').hidden = true; } });
window.addEventListener('storage', e => {
  if (![KEY, PREFS, SESSION, RESULT].includes(e.key)) return;
  if (!demo()) loadData();
  loadPrefs(); loadSession(); loadSaved(); analysisCache = researchCache = null;
  if (session) showSleep(); else hideSleep();
  renderAll();
});
window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (currentTab === 'basis' && resultLive()) drawChart(saved.result); if (currentTab === 'analysis' && analysisCache) drawTimeline(analysisCache.result); }, 150); });
setInterval(() => { if (document.visibilityState === 'visible' && currentTab === 'home' && !session) renderHome(); }, 60000);

// ---------- press feedback: every button shrinks while touched and glows briefly once pressed.
// Toggles also keep their own on/off look (aria-pressed, aria-current); a press on an
// unavailable control (aria-disabled) glows red and explains itself.
const FLASH_TIMERS = new WeakMap();
function flash(el, deny = false) {
  if (!el) return;
  const cls = deny ? 'flash-deny' : 'flash';
  el.classList.remove('flash', 'flash-deny');
  void el.offsetWidth;  // restart the animation on a quick second press
  el.classList.add(cls);
  clearTimeout(FLASH_TIMERS.get(el));
  FLASH_TIMERS.set(el, setTimeout(() => el.classList.remove(cls), 700));
}
const KEYED = ['data-period', 'data-latency', 'data-kss', 'data-kind', 'data-obs', 'data-tab', 'data-edit'];
function pressKey(el) {
  if (el.id) return `#${CSS.escape(el.id)}`;
  const a = KEYED.find(k => el.hasAttribute(k));
  return a ? `[${a}="${CSS.escape(el.getAttribute(a))}"]` : null;
}
let pressed = null;
document.addEventListener('click', e => {
  const el = e.target instanceof Element && e.target.closest('button, summary');
  pressed = null;
  if (!el || el.disabled) return;
  const deny = el.getAttribute('aria-disabled') === 'true';
  flash(el, deny);
  pressed = {el, deny, key: pressKey(el)};
}, true);
document.addEventListener('click', () => {
  // runs after the app's own handlers: a control they redrew (chips) lights up again
  if (pressed && !pressed.el.isConnected && pressed.key) flash(document.querySelector(pressed.key), pressed.deny);
  pressed = null;
});
let pressing = null, pressedAt = 0;
document.addEventListener('pointerdown', e => {
  const el = e.target instanceof Element && e.target.closest('button, summary');
  if (!el || el.disabled) return;
  pressing = el; pressedAt = Date.now(); el.classList.add('pressing');
}, {capture: true, passive: true});
function release() {
  const el = pressing; pressing = null;
  if (el) setTimeout(() => el.classList.remove('pressing'), Math.max(0, 120 - (Date.now() - pressedAt)));
}
for (const type of ['pointerup', 'pointercancel', 'dragstart']) document.addEventListener(type, release, {capture: true, passive: true});

// ---------- start
$('latency-chips').innerHTML = LATENCIES.map(([m, label]) => `<button type="button" class="mini-chip" data-latency="${m}" aria-pressed="false">${label}</button>`).join('');
$('sheet-kss').innerHTML = KSS.map(([v, label]) => `<button type="button" class="kss" data-kss="${v}" aria-pressed="false"><b>${v}</b><small>${label}</small></button>`).join('');
const glossary = GLOSSARY.map(([term, text]) => `<dt>${esc(term)}</dt><dd>${esc(text)}</dd>`).join('');
$('intro-glossary').innerHTML = glossary; $('basis-glossary').innerHTML = glossary;
loadData(); loadPrefs(); loadSession(); loadSaved();
try { renderAll(); navigate(location.hash.slice(1) || 'home'); }
catch {
  // Keep the stored copy before falling back, so nothing is lost silently.
  try { const raw = localStorage.getItem(KEY); if (raw && !localStorage.getItem(RESCUE)) localStorage.setItem(RESCUE, raw); } catch { /* storage unavailable */ }
  data = defaultData(); storedUnreadable = true; session = null; renderAll(); navigate('home');
}
const IN_APP = /KAKAOTALK|Instagram|FBAN|FBAV|Line\/|NAVER\(inapp|DaumApps/i.test(navigator.userAgent);
let inAppDismissed = false;
try { inAppDismissed = sessionStorage.getItem('rhythm-inapp-hidden') === '1'; } catch { /* private mode */ }
$('inapp-banner').hidden = !IN_APP || inAppDismissed;
$('inapp-close').addEventListener('click', () => { $('inapp-banner').hidden = true; try { sessionStorage.setItem('rhythm-inapp-hidden', '1'); } catch { /* private mode */ } });
if (session) { showSleep(); maybeAskWake(); }
else if (!introHidden()) openIntro();
if (storedUnreadable) toast('저장된 기록을 읽지 못했어요. 원본은 따로 보관했으니 설정 탭에서 ‘읽지 못한 원본 저장’을 눌러 확인하세요.', 8000);
fetch('/healthz', {cache: 'no-store'}).catch(() => { /* offline: recording still works */ });
if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/sw.js').catch(() => { /* the app works online without it */ });
