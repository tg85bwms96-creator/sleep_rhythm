import json
import random
import unittest
from datetime import datetime, timedelta, timezone

from sleepapp.analysis import analysis, circular_sd_minutes, clock_difference, necessary_check
from sleepapp.model import InputError, Model, necessary_sleep_end, pressure, recent_history, threshold, validate_dataset
from tests.test_model import NOW, ZONE, sample

UTC = timezone.utc


def nights(pattern, last='2026-10-10'):
    """Records from (bed, wake) clock pairs; the last pair wakes on ``last``."""
    end_day = datetime.fromisoformat(last)
    out = []
    for i, (bed, wake) in enumerate(pattern):
        day = end_day - timedelta(days=len(pattern) - 1 - i)
        wh, wm = map(int, wake.split(':'))
        bh, bm = map(int, bed.split(':'))
        end = day.replace(hour=wh, minute=wm, tzinfo=ZONE)
        start = day.replace(hour=bh, minute=bm, tzinfo=ZONE)
        if start >= end:
            start -= timedelta(days=1)
        out.append({'id': f'n{i}', 'kind': 'main', 'start': start.isoformat(timespec='minutes'),
                    'end': end.isoformat(timespec='minutes')})
    return out


def dataset(records, age='teen'):
    d = sample()
    d['records'] = records
    d['profile']['age_group'] = age
    return d


def comment(r, word):
    return [c for c in r['comments'] if word in c['title'] + c['text']]


