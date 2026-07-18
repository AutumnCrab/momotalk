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
from momotalk.paths import get_base_dir
import json

BASE_DIR = get_base_dir()
HISTORY_PATH = os.path.join(BASE_DIR, "chat_history.json")


def _dedupe_recv_run(run):
    """한 recv-run(학생 발화 연속, 각 원소는 [sender, text] 또는 [sender, text, 시각] 전체 엔트리)
    안에서 인접하게 통째로 반복되는 블록을 축약한다. 비교는 텍스트(index 1)만 기준으로 하되,
    실제로 남기고 지울 땐 타임스탬프 등 나머지 필드까지 포함한 전체 엔트리를 그대로 유지한다.
    예: 텍스트가 [A,B,C, A,B,C, D]면 → [A,B,C, D](뒤쪽 중복 엔트리 통째로 삭제).
    긴 블록부터 탐욕적으로 접는다. 반환: (정리된 run, 제거수)."""
    removed = 0
    changed = True
    while changed:
        changed = False
        texts = [e[1] for e in run]
        for L in range(len(run) // 2, 0, -1):
            found = False
            i = 0
            while i + 2 * L <= len(run):
                if texts[i:i + L] == texts[i + L:i + 2 * L]:
                    del run[i + L:i + 2 * L]
                    del texts[i + L:i + 2 * L]
                    removed += L
                    found = True
                    changed = True
                else:
                    i += 1
            if found:
                break
    return run, removed


def clean_repeated_recv(store):
    """store 전체에서 학생(recv) 발화의 인접 블록 반복을 제거한다.
    send/absent(선생님 발화·부재중 안내)는 절대 건드리지 않는다.
    앱 시작 시 1회 호출해 과거에 쌓인 중복을 청소하는 용도.
    반환: 제거된 총 발화 수(0이면 정리할 게 없었음)."""
    total_removed = 0
    for key, conv in store.items():
        segments = []
        i, n = 0, len(conv)
        while i < n:
            if conv[i][0] == "recv":
                run = []
                while i < n and conv[i][0] == "recv":
                    run.append(list(conv[i])); i += 1   # 전체 엔트리(타임스탬프 포함) 그대로 유지
                segments.append(("recv", run))
            else:
                segments.append(("other", conv[i])); i += 1
        rebuilt = []
        for kind, payload in segments:
            if kind == "recv":
                cleaned, r = _dedupe_recv_run(payload)
                total_removed += r
                for entry in cleaned:
                    rebuilt.append(tuple(entry))
            else:
                rebuilt.append(tuple(payload))
        store[key] = rebuilt
    return total_removed


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
