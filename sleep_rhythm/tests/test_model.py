import copy
import json
import math
import random
import unittest
from datetime import datetime, timedelta, timezone

from sleepapp.model import (AGE_GROUPS, CALIBRATION_MARGIN_HOURS, SHIFT_LIMIT, Episode, InputError, Model, Scenario,
                            advance, candidate_times, circadian_trough, circular, decide, get_zone, grid_times,
                            habitual_bed_before, necessary_sleep_end, parse_records, parse_targets, parse_time,
                            pressure, pressure_series, profile_data, ranks, recent_history, recommend, research,
                            scan_blocks, scan_target, spearman, summary, threshold, validate_dataset)

UTC = timezone.utc
ZONE = get_zone('Asia/Seoul')
NOW = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)  # 12:00 in Seoul


def sample(days=14):
    """Teen, wake 07:00 daily, 7.5-8 h nights, plan for tomorrow 09:00-10:40."""
    records = []
    for i in range(days):
        end = datetime(2026, 10, 10, 7, 0, tzinfo=ZONE) - timedelta(days=days - 1 - i)
        start = end - timedelta(hours=7.5 + (i % 3) * .25)
        records.append({'id': f's{i}', 'start': start.isoformat(timespec='minutes'),
                        'end': end.isoformat(timespec='minutes'), 'kind': 'main', 'sleepiness_wake': 4, 'light_minutes': 30})
    return {'schema_version': 1, 'data_kind': 'personal',
            'profile': {'age_group': 'teen', 'timezone': 'Asia/Seoul', 'schedule': 'day'},
            'records': records, 'observations': [],
            'plan': {'earliest': '2026-10-10T21:00', 'latest': '2026-10-11T01:00', 'wake': '2026-10-11T07:00',
                     'target_start': '2026-10-11T09:00', 'target_end': '2026-10-11T10:40', 'baseline': '2026-10-10T23:30'}}


def regular(bed, wake, days=14, age='teen'):
    """Same bed/wake clock times every night; no planned bedtime (habitual pattern is the anchor)."""
    bh, bm = map(int, bed.split(':'))
    wh, wm = map(int, wake.split(':'))
    records = []
    for i in range(days):
        end = datetime(2026, 10, 10, wh, wm, tzinfo=ZONE) - timedelta(days=days - 1 - i)
        start = end.replace(hour=bh, minute=bm)
        if start >= end:
            start -= timedelta(days=1)
        records.append({'id': f'r{i}', 'start': start.isoformat(timespec='minutes'),
                        'end': end.isoformat(timespec='minutes'), 'kind': 'main'})
    d = sample()
    d['records'] = records
    d['profile']['age_group'] = age
    d['plan']['baseline'] = None
    return d


def zoned_nights(zone_name, bed, wake, last_wake, days=14):
    """Regular nights on the local clock of ``zone_name`` (DST-aware)."""
    zone = get_zone(zone_name)
    bh, bm = map(int, bed.split(':'))
    wh, wm = map(int, wake.split(':'))
    last = datetime.fromisoformat(last_wake)
    out = []
    for i in range(days):
        day = last - timedelta(days=days - 1 - i)
        end, start = day.replace(hour=wh, minute=wm), day.replace(hour=bh, minute=bm)
        if start >= end:
            start -= timedelta(days=1)
        out.append({'id': f'z{i}', 'kind': 'main', 'start': start.replace(tzinfo=zone).isoformat(timespec='minutes'),
                    'end': end.replace(tzinfo=zone).isoformat(timespec='minutes')})
    return out


def local(iso_text):
    return datetime.fromisoformat(iso_text).strftime('%H:%M')


def hours_from(a, b):
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600


class TimeTests(unittest.TestCase):
    def test_circular_midnight(self):
        value, concentration = circular([23.5, .5])
        self.assertLess(min(abs(value), abs(value - 24)), 1e-9)
        self.assertGreater(concentration, .95)

    def test_trough_halfway_between_mid_sleep_and_wake(self):
        self.assertAlmostEqual(circadian_trough(3.0, 7.0), 5.0)
        self.assertAlmostEqual(circadian_trough(23.0, 3.0), 1.0)
        self.assertIsNone(circadian_trough(None, 7.0))

    def test_nonexistent_dst_rejected(self):
        with self.assertRaisesRegex(InputError, '존재하지'):
            parse_time('2026-03-08T02:30', get_zone('America/New_York'))

    def test_ambiguous_dst_rejected(self):
        with self.assertRaisesRegex(InputError, '두 번'):
            parse_time('2026-11-01T01:30', get_zone('America/New_York'))

    def test_explicit_dst_offsets_distinct(self):
        a = parse_time('2026-11-01T01:30-04:00', get_zone('America/New_York'))
        b = parse_time('2026-11-01T01:30-05:00', get_zone('America/New_York'))
        self.assertEqual((b - a).total_seconds(), 3600)

    def test_bad_dates_and_seconds(self):
        for s in ('2026-02-30T07:00', '2026-10-10T25:00', '07:00', '2026-10-10T07:00:15', 'hello', None, 5):
            with self.subTest(s=s), self.assertRaises(InputError):
                parse_time(s, ZONE)

    def test_quarter_hour_grid_nonround(self):
        a = parse_time('2026-10-10T22:35', ZONE)
        b = parse_time('2026-10-10T23:01', ZONE)
        self.assertEqual([t.astimezone(ZONE).strftime('%H:%M') for t in grid_times(a, b, ZONE)], ['22:45', '23:00'])

    def test_candidates_include_exact_limits(self):
        a, b = parse_time('2026-10-10T22:35', ZONE), parse_time('2026-10-10T23:01', ZONE)
        extra = (parse_time('2026-10-10T22:50', ZONE), parse_time('2026-10-11T03:00', ZONE), None)
        self.assertEqual([t.astimezone(ZONE).strftime('%H:%M') for t in candidate_times(a, b, ZONE, extra)],
                         ['22:35', '22:45', '22:50', '23:00', '23:01'])

    def test_grid_with_seconds_never_before_start(self):
        start = datetime(2026, 10, 10, 13, 15, 30, tzinfo=UTC)
        self.assertGreaterEqual(grid_times(start, start + timedelta(hours=1), ZONE)[0], start)

    def test_elapsed_sleep_across_dst(self):
        r = [{'id': 'dst', 'kind': 'main', 'start': '2026-11-01T00:00-04:00', 'end': '2026-11-01T08:00-05:00'}]
        self.assertEqual(parse_records(r, get_zone('America/New_York'))[0].hours, 9)


