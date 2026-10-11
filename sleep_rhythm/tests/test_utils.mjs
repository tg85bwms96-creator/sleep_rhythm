import test from 'node:test';
import assert from 'node:assert/strict';
import {AGE, DEFAULT_TIMETABLE, KSS, MIN_PERIODS, MAX_PERIODS, esc, hoursLabel, minutesLabel, zoneLocal, timeLabel, dayLabel, addDay, localStatus, offsetMinutes,
  localToMs, isoInZone, hhmm, toMs, nextWake, periodTargets, validateTimetable, timetableRows, sameTimetable, upgradeTimetable, addPeriod, removePeriod,
  defaultTimetable, nearestOccurrence, latestBefore, latestAtOrBefore,
  defaultKind, canonicalZone,
  historyStatus, recordProblem, validateImport, datasetProblem, csv, demoData, defaultData, candidateRangeText, chartScale} from '../web/utils.js';

const at = iso => Date.parse(iso);
const SEOUL = 'Asia/Seoul', NY = 'America/New_York';

test('age table matches the server table and the recommended minimums', () => {
  assert.deepEqual(Object.keys(AGE), ['newborn', 'infant', 'toddler', 'preschool', 'school', 'teen', 'adult', 'older', 'senior']);
  assert.deepEqual(AGE.teen, ['만 13–17세', 8, 10, true, 10]);
  assert.deepEqual(AGE.adult, ['만 18–60세', 7, null, true, 9]);
  for (const [label, lo, hi, eligible, searchMax] of Object.values(AGE)) {
    assert.equal(typeof label, 'string');
    assert.ok(searchMax >= lo);
    if (hi != null) assert.equal(searchMax, hi);
    assert.equal(typeof eligible, 'boolean');
  }
});

const slots = t => t.map(p => `${p.label} ${p.start}-${p.end}`);

test('timetable and sleepiness scale', () => {
  assert.deepEqual(slots(DEFAULT_TIMETABLE), ['1교시 08:40-09:30', '2교시 09:40-10:30', '3교시 10:40-11:30', '4교시 12:30-13:20',
    '5교시 13:30-14:20', '6교시 14:30-15:20', '7교시 15:30-16:20', '방과후 16:30-18:00']);
  assert.deepEqual(KSS.map(k => k[0]), [1, 3, 5, 7, 9]);
  assert.deepEqual(validateTimetable(DEFAULT_TIMETABLE), DEFAULT_TIMETABLE);
  const edited = DEFAULT_TIMETABLE.map(p => ({...p}));
  edited[0] = {start: '08:30', end: '09:20', label: 'x', id: 'evil'};
  assert.deepEqual(validateTimetable(edited)[0], {id: 'p1', label: '1교시', start: '08:30', end: '09:20'});
  for (const bad of [[], null, DEFAULT_TIMETABLE.slice(1), DEFAULT_TIMETABLE.map((p, i) => i === 2 ? {...p, end: '10:00'} : p),
    DEFAULT_TIMETABLE.map((p, i) => i === 3 ? {...p, start: '24:00'} : p), DEFAULT_TIMETABLE.map((p, i) => i === 4 ? {...p, start: '9:00'} : p),
    [...defaultTimetable(9).slice(0, 9), {start: '18:30', end: '19:20'}, {start: '19:30', end: '21:00'}], [null, ...DEFAULT_TIMETABLE.slice(1)]]) {
    assert.throws(() => validateTimetable(bad));
  }
  assert.throws(() => validateTimetable(DEFAULT_TIMETABLE.map((p, i) => i === 7 ? {...p, end: '16:00'} : p)), /방과후는 끝나는 시각이/);
});

