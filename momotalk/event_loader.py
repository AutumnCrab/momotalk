# -*- coding: utf-8 -*-
"""
특별기간 이벤트(여름휴가 / 겨울 제설작전) 로더.

설계 원칙
- 이벤트 스케줄은 학생 JSON 이 아니라 data/events/<id>.json 에 '전원 몫이 한 파일에' 들어간다.
  같은 시각 같은 장소에 다 같이 있어야 co-presence 가 제대로 잡히는데, 6개 파일에
  흩어놓으면 그 정합성을 사람이 확인하기 어렵기 때문이다.
- 요일(mon/tue) 대신 day1/day2/day3 을 쓴다. 이벤트는 '며칠째'가 기준이지 요일이 아니다.
- 날짜는 '해마다 한 번만' 뽑아 event_dates.json 에 적어두고 그 뒤로는 절대 다시 뽑지 않는다.
  켤 때마다 새로 뽑으면 어제는 휴가였는데 오늘은 아닌 자기모순이 생긴다.
- 이벤트가 하나도 없거나 파일이 깨져도 전부 조용히 무시하고 평소 스케줄로 돌아간다
  (이벤트 기능만 꺼지고 앱 동작은 그대로).
"""

import os
import json
import random
import datetime
import calendar

from momotalk.paths import get_base_dir

BASE_DIR = get_base_dir()
EVENTS_DIR = os.path.join(BASE_DIR, "data", "events")
DATES_PATH = os.path.join(BASE_DIR, "event_dates.json")

_WEEKDAY_NUM = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

_events_cache = None      # [event dict, ...]
_dates_cache = None       # {event_id: {"2026": "2026-08-14"}}


def load_events():
    """data/events/*.json 전부 읽기. 폴더가 없으면 빈 리스트(=이벤트 기능 비활성)."""
    global _events_cache
    if _events_cache is not None:
        return _events_cache
    events = []
    if os.path.isdir(EVENTS_DIR):
        for fname in sorted(os.listdir(EVENTS_DIR)):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(EVENTS_DIR, fname), encoding="utf-8") as f:
                    ev = json.load(f)
                if ev.get("id") and ev.get("schedules"):
                    events.append(ev)
            except Exception as e:
                print("[이벤트] %s 읽기 실패: %r" % (fname, e))
    _events_cache = events
    return events


def _load_dates():
    global _dates_cache
    if _dates_cache is not None:
        return _dates_cache
    data = {}
    if os.path.exists(DATES_PATH):
        try:
            with open(DATES_PATH, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except Exception as e:
            print("[이벤트] event_dates.json 읽기 실패(새로 만듭니다): %r" % e)
    _dates_cache = data
    return data


def _save_dates(data):
    try:
        with open(DATES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[이벤트] event_dates.json 저장 실패: %r" % e)


def _pick_start_date(event, year):
    """그 해의 이벤트 시작일을 한 번 뽑는다. 후보가 없으면 None."""
    trig = event.get("trigger") or {}
    months = trig.get("months") or []
    want_wd = _WEEKDAY_NUM.get(trig.get("start_weekday"))
    duration = int(trig.get("duration_days") or 1)

    candidates = []
    for m in months:
        try:
            last_day = calendar.monthrange(year, int(m))[1]
        except Exception:
            continue
        for d in range(1, last_day + 1):
            day = datetime.date(year, int(m), d)
            if want_wd is not None and day.weekday() != want_wd:
                continue
            # 이벤트가 그 달을 넘어 연말을 벗어나지 않게(12월 말 시작 방지)
            if (day + datetime.timedelta(days=duration - 1)).year != year:
                continue
            candidates.append(day)
    if not candidates:
        return None
    return random.choice(candidates)


def get_event_period(event, year):
    """그 해 이벤트의 (시작일, 종료일). 아직 안 뽑았으면 지금 뽑아서 저장한다."""
    dates = _load_dates()
    eid = event.get("id")
    ykey = str(year)
    stored = dates.get(eid, {}).get(ykey)
    if stored:
        try:
            start = datetime.datetime.strptime(stored, "%Y-%m-%d").date()
        except Exception:
            start = None
    else:
        start = None

    if start is None:
        start = _pick_start_date(event, year)
        if start is None:
            return None, None
        dates.setdefault(eid, {})[ykey] = start.isoformat()
        _save_dates(dates)
        print("[이벤트] %s %d년 일정 확정: %s" % (event.get("name", eid), year, start.isoformat()))

    duration = int((event.get("trigger") or {}).get("duration_days") or 1)
    return start, start + datetime.timedelta(days=duration - 1)


def active_event(date):
    """그 날짜에 진행 중인 이벤트가 있으면 (event, day_index) 를 준다. day_index 는 1부터.
    없으면 (None, None). 이벤트가 겹치면 먼저 매칭된 것을 쓴다(설계상 겹치지 않게 관리)."""
    for ev in load_events():
        start, end = get_event_period(ev, date.year)
        if start is None:
            continue
        if start <= date <= end:
            return ev, (date - start).days + 1
    return None, None


def activity_for(char_key, date):
    """그 날짜·그 학생에게 적용할 이벤트 activity 맵. 해당 없으면 None(=평소 스케줄 사용)."""
    ev, day_idx = active_event(date)
    if ev is None:
        return None
    if char_key not in (ev.get("participants") or []):
        return None
    return (ev.get("schedules") or {}).get(char_key, {}).get("day%d" % day_idx)


def awake_for(char_key, date):
    """그 날짜·그 학생에게 적용할 이벤트 awake 구간. 해당 없으면 None(=평소 awake 사용)."""
    ev, day_idx = active_event(date)
    if ev is None:
        return None
    if char_key not in (ev.get("participants") or []):
        return None
    return (ev.get("awake_override") or {}).get(char_key, {}).get("day%d" % day_idx)


def message_window_for(date):
    """그 날짜 이벤트의 기념일 톡 허용 시간대 [(시작분, 끝분), ...]. 없으면 None."""
    ev, _ = active_event(date)
    if ev is None:
        return None
    windows = ev.get("event_message_window")
    if not windows:
        return None
    out = []
    for pair in windows:
        try:
            s, e = pair
            sh, sm = s.split(":")
            eh, em = e.split(":")
            out.append((int(sh) * 60 + int(sm), int(eh) * 60 + int(em)))
        except Exception:
            continue
    return out or None


def event_note_for(char_key, date):
    """지금이 특별기간이라는 걸 모델에게 알려줄 안내문. 해당 없으면 ""."""
    ev, day_idx = active_event(date)
    if ev is None or char_key not in (ev.get("participants") or []):
        return ""
    total = int((ev.get("trigger") or {}).get("duration_days") or 1)
    if total > 1:
        return ("[특별한 기간] 지금은 '%s' 기간이다(%d일 중 %d일째)."
                " 평소 요일 스케줄이 아니라 이 기간 전용 일정으로 지내는 중이다."
                % (ev.get("name", ""), total, day_idx))
    return ("[특별한 기간] 오늘은 '%s' 날이다. 평소 요일 스케줄이 아니라 오늘만의 특별한"
            " 일정으로 움직이는 중이다." % ev.get("name", ""))