class ValidationTests(unittest.TestCase):
    def test_overlapping_sleep_rejected(self):
        d = sample()
        row = copy.deepcopy(d['records'][-1])
        row['id'], row['kind'] = 'overlap', 'nap'
        d['records'].append(row)
        with self.assertRaisesRegex(InputError, '겹치는'):
            validate_dataset(d, NOW)

    def test_adjacent_allowed(self):
        d = sample()
        d['records'].append({'id': 'nap', 'start': d['records'][-1]['end'], 'end': '2026-10-10T07:30+09:00', 'kind': 'nap'})
        self.assertEqual(len(validate_dataset(d, NOW)[2]), 15)

    def test_future_records_rejected(self):
        d = sample()
        d['records'][-1]['end'] = '2026-10-11T07:00'
        with self.assertRaises(InputError):
            validate_dataset(d, NOW)

    def test_duplicate_ids_rejected(self):
        d = sample()
        d['records'][0]['id'] = d['records'][1]['id']
        with self.assertRaises(InputError):
            validate_dataset(d, NOW)

    def test_bad_duration(self):
        for end in ('2026-10-10T00:00', '2026-10-09T00:00', '2026-10-11T05:00'):
            with self.subTest(end=end), self.assertRaises(InputError):
                parse_records([{'id': 'bad', 'start': '2026-10-10T00:00', 'end': end, 'kind': 'main'}], ZONE)

    def test_nonfinite_bool_fractional_scores(self):
        for score in (True, float('nan'), float('inf'), 0, 10, 3.5, '4', 10 ** 400):
            d = sample()
            d['records'][0]['sleepiness_wake'] = score
            with self.subTest(score=score), self.assertRaises(InputError):
                validate_dataset(d, NOW)

    def test_unknown_or_directory_zone_is_input_error(self):
        for name in ('Mars/Olympus', 'America', 'Europe', '../etc', ''):
            with self.subTest(name=name), self.assertRaises(InputError):
                get_zone(name)

    def test_light_is_record_only(self):
        d = sample()
        a = recommend(d, NOW)
        d['records'][0]['light_minutes'] = 120
        self.assertEqual(a['best'], recommend(d, NOW)['best'])

    def test_age_groups_follow_cdc_table(self):
        expected = {'newborn': (14, 17), 'infant': (12, 16), 'toddler': (11, 14), 'preschool': (10, 13),
                    'school': (9, 12), 'teen': (8, 10), 'adult': (7, None), 'older': (7, 9), 'senior': (7, 8)}
        for key, (lo, hi) in expected.items():
            p, _ = profile_data({'age_group': key})
            self.assertEqual((p['minimum'], p['maximum']), (lo, hi))
            self.assertTrue(p['label'].startswith('만 '))
            self.assertEqual(p['eligible'], key in ('school', 'teen', 'adult', 'older', 'senior'))
            self.assertGreaterEqual(p['search_maximum'], lo)
            if hi is not None:
                self.assertEqual(p['search_maximum'], hi)

    def test_legacy_desired_hours_ignored(self):
        for legacy in (8.5, 'x', None, float('nan')):
            p, _ = profile_data({'age_group': 'teen', 'desired_hours': legacy})
            self.assertNotIn('desired_hours', p)