test('periods can be added up to 9교시 and removed down to 7교시', () => {
  assert.deepEqual([MIN_PERIODS, MAX_PERIODS], [7, 9]);
  const eight = addPeriod(DEFAULT_TIMETABLE);
  assert.deepEqual(slots(eight).slice(6), ['7교시 15:30-16:20', '8교시 16:30-17:20', '방과후 17:30-19:00']);  // 방과후 moves after 8교시
  assert.deepEqual(eight.map(p => p.id), ['p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8', 'after']);
  const nine = addPeriod(eight);
  assert.deepEqual(slots(nine).slice(7), ['8교시 16:30-17:20', '9교시 17:30-18:20', '방과후 18:30-20:00']);
  assert.deepEqual(addPeriod(nine), nine);  // at most 9교시
  assert.deepEqual(validateTimetable(nine), nine);
  assert.ok(sameTimetable(removePeriod(nine), eight));
  assert.ok(sameTimetable(removePeriod(eight), DEFAULT_TIMETABLE));  // 방과후 returns to 16:30
  assert.deepEqual(removePeriod(DEFAULT_TIMETABLE), timetableRows(DEFAULT_TIMETABLE));  // never below 7교시
  assert.ok(sameTimetable(defaultTimetable(8), eight) && sameTimetable(defaultTimetable(), DEFAULT_TIMETABLE));
  // the new period copies the length of the last period and the break before it
  const custom = DEFAULT_TIMETABLE.map((p, i) => i === 5 ? {...p, end: '15:15'} : i === 6 ? {...p, start: '15:25', end: '16:10'} : p);
  assert.deepEqual(slots(addPeriod(custom)).slice(7), ['8교시 16:20-17:05', '방과후 17:25-18:55']);  // keeps its 20-minute gap
  // a 방과후 that does not overlap stays where it is, and a far-away one does not move back
  const late = DEFAULT_TIMETABLE.map((p, i) => i === 7 ? {...p, start: '18:30', end: '20:00'} : p);
  assert.deepEqual(slots(addPeriod(late)).at(-1), '방과후 18:30-20:00');
  assert.deepEqual(slots(removePeriod(addPeriod(late))).at(-1), '방과후 18:30-20:00');
  // unfinished inputs never crash the buttons
  const blank = DEFAULT_TIMETABLE.map((p, i) => i === 6 ? {...p, start: '', end: ''} : p);
  assert.equal(addPeriod(blank).length, 9);
  assert.equal(addPeriod([]).length, 0);
});

test('a saved copy of the old default timetable becomes the new default', () => {
  const old = ['09:00-09:50', '10:00-10:50', '11:00-11:50', '12:00-12:50', '13:50-14:40', '14:50-15:40', '15:50-16:40', '16:50-18:20']
    .map((s, i) => ({id: i < 7 ? `p${i + 1}` : 'after', start: s.slice(0, 5), end: s.slice(6)}));
  assert.deepEqual(upgradeTimetable(old), DEFAULT_TIMETABLE);
  const mine = old.map((r, i) => i === 0 ? {...r, start: '08:50'} : r);
  assert.equal(upgradeTimetable(mine), mine);  // anything the user changed is kept
  assert.equal(upgradeTimetable(null), null);
});

test('time zone names are canonical IANA names the server can load', () => {
  assert.equal(canonicalZone('asia/seoul'), 'Asia/Seoul');
  assert.equal(canonicalZone(' Asia/Seoul '), 'Asia/Seoul');
  assert.equal(canonicalZone('America/New_York'), 'America/New_York');
  assert.equal(canonicalZone('UTC'), 'UTC');
  for (const bad of ['+09', '+09:00', 'Mars/Base', '', null, 'Seoul']) assert.equal(canonicalZone(bad), null, String(bad));
});

test('untrusted labels are escaped', () => assert.equal(esc('<img onerror="x">\''), '&lt;img onerror=&quot;x&quot;&gt;&#39;'));

test('date arithmetic and labels', () => {
  assert.equal(addDay('2024-03-01', -1), '2024-02-29');
  assert.equal(addDay('2026-12-31', 1), '2027-01-01');
  assert.equal(dayLabel('2026-10-11'), '10/11(일)');
  assert.equal(dayLabel('2026-01-05'), '1/5(월)');
});

test('time zone conversion does not depend on the system zone', () => {
  assert.equal(zoneLocal('2026-10-10T00:00:00Z', SEOUL), '2026-10-10T09:00');
  assert.equal(zoneLocal('2026-07-01T12:00:00Z', NY), '2026-07-01T08:00');
  assert.equal(timeLabel('2026-10-10T00:00:00Z', SEOUL), '09:00');
  assert.equal(timeLabel(at('2026-10-10T00:00:00Z'), SEOUL, true), '10/10 09:00');
  assert.equal(timeLabel(null), '—');
  assert.equal(timeLabel(NaN), '—');
  assert.equal(timeLabel('not a date'), '—');
  assert.equal(hhmm(at('2026-10-10T14:05:59Z'), SEOUL), '23:05');
});

test('duration labels round once and handle missing values', () => {
  assert.equal(hoursLabel(7.99999), '8시간');
  assert.equal(hoursLabel(8.25), '8시간 15분');
  assert.equal(hoursLabel(null), '—');
  assert.equal(minutesLabel(45), '45분');
  assert.equal(minutesLabel(95), '1시간 35분');
  assert.equal(minutesLabel(undefined), '—');
});

