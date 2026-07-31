# -*- coding: utf-8 -*-
"""
chat_history.json 을 훑어 '지금까지 실제로 문제가 됐던 패턴'만 자동으로 집계한다.

실행:  python scan_log.py            (프로젝트 루트의 chat_history.json)
       python scan_log.py --dist     (dist\\MomoTalk\\chat_history.json)
       python scan_log.py --days 7   (최근 7일치만)

Gemini 호출이 전혀 없는 순수 로컬 분석이라 얼마든지 돌려도 비용이 들지 않는다.
학생 발화(recv)만 검사한다 — 선생님(send)이 뭘 치든 그건 규칙 위반이 아니므로.
"""

import json
import os
import re
import sys
import datetime

from momotalk.paths import get_base_dir

BASE_DIR = get_base_dir()


def _load_history(use_dist):
    if use_dist:
        path = os.path.join(BASE_DIR, "dist", "MomoTalk", "chat_history.json")
    else:
        path = os.path.join(BASE_DIR, "chat_history.json")
    if not os.path.exists(path):
        print("[오류] 파일을 찾을 수 없습니다:", path)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f), path


# ── 검사 규칙들 ────────────────────────────────────────────────────────────
# 각 규칙: (규칙명, 판정함수(text) -> bool, 설명)

_TIME_NUMERIC = re.compile(r"\d{1,2}\s*:\s*\d{2}|\d{1,2}\s*시\s*\d{1,2}\s*분|\b\d{1,2}시부터\b")
_VISIT_PRESSURE = re.compile(r"왜\s*안\s*(왔|오|왔어|와)|안\s*왔잖|오기로\s*했|약속.{0,4}(어겼|안\s*지)")
_TIME_SPONTANEOUS = re.compile(r"벌써\s*시간이|시간이\s*이렇게|벌써\s*\d|지금\s*몇\s*시")
_DIRECT_SUMMON = re.compile(r"(여기로|이리)\s*(와|오세요|와줘)|지금\s*당장\s*와|와야\s*(해|합니다)")


def _check_time_numeric(text):
    return bool(_TIME_NUMERIC.search(text))


def _check_visit_pressure(text):
    return bool(_VISIT_PRESSURE.search(text))


def _check_time_spontaneous(text):
    return bool(_TIME_SPONTANEOUS.search(text))


def _check_direct_summon(text):
    return bool(_DIRECT_SUMMON.search(text))


RULES = [
    ("시각 숫자 발화",   _check_time_numeric,
     "스케줄의 HH:MM 을 그대로 읽어 말함 (예: '21시부터', '20:00에')"),
    ("방문 약속 추궁",   _check_visit_pressure,
     "선생님이 온다고 한 걸 나중에 추궁하거나 서운해함"),
    ("시간 얘기 먼저 꺼냄", _check_time_spontaneous,
     "묻지 않았는데 스스로 시간을 언급 (예: '벌써 시간이 그렇게 됐어?')"),
    ("직접 호출 요구",   _check_direct_summon,
     "선생님에게 '여기로 와' 처럼 직접 오라고 요구함"),
]


def _iter_recv(store, since=None):
    """학생 발화(recv)만 (학생key, 텍스트, 시각) 로 순회."""
    for char_key, msgs in store.items():
        for entry in msgs:
            if not entry or entry[0] != "recv":
                continue
            text = entry[1]
            ts_raw = entry[2] if len(entry) > 2 else None
            ts = None
            if ts_raw:
                try:
                    ts = datetime.datetime.fromisoformat(ts_raw)
                except Exception:
                    ts = None
            if since is not None and (ts is None or ts < since):
                continue
            yield char_key, text, ts


def _check_intra_message_repeat(text):
    """한 말풍선 안에서 같은 표현을 두 번 이어붙인 경우(예: '나중에 보자, 나중에 봐!').
    쉼표/공백으로 나눈 조각 중 2글자 이상 겹치는 앞부분이 반복되면 의심으로 본다."""
    parts = [p.strip() for p in re.split(r"[,，]", text) if p.strip()]
    if len(parts) < 2:
        return False
    for i in range(len(parts) - 1):
        a, b = parts[i], parts[i + 1]
        head = a[:3]
        if len(head) >= 2 and b.startswith(head):
            return True
    return False


def main():
    use_dist = "--dist" in sys.argv
    days = None
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except (IndexError, ValueError):
            print("[오류] --days 뒤에 숫자를 주세요 (예: --days 7)")
            sys.exit(1)

    data, path = _load_history(use_dist)
    store = data.get("store", {})
    since = None
    if days is not None:
        since = datetime.datetime.now() - datetime.timedelta(days=days)

    print("[로그 스캔]", path)
    if since:
        print("  대상 기간: 최근 %d일 (%s 이후)" % (days, since.strftime("%Y-%m-%d %H:%M")))
    print()

    all_rules = RULES + [
        ("말풍선 내 반복", _check_intra_message_repeat,
         "한 말풍선 안에서 같은 뜻을 두 번 말함"),
    ]

    total_recv = 0
    hits = {name: [] for name, _, _ in all_rules}
    for char_key, text, ts in _iter_recv(store, since):
        total_recv += 1
        for name, fn, _desc in all_rules:
            if fn(text):
                hits[name].append((char_key, ts, text))

    print("검사한 학생 발화 수: %d개" % total_recv)
    print()

    any_hit = False
    for name, _fn, desc in all_rules:
        found = hits[name]
        if not found:
            print("[OK] %s: 0건" % name)
            continue
        any_hit = True
        print("[!!] %s: %d건  — %s" % (name, len(found), desc))
        for char_key, ts, text in found:
            when = ts.strftime("%m-%d %H:%M") if ts else "시각모름"
            shown = text if len(text) <= 60 else text[:60] + "…"
            print("      %s %s: %s" % (when, char_key, shown))
        print()

    if not any_hit:
        print("\n문제 패턴이 하나도 발견되지 않았습니다.")


if __name__ == "__main__":
    main()