class PhysiologyTests(unittest.TestCase):
    def test_pressure_monotone_and_bounded(self):
        for s in (0, .01, .5, .99, 1):
            for dt in (.01, .25, 8, 24, 1000):
                self.assertTrue(0 <= advance(s, dt, True) <= s)
                self.assertTrue(s <= advance(s, dt, False) <= 1)

    def test_semigroup_exact(self):
        for asleep in (True, False):
            self.assertAlmostEqual(advance(advance(.53, .13, asleep), .37, asleep), advance(.53, .5, asleep))

    def test_fifteen_minute_steps_equal_exact_update(self):
        # The plan's "fixed ratio every 15 minutes" is the same exponential update.
        s = .4
        for _ in range(32):
            s = advance(s, .25, False)
        self.assertAlmostEqual(s, advance(.4, 8, False), places=12)

    def test_nap_reduces_pressure(self):
        records = validate_dataset(sample(), NOW)[2]
        nap = Episode('nap', NOW, NOW + timedelta(hours=.5), 'nap')
        at = NOW + timedelta(hours=2)
        self.assertLess(pressure(at, records + [nap]), pressure(at, records))

    def test_non_grid_episode_exact(self):
        start = parse_time('2026-10-10T00:07', ZONE)
        end = start + timedelta(minutes=23)
        s0 = Model().calibration['onset_pressure']
        self.assertAlmostEqual(pressure(end, [Episode('x', start, end, 'nap')]), s0 * math.exp(-(23 / 60) / 4.2))

    def test_pressure_series_matches_pointwise(self):
        records = validate_dataset(sample(), NOW)[2]
        first = records[0].start
        times = sorted({first + timedelta(minutes=37 * k) for k in range(0, 520)}
                       | {r.end for r in records} | {r.start + timedelta(hours=3) for r in records})
        series = pressure_series(times, records)
        for t, s in zip(times, series):
            # reference: integrate from scratch each time
            ref, cursor = Model().calibration['onset_pressure'], first
            for ep in records:
                if ep.start >= t:
                    break
                if ep.start > cursor:
                    ref = advance(ref, (ep.start - cursor).total_seconds() / 3600, False)
                end = min(ep.end, t)
                ref = advance(ref, (end - ep.start).total_seconds() / 3600, True)
                cursor = end
            if t > cursor:
                ref = advance(ref, (t - cursor).total_seconds() / 3600, False)
            self.assertAlmostEqual(s, ref, places=12)
        with self.assertRaises(ValueError):
            pressure(first - timedelta(minutes=1), records)

    def test_target_scan_mean_and_endpoints(self):
        r = scan_target(NOW, NOW + timedelta(minutes=100), lambda t: (t - NOW).total_seconds() / 60)
        self.assertAlmostEqual(r['mean'], 50)
        self.assertEqual(r['minimum'], 0)
        # negative only at the very start: the endpoint check must catch it
        r = scan_target(NOW, NOW + timedelta(minutes=30), lambda t: -1 if t == NOW else 1)
        self.assertLess(r['minimum'], 0)
        self.assertEqual(r['below_fraction'], 0)

    def test_threshold_trough_and_period(self):
        trough = 5.0
        night = parse_time('2026-10-10T00:00', ZONE)
        values = [(threshold(night + timedelta(minutes=10 * i), trough, ZONE), i) for i in range(144)]
        lowest = min(values)[1] * 10 / 60
        self.assertAlmostEqual(lowest, trough, delta=.2)
        self.assertAlmostEqual(threshold(night, trough, ZONE), threshold(night + timedelta(hours=24), trough, ZONE))
        later = Model(phase=1)
        self.assertAlmostEqual(threshold(night + timedelta(hours=1), trough, ZONE, later), threshold(night, trough, ZONE))

    def test_calibration_puts_reference_sleeper_in_balance(self):
        # Someone who sleeps exactly the age minimum on a fixed schedule falls asleep
        # when S reaches C and finishes necessary sleep 15 minutes before waking.
        for age, hours in (('adult', 7), ('teen', 8), ('school', 9)):
            wake = datetime(2026, 10, 10, 7, 0, tzinfo=ZONE)
            bed = wake - timedelta(hours=hours)
            d = regular(bed.strftime('%H:%M'), '07:00', days=14, age=age)
            records = validate_dataset(d, NOW)[2]
            hist = recent_history(records, NOW, ZONE)
            model = Model(reference_hours=hours)
            tonight = bed + timedelta(days=1)
            s_bed = pressure(tonight, hist['episodes'], model)
            with self.subTest(age=age):
                self.assertAlmostEqual(s_bed, threshold(tonight, hist['trough'], ZONE, model), delta=.01)
                end = necessary_sleep_end(tonight, s_bed, lambda t: threshold(t, hist['trough'], ZONE, model))
                expected = tonight + timedelta(hours=hours - CALIBRATION_MARGIN_HOURS)
                self.assertLessEqual(abs((end - expected).total_seconds()), 5 * 60)

    def scenario(self, age='teen'):
        records = validate_dataset(sample(), NOW)[2]
        hist = recent_history(records, NOW, ZONE)
        profile = profile_data({'age_group': age})[0]
        wake = parse_time('2026-10-11T07:00', ZONE)
        t0, t1 = parse_time('2026-10-11T09:00', ZONE), parse_time('2026-10-11T10:40', ZONE)
        return Scenario(Model(profile['minimum']), hist, profile, ZONE, NOW, wake, [(t0, t1)]), hist

    def test_scenario_uses_exact_pressure(self):
        sc, hist = self.scenario()
        for bed in (parse_time('2026-10-10T21:00', ZONE), parse_time('2026-10-10T23:37', ZONE)):
            self.assertAlmostEqual(sc.s_at(bed), pressure(bed, hist['episodes'], sc.model), places=12)

    def test_later_bed_never_ends_necessary_sleep_earlier(self):
        sc, _ = self.scenario()
        rows = [sc.evaluate(b) for b in grid_times(parse_time('2026-10-10T21:00', ZONE), parse_time('2026-10-11T01:00', ZONE), ZONE)]
        for a, b in zip(rows, rows[1:]):
            self.assertLessEqual(a['necessary_end'], b['necessary_end'])
            self.assertLess(a['wake_pressure'], b['wake_pressure'])
            self.assertGreater(a['mean_alertness'], b['mean_alertness'])
            self.assertGreater(a['wake_alertness'], b['wake_alertness'])

    def test_necessary_sleep_can_be_zero(self):
        # S already below C at bedtime and staying there: necessary sleep ends at bedtime.
        bed = parse_time('2026-10-10T22:00', ZONE)
        self.assertEqual(necessary_sleep_end(bed, .1, lambda t: .5), bed)
        self.assertIsNone(necessary_sleep_end(bed, .9, lambda t: .0))

    def test_model_variants(self):
        variants = Model(8).variants()
        self.assertEqual(len(variants), 5)
        self.assertEqual(len({v.name for v in variants}), 5)
        self.assertTrue(all(v.reference_hours == 8 for v in variants))


def row(bed_h, wake_h=31.0, target_until=40.0, minimum=8, maximum=10):
    """Synthetic candidate for decision tests: hours are clock hours (25 = 01:00 next day)."""
    base = datetime(2026, 10, 10, tzinfo=UTC)
    hours = wake_h - bed_h
    return {'bed': base + timedelta(hours=bed_h), 'hours': hours, 'mean_alertness': hours / 100,
            'meets_minimum': hours >= minimum, 'within_maximum': hours <= maximum,
            'target_ok': bed_h <= target_until, 'necessary_ok': True}