test('offsets, local times and ISO strings across daylight saving', () => {
  assert.equal(offsetMinutes(at('2026-10-10T00:00Z'), SEOUL), 540);
  assert.equal(offsetMinutes(at('2026-07-01T00:00Z'), NY), -240);
  assert.equal(offsetMinutes(at('2026-07-01T00:00Z'), 'Asia/Kolkata'), 330);
  assert.equal(isoInZone(at('2026-10-10T14:05:42Z'), SEOUL), '2026-10-10T23:05+09:00');
  assert.equal(isoInZone(at('2026-01-10T14:05Z'), NY), '2026-01-10T09:05-05:00');
  assert.equal(isoInZone(at('2026-10-10T14:05Z'), 'Asia/Kolkata'), '2026-10-10T19:35+05:30');
  assert.equal(isoInZone(at('2026-10-10T14:05Z'), 'Pacific/Chatham'), '2026-10-11T03:50+13:45');
  assert.equal(localToMs('2026-10-10T23:00', SEOUL), at('2026-10-10T14:00Z'));
  assert.equal(localToMs('2026-03-08T02:30', NY), at('2026-03-08T07:30Z'));          // skipped hour -> 03:30 EDT
  assert.equal(localToMs('2026-11-01T01:30', NY), at('2026-11-01T05:30Z'));          // repeated hour -> the earlier one
  assert.equal(localStatus('2026-10-10T23:00', SEOUL), 'ok');
  assert.equal(localStatus('2026-03-08T02:30', NY), 'gap');
  assert.equal(localStatus('2026-11-01T01:30', NY), 'ambiguous');
  for (let h = 0; h < 48; h++) {  // ISO strings round-trip through the strict parser
    const ms = at('2026-03-07T12:00Z') + h * 36e5;
    assert.equal(toMs(isoInZone(ms, NY), NY), ms);
  }
});

test('strict time parser matches the server rules', () => {
  assert.equal(toMs('2026-10-10T07:00+09:00', SEOUL), at('2026-10-09T22:00Z'));
  assert.equal(toMs('2026-10-10T07:00:00+09:00', SEOUL), at('2026-10-09T22:00Z'));
  assert.equal(toMs('2026-10-10T07:00Z', SEOUL), at('2026-10-10T07:00Z'));
  assert.equal(toMs('2026-10-10T07:00', SEOUL), at('2026-10-09T22:00Z'));
  for (const bad of ['2026-02-30T07:00+09:00', '2026-10-10T24:00+09:00', '2026-10-10T07:00:15+09:00', '2026-10-10 07:00', '07:00',
    '1999-12-31T23:00Z', '2101-01-01T00:00Z', '2026-10-10T07:00+24:00', '2026-03-08T02:30', '2026-11-01T01:30', null, 5]) {
    assert.ok(Number.isNaN(toMs(bad, bad === '2026-03-08T02:30' || bad === '2026-11-01T01:30' ? NY : SEOUL)), String(bad));
  }
});

test('next wake-up: tonight, after midnight and early morning', () => {
  const kst = s => at(`${s}+09:00`);
  assert.deepEqual(nextWake(kst('2026-10-10T21:00'), SEOUL, '07:00'), {ms: kst('2026-10-11T07:00'), day: '2026-10-11'});
  assert.equal(nextWake(kst('2026-10-11T00:30'), SEOUL, '07:00').day, '2026-10-11');   // still tonight's sleep
  assert.equal(nextWake(kst('2026-10-11T05:30'), SEOUL, '07:00').day, '2026-10-12');   // under 2 h: plan the next night
  assert.equal(nextWake(kst('2026-10-11T13:00'), SEOUL, '07:00').day, '2026-10-12');
  assert.equal(nextWake(at('2026-03-07T20:00-05:00'), NY, '07:00').ms, at('2026-03-08T07:00-04:00'));
});

