# -*- coding: utf-8 -*-
"""
dialogues.json 을 읽어 캐릭터/스케줄 데이터로 변환하는 모듈.

스케줄러와 채팅창이 같은 데이터를 공유하도록, 읽기는 여기 한 곳에서만 합니다.

JSON 의 'day' 값으로 쓸 수 있는 것:
  - 요일: mon tue wed thu fri sat sun  (또는 한글 월 화 수 목 금 토 일)
  - 묶음: everyday(매일) / weekday(평일) / weekend(주말)
  - 여러 개: ["mon", "wed", "fri"] 처럼 배열도 가능
'time' 은 24시간제 "HH:MM" (예: "07:00", "19:30")
'messages' 는 보낼 대사들의 배열 (여러 줄이면 연달아 도착)
"""

import os
from momotalk.paths import get_base_dir
import json

BASE_DIR = get_base_dir()

# 파이썬 datetime.weekday(): 월=0 ... 일=6
_DAY_MAP = {
    "mon": {0}, "tue": {1}, "wed": {2}, "thu": {3}, "fri": {4}, "sat": {5}, "sun": {6},
    "월": {0}, "화": {1}, "수": {2}, "목": {3}, "금": {4}, "토": {5}, "일": {6},
    "everyday": {0, 1, 2, 3, 4, 5, 6}, "daily": {0, 1, 2, 3, 4, 5, 6}, "매일": {0, 1, 2, 3, 4, 5, 6},
    "weekday": {0, 1, 2, 3, 4}, "평일": {0, 1, 2, 3, 4},
    "weekend": {5, 6}, "주말": {5, 6},
}


def _parse_days(value):
    """'day' 값(문자열 또는 배열)을 요일 번호 집합으로 변환."""
    if isinstance(value, list):
        days = set()
        for v in value:
            days |= _DAY_MAP.get(str(v).strip().lower(), set())
        return days
    return _DAY_MAP.get(str(value).strip().lower(), set())


def load_characters():
    """캐릭터 리스트를 반환. 각 캐릭터는 parsed schedule 을 가진다."""
    path = os.path.join(BASE_DIR, "data", "dialogues.json")
    characters = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print("[dialogues.json 읽기 실패]", e)
        return [{
            "key": "shiroko", "name": "시로코",
            "profile_img": "", "intro": "", "schedule": [], "snippet": "안녕, 선생님.",
        }]

    for key, c in data.get("characters", {}).items():
        schedule = []
        first_msg = ""
        for entry in c.get("schedule", []):
            days = _parse_days(entry.get("day", ""))
            time_str = str(entry.get("time", "")).strip()
            messages = [str(m) for m in entry.get("messages", []) if str(m).strip()]
            if not days or not time_str or not messages:
                continue
            schedule.append({"days": days, "time": time_str, "messages": messages})
            if not first_msg:
                first_msg = messages[0]

        characters.append({
            "key": key,
            "name": c.get("name", key),
            "full_name": c.get("full_name", c.get("name", key)),
            "profile_img": os.path.join(BASE_DIR, c.get("profile_img", "")) if c.get("profile_img") else "",
            "intro": c.get("intro", ""),
            "schedule": schedule,
            "snippet": first_msg or "...",
        })

    if not characters:
        characters.append({
            "key": "shiroko", "name": "시로코", "full_name": "스나오오카미 시로코",
            "profile_img": "", "intro": "", "schedule": [], "snippet": "안녕, 선생님.",
        })
    return characters
