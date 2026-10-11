"""Sleep-record analysis with plain-language commentary (v2.2).

Descriptive statistics of the user's own records plus one model-based figure:
the share of nights on which the app's simplified 'necessary sleep' ended before
waking (a simplified form of the circadian sleep sufficiency, CSS, idea from
sleep research; this is neither a published model nor its CSS value). Thresholds
used to word the commentary are app display rules, not clinical cut-offs.
See docs/MODEL.md.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import mean

from .model import (UTC, Model, circular, hour, iso, necessary_sleep_end, pressure, recent_history, threshold,
                    validate_dataset)

WINDOW_DAYS = 14
WEEKEND = (5, 6)          # wake on Saturday or Sunday = free day
STALE_HOURS = 36
REGULAR_MINUTES = 30      # display rule: spread up to +-30 min reads as "regular"
IRREGULAR_MINUTES = 60    # above +-60 min reads as "irregular"
NECESSARY_TOLERANCE_MINUTES = 15  # display rule: the model works in 5-minute steps and records are approximate
WEEKDAY_KO = "월화수목금토일"
DISCLAIMER = ("내 기록을 요약한 교육용 해설입니다. 의료 진단이 아니며, 충분히 자도 낮 졸림이나 수면 문제가 "
              "계속되면 의료 전문가와 상담하세요. ‘±30분’, ‘1시간’ 같은 판단 기준은 이 앱의 표시 기준입니다.")


def duration_text(hours):
    minutes = round(abs(hours) * 60)
    h, m = divmod(minutes, 60)
    return f"{h}시간 {m}분" if h and m else f"{h}시간" if h else f"{m}분"


def clock_text(value):
    minutes = round(value * 60) % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def circular_sd_minutes(values):
    """Circular standard deviation sqrt(-2 ln R) of clock hours, in minutes (capped at 12 h)."""
    _, r = circular(values)
    if r >= 1:
        return 0.0
    if r <= 1e-12:
        return 720.0
    return min(720.0, math.sqrt(-2 * math.log(r)) * 24 / math.tau * 60)


def clock_difference(a, b):
    """a - b on the 24-hour clock, in hours within (-12, 12]."""
    d = (a - b) % 24
    return d - 24 if d > 12 else d


def _night_rows(records, zone, anchor):
    """One row per wake date in the 14-day window ending at ``anchor``. A date's
    main sleep is its longest main episode; extra main episodes are flagged."""
    first = anchor - timedelta(days=WINDOW_DAYS - 1)
    mains, naps = {}, {}
    for r in records:
        day = r.end.astimezone(zone).date()
        if first <= day <= anchor:
            (mains if r.kind == "main" else naps).setdefault(day, []).append(r)
    rows = []
    for k in range(WINDOW_DAYS):
        day = first + timedelta(days=k)
        items = sorted(mains.get(day, []), key=lambda r: (r.hours, r.start), reverse=True)
        rows.append({"day": day, "main": items[0] if items else None, "duplicate": len(items) > 1,
                     "nap_minutes": sum(r.hours for r in naps.get(day, [])) * 60,
                     "nap_count": len(naps.get(day, []))})
    return rows


def necessary_check(records, zone, main, minimum):
    """When the app's simplified necessary sleep ended relative to the recorded wake
    time, using only records before that night. ``gap_minutes`` > 0: woke that many
    minutes before it ended. ``None`` during the 4-night warm-up or when the recent
    pattern is not a regular night-time one (as in recommend)."""
    hist = recent_history(records, main.start, zone)
    if (hist["days"] < 4 or hist["stale"] or hist["concentration"] < .5
            or not 4 <= hist["wake"] <= 13 or not (hist["bed"] >= 17 or hist["bed"] <= 5)):
        return None
    model = Model(reference_hours=minimum)
    s_bed = pressure(main.start, hist["episodes"], model)
    end = necessary_sleep_end(main.start, s_bed, lambda t: threshold(t, hist["trough"], zone, model),
                              model.tau_sleep)
    gap = None if end is None else (end - main.end).total_seconds() / 60
    return {"ok": gap is not None and gap <= NECESSARY_TOLERANCE_MINUTES, "end": end, "gap_minutes": gap}


def analysis(payload, now=None):
    now = (now or datetime.now(UTC)).replace(second=0, microsecond=0)
    profile, zone, records, _ = validate_dataset(payload, now)
    lo, hi, label, eligible = profile["minimum"], profile["maximum"], profile["label"], profile["eligible"]
    out = {"status": "empty", "profile": profile, "range": None, "nights": [], "stats": {},
           "comments": [], "model_used": False, "message": DISCLAIMER}
    stats, comments = out["stats"], out["comments"]

    def add(tone, title, body):
        comments.append({"tone": tone, "title": title, "text": body})

    if not records:
        add("info", "아직 기록이 없어요", "자기 전에 ‘잠자러 가기’, 일어나서 ‘일어났어요’를 누르면 기록이 쌓여요. "
            "3일 이상 모이면 분석과 해설을 보여 드려요.")
        return out

    last_end = max(r.end for r in records)
    anchor = last_end.astimezone(zone).date()
    recent_start = anchor - timedelta(days=6)
    mains_all = [r for r in records if r.kind == "main"]
    out["range"] = {"first": iso(records[0].start, zone), "last": iso(last_end, zone),
                    "days": (anchor - records[0].start.astimezone(zone).date()).days + 1,
                    "records": len(records), "mains": len(mains_all), "naps": len(records) - len(mains_all)}
    rows = _night_rows(records, zone, anchor)

    # Amount per wake date: main sleep only where the model applies (naps never stand
    # in for the main-sleep minimum); main sleep + naps for under-6s and shift work.
    def counted(row):
        return row["main"] is not None if eligible else (row["main"] is not None or row["nap_minutes"] > 0)

    def amount(row):
        main_h = row["main"].hours if row["main"] else 0.0
        return main_h if eligible else main_h + row["nap_minutes"] / 60

    for row in rows:
        main, has = row["main"], counted(row)
        out["nights"].append({
            "date": row["day"].isoformat(), "weekday": row["day"].weekday(), "weekend": row["day"].weekday() in WEEKEND,
            "recorded": has, "hours": round(amount(row), 4) if has else None,
            "meets_minimum": amount(row) >= lo - 1e-9 if has else None,
            "nap_minutes": round(row["nap_minutes"], 1), "nap_count": row["nap_count"], "duplicate": row["duplicate"],
            "start": iso(main.start, zone) if main else None, "end": iso(main.end, zone) if main else None,
            "sleepiness_wake": main.sleepiness_wake if main else None,
            "necessary_ok": None, "necessary_end": None, "necessary_gap_minutes": None})

    last_main_end = max((r.end for r in mains_all), default=None)
    reference_end = last_main_end if eligible and last_main_end else last_end
    if now - reference_end > timedelta(hours=STALE_HOURS):
        local = reference_end.astimezone(zone)
        what = "밤잠 기록" if eligible and last_main_end else "기록"
        add("info", "최근 기록이 비어 있어요",
            f"마지막 {what}은 {local.month}월 {local.day}일 {local:%H:%M}에 끝났어요. 아래 분석은 그때까지의 기록이에요. "
            "잊은 날은 기록 탭에서 직접 추가할 수 있어요.")
    if any(r["duplicate"] for r in rows):
        add("warn", "하루에 밤잠이 2개인 날이 있어요",
            "분석에는 그날 가장 긴 수면만 밤잠으로 썼어요. 기록 탭에서 나머지를 낮잠으로 바꾸면 취침 시각 계산에도 다시 쓸 수 있어요.")

    days = [row for row in rows if counted(row)]
    stats["window"] = {"start": rows[0]["day"].isoformat(), "end": anchor.isoformat(),
                       "recent_start": recent_start.isoformat()}
    stats["nights14"] = len(days)
    if len(days) < 3:
        add("info", "기록이 조금 더 필요해요",
            f"최근 14일 중 {'밤잠' if eligible else '수면'} 기록이 있는 날이 {len(days)}일이에요. 3일 이상 모이면 "
            "수면시간과 규칙성을 분석해요.")
        out["status"] = "insufficient"
        return out
    out["status"] = "ready"

    # ---------------------------------------------------------------- statistics
    last7 = [row for row in days if row["day"] >= recent_start]
    prev7 = [row for row in days if row["day"] < recent_start]
    amounts7 = [amount(r) for r in last7]
    stats.update(avg14=round(mean(amount(r) for r in days), 4), nights7=len(last7))
    if last7:
        stats.update(avg7=round(mean(amounts7), 4), meets7=sum(a >= lo - 1e-9 for a in amounts7),
                     shortfall7=round(sum(max(0.0, lo - a) for a in amounts7), 4))
    if len(last7) >= 3 and len(prev7) >= 3:
        stats["trend_minutes"] = round((mean(amounts7) - mean(amount(r) for r in prev7)) * 60)
    mains = [r["main"] for r in rows if r["main"] is not None]
    if eligible and len(mains) >= 4:
        beds, wakes = [hour(r.start, zone) for r in mains], [hour(r.end, zone) for r in mains]
        stats.update(bed_mean=round(circular(beds)[0], 4), wake_mean=round(circular(wakes)[0], 4),
                     bed_sd_minutes=round(circular_sd_minutes(beds)), wake_sd_minutes=round(circular_sd_minutes(wakes)))
    if eligible:
        mids = [(r.end.astimezone(zone).weekday() in WEEKEND, hour(r.start + (r.end - r.start) / 2, zone)) for r in mains]
        weekend, weekday = [m for w, m in mids if w], [m for w, m in mids if not w]
        if weekend and len(weekday) >= 2:
            stats["weekend_shift_minutes"] = round(clock_difference(circular(weekend)[0], circular(weekday)[0]) * 60)
        checked = []
        for row, night in zip(rows, out["nights"]):
            if row["main"] is None:
                continue
            result = necessary_check(records, zone, row["main"], lo)
            if result is not None:
                night["necessary_ok"] = result["ok"]
                night["necessary_end"] = iso(result["end"], zone) if result["end"] else None
                night["necessary_gap_minutes"] = round(result["gap_minutes"]) if result["gap_minutes"] is not None else None
                checked.append(result)
        out["model_used"] = bool(checked)
        if checked:
            ok = sum(r["ok"] for r in checked)
            stats.update(necessary_nights=len(checked), necessary_ok=ok, necessary_ratio=round(ok / len(checked), 4),
                         necessary_close=sum(r["ok"] and r["gap_minutes"] > 0 for r in checked),
                         necessary_tolerance_minutes=NECESSARY_TOLERANCE_MINUTES)
        if len(mains) >= 4:
            latest, others = mains[-1], mains[:-1]
            stats["latest"] = {"date": latest.end.astimezone(zone).date().isoformat(), "hours": round(latest.hours, 4),
                               "diff_minutes": round((latest.hours - mean(r.hours for r in others)) * 60)}
        met = [r.sleepiness_wake for r in mains if r.sleepiness_wake is not None and r.hours >= lo - 1e-9]
        unmet = [r.sleepiness_wake for r in mains if r.sleepiness_wake is not None and r.hours < lo - 1e-9]
        if len(met) >= 2 and len(unmet) >= 2:
            stats["sleepiness"] = {"met": round(mean(met), 2), "unmet": round(mean(unmet), 2),
                                   "n_met": len(met), "n_unmet": len(unmet)}
    naps7 = [r for r in records if r.kind == "nap" and recent_start <= r.end.astimezone(zone).date() <= anchor]
    if naps7:
        stats.update(naps7=len(naps7), nap_avg_minutes=round(mean(r.hours for r in naps7) * 60))

    # ---------------------------------------------------------------- commentary
    what = "밤잠" if eligible else "하루 수면(낮잠 포함)"
    if last7:
        missing = 7 - len(last7)
        gap = f" 기록이 없는 {missing}일은 빼고 계산했어요." if missing else ""
        if stats["meets7"] == len(last7):
            add("good", "권장 수면시간을 지켰어요",
                f"최근 7일 중 기록한 {len(last7)}일 모두 {what}이 {label} 권장 최소 {lo}시간 이상이었어요. "
                f"평균 {duration_text(stats['avg7'])}.{gap}")
        else:
            add("warn", "수면시간이 부족한 날이 있어요",
                f"최근 7일 중 기록한 {len(last7)}일 가운데 {len(last7) - stats['meets7']}일은 {what}이 {lo}시간보다 "
                f"짧았어요. 모자란 시간을 모두 더하면 {duration_text(stats['shortfall7'])}, 평균은 "
                f"{duration_text(stats['avg7'])}이에요.{gap}")
        if hi is not None and stats["avg7"] > hi + 1e-9:
            add("info", "권장 범위보다 오래 자는 편이에요",
                f"최근 7일 평균 {duration_text(stats['avg7'])}은 {label} 권장 범위({lo}~{hi}시간)보다 길어요. "
                "충분히 자는데도 낮에 계속 졸리면 의료 전문가와 상담해 보세요.")
    else:
        add("info", f"최근 7일 {'밤잠 ' if eligible else ''}기록이 없어요",
            f"최근 7일에는 {'밤잠' if eligible else '수면'} 기록이 없어 그 전 7일만 요약했어요.")
    if not eligible:
        add("info", "수면량만 요약해요",
            "만 6세 미만과 교대근무는 이 앱의 단순 밤잠 모형 전제와 맞지 않아 모형 분석과 규칙성 해설은 하지 않아요. "
            "만 5세 이하는 낮잠을 포함한 하루 수면을 기준으로 봐요.")

    if "bed_sd_minutes" in stats:
        bed_sd, wake_sd = stats["bed_sd_minutes"], stats["wake_sd_minutes"]
        spread = max(bed_sd, wake_sd)
        detail = (f"최근 {len(mains)}일 잠든 시각은 평균 {clock_text(stats['bed_mean'])}에서 보통 ±{bed_sd}분, "
                  f"일어난 시각은 평균 {clock_text(stats['wake_mean'])}에서 ±{wake_sd}분 정도 달라졌어요.")
        if spread <= REGULAR_MINUTES:
            add("good", "자고 일어나는 시각이 일정해요", detail)
        elif spread <= IRREGULAR_MINUTES:
            add("info", "시각이 조금 들쭉날쭉해요", detail + " 매일 같은 시각에 자고 일어나면 리듬을 지키기 쉬워요.")
        else:
            add("warn", "자고 일어나는 시각이 들쭉날쭉해요", detail + " 매일 같은 시각에 자고 일어나면 리듬을 지키기 쉬워요.")

    if "weekend_shift_minutes" in stats:
        shift = stats["weekend_shift_minutes"]
        text = (f"토·일 아침에 일어난 날의 수면 중간 시각이 평일보다 {duration_text(shift / 60)} "
                f"{'늦어요' if shift > 0 else '일러요'}.")
        if abs(shift) < 60:
            add("good", "평일과 주말 리듬이 비슷해요", text if abs(shift) >= 5 else "평일과 주말의 수면 중간 시각이 거의 같아요.")
        else:
            add("info" if abs(shift) < 120 else "warn", "주말 리듬이 평일과 달라요",
                text + " 평일과 쉬는 날의 이런 차이를 ‘사회적 시차(social jetlag)’라고도 해요. "
                       "쉬는 날에도 비슷한 시각에 자고 일어나면 차이가 줄어요.")

    if eligible:
        n = stats.get("necessary_nights", 0)
        if n >= 3:
            ok, close, tol = stats["necessary_ok"], stats["necessary_close"], NECESSARY_TOLERANCE_MINUTES
            near = f" 그중 {close}일은 일어난 뒤 {tol}분 안에 끝나 거의 채운 날로 셌어요." if close else ""
            if ok == n:
                add("good", "모형상 필요한 잠을 채웠어요",
                    f"준비 기간이 지난 {n}일 모두, 이 앱 모형이 계산한 ‘필요 수면’을 채우고 일어났어요.{near}")
            else:
                add("warn" if ok / n < .5 else "info", "필요한 잠이 끝나기 전에 깬 날이 있어요 (모형)",
                    f"준비 기간이 지난 {n}일 중 {n - ok}일은 모형상 ‘필요 수면’이 끝나기 {tol}분 넘게 전에 일어났어요.{near} "
                    "이 앱의 계산은 수면 연구의 개념을 단순화한 것이라 참고로만 보세요. 일어나는 시각이 정해져 있다면, "
                    "모형에서는 조금 일찍 잠들수록 필요 수면이 일찍 끝나요.")
        else:
            add("info", "필요 수면 분석을 준비하고 있어요",
                f"모형 분석은 연속 기록 5일째 밤부터 해요(처음 4일은 준비 기간). 지금 분석할 수 있는 밤: {n}일.")

    if "latest" in stats:
        latest = stats["latest"]
        day = datetime.fromisoformat(latest["date"])
        diff = latest["diff_minutes"]
        compare = ("다른 날 평균과 비슷해요" if abs(diff) < 10 else
                   f"다른 날 평균보다 {duration_text(diff / 60)} {'길어요' if diff > 0 else '짧아요'}")
        add("info", "가장 최근 수면",
            f"{day.month}월 {day.day}일({WEEKDAY_KO[day.weekday()]}) 아침까지 {duration_text(latest['hours'])} 잤어요. {compare}.")
    if "trend_minutes" in stats:
        trend = stats["trend_minutes"]
        if abs(trend) >= 10:
            add("info", f"그 전 7일보다 {'늘었어요' if trend > 0 else '줄었어요'}",
                f"최근 7일 평균 수면이 그 전 7일보다 {duration_text(trend / 60)} {'길어요' if trend > 0 else '짧아요'}.")
        else:
            add("info", "그 전 7일과 비슷해요", "최근 7일 평균 수면이 그 전 7일과 10분 이내로 비슷해요.")
    if "naps7" in stats:
        add("info", f"최근 7일 낮잠 {stats['naps7']}번",
            f"평균 {stats['nap_avg_minutes']}분이에요. 낮잠도 수면압을 낮추기 때문에, 모형에서는 낮잠이 길거나 늦을수록 "
            "밤에 졸음이 늦게 와요.")
    if "sleepiness" in stats:
        s = stats["sleepiness"]
        gap = s["unmet"] - s["met"]
        title = ("덜 잔 날 아침에 더 졸렸어요" if gap >= .5 else "덜 잔 날 아침에 덜 졸렸어요" if gap <= -.5
                 else "아침 졸림은 수면시간과 큰 차이가 없었어요")
        add("info", title,
            f"깬 직후 졸림(1 매우 또렷 ~ 9 매우 졸림) 평균이 {lo}시간 이상 잔 날({s['n_met']}일) {s['met']:.1f}, "
            f"덜 잔 날({s['n_unmet']}일) {s['unmet']:.1f}이에요. 날이 적으면 우연히 생긴 차이일 수 있어요.")
    return out