test('selected periods become target blocks on the wake-up day', () => {
  const wake = at('2026-10-11T07:00+09:00');
  const r = periodTargets(wake, SEOUL, DEFAULT_TIMETABLE, ['p5', 'p1', 'after']);
  assert.deepEqual(r.targets, [['2026-10-11T08:40+09:00', '2026-10-11T09:30+09:00'], ['2026-10-11T13:30+09:00', '2026-10-11T14:20+09:00'], ['2026-10-11T16:30+09:00', '2026-10-11T18:00+09:00']]);
  assert.deepEqual(r.skipped, []);
  const late = periodTargets(at('2026-10-11T09:45+09:00'), SEOUL, DEFAULT_TIMETABLE, ['p1', 'p2', 'p3']);
  assert.deepEqual(late.skipped, ['p1', 'p2']);
  assert.deepEqual(late.targets, [['2026-10-11T10:40+09:00', '2026-10-11T11:30+09:00']]);
  assert.deepEqual(periodTargets(wake, SEOUL, DEFAULT_TIMETABLE, []).targets, []);
  assert.deepEqual(periodTargets(wake, SEOUL, defaultTimetable(8), ['p8']).targets, [['2026-10-11T16:30+09:00', '2026-10-11T17:20+09:00']]);
});

test('clock times typed in the record sheet resolve to the intended instants', () => {
  const kst = s => at(`${s}+09:00`);
  assert.equal(nearestOccurrence('07:05', kst('2026-10-11T07:02'), SEOUL), kst('2026-10-11T07:05'));
  assert.equal(nearestOccurrence('23:50', kst('2026-10-11T00:10'), SEOUL), kst('2026-10-10T23:50'));
  assert.equal(latestBefore('23:19', kst('2026-10-11T07:02'), SEOUL), kst('2026-10-10T23:19'));
  assert.equal(latestBefore('01:30', kst('2026-10-11T07:02'), SEOUL), kst('2026-10-11T01:30'));
  assert.equal(latestBefore('13:00', kst('2026-10-11T15:00'), SEOUL), kst('2026-10-11T13:00'));
  assert.equal(latestAtOrBefore('07:00', kst('2026-10-11T19:30'), SEOUL), kst('2026-10-11T07:00'));  // opened in the evening
  assert.equal(latestAtOrBefore('07:40', kst('2026-10-11T07:17'), SEOUL), kst('2026-10-10T07:40'));  // a future time falls back a day
  assert.equal(latestAtOrBefore('07:17', kst('2026-10-11T07:17'), SEOUL), kst('2026-10-11T07:17'));
  assert.equal(defaultKind(179), 'nap');
  assert.equal(defaultKind(180), 'main');
});

function nights(n, lastWake = '2026-10-10', bed = '23:00', wake = '07:00') {
  return Array.from({length: n}, (_, i) => {
    const day = addDay(lastWake, i - n + 1);
    return {id: `n${i}`, start: `${addDay(day, -1)}T${bed}+09:00`, end: `${day}T${wake}+09:00`, kind: 'main', sleepiness_wake: null, light_minutes: null};
  });
}

test('history status mirrors the server continuity rules', () => {
  const now = at('2026-10-10T12:00+09:00');
  let h = historyStatus(nights(14), SEOUL, now);
  assert.deepEqual([h.days, h.mean, h.stale, h.duplicate, h.last.hours], [14, 8, false, false, 8]);
  h = historyStatus(nights(20), SEOUL, now);
  assert.equal(h.days, 14);                          // at most 14 nights
  const gap = nights(10); gap.splice(6, 1);          // a missing night ends the block
  assert.equal(historyStatus(gap, SEOUL, now).days, 3);
  assert.equal(historyStatus(gap, SEOUL, now).missing, '2026-10-07');  // the night to add back
  assert.equal(historyStatus(nights(3), SEOUL, now).missing, null);    // nothing older: no gap to fill
  const dup = [...nights(6), {id: 'x', start: '2026-10-10T08:00+09:00', end: '2026-10-10T09:00+09:00', kind: 'main'}];
  h = historyStatus(dup, SEOUL, now);
  assert.deepEqual([h.days, h.duplicate], [0, true]);
  h = historyStatus(nights(6, '2026-10-08'), SEOUL, now);
  assert.equal(h.stale, true);                       // last main sleep ended more than 36 h ago
  h = historyStatus([...nights(3), {id: 'nap', start: '2026-10-10T10:00+09:00', end: '2026-10-10T10:30+09:00', kind: 'nap'}], SEOUL, now);
  assert.deepEqual([h.days, h.last.hours], [3, 8]);  // naps never count as the main sleep
  h = historyStatus([], SEOUL, now);
  assert.deepEqual([h.days, h.mean, h.last, h.stale], [0, null, null, true]);
  // backups may hold local times without an offset: they are read in the profile's zone, as on the server
  const naive = nights(5).map(r => ({...r, start: r.start.slice(0, 16), end: r.end.slice(0, 16)}));
  h = historyStatus(naive, SEOUL, now);
  assert.deepEqual([h.days, h.mean, h.stale], [5, 8, false]);
  assert.equal(historyStatus(nights(5).map(r => ({...r, end: r.end.slice(0, 16)})), NY, now).days, 4);  // the last 07:00 in New York is still ahead
});