class AnalysisTests(unittest.TestCase):
    def test_empty_and_insufficient(self):
        r = analysis(sample(0), NOW)
        self.assertEqual((r['status'], len(r['comments'])), ('empty', 1))
        r = analysis(sample(2), NOW)
        self.assertEqual(r['status'], 'insufficient')
        self.assertIn('3일 이상', r['comments'][-1]['text'])

    def test_sample_statistics(self):
        r = analysis(sample(), NOW)
        s = r['stats']
        # last 7 nights of the sample: 7.75, 8, 7.5, 7.75, 8, 7.5, 7.75 hours
        self.assertEqual((s['nights7'], s['meets7']), (7, 2))
        self.assertAlmostEqual(s['avg7'], 7.75)
        self.assertAlmostEqual(s['shortfall7'], 1.75)
        self.assertEqual(s['wake_sd_minutes'], 0)
        self.assertEqual(round(s['wake_mean'], 6), 7)
        self.assertEqual(s['necessary_nights'], 10)  # nights 5..14: the first 4 are warm-up
        self.assertEqual(len(r['nights']), 14)
        self.assertEqual(r['nights'][-1]['date'], '2026-10-10')
        self.assertTrue(comment(r, '부족한 날'))
        self.assertEqual(r['range']['records'], 14)
        json.dumps(r, allow_nan=False)

    def test_warmup_nights_are_not_judged(self):
        r = analysis(sample(), NOW)
        flags = [n['necessary_ok'] for n in r['nights']]
        self.assertEqual(flags[:4], [None] * 4)
        self.assertTrue(all(f is not None for f in flags[4:]))

    def test_short_night_fails_necessary_sleep(self):
        pattern = [('23:00', '07:00')] * 9 + [('03:30', '07:00')]
        r = analysis(dataset(nights(pattern)), NOW)
        self.assertFalse(r['nights'][-1]['necessary_ok'])
        self.assertTrue(r['nights'][-2]['necessary_ok'])
        self.assertTrue(comment(r, '필요한 잠이 끝나기 전'))

    def test_small_necessary_gaps_are_tolerated(self):
        start = datetime(2026, 9, 27)  # 8 h every night; weekends 00:30-08:30
        pattern = [('00:30', '08:30') if (start + timedelta(days=k)).weekday() >= 5 else ('23:00', '07:00') for k in range(14)]
        r = analysis(dataset(nights(pattern)), NOW)
        gaps = [n['necessary_gap_minutes'] for n in r['nights'] if n['necessary_gap_minutes'] is not None]
        self.assertTrue(any(0 < g <= 15 for g in gaps))
        self.assertEqual((r['stats']['necessary_ok'], r['stats']['necessary_nights']), (10, 10))
        self.assertEqual(r['stats']['necessary_close'], sum(0 < g <= 15 for g in gaps))
        hit = comment(r, '필요한 잠을 채웠어요')
        self.assertEqual(hit[0]['tone'], 'good')
        self.assertIn('15분 안에', hit[0]['text'])

    def test_stale_notice_follows_the_last_main_sleep(self):
        records = nights([('23:00', '07:00')] * 6, last='2026-09-30')
        records.append({'id': 'nap', 'kind': 'nap', 'start': '2026-10-10T08:00+09:00', 'end': '2026-10-10T08:40+09:00'})
        r = analysis(dataset(records), NOW)
        stale = comment(r, '최근 기록이 비어')
        self.assertTrue(stale and '마지막 밤잠 기록은 9월 30일' in stale[0]['text'], stale)
        self.assertTrue(comment(r, '최근 7일 밤잠 기록이 없어요'))
        self.assertEqual(r['stats']['naps7'], 1)

    def test_necessary_uses_only_earlier_records(self):
        base = nights([('23:00', '07:00')] * 10)
        r1 = analysis(dataset(base), NOW)
        later = base + [{'id': 'nap', 'kind': 'nap', 'start': '2026-10-10T08:00+09:00', 'end': '2026-10-10T10:00+09:00'}]
        r2 = analysis(dataset(later), NOW)
        self.assertEqual([n['necessary_ok'] for n in r1['nights']], [n['necessary_ok'] for n in r2['nights']])
        profile, zone, records, _ = validate_dataset(dataset(base), NOW)
        main = records[-1]
        hist = recent_history(records, main.start, zone)
        model = Model(reference_hours=8)
        direct = necessary_sleep_end(main.start, pressure(main.start, hist['episodes'], model),
                                     lambda t: threshold(t, hist['trough'], zone, model))
        self.assertEqual(necessary_check(records, zone, main, 8)['end'], direct)

    def test_weekend_shift_is_reported(self):
        start = datetime(2026, 9, 27)  # Sunday; 14 wake dates through Saturday 10 Oct
        pattern = []
        for k in range(14):
            weekend = (start + timedelta(days=k)).weekday() >= 5
            pattern.append(('01:30', '10:30') if weekend else ('23:00', '07:00'))
        r = analysis(dataset(nights(pattern)), NOW)
        self.assertEqual(r['stats']['weekend_shift_minutes'], 180)  # mid-sleep 03:00 vs 06:00
        hit = comment(r, '사회적 시차')
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]['tone'], 'warn')

    def test_irregular_timing_is_warned(self):
        beds = ['21:00', '23:30', '01:30', '22:00', '00:45', '20:30', '02:00', '23:00']
        r = analysis(dataset(nights([(b, '07:00') for b in beds])), NOW)
        self.assertGreater(r['stats']['bed_sd_minutes'], 60)
        self.assertEqual(comment(r, '들쭉날쭉')[0]['tone'], 'warn')

    def test_duplicate_main_uses_longest(self):
        records = nights([('23:00', '07:00')] * 6)
        records.append({'id': 'dup', 'kind': 'main', 'start': '2026-10-10T08:00+09:00', 'end': '2026-10-10T09:00+09:00'})
        r = analysis(dataset(records), NOW)
        self.assertTrue(r['nights'][-1]['duplicate'])
        self.assertAlmostEqual(r['nights'][-1]['hours'], 8)
        self.assertTrue(comment(r, '밤잠이 2개'))

    def test_stale_and_naps(self):
        records = nights([('23:00', '07:00')] * 7, last='2026-10-06')
        records.append({'id': 'nap', 'kind': 'nap', 'start': '2026-10-05T15:00+09:00', 'end': '2026-10-05T15:40+09:00'})
        r = analysis(dataset(records), NOW)
        self.assertTrue(comment(r, '최근 기록이 비어'))
        self.assertEqual((r['stats']['naps7'], r['stats']['nap_avg_minutes']), (1, 40))
        self.assertAlmostEqual(r['stats']['avg7'], 8)  # naps never count towards the main-sleep minimum

    def test_tracking_only_groups_count_naps(self):
        records = nights([('20:00', '06:00')] * 5)
        records.append({'id': 'nap', 'kind': 'nap', 'start': '2026-10-09T13:00+09:00', 'end': '2026-10-09T15:00+09:00'})
        r = analysis(dataset(records, age='preschool'), NOW)
        self.assertFalse(r['model_used'])
        self.assertNotIn('bed_sd_minutes', r['stats'])
        self.assertAlmostEqual(r['nights'][-2]['hours'], 12)  # 10 h night + 2 h nap
        self.assertTrue(comment(r, '수면량만'))

    def test_sleepiness_groups(self):
        records = nights([('23:00', '07:00'), ('00:30', '07:00')] * 3)
        for i, r in enumerate(records):
            r['sleepiness_wake'] = 3 if i % 2 == 0 else 7
        r = analysis(dataset(records), NOW)
        self.assertEqual(r['stats']['sleepiness'], {'met': 3, 'unmet': 7, 'n_met': 3, 'n_unmet': 3})
        self.assertTrue(comment(r, '덜 잔 날 아침에 더 졸렸어요'))

    def test_helpers(self):
        self.assertEqual(circular_sd_minutes([23.0, 23.0]), 0)
        self.assertAlmostEqual(circular_sd_minutes([22.5, 23.5]), 30, delta=.3)
        self.assertEqual(circular_sd_minutes([0, 6, 12, 18]), 720)
        self.assertAlmostEqual(clock_difference(1, 23), 2)
        self.assertAlmostEqual(clock_difference(23, 1), -2)

    def test_random_inputs_are_safe(self):
        rnd = random.Random(2110)
        for case in range(60):
            pattern = [(f'{rnd.choice([21, 22, 23, 0, 1, 2]):02d}:{rnd.choice([0, 15, 30, 45]):02d}',
                        f'{rnd.choice([5, 6, 7, 8, 9]):02d}:{rnd.choice([0, 30]):02d}') for _ in range(rnd.randint(1, 20))]
            records = nights(pattern)
            keep = [r for r in records if rnd.random() > .15]
            age = rnd.choice(['preschool', 'school', 'teen', 'adult', 'senior'])
            with self.subTest(case=case):
                r = analysis(dataset(keep, age), NOW)
                json.dumps(r, allow_nan=False)
                self.assertEqual(len(r['nights']), 14 if keep else 0)
                self.assertTrue(r['comments'])

    def test_comments_carry_no_citations(self):
        start = datetime(2026, 9, 27)
        weekend = [('01:30', '10:30') if (start + timedelta(days=k)).weekday() >= 5 else ('23:00', '07:00') for k in range(14)]
        irregular = [(b, '07:00') for b in ['21:00', '23:30', '01:30', '22:00', '00:45', '20:30', '02:00', '23:00']]
        short = [('23:00', '07:00')] * 9 + [('03:30', '07:00')]
        for pattern in (weekend, irregular, short):
            text = ' '.join(c['title'] + c['text'] for c in analysis(dataset(nights(pattern)), NOW)['comments'])
            for word in ('CDC', 'AASM', 'Hong', 'Wittmann', '외 20', '출처'):
                self.assertNotIn(word, text)

    def test_invalid_input_is_input_error(self):
        d = sample()
        d['records'][0]['end'] = '2026-10-12T07:00'
        with self.assertRaises(InputError):
            analysis(d, NOW)


if __name__ == '__main__':
    unittest.main()
