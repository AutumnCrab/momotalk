# -*- coding: utf-8 -*-
"""
대화 기록 영속화.

앱을 껐다 켜도 대화가 남도록 store(대화)와 unread(안 읽음)를
프로젝트 루트의 chat_history.json 에 저장/복원한다.

- store[key]   = [(sender, text), ...]   (sender: 'recv'=학생, 'send'=선생님)
- unread[key]  = 안 읽은 메시지 수
(다음 단계에서 '보류 답장 대기 목록'도 여기에 같이 저장할 예정)
"""

import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_PATH = os.path.join(BASE_DIR, "chat_history.json")


def save(store, unread):
    """현재 대화/안읽음을 파일로 저장."""
    try:
        data = {
            "store": {k: [list(p) for p in v] for k, v in store.items()},
            "unread": dict(unread),
        }
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[기록 저장 실패]", e)


def load():
    """저장된 대화/안읽음을 복원. 없으면 (None, None)."""
    if not os.path.exists(HISTORY_PATH):
        return None, None
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        store = {
            k: [tuple(p) for p in v]
            for k, v in data.get("store", {}).items()
        }
        unread = dict(data.get("unread", {}))
        return store, unread
    except Exception as e:
        print("[기록 불러오기 실패]", e)
        return None, None