class DecisionRuleTests(unittest.TestCase):
    beds = [21 + i / 4 for i in range(17)]  # 21:00 .. 01:00

    def decide(self, anchor_h=None, target_until=40.0, in_range=True):
        rows = [row(b, target_until=target_until) for b in self.beds]
        anchor = row(anchor_h, target_until=target_until) if anchor_h is not None else None
        return decide(rows, anchor, in_range)

    def clock(self, result):
        return [r['bed'].strftime('%H:%M') for r in result['window']]

    def test_keep_acceptable_plan(self):
        r = self.decide(22.0)
        self.assertEqual((r['status'], r['mode']), ('ready', 'keep'))

    def test_keep_plan_longer_than_search_maximum(self):
        # The user's own plan is never shortened just because it is long.
        r = self.decide(20.75)  # 10 h 15 min > 10 h
        self.assertEqual((r['status'], r['mode']), ('ready', 'keep'))

    def test_advance_to_deadline_window(self):
        r = self.decide(23.5)
        self.assertEqual((r['status'], r['mode']), ('ready', 'advance'))
        self.assertEqual(self.clock(r), ['22:30', '22:45', '23:00'])

    def test_earliest_without_anchor(self):
        r = self.decide(None)
        self.assertEqual(r['mode'], 'earliest')
        self.assertEqual(self.clock(r)[0], '21:00')

    def test_delay_when_plan_is_before_range(self):
        r = self.decide(20.5, in_range=False)
        self.assertEqual(r['mode'], 'delay')
        self.assertEqual(self.clock(r)[0], '21:00')

    def test_model_condition_within_one_hour_is_ready(self):
        r = self.decide(24.0, target_until=23.0)  # model and hard rule both need 60 min
        self.assertEqual((r['status'], r['mode']), ('ready', 'advance'))
        self.assertEqual(self.clock(r)[-1], '23:00')

    def test_model_condition_beyond_one_hour_is_capped(self):
        r = self.decide(24.0, target_until=22.5)  # model needs 90 min, hard rule 60 min
        self.assertEqual((r['status'], r['partial_reason']), ('partial', 'large_shift'))
        self.assertEqual(self.clock(r)[-1], '23:00')
        self.assertEqual(r['deadline']['bed'].strftime('%H:%M'), '23:00')
        self.assertEqual(r['deadlines']['overall']['bed'].strftime('%H:%M'), '22:30')

    def test_large_model_shift_is_capped(self):
        r = self.decide(25.0, target_until=21.75)  # hard rule needs 120 min, model 195 min
        self.assertEqual((r['status'], r['partial_reason']), ('partial', 'large_shift'))
        self.assertEqual(self.clock(r), ['22:30', '22:45', '23:00'])
        self.assertEqual(r['deadlines']['overall']['bed'].strftime('%H:%M'), '21:45')
        self.assertEqual(SHIFT_LIMIT, timedelta(minutes=60))

    def test_unattainable_target_keeps_hard_constraints(self):
        r = self.decide(23.5, target_until=0)
        self.assertEqual((r['status'], r['partial_reason']), ('partial', 'unattainable'))
        self.assertTrue(all(x['meets_minimum'] and x['within_maximum'] for x in r['window']))
        self.assertIsNone(r['deadlines']['target'])

    def test_deadlines_only_from_rows_within_limits(self):
        rows = [row(b, target_until=21.0) for b in self.beds]  # only 21:00 (10 h) passes the model
        rows.insert(0, row(20.5, target_until=21.0))           # 10.5 h: passes the model, breaks the maximum
        r = decide(rows)
        self.assertEqual(r['deadlines']['target']['bed'].strftime('%H:%M'), '21:00')
        rows = [row(b, target_until=20.75) for b in [20.5] + self.beds]
        r = decide(rows)
        self.assertIsNone(r['deadlines']['target'])  # only the too-long candidate passes
        self.assertEqual(r['partial_reason'], 'unattainable')

    def test_no_candidate_meets_minimum(self):
        rows = [row(b) for b in (23.25, 23.5)]
        self.assertEqual(decide(rows)['status'], 'infeasible')


