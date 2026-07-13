# -*- coding: utf-8 -*-
"""
선생님(사용자) 생일 + 세계 기념일 목록을 anniversaries.json 에서 읽는다.

학생 개별 생일은 여기서 다루지 않는다. 각 prompts/<key>.json 의 'birthday' 필드("MM-DD")를 쓴다.
"""

import os
import json
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(BASE_DIR, "anniversaries.json")

DEFAULT = {
    "user_birthday": "",
    "world_holidays": {
        "01-01": "새해",
        "02-14": "발렌타인데이",
        "03-14": "화이트데이",
        "10-31": "할로윈",
        "12-25": "크리스마스",
    },
}


def load():
    """anniversaries.json 읽기. 없거나 깨지면 기본값으로 안전하게 반환."""
    if not os.path.exists(PATH):
        print("[기념일] anniversaries.json 이 없어요. 기본값(세계 기념일만)으로 동작합니다.")
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT.items()}
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("형식이 dict 가 아님")
        return {
            "user_birthday": str(data.get("user_birthday", "")).strip(),
            "world_holidays": dict(data.get("world_holidays", {})),
        }
    except Exception as e:
        print("[기념일] anniversaries.json 읽기 실패:", e)
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT.items()}


def is_user_birthday_today(anniversaries, now=None):
    if now is None:
        now = datetime.datetime.now()
    b = anniversaries.get("user_birthday", "")
    return bool(b) and now.strftime("%m-%d") == b


def todays_world_holiday(anniversaries, now=None):
    """오늘이 세계 기념일이면 그 이름을, 아니면 None."""
    if now is None:
        now = datetime.datetime.now()
    key = now.strftime("%m-%d")
    return anniversaries.get("world_holidays", {}).get(key)
