// Pure helpers shared by the app and the Node tests (no DOM access here).

// key: [label, minimum h, published maximum h (null = "or more"), model recommendation, search maximum h]
export const AGE = {
  newborn: ['만 0–3개월', 14, 17, false, 17], infant: ['만 4–11개월', 12, 16, false, 16],
  toddler: ['만 1–2세', 11, 14, false, 14], preschool: ['만 3–5세', 10, 13, false, 13],
  school: ['만 6–12세', 9, 12, true, 12], teen: ['만 13–17세', 8, 10, true, 10],
  adult: ['만 18–60세', 7, null, true, 9], older: ['만 61–64세', 7, 9, true, 9],
  senior: ['만 65세 이상', 7, 8, true, 8]
};

// Default school periods (editable in Settings, where 8·9교시 can be added before
// 방과후). The wake-up day's selected periods are the activity the bedtime is planned for.
export const DEFAULT_TIMETABLE = [
  {id: 'p1', label: '1교시', start: '08:40', end: '09:30'},
  {id: 'p2', label: '2교시', start: '09:40', end: '10:30'},
  {id: 'p3', label: '3교시', start: '10:40', end: '11:30'},
  {id: 'p4', label: '4교시', start: '12:30', end: '13:20'},
  {id: 'p5', label: '5교시', start: '13:30', end: '14:20'},
  {id: 'p6', label: '6교시', start: '14:30', end: '15:20'},
  {id: 'p7', label: '7교시', start: '15:30', end: '16:20'},
  {id: 'after', label: '방과후', start: '16:30', end: '18:00'}
];
export const MIN_PERIODS = 7, MAX_PERIODS = 9;
// The v2.1 default: a saved copy of it is replaced by the current default when loaded.
const V21_DEFAULT = ['09:00-09:50', '10:00-10:50', '11:00-11:50', '12:00-12:50', '13:50-14:40', '14:50-15:40', '15:50-16:40', '16:50-18:20'];

// Sleepiness 1~9 anchors used as one-tap buttons.
export const KSS = [[1, '매우 또렷'], [3, '또렷'], [5, '보통'], [7, '졸림'], [9, '매우 졸림']];

export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