test('record checks: overlap, future, duration and adjacency', () => {
  const now = at('2026-10-10T12:00+09:00'), recs = nights(3);
  const rec = (start, end, extra = {}) => ({id: 'new', start, end, kind: 'main', sleepiness_wake: null, ...extra});
  assert.equal(recordProblem(recs, rec('2026-10-10T07:00+09:00', '2026-10-10T07:40+09:00', {kind: 'nap'}), SEOUL, now), '');
  assert.match(recordProblem(recs, rec('2026-10-10T06:30+09:00', '2026-10-10T07:30+09:00'), SEOUL, now), /겹쳐요/);
  assert.match(recordProblem(recs, rec('2026-10-10T12:00+09:00', '2026-10-10T13:00+09:00'), SEOUL, now), /아직 오지/);
  assert.match(recordProblem(recs, rec('2026-10-10T08:00+09:00', '2026-10-10T08:00+09:00'), SEOUL, now), /늦어야/);
  assert.match(recordProblem(recs, rec('2026-10-06T08:00+09:00', '2026-10-07T05:00+09:00'), SEOUL, now), /20시간/);
  assert.match(recordProblem(recs, rec('2026-10-10T08:00+09:00', '2026-10-10T09:00+09:00', {sleepiness_wake: 4.5}), SEOUL, now), /1~9/);
  assert.equal(recordProblem(recs, {...recs[1], end: '2026-10-09T07:30+09:00'}, SEOUL, now), '');  // editing a record never clashes with itself
  assert.equal(recordProblem(recs, rec('2026-10-10T11:00+09:00', '2026-10-10T12:01+09:00'), SEOUL, now), '');  // 2-minute clock tolerance
});

test('backup import validates shape, then every server rule', () => {
  const now = at('2026-10-10T12:00+09:00');
  assert.equal(validateImport(defaultData()).schema_version, 1);
  for (const v of [null, {}, [], {...defaultData(), schema_version: 2}, {...defaultData(), data_kind: null},
    {...defaultData(), profile: {age_group: '__proto__', timezone: SEOUL}},
    {...defaultData(), profile: {age_group: 'teen', timezone: '<script>'}},
    {...defaultData(), records: 'x'}, {...defaultData(), records: new Array(1501).fill({})}]) {
    assert.throws(() => validateImport(v));
  }
  const legacy = {...defaultData(), extra: 'x', profile: {age_group: 'adult', timezone: 'Europe/London', desired_hours: 8, schedule: 'weird'},
    records: [{id: 'a', start: '2026-10-09T23:00+09:00', end: '2026-10-10T07:00+09:00', kind: 'main', evil: '<b>'}],
    observations: [{id: 'o', at: '2026-10-10T10:00+09:00', sleepiness: 4, more: 1}]};
  const out = validateImport(legacy);
  assert.deepEqual(out.profile, {age_group: 'adult', timezone: 'Europe/London', schedule: 'day'});
  assert.equal('extra' in out, false);
  assert.deepEqual(out.records[0], {id: 'a', start: '2026-10-09T23:00+09:00', end: '2026-10-10T07:00+09:00', kind: 'main', sleepiness_wake: null, light_minutes: null});
  assert.equal(datasetProblem({...defaultData(), records: nights(5)}, now), '');
  const d = {...defaultData(), records: [...nights(5), {...nights(1)[0], id: 'n0'}]};
  assert.match(datasetProblem(d, now), /ID/);
  assert.match(datasetProblem({...defaultData(), records: [...nights(2), {...nights(1)[0], id: 'z'}]}, now), /겹쳐요/);
  assert.match(datasetProblem({...defaultData(), records: [{...nights(1)[0], light_minutes: 500}]}, now), /빛/);
  assert.match(datasetProblem({...defaultData(), observations: [{id: 'o', at: '2026-10-11T10:00+09:00', sleepiness: 4}]}, now), /졸림/);
  assert.match(datasetProblem({...defaultData(), observations: [{id: 'o', at: '2026-10-10T10:00+09:00', sleepiness: 4.5}]}, now), /졸림/);
  assert.match(datasetProblem({...defaultData(), profile: {age_group: 'teen', timezone: 'Mars/Base', schedule: 'day'}}, now), /시간대/);
});