class RecommendationTests(unittest.TestCase):
    def test_sample_plan_moves_earlier(self):
        r = recommend(sample(), NOW)
        self.assertEqual((r['status'], r['mode']), ('ready', 'advance'))
        self.assertEqual((local(r['window']['start']), local(r['window']['end'])), ('22:30', '23:00'))
        self.assertEqual(r['advance_minutes'], 30)
        self.assertFalse(r['baseline']['meets_minimum'])
        self.assertEqual(r['baseline']['source'], 'input')

    def test_regular_sleeper_keeps_plan(self):
        r = recommend(regular('23:00', '07:00'), NOW)
        self.assertEqual((r['status'], r['mode']), ('ready', 'keep'))
        self.assertEqual(local(r['best']['bed']), '23:00')
        self.assertEqual(r['baseline']['source'], 'habitual')
        self.assertTrue(r['baseline']['necessary_ok'])

    def test_long_sleeper_is_not_told_to_sleep_less_than_needed(self):
        r = recommend(regular('22:00', '06:00'), NOW)  # habitual 22:00, wake tomorrow 07:00 = 9 h
        self.assertEqual(r['mode'], 'keep')
        self.assertEqual(local(r['best']['bed']), '22:00')

    def test_long_plan_inside_range_is_kept_with_note(self):
        d = regular('20:30', '07:00')  # 10.5 h > 10 h teen maximum
        d['plan']['earliest'] = '2026-10-10T20:00'
        r = recommend(d, NOW)
        self.assertEqual((r['status'], r['mode']), ('ready', 'keep'))
        self.assertTrue(r['baseline']['exceeds_recommended'])
        self.assertIn('권장 범위', ' '.join(r['warnings']))

    def test_adult_long_habit_is_kept(self):
        d = regular('22:00', '07:30', age='adult')
        d['plan']['wake'] = '2026-10-11T07:30'
        r = recommend(d, NOW)
        self.assertEqual((r['status'], r['mode']), ('ready', 'keep'))
        self.assertEqual(local(r['best']['bed']), '22:00')
        self.assertFalse(r['baseline']['exceeds_recommended'])  # adults: the recommendation has no upper limit

    def test_plan_before_range_is_delayed(self):
        r = recommend(regular('20:30', '07:00'), NOW)  # range starts 21:00
        self.assertEqual(r['mode'], 'delay')
        self.assertEqual(local(r['window']['start']), '21:00')

    def test_earliest_after_habitual_time_passed(self):
        r = recommend(regular('21:30', '07:00'), datetime(2026, 10, 10, 13, 10, tzinfo=UTC))  # 22:10 Seoul
        self.assertEqual(r['mode'], 'earliest')
        self.assertEqual(local(r['window']['start']), '22:10')
        self.assertIn('지나', ' '.join(r['warnings']))

    def test_target_time_changes_decision(self):
        early = regular('00:00', '08:00', age='adult')
        early['plan'].update(target_start='2026-10-11T07:15', target_end='2026-10-11T08:15')
        later = regular('00:00', '08:00', age='adult')
        a, b = recommend(early, NOW), recommend(later, NOW)
        self.assertEqual((a['mode'], b['mode']), ('advance', 'keep'))
        self.assertLess(datetime.fromisoformat(a['window']['end']), datetime.fromisoformat(b['best']['bed']))

    def test_large_shift_partial(self):
        r = recommend(regular('01:00', '08:00'), NOW)
        self.assertEqual((r['status'], r['partial_reason']), ('partial', 'large_shift'))
        self.assertEqual(local(r['window']['end']), '23:00')
        self.assertEqual(r['advance_minutes'], 120)  # what the 8-hour minimum alone requires
        self.assertLess(datetime.fromisoformat(r['deadlines']['overall']), datetime.fromisoformat(r['window']['end']))

    def test_unattainable_target_partial(self):
        d = regular('02:00', '09:00')
        d['plan'].update(target_start='2026-10-11T07:00', target_end='2026-10-11T08:00')
        r = recommend(d, NOW)
        self.assertEqual((r['status'], r['partial_reason']), ('partial', 'unattainable'))
        self.assertIsNone(r['deadlines']['target'])

    def test_section8_necessary_sleep_outputs(self):
        d = sample()
        d['plan']['baseline'] = '2026-10-11T00:15'
        r = recommend(d, NOW)
        base, deadline = r['baseline'], r['deadlines']['necessary']
        self.assertFalse(base['necessary_ok'])
        self.assertGreater(datetime.fromisoformat(base['necessary_end']), datetime.fromisoformat(r['wake']))
        self.assertLess(base['wake_alertness'], 0)  # 'wake-up pressure too high' in the plan's words
        expected = (datetime.fromisoformat(base['bed']) - datetime.fromisoformat(deadline)).total_seconds() / 60
        self.assertEqual(r['necessary_advance_minutes'], round(expected))
        feasible = [c for c in r['candidates'] if c['meets_minimum'] and c['within_maximum']]
        self.assertTrue(next(c for c in feasible if c['bed'] == deadline)['necessary_ok'])
        self.assertTrue(all(not c['necessary_ok'] for c in feasible if c['bed'] > deadline))
        d['plan']['baseline'] = '2026-10-10T23:30'  # already ends by the wake time: no advance suggested
        r = recommend(d, NOW)
        self.assertTrue(r['baseline']['necessary_ok'])
        self.assertEqual(r['necessary_advance_minutes'], 0)

    def test_plan_example_reverse_calculation(self):
        # The plan's section 8 example: wake 06:50 -> bedtime window ending exactly 8 h before.
        d = sample()
        d['plan'].update(wake='2026-10-11T06:50', baseline='2026-10-10T23:00', target_end='2026-10-11T11:00')
        r = recommend(d, NOW)
        self.assertEqual((local(r['window']['start']), local(r['window']['end'])), ('22:30', '22:50'))
        self.assertEqual(r['advance_minutes'], 10)
        self.assertAlmostEqual(r['deadline']['hours'], 8)

    def test_off_grid_plan_and_limits(self):
        d = regular('23:00', '07:00')
        d['plan'].update(wake='2026-10-11T07:10', baseline='2026-10-10T23:05')
        r = recommend(d, NOW)
        self.assertEqual(r['mode'], 'keep')
        self.assertGreaterEqual(r['deadline']['bed'], r['best']['bed'])
        self.assertEqual(local(r['deadlines']['minimum']), '23:10')
        d = regular('23:00', '07:00')
        d['plan'].update(latest='2026-10-10T22:59')
        r = recommend(d, datetime(2026, 10, 10, 13, 50, tzinfo=UTC))  # 22:50 Seoul: no quarter-hour left in range
        self.assertIn(r['status'], ('ready', 'partial'))
        self.assertEqual(local(r['window']['start']), '22:50')

    def test_window_meets_all_constraints_and_chart_is_consistent(self):
        r = recommend(sample(), NOW)
        wake = datetime.fromisoformat(r['wake'])
        for point in r['window'].values():
            self.assertGreaterEqual((wake - datetime.fromisoformat(point)).total_seconds() / 3600, 8)
        self.assertEqual(len(r['chart']), 97)
        self.assertEqual(local(r['chart'][0]['at'])[3:], '00')  # chart starts on a whole hour
        for c in r['chart']:
            self.assertAlmostEqual(c['AL'], c['C'] - c['S'], places=4)
            at = datetime.fromisoformat(c['at'])
            self.assertEqual(c['asleep'], datetime.fromisoformat(r['best']['bed']) <= at < wake)
        limits = {r['search']['earliest'], r['search']['latest']}
        for c in r['candidates']:
            self.assertTrue(datetime.fromisoformat(c['bed']).minute % 15 == 0 or c['bed'] in limits
                            or c['hours'] in (8, 10) or c['bed'] == r['baseline']['bed'])

    def test_no_feasible_plan(self):
        d = sample()
        d['plan']['earliest'] = '2026-10-10T23:15'
        r = recommend(d, NOW)
        self.assertEqual((r['status'], r['infeasible_reason']), ('infeasible', 'too_late'))
        self.assertNotIn('best', r)
        self.assertTrue(r['minimum_reachable'])

    def test_infeasible_messages(self):
        late = recommend(regular('23:00', '07:00'), datetime(2026, 10, 10, 14, 40, tzinfo=UTC))  # 23:40 Seoul
        self.assertEqual((late['status'], late['infeasible_reason']), ('infeasible', 'minimum_unreachable'))
        self.assertFalse(late['minimum_reachable'])
        early = regular('23:00', '07:00')
        early['plan'].update(earliest='2026-10-10T19:00', latest='2026-10-10T20:30')
        r = recommend(early, NOW)
        self.assertEqual(r['infeasible_reason'], 'too_long')
        self.assertIn('상한', r['message'])
        self.assertEqual(local(r['earliest_within_maximum']), '21:00')

    def test_exact_minimum_and_nonround_wake(self):
        d = sample()
        d['plan'].update(wake='2026-10-11T06:50', earliest='2026-10-10T22:35', latest='2026-10-10T22:50')
        r = recommend(d, NOW)
        self.assertEqual((local(r['window']['start']), local(r['window']['end'])), ('22:35', '22:50'))
        self.assertEqual(r['deadline']['bed'], '2026-10-10T22:50+09:00')
        self.assertAlmostEqual(r['deadline']['hours'], 8, 6)

    def test_first_four_days_no_recommendations(self):
        for days in range(5):
            with self.subTest(days=days):
                self.assertEqual(recommend(sample(days), NOW)['status'], 'warmup')
        self.assertIn(recommend(sample(5), NOW)['status'], ('ready', 'partial'))

    def test_missing_day_resets(self):
        d = sample()
        d['records'].pop(-3)
        r = recommend(d, NOW)
        self.assertEqual((r['status'], r['history_days']), ('warmup', 2))

    def test_duplicate_wake_date_no_false_warmup(self):
        d = sample()
        d['records'].append({'id': 'extra', 'kind': 'main', 'start': '2026-10-10T08:00', 'end': '2026-10-10T09:00'})
        r = recommend(d, NOW)
        self.assertEqual(r['status'], 'warmup')
        self.assertTrue(r['warnings'])
        self.assertTrue(summary(d, NOW)['duplicate_day'])

    def test_older_duplicate_is_reported(self):
        d = sample()
        d['records'].append({'id': 'extra', 'kind': 'main', 'start': '2026-10-02T13:00', 'end': '2026-10-02T14:00'})
        r = recommend(d, NOW)
        self.assertEqual(r['history_days'], 8)  # 10-03 .. 10-10; the duplicated 10-02 ends the block
        self.assertIn('같은 기상 날짜', ' '.join(r['warnings']))

    def test_stale_records_blocked(self):
        d = sample()
        d['records'] = d['records'][:-2]
        self.assertEqual(recommend(d, NOW)['status'], 'warmup')

    def test_age_specific_constraints(self):
        for key in ('school', 'adult', 'older', 'senior'):
            d = sample()
            d['profile']['age_group'] = key
            d['plan']['earliest'] = '2026-10-10T19:00'
            r = recommend(d, NOW)
            lo, search_max = AGE_GROUPS[key][1], AGE_GROUPS[key][4]
            with self.subTest(age=key):
                self.assertIn(r['status'], ('ready', 'partial'))
                wake = datetime.fromisoformat(r['wake'])
                for point in r['window'].values():
                    hours = (wake - datetime.fromisoformat(point)).total_seconds() / 3600
                    self.assertTrue(lo - 1e-9 <= hours <= search_max + 1e-9)

    def test_tracking_only_groups(self):
        d = sample()
        d['profile']['age_group'] = 'preschool'
        self.assertEqual(recommend(d, NOW)['status'], 'tracking_only')
        d = sample()
        d['profile']['schedule'] = 'shift'
        self.assertEqual(recommend(d, NOW)['status'], 'tracking_only')

    def test_invalid_plans(self):
        for key, value in [('earliest', '2026-10-10T10:00'), ('latest', '2026-10-11T08:00'),
                           ('target_start', '2026-10-11T06:30'), ('target_end', '2026-10-11T08:00'),
                           ('wake', '2026-10-14T07:00'), ('baseline', '2026-10-10T01:00')]:
            d = sample()
            d['plan'][key] = value
            with self.subTest(key=key), self.assertRaises(InputError):
                recommend(d, NOW)
        d = sample()
        d['plan'].update(earliest='2026-10-10T09:00', latest='2026-10-10T11:00', wake='2026-10-11T03:00')
        with self.assertRaisesRegex(InputError, '지났'):
            recommend(d, NOW)

    def test_past_earliest_is_clamped(self):
        d = sample()
        d['plan']['earliest'] = '2026-10-10T11:00'  # one hour before NOW; 20 h before wake
        r = recommend(d, NOW)
        self.assertEqual(r['search']['earliest'], '2026-10-10T12:00+09:00')
        self.assertIn('이미 지나', ' '.join(r['warnings']))

    def test_past_baseline_falls_back_to_habitual(self):
        d = sample()
        d['plan']['baseline'] = '2026-10-10T11:30'
        r = recommend(d, NOW)
        self.assertIn('제외', ' '.join(r['warnings']))
        self.assertEqual(r['baseline']['source'], 'habitual')
        self.assertEqual(datetime.fromisoformat(r['baseline']['bed']).minute % 5, 0)

    def test_sensitivity_is_reported(self):
        s = recommend(sample(), NOW)['sensitivity']
        self.assertEqual(s['scenarios'], 5)
        self.assertLessEqual(s['overall_earliest'], s['overall_latest'])

    def test_onset_note_for_advances(self):
        r = recommend(regular('01:00', '08:00'), NOW)
        self.assertGreater(r['best']['onset_alertness'], .05)
        self.assertIn('바로 잠들기 어려울 수', ' '.join(r['warnings']))
        self.assertIn('15분 이상씩', ' '.join(r['warnings']))  # gradual advice, without a citation
        self.assertNotIn('AASM', ' '.join(r['warnings']))

    def test_habitual_anchor_uses_local_clock_across_dst(self):
        for last_wake, wake, now, expected_hours in (
                ('2026-03-07T07:00', '2026-03-08T07:00', datetime(2026, 3, 7, 17, 0, tzinfo=UTC), 7),   # spring forward
                ('2026-10-31T07:00', '2026-11-01T07:00', datetime(2026, 10, 31, 16, 0, tzinfo=UTC), 9)):  # fall back
            d = regular('23:00', '07:00')
            d['profile']['timezone'] = 'America/New_York'
            d['records'] = zoned_nights('America/New_York', '23:00', '07:00', last_wake)
            day = wake[:10]
            prev = (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()
            d['plan'] = {'earliest': f'{prev}T21:00', 'latest': f'{day}T00:30', 'wake': wake,
                         'target_start': f'{day}T09:00', 'target_end': f'{day}T11:00', 'baseline': None}
            with self.subTest(wake=wake):
                r = recommend(d, now)
                self.assertEqual(local(r['baseline']['bed']), '23:00')
                self.assertAlmostEqual(r['baseline']['hours'], expected_hours)
                self.assertEqual(r['mode'], 'advance' if expected_hours < 8 else 'keep')

    def test_random_inputs_never_break_hard_rules(self):
        rnd = random.Random(20261010)
        for case in range(80):
            bed_h = rnd.choice([21, 22, 23, 0, 1])
            bed_m = rnd.choice([0, 15, 30, 45])
            wake_h = rnd.choice([5, 6, 7, 8])
            age = rnd.choice(['school', 'teen', 'adult', 'older', 'senior'])
            d = regular(f'{bed_h:02d}:{bed_m:02d}', f'{wake_h:02d}:{rnd.choice([0, 30])}', age=age)
            ts = rnd.choice(['07:45', '09:00', '13:00', '19:00'])
            d['plan'].update(target_start=f'2026-10-11T{ts}', target_end=f'2026-10-11T{int(ts[:2]) + 1:02d}{ts[2:]}')
            d['plan']['wake'] = f"2026-10-11T{rnd.choice(['05:30', '06:50', '07:00', '07:40'])}"
            if rnd.random() < .5:
                d['plan']['baseline'] = f"2026-10-1{rnd.choice(['0T22', '0T23', '1T00'])}:{rnd.choice(['00', '20', '40', '55'])}"
            r = recommend(d, NOW)
            json.dumps(r, allow_nan=False)
            if r['status'] not in ('ready', 'partial'):
                continue
            lo, search_max = AGE_GROUPS[age][1], AGE_GROUPS[age][4]
            wake = datetime.fromisoformat(r['wake'])
            with self.subTest(case=case):
                for point in (r['window']['start'], r['window']['end'], r['best']['bed'], r['deadline']['bed']):
                    hours = (wake - datetime.fromisoformat(point)).total_seconds() / 3600
                    self.assertGreaterEqual(hours, lo - 1e-9)
                    if r['mode'] != 'keep':
                        self.assertLessEqual(hours, search_max + 1e-9)
                    self.assertGreaterEqual(datetime.fromisoformat(point), datetime.fromisoformat(r['search']['earliest']))
                for key, value in r['deadlines'].items():  # every reported deadline respects the hard limits
                    if value:
                        hours = (wake - datetime.fromisoformat(value)).total_seconds() / 3600
                        self.assertTrue(lo - 1e-9 <= hours <= search_max + 1e-9, (key, hours))
                if r['status'] == 'ready':
                    self.assertTrue(r['best']['target_ok'])
                base = r['baseline']
                if base and r['mode'] == 'advance':
                    needed_by_minimum = max(0.0, (lo - base['hours']) * 60)
                    self.assertLessEqual(r['advance_minutes'], max(60, round(needed_by_minimum)) + 1)
                if base and r.get('necessary_advance_minutes'):
                    planned = (wake - datetime.fromisoformat(base['bed'])).total_seconds() / 3600
                    implied = planned + r['necessary_advance_minutes'] / 60
                    self.assertTrue(lo - 1e-9 <= implied <= search_max + 1e-9 or r['necessary_advance_minutes'] == 0)


def phone_plan(d, wake='2026-10-11T07:00', periods=(('09:00', '09:50'),)):
    """The v2.1 phone payload: wake time and class periods only (automatic range)."""
    day = wake[:10]
    d['plan'] = {'wake': wake, 'targets': [[f'{day}T{a}', f'{day}T{b}'] for a, b in periods]}
    return d


class TargetBlockTests(unittest.TestCase):
    def test_parse_targets_sorts_and_merges(self):
        plan = {'targets': [['2026-10-11T13:50', '2026-10-11T14:40'], ['2026-10-11T09:00', '2026-10-11T09:50'],
                            ['2026-10-11T09:50', '2026-10-11T10:50'], ['2026-10-11T10:30', '2026-10-11T10:40']]}
        blocks = parse_targets(plan, ZONE)
        self.assertEqual([(a.astimezone(ZONE).strftime('%H:%M'), b.astimezone(ZONE).strftime('%H:%M')) for a, b in blocks],
                         [('09:00', '10:50'), ('13:50', '14:40')])

    def test_parse_targets_legacy_and_errors(self):
        legacy = parse_targets({'target_start': '2026-10-11T09:00', 'target_end': '2026-10-11T10:40'}, ZONE)
        self.assertEqual(len(legacy), 1)
        for targets in ([], 'x', [['2026-10-11T09:00']], [['2026-10-11T10:00', '2026-10-11T09:00']],
                        [['2026-10-11T09:00', '2026-10-11T09:50']] * 13, [None], [[1, 2]]):
            with self.subTest(targets=targets), self.assertRaises(InputError):
                parse_targets({'targets': targets}, ZONE)

    def test_scan_blocks_weights_by_length(self):
        a = (NOW, NOW + timedelta(minutes=60))
        b = (NOW + timedelta(hours=5), NOW + timedelta(hours=5, minutes=20))
        r = scan_blocks([a, b], lambda t: 1.0 if t < NOW + timedelta(hours=2) else -1.0)
        self.assertAlmostEqual(r['mean'], (60 - 20) / 80)
        self.assertEqual(r['minimum'], -1.0)
        self.assertAlmostEqual(r['below_fraction'], 20 / 80)

    def test_selected_periods_change_the_plan(self):
        def run(periods):
            return recommend(phone_plan(regular('00:00', '08:00', age='adult'), '2026-10-11T07:00', periods), NOW)
        early, afternoon = run([('07:15', '08:05')]), run([('13:50', '14:40')])
        both = run([('07:15', '08:05'), ('13:50', '14:40')])
        self.assertEqual((afternoon['mode'], local(afternoon['best']['bed'])), ('keep', '00:00'))
        self.assertEqual((early['mode'], local(early['deadline']['bed'])), ('advance', '23:15'))
        # every selected period must keep AL >= 0, so the combined plan follows the stricter one
        self.assertEqual((both['mode'], both['deadline']['bed']), (early['mode'], early['deadline']['bed']))
        self.assertEqual(len(both['targets']), 2)
        targets = [(datetime.fromisoformat(a), datetime.fromisoformat(b)) for a, b in both['targets']]
        for c in both['chart']:
            at = datetime.fromisoformat(c['at'])
            self.assertEqual(c['target'], any(a <= at < b for a, b in targets))

    def test_auto_range_from_wake_time(self):
        r = recommend(phone_plan(sample()), NOW)
        self.assertTrue(r['auto_range'])
        self.assertEqual((local(r['search']['earliest']), local(r['search']['latest'])), ('21:00', '00:00'))
        self.assertIn(r['status'], ('ready', 'partial'))
        self.assertEqual(r['baseline']['source'], 'habitual')
        self.assertNotIn('지나', ' '.join(r['warnings']))
        hours = [c['hours'] for c in r['candidates']]
        self.assertAlmostEqual(max(hours), 10)
        self.assertAlmostEqual(min(hours), 7)

    def test_auto_range_starts_now_without_warning(self):
        late = datetime(2026, 10, 10, 13, 20, tzinfo=UTC)  # 22:20 Seoul
        r = recommend(phone_plan(regular('23:00', '07:00')), late)
        self.assertEqual(local(r['search']['earliest']), '22:20')
        self.assertEqual(r['mode'], 'keep')
        self.assertFalse(any('지나' in w for w in r['warnings']))

    def test_auto_range_keeps_long_habit(self):
        r = recommend(phone_plan(regular('20:30', '07:00')), NOW)  # 10.5 h habit > 10 h search maximum
        self.assertEqual(local(r['search']['earliest']), '20:30')
        self.assertEqual((r['status'], r['mode']), ('ready', 'keep'))
        self.assertTrue(r['baseline']['exceeds_recommended'])

    def test_auto_range_late_night_and_passed_wake(self):
        r = recommend(phone_plan(regular('23:00', '07:00')), datetime(2026, 10, 10, 14, 40, tzinfo=UTC))  # 23:40
        self.assertEqual((r['status'], r['infeasible_reason']), ('infeasible', 'minimum_unreachable'))
        with self.assertRaisesRegex(InputError, '지났'):
            recommend(phone_plan(sample(), '2026-10-10T07:00', [('09:00', '09:50')]), NOW)
        with self.assertRaisesRegex(InputError, '기상 시각보다 늦어야'):
            recommend(phone_plan(sample(), '2026-10-11T09:30', [('09:00', '09:50')]), NOW)


class ResearchTests(unittest.TestCase):
    def observations(self, d):
        for i, r in enumerate(d['records']):
            at = datetime.fromisoformat(r['end']) + timedelta(hours=2)
            d['observations'].append({'id': f'o{i}', 'at': at.isoformat(timespec='minutes'), 'sleepiness': 3 + i % 5})
        return d

    def test_ranks_ties_and_correlation(self):
        self.assertEqual(ranks([3, 1, 1, 2]), [4, 1.5, 1.5, 3])
        self.assertAlmostEqual(spearman([1, 2, 3], [3, 2, 1]), -1)
        self.assertIsNone(spearman([1, 1, 1], [1, 2, 3]))

    def test_research_warmup_exclusions(self):
        r = research(self.observations(sample()), NOW)
        self.assertEqual((r['excluded'], len(r['rows']), r['status']), (4, 10, 'ready'))

    def test_model_a_is_hours_slept_in_previous_24h(self):
        d = self.observations(sample())
        r = research(d, NOW)
        last = validate_dataset(d, NOW)[2][-1]
        self.assertAlmostEqual(r['rows'][-1]['A'], last.hours, places=5)

    def test_model_c_matches_direct_calculation(self):
        d = self.observations(sample())
        d['records'].append({'id': 'nap', 'kind': 'nap', 'start': '2026-10-05T14:00+09:00', 'end': '2026-10-05T14:40+09:00'})
        r = research(d, NOW)
        profile, zone, records, observations = validate_dataset(d, NOW)
        model = Model(profile['minimum'])
        by_time = {row['at']: row for row in r['rows']}
        checked = 0
        for ob in observations:
            key = ob['at'].astimezone(zone).isoformat(timespec='minutes')
            if key not in by_time:
                continue
            h = recent_history(records, ob['at'], zone)
            direct = threshold(ob['at'], h['trough'], zone, model) - pressure(ob['at'], h['episodes'], model)
            self.assertAlmostEqual(by_time[key]['C'], direct, places=5)
            checked += 1
        self.assertEqual(checked, len(r['rows']))

    def test_future_data_no_leak(self):
        d = self.observations(sample())
        d['observations'] = d['observations'][:8]
        a = research(d, NOW)
        d['records'] = d['records'][:8]
        self.assertEqual(a['rows'], research(d, NOW)['rows'])

    def test_same_day_aggregated(self):
        d = self.observations(sample())
        ob = copy.deepcopy(d['observations'][-1])
        ob['id'] = 'extra'
        d['observations'].append(ob)
        r = research(d, NOW)
        self.assertEqual((len(r['rows']), len(r['daily'])), (11, 10))

    def test_sleep_time_observation_excluded(self):
        d = sample()
        d['observations'] = [{'id': 'bad', 'at': d['records'][-1]['start'], 'sleepiness': 8}]
        r = research(d, NOW)
        self.assertEqual((r['excluded'], r['rows']), (1, []))

    def test_summary_empty(self):
        s = summary(sample(0), NOW)
        self.assertIsNone(s['mean_main_hours'])
        self.assertEqual(s['last24_hours'], 0)
        self.assertFalse(s['duplicate_day'])

    def test_habitual_bed_before_wake(self):
        hist = recent_history(validate_dataset(regular('23:30', '07:00'), NOW)[2], NOW, ZONE)
        bed = habitual_bed_before(parse_time('2026-10-11T07:00', ZONE), hist, ZONE)
        self.assertEqual(bed.astimezone(ZONE).strftime('%m-%d %H:%M'), '10-10 23:30')
        hist['bed'] = 23 + 31 / 60  # an average is rounded to 5 minutes
        bed = habitual_bed_before(parse_time('2026-10-11T07:00', ZONE), hist, ZONE)
        self.assertEqual(bed.astimezone(ZONE).strftime('%H:%M'), '23:30')
        hist['bed'] = 1.0
        bed = habitual_bed_before(parse_time('2026-10-11T07:00', ZONE), hist, ZONE)
        self.assertEqual(bed.astimezone(ZONE).strftime('%m-%d %H:%M'), '10-11 01:00')


if __name__ == '__main__':
    unittest.main()