export function uid() {
  return globalThis.crypto?.randomUUID?.() || `r${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function defaultData() {
  return {schema_version: 1, data_kind: 'personal', profile: {age_group: 'teen', timezone: 'Asia/Seoul', schedule: 'day'}, records: [], observations: []};
}

export function hoursLabel(h) {
  if (h == null || !Number.isFinite(Number(h))) return '—';
  const minutes = Math.round(Number(h) * 60);
  return `${Math.floor(minutes / 60)}시간${minutes % 60 ? ` ${minutes % 60}분` : ''}`;
}

export function minutesLabel(m) {
  if (m == null || !Number.isFinite(Number(m))) return '—';
  const v = Math.round(Number(m));
  return v >= 60 ? hoursLabel(v / 60) : `${v}분`;
}

const FORMATTERS = new Map();  // building an Intl formatter is slow; one per zone is enough
export function zoneLocal(value, zone = 'Asia/Seoul') {
  let f = FORMATTERS.get(zone);
  if (!f) {
    f = new Intl.DateTimeFormat('en-CA', {timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'});
    FORMATTERS.set(zone, f);
  }
  const d = Object.fromEntries(f.formatToParts(new Date(value)).map(p => [p.type, p.value]));
  return `${d.year}-${d.month}-${d.day}T${d.hour}:${d.minute}`;
}

// The browser's canonical IANA name for a time zone the user typed ('asia/seoul' ->
// 'Asia/Seoul'), or null for names the server cannot load (offsets such as '+09').
export function canonicalZone(name) {
  if (typeof name !== 'string' || !name.trim()) return null;
  try {
    const zone = new Intl.DateTimeFormat('en-US', {timeZone: name.trim()}).resolvedOptions().timeZone;
    return /^(UTC|[A-Za-z]+(\/[A-Za-z0-9_+\-]+)+)$/.test(zone) && zone.length <= 80 ? zone : null;
  } catch { return null; }
}

export function timeLabel(value, zone = 'Asia/Seoul', date = false) {
  if (!value && value !== 0) return '—';
  try {
    const s = zoneLocal(value, zone);
    return date ? `${s.slice(5, 10).replace('-', '/')} ${s.slice(11)}` : s.slice(11);
  } catch { return '—'; }
}

const WEEKDAYS = '일월화수목금토';
// "10/11(일)" for a local date "YYYY-MM-DD".
export function dayLabel(day) {
  const d = new Date(`${day}T12:00:00Z`);
  return `${Number(day.slice(5, 7))}/${Number(day.slice(8, 10))}(${WEEKDAYS[d.getUTCDay()]})`;
}

export function addDay(day, delta) {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

// UTC offset of `zone` (minutes east of UTC) at instant `ms`.
export function offsetMinutes(ms, zone) {
  return Math.round((Date.parse(`${zoneLocal(ms, zone)}:00Z`) - Math.floor(ms / 6e4) * 6e4) / 6e4);
}

// 'ok', 'gap' (skipped by a daylight-saving change) or 'ambiguous' (occurs twice)
// for a wall-clock "YYYY-MM-DDTHH:MM" in the zone. Uses the UTC offsets one day
// before and after, which bracket any single transition.
export function localStatus(local, zone) {
  const naive = Date.parse(`${local}:00Z`);
  const offsets = [naive - 864e5, naive + 864e5].map(probe => offsetMinutes(probe, zone));
  const valid = [...new Set(offsets)].filter(offset => zoneLocal(naive - offset * 6e4, zone) === local);
  return valid.length === 0 ? 'gap' : valid.length > 1 ? 'ambiguous' : 'ok';
}

// Instant of a local wall-clock time. A time skipped by a daylight-saving change
// moves forward by the gap; a repeated time takes the earlier instant.
export function localToMs(local, zone) {
  const naive = Date.parse(`${local}:00Z`);
  if (!Number.isFinite(naive)) return NaN;
  const offsets = [...new Set([naive - 864e5, naive + 864e5].map(p => offsetMinutes(p, zone)))];
  const hits = offsets.map(o => naive - o * 6e4).filter(ms => zoneLocal(ms, zone) === local).sort((a, b) => a - b);
  return hits.length ? hits[0] : naive - offsetMinutes(naive - 864e5, zone) * 6e4;
}

// "YYYY-MM-DDTHH:MM+09:00" for an instant (seconds dropped), unambiguous for the server.
export function isoInZone(ms, zone) {
  const off = offsetMinutes(ms, zone), a = Math.abs(off);
  return `${zoneLocal(ms, zone)}${off < 0 ? '-' : '+'}${String(Math.floor(a / 60)).padStart(2, '0')}:${String(a % 60).padStart(2, '0')}`;
}

export const hhmm = (ms, zone) => zoneLocal(ms, zone).slice(11);

// Parses a stored time exactly as the server does (sleepapp/model.py parse_time):
// minute precision, optional ":00" seconds, optional offset; a local time without
// an offset must exist exactly once in the zone. Returns NaN when the server would refuse it.
const ISO_RE = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)(?::00)?(Z|[+-]\d\d:\d\d)?$/;
export function toMs(value, zone) {
  const m = typeof value === 'string' ? ISO_RE.exec(value) : null;
  if (!m) return NaN;
  const [y, mo, d, h, mi] = m.slice(1, 6).map(Number);
  const wall = Date.UTC(y, mo - 1, d, h, mi), check = new Date(wall);
  if (y < 2000 || y > 2100 || h > 23 || mi > 59 || check.getUTCMonth() !== mo - 1 || check.getUTCDate() !== d) return NaN;
  if (!m[6]) return localStatus(value.slice(0, 16), zone) === 'ok' ? localToMs(value.slice(0, 16), zone) : NaN;
  if (m[6] === 'Z') return wall;
  const oh = Number(m[6].slice(1, 3)), om = Number(m[6].slice(4, 6));
  if (oh > 23 || om > 59) return NaN;
  return wall - (m[6][0] === '-' ? -1 : 1) * (oh * 60 + om) * 6e4;
}

// The coming occurrence of the clock time `time` ("HH:MM") at least `ahead` hours from now:
// at 23:30 an 07:00 wake-up is tonight's, at 06:00 it is tomorrow's.
export function nextWake(nowMs, zone, time, ahead = 2) {
  const today = zoneLocal(nowMs, zone).slice(0, 10);
  for (const day of [today, addDay(today, 1), addDay(today, 2)]) {
    const ms = localToMs(`${day}T${time}`, zone);
    if (ms - nowMs >= ahead * 36e5) return {ms, day: zoneLocal(ms, zone).slice(0, 10)};
  }
  return null;
}

// Selected periods on the wake-up day as [[start, end], ...] ISO pairs; periods that
// start before the wake-up time are skipped (and reported).
export function periodTargets(wakeMs, zone, timetable, selected) {
  const day = zoneLocal(wakeMs, zone).slice(0, 10), blocks = [], skipped = [];
  for (const p of timetable) {
    if (!selected.includes(p.id)) continue;
    const a = localToMs(`${day}T${p.start}`, zone), b = localToMs(`${day}T${p.end}`, zone);
    if (!(a < b) || a < wakeMs) skipped.push(p.id); else blocks.push([a, b]);
  }
  blocks.sort((x, y) => x[0] - y[0]);
  return {targets: blocks.map(([a, b]) => [isoInZone(a, zone), isoInZone(b, zone)]), skipped};
}

const CLOCK = /^([01]\d|2[0-3]):[0-5]\d$/;
const LAST_MINUTE = 23 * 60 + 59;
const minutesOf = t => CLOCK.test(t) ? Number(t.slice(0, 2)) * 60 + Number(t.slice(3)) : NaN;
const clockOf = m => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;

// Rows in order 1..n교시 then 방과후 get their ids and labels from their position (times unchecked).
export function timetableRows(rows) {
  const n = rows.length - 1;
  return rows.map((r, i) => ({...(i < n ? {id: `p${i + 1}`, label: `${i + 1}교시`} : {id: 'after', label: '방과후'}),
    start: r?.start ?? '', end: r?.end ?? ''}));
}

// Cleans an edited timetable (7~9 periods + 방과후); throws a user-facing message when a row is invalid.
export function validateTimetable(rows) {
  const n = Array.isArray(rows) ? rows.length - 1 : -1;
  if (n < MIN_PERIODS || n > MAX_PERIODS) throw new Error('시간표 형식이 올바르지 않아요.');
  return timetableRows(rows).map(r => {
    if (!CLOCK.test(r.start) || !CLOCK.test(r.end)) throw new Error(`${r.label}의 시각을 확인해 주세요.`);
    if (!(r.start < r.end)) throw new Error(`${r.label}는 끝나는 시각이 시작보다 늦어야 해요.`);
    return r;
  });
}

export const sameTimetable = (a, b) => a.length === b.length && a.every((r, i) => r.start === b[i].start && r.end === b[i].end);

// A saved timetable that is exactly the v2.1 default becomes the current default.
export function upgradeTimetable(rows) {
  const old = Array.isArray(rows) && rows.length === V21_DEFAULT.length && rows.every((r, i) => `${r?.start}-${r?.end}` === V21_DEFAULT[i]);
  return old ? DEFAULT_TIMETABLE.map(p => ({...p})) : rows;
}

// The next period goes before 방과후 with the length of the last period and the break
// before it; 방과후 moves after it (same break and length) when the two would overlap.
export function addPeriod(rows) {
  const t = timetableRows(rows), n = t.length - 1;
  if (n < MIN_PERIODS || n >= MAX_PERIODS) return t;
  const last = t[n - 1], after = t[n];
  const lastStart = minutesOf(last.start), lastEnd = minutesOf(last.end), prevEnd = minutesOf(t[n - 2].end);
  const length = lastEnd - lastStart >= 10 && lastEnd - lastStart <= 120 ? lastEnd - lastStart : 50;
  const pause = lastStart - prevEnd >= 0 && lastStart - prevEnd <= 30 ? lastStart - prevEnd : 10;
  const start = Math.min(Number.isFinite(lastEnd) ? lastEnd + pause : 16 * 60 + 30, LAST_MINUTE - 10);
  const end = Math.min(start + length, LAST_MINUTE);
  let next = after;
  const aStart = minutesOf(after.start), aEnd = minutesOf(after.end);
  if (aStart < end) {
    const gap = aStart - lastEnd >= 0 && aStart - lastEnd <= 60 ? aStart - lastEnd : 10;
    const s = Math.min(end + gap, LAST_MINUTE - 1);
    next = {start: clockOf(s), end: clockOf(Math.min(s + (aEnd > aStart ? aEnd - aStart : 90), LAST_MINUTE))};
  }
  return timetableRows([...t.slice(0, n), {start: clockOf(start), end: clockOf(end)}, next]);
}

// Removes the last period (never below 7교시). 방과후 that started within 30 minutes
// after it moves up to follow the new last period with the same break and length.
export function removePeriod(rows) {
  const t = timetableRows(rows), n = t.length - 1;
  if (n <= MIN_PERIODS) return t;
  const removed = t[n - 1], after = t[n], keepEnd = minutesOf(t[n - 2].end);
  const gap = minutesOf(after.start) - minutesOf(removed.end), length = minutesOf(after.end) - minutesOf(after.start);
  let next = after;
  if (gap >= 0 && gap <= 30 && length > 0 && Number.isFinite(keepEnd)) {
    const s = Math.min(keepEnd + gap, LAST_MINUTE - 1);
    next = {start: clockOf(s), end: clockOf(Math.min(s + length, LAST_MINUTE))};
  }
  return timetableRows([...t.slice(0, n - 1), next]);
}

// The default times for a timetable with `periods` periods (7~9).
export function defaultTimetable(periods = MIN_PERIODS) {
  let t = DEFAULT_TIMETABLE.map(p => ({...p}));
  while (t.length - 1 < Math.min(periods, MAX_PERIODS)) t = addPeriod(t);
  return t;
}

// Clock time `time` nearest to the instant `refMs` (yesterday, today or tomorrow).
export function nearestOccurrence(time, refMs, zone) {
  const day = zoneLocal(refMs, zone).slice(0, 10);
  let best = NaN;
  for (const d of [addDay(day, -1), day, addDay(day, 1)]) {
    const ms = localToMs(`${d}T${time}`, zone);
    if (!Number.isFinite(best) || Math.abs(ms - refMs) < Math.abs(best - refMs)) best = ms;
  }
  return best;
}

// Latest occurrence of the clock time `time` strictly before `endMs` (within a day).
export function latestBefore(time, endMs, zone) {
  const day = zoneLocal(endMs, zone).slice(0, 10);
  const found = [addDay(day, -1), day].map(d => localToMs(`${d}T${time}`, zone)).filter(ms => ms < endMs);
  return found.length ? Math.max(...found) : NaN;
}
export const latestAtOrBefore = (time, refMs, zone) => latestBefore(time, refMs + 1, zone);

// A sleep of 3 hours or more is offered as the main sleep, a shorter one as a nap.
export const defaultKind = minutes => minutes >= 180 ? 'main' : 'nap';

// Mirrors recent_history() in sleepapp/model.py: one main sleep per wake date,
// consecutive dates ending at the latest one (at most 14); a missing or duplicated
// date ends the block. `stale`: the last main sleep ended more than 36 h ago.
export function historyStatus(records, zone, nowMs) {
  const span = r => (toMs(r.end, zone) - toMs(r.start, zone)) / 36e5;
  const byDay = new Map();
  for (const r of records) {
    const end = toMs(r.end, zone);
    if (r.kind !== 'main' || !Number.isFinite(end) || end > nowMs || end < nowMs - 22 * 864e5) continue;
    const day = zoneLocal(end, zone).slice(0, 10);
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(r);
  }
  const chosen = [];
  let duplicate = false, missing = null;
  if (byDay.size) {
    const days = [...byDay.keys()].sort();
    let day = days.at(-1);
    for (let i = 0; i < 14; i++) {
      const items = byDay.get(day) || [];
      if (items.length !== 1) {
        duplicate = items.length > 1;
        if (!items.length && days[0] < day) missing = day;  // older nights exist: this gap breaks the streak
        break;
      }
      chosen.push(items[0]);
      day = addDay(day, -1);
    }
  }
  chosen.reverse();
  const mains = records.filter(r => r.kind === 'main' && toMs(r.end, zone) <= nowMs).sort((a, b) => toMs(a.end, zone) - toMs(b.end, zone));
  const last = mains.at(-1) || null;
  return {
    days: chosen.length, duplicate, missing,
    mean: chosen.length ? chosen.reduce((s, r) => s + span(r), 0) / chosen.length : null,
    last: last && {hours: span(last), start: last.start, end: last.end},
    stale: !chosen.length || nowMs - toMs(chosen.at(-1).end, zone) > 36 * 36e5
  };
}

// The checks of sleepapp/model.py parse_records for one new or edited record, so
// records saved offline are accepted by the server later. Returns '' or a message.
export function recordProblem(records, rec, zone, nowMs) {
  const s = toMs(rec.start, zone), e = toMs(rec.end, zone);
  if (!Number.isFinite(s) || !Number.isFinite(e)) return '시각을 확인해 주세요.';
  const minutes = (e - s) / 6e4;
  if (minutes < 1) return '일어난 시각이 잠든 시각보다 늦어야 해요.';
  if (minutes > 1200) return '한 번의 수면은 20시간 이하로 기록해 주세요. 날짜와 시각을 확인해 주세요.';
  if (e > nowMs + 2 * 6e4) return '아직 오지 않은 시각에는 일어날 수 없어요. 시각을 확인해 주세요.';
  if (rec.kind !== 'main' && rec.kind !== 'nap') return '수면 종류를 골라 주세요.';
  if (rec.sleepiness_wake != null && !(Number.isInteger(rec.sleepiness_wake) && rec.sleepiness_wake >= 1 && rec.sleepiness_wake <= 9)) return '졸림 정도는 1~9 중에서 골라 주세요.';
  const others = records.filter(r => r.id !== rec.id);
  if (others.length >= 1500) return '기록은 최대 1,500개까지 보관할 수 있어요. 오래된 기록을 백업한 뒤 지워 주세요.';
  for (const r of others) {
    const rs = toMs(r.start, zone), re = toMs(r.end, zone);
    if (s < re && rs < e) return `다른 기록(${timeLabel(rs, zone, true)}~${timeLabel(re, zone)})과 시간이 겹쳐요.`;
  }
  const all = [...others.map(r => [toMs(r.start, zone), toMs(r.end, zone)]), [s, e]];
  if (Math.max(...all.map(x => x[1])) - Math.min(...all.map(x => x[0])) >= 731 * 864e5) return '한 기기에는 최대 2년 범위의 기록을 보관할 수 있어요. 오래된 기록을 백업한 뒤 지워 주세요.';
  return '';
}

const ZONE_RE = /^[A-Za-z0-9_+\-/]{1,80}$/;

export function validateImport(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || value.schema_version !== 1) throw new Error('리듬에서 내보낸 버전 1 JSON 파일을 선택하세요.');
  if (!Array.isArray(value.records) || value.records.length > 1500 || !Array.isArray(value.observations) || value.observations.length > 400) throw new Error('기록 개수 또는 형식이 올바르지 않습니다.');
  const p = value.profile;
  if (!p || typeof p !== 'object' || !Object.hasOwn(AGE, p.age_group)) throw new Error('연령대 설정을 확인하세요.');
  if (typeof p.timezone !== 'string' || !ZONE_RE.test(p.timezone)) throw new Error('시간대 설정을 확인하세요.');
  if (value.data_kind !== 'personal' && value.data_kind !== 'demo') throw new Error('실제 기록·모의 기록 구분이 없는 파일입니다.');
  const str = (v, max) => typeof v === 'string' && v.length > 0 && v.length <= max;
  const num = v => v == null || (typeof v === 'number' && Number.isFinite(v));
  if (!value.records.every(r => r && typeof r === 'object' && str(r.id, 80) && str(r.start, 40) && str(r.end, 40) && (r.kind === 'main' || r.kind === 'nap') && num(r.sleepiness_wake) && num(r.light_minutes))
    || !value.observations.every(r => r && typeof r === 'object' && str(r.id, 80) && str(r.at, 40) && typeof r.sleepiness === 'number' && Number.isFinite(r.sleepiness))) throw new Error('기록 형식이 올바르지 않습니다.');
  return {schema_version: 1, data_kind: value.data_kind,
    profile: {age_group: p.age_group, timezone: p.timezone, schedule: p.schedule === 'shift' ? 'shift' : 'day'},
    records: value.records.map(r => ({id: r.id, start: r.start, end: r.end, kind: r.kind, sleepiness_wake: r.sleepiness_wake ?? null, light_minutes: r.light_minutes ?? null})),
    observations: value.observations.map(r => ({id: r.id, at: r.at, sleepiness: r.sleepiness}))};
}

// Every server rule for a whole dataset (records and observations), for imported
// backups and time-zone changes. Overlaps are found in one sorted pass, as on the server.
export function datasetProblem(data, nowMs) {
  const zone = data.profile.timezone;
  try { zoneLocal(nowMs, zone); } catch { return '이 기기에서 쓸 수 없는 시간대예요. 설정에서 시간대를 확인해 주세요.'; }
  const ids = new Set(), spans = [];
  for (const r of data.records) {
    if (ids.has(r.id)) return '같은 ID의 기록이 두 번 들어 있어요.';
    ids.add(r.id);
    const s = toMs(r.start, zone), e = toMs(r.end, zone);
    const where = Number.isFinite(e) ? `${timeLabel(e, zone, true)} 기록: ` : '';
    if (r.light_minutes != null && !(r.light_minutes >= 0 && r.light_minutes <= 120)) return `${where}빛 노출 시간은 0~120분이어야 해요.`;
    const problem = recordProblem([], r, zone, nowMs);
    if (problem) return where + problem;
    spans.push([s, e]);
  }
  spans.sort((a, b) => a[0] - b[0]);
  for (let i = 1; i < spans.length; i++) {
    if (spans[i][0] < spans[i - 1][1]) return `${timeLabel(spans[i][0], zone, true)}에 시작한 기록이 다른 기록과 시간이 겹쳐요.`;
  }
  if (spans.length && Math.max(...spans.map(x => x[1])) - spans[0][0] >= 731 * 864e5) return '한 기기에는 최대 2년 범위의 기록을 보관할 수 있어요.';
  const obIds = new Set();
  for (const o of data.observations) {
    const at = toMs(o.at, zone);
    if (obIds.has(o.id)) return '같은 ID의 졸림 기록이 두 번 들어 있어요.';
    obIds.add(o.id);
    if (!Number.isFinite(at) || at > nowMs + 2 * 6e4 || !Number.isInteger(o.sleepiness) || o.sleepiness < 1 || o.sleepiness > 9) return '졸림 기록의 시각이나 값이 올바르지 않아요.';
  }
  return '';
}

// Spreadsheet-safe CSV: text that could start a formula gets a leading quote,
// while plain numbers (including negative model values) stay numeric.
const PLAIN_NUMBER = /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/;
export function csv(rows, fields) {
  const cell = v => { let s = String(v ?? ''); if (/^[=+\-@\t\r]/.test(s) && !PLAIN_NUMBER.test(s)) s = "'" + s; return '"' + s.replaceAll('"', '""') + '"'; };
  return '﻿' + [fields.map(cell).join(','), ...rows.map(r => fields.map(f => cell(r[f])).join(','))].join('\r\n');
}

export function demoData(now = new Date()) {
  const data = defaultData(); data.data_kind = 'demo';
  // Explicitly synthetic examples, never written into personal storage.
  const local = zoneLocal(now, 'Asia/Seoul'), today = local.slice(0, 10);
  const last = local.slice(11) >= '10:01' ? today : addDay(today, -1);
  const starts = ['23:40', '23:10', '00:15', '23:30', '22:50', '23:50', '00:05', '23:00', '23:20', '22:40', '23:45', '23:15', '23:00', '22:55'];
  const scores = [6, 4, 7, 5, 3, 6, 7, 4, 5, 3, 6, 5, 4, 4];
  for (let i = 0; i < 14; i++) {
    const day = addDay(last, i - 13), t = starts[i];
    const startDay = t < '12:00' ? day : addDay(day, -1);
    data.records.push({id: `demo-s-${i}`, start: `${startDay}T${t}+09:00`, end: `${day}T07:00+09:00`, kind: 'main', sleepiness_wake: scores[i], light_minutes: [45, 30, 90, 60][i % 4]});
    if (i === 4 || i === 9) data.records.push({id: `demo-n-${i}`, start: `${day}T16:10+09:00`, end: `${day}T16:40+09:00`, kind: 'nap', sleepiness_wake: null, light_minutes: null});
    data.observations.push({id: `demo-o-${i}`, at: `${day}T10:00+09:00`, sleepiness: scores[i]});
  }
  return data;
}

export function candidateRangeText(result, zone) {
  if (!result?.window) return '—';
  const a = timeLabel(result.window.start, zone), b = timeLabel(result.window.end, zone);
  return a === b ? a : `${a}–${b}`;
}

// "Nice" y axis covering every plotted value (and 0~1): bounds and ticks are
// exact multiples of the tick step, so every label is an exact value.
export function chartScale(rows) {
  const values = rows.flatMap(r => [r.S, r.C, r.AL, r.baseline_AL]).filter(v => Number.isFinite(v));
  const min = Math.min(0, ...values), max = Math.max(1, ...values);
  const count = s => Math.ceil(max / s - 1e-9) - Math.floor(min / s + 1e-9) + 1;
  const step = count(0.25) > 7 ? 0.5 : 0.25;  // at most 7 labelled lines
  const first = Math.floor(min / step + 1e-9), last = Math.ceil(max / step - 1e-9);
  const ticks = [];
  for (let k = first; k <= last; k++) ticks.push(Math.round(k * step * 100) / 100 || 0);
  return {lo: ticks[0], hi: ticks.at(-1), step, ticks};
}