test('large backups are checked quickly (one sorted pass)', () => {
  const now = at('2026-10-10T12:00+09:00');
  const big = {...defaultData(), records: nights(730), observations: []};
  let t = performance.now();
  assert.equal(datasetProblem(big, now), '');
  const elapsed = performance.now() - t;
  assert.ok(elapsed < 1500, `${elapsed} ms`);
  const naive = big.records.map(r => ({...r, start: r.start.slice(0, 16), end: r.end.slice(0, 16)}));
  t = performance.now();
  assert.equal(historyStatus(naive, SEOUL, now).days, 14);
  assert.ok(performance.now() - t < 1500);
});

test('CSV protects against formula injection and keeps quotes', () => {
  const s = csv([{a: '=CMD()', b: '"hello,world"', c: '-1+1', d: '@x', e: 5, f: -0.12345, g: '+3', h: '-2e-3', i: '-'}], ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i']);
  assert.ok(s.startsWith('﻿'));
  assert.ok(s.includes("'=CMD()"));
  assert.ok(s.includes('""hello,world""'));
  assert.ok(s.includes("'-1+1") && s.includes("'@x") && s.includes(`"'-"`));
  assert.ok(s.includes('"5"') && s.includes('"-0.12345"') && s.includes('"+3"') && s.includes('"-2e-3"'));
});

test('demo data: 14 nights and 2 naps, synthetic and never in the future', () => {
  for (let hour = 0; hour < 24; hour++) {
    for (const minute of ['00', '05', '59']) {
      const now = new Date(`2026-10-10T${String(hour).padStart(2, '0')}:${minute}:00Z`);
      const d = demoData(now);
      assert.equal(d.data_kind, 'demo');
      const mains = d.records.filter(r => r.kind === 'main'), naps = d.records.filter(r => r.kind === 'nap');
      assert.deepEqual([mains.length, naps.length], [14, 2]);
      assert.equal(new Set(d.records.map(r => r.id)).size, 16);
      assert.ok(d.records.every(r => new Date(r.end) <= now && new Date(r.start) < new Date(r.end)));
      assert.ok(d.observations.every(r => new Date(r.at) <= now));
      assert.equal(datasetProblem(d, now.getTime()), '');  // the server accepts it
      const wakeDays = mains.map(r => zoneLocal(r.end, SEOUL).slice(0, 10));
      for (let i = 1; i < 14; i++) assert.equal(addDay(wakeDays[i - 1], 1), wakeDays[i]);
      assert.equal(historyStatus(d.records, SEOUL, now.getTime()).days, 14);
    }
  }
});

test('demo does not alter the personal default', () => {
  const p = defaultData();
  demoData();
  assert.equal(p.records.length, 0);
  assert.equal(p.data_kind, 'personal');
});

test('candidate range collapses a single point', () => {
  assert.equal(candidateRangeText({window: {start: '2026-10-10T22:30+09:00', end: '2026-10-10T22:30+09:00'}}, SEOUL), '22:30');
  assert.equal(candidateRangeText({window: {start: '2026-10-10T22:00+09:00', end: '2026-10-10T22:30+09:00'}}, SEOUL), '22:00–22:30');
  assert.equal(candidateRangeText({}, SEOUL), '—');
});

test('chart axis: exact tick values that cover every plotted value', () => {
  assert.deepEqual(chartScale([{S: .2, C: .9, AL: .7, baseline_AL: null}]), {lo: 0, hi: 1, step: .25, ticks: [0, .25, .5, .75, 1]});
  assert.deepEqual(chartScale([{S: .8, C: 1.13, AL: -0.3, baseline_AL: -0.6}]), {lo: -1, hi: 1.5, step: .5, ticks: [-1, -0.5, 0, .5, 1, 1.5]});
  assert.deepEqual(chartScale([{S: NaN, C: undefined, AL: null, baseline_AL: null}]).ticks, [0, .25, .5, .75, 1]);
  const {ticks} = chartScale([{S: .62, C: 1.4, AL: -0.12, baseline_AL: -0.31}]);
  assert.ok(ticks.includes(0) && ticks[0] <= -0.31 && ticks.at(-1) >= 1.4);
  assert.ok(ticks.every(v => Object.is(v, -0) === false));
});
