# -*- coding: utf-8 -*-
"""
토스트 알림(자리 비운 사이 온 메시지 팝업) 켬/끔 설정. autostart.py와 같은 방식으로
독립된 작은 상태 파일 하나로 관리한다 — 알림음/보이스는 그대로 두고 화면에 뜨는
팝업만 껐다 켰다 할 수 있게 한다.
"""
import json
import os

from momotalk.paths import get_base_dir

_STATE_PATH = os.path.join(get_base_dir(), "notify_state.json")


def is_enabled():
    try:
        with open(_STATE_PATH, encoding="utf-8") as f:
            return bool(json.load(f).get("enabled", True))
    except Exception:
        return True  # 파일이 없으면 기본값: 켜짐


def _set(enabled):
    try:
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"enabled": enabled}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[모모톡] 알림 설정 저장 실패:", repr(e))


def enable():
    _set(True)


def disable():
    _set(False)
