# -*- coding: utf-8 -*-
"""
대화 기록 영속화.

앱을 껐다 켜도 대화가 남도록 store(대화)와 unread(안 읽음), pending(수면 중 대기 메시지)을
프로젝트 루트의 chat_history.json 에 저장/복원한다.

- store[key]   = [(sender, text), ...]   (sender: 'recv'=학생, 'send'=선생님, 'absent'=부재중 안내)
- unread[key]  = 안 읽은 메시지 수
- pending[key] = [{"text": str, "at": ISO 시각 문자열}, ...]  (학생이 자는 동안 보낸 메시지, 기상 후 일괄 답장용)
"""

import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_PATH = os.path.join(BASE_DIR, "chat_history.json")


def save(store, unread, pending=None):
    """현재 대화/안읽음/대기메시지를 파일로 저장."""
    try:
        data = {
            "store": {k: [list(p) for p in v] for k, v in store.items()},
            "unread": dict(unread),
            "pending": {k: list(v) for k, v in (pending or {}).items()},
        }
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[기록 저장 실패]", e)


def load():
    """저장된 대화/안읽음/대기메시지를 복원. 파일이 없으면 (None, None, None)."""
    if not os.path.exists(HISTORY_PATH):
        return None, None, None
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        store = {
            k: [tuple(p) for p in v]
            for k, v in data.get("store", {}).items()
        }
        unread = dict(data.get("unread", {}))
        pending = {
            k: list(v) for k, v in data.get("pending", {}).items()
        }
        return store, unread, pending
    except Exception as e:
        print("[기록 불러오기 실패]", e)
        return None, None, None
