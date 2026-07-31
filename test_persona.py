# -*- coding: utf-8 -*-
"""
학생 한 명(또는 여러 명)에게 고정 질문 세트를 던져 실제 Gemini 응답을 확인하는 디버깅 도구.

실행:  python test_persona.py hoshino
       python test_persona.py hoshino serika nonomi
       python test_persona.py --all
       python test_persona.py hoshino --at "2026-08-03 14:30"   (특정 시각 기준으로 테스트)
       python test_persona.py hoshino --dry                      (API 호출 없이 프롬프트만 확인)

주의: --dry 가 아니면 실제 Gemini API 를 호출한다(질문 수 × 학생 수 만큼 과금).
프롬프트 규칙을 크게 고친 직후에만 쓰는 걸 권장.

취침/부재중이어도 그대로 응답을 받는다 — 실제 앱에서는 그 상태면 답장을 미루지만,
여기서는 "그 상황에서 이 캐릭터가 어떻게 답하는가"를 확인하는 게 목적이기 때문.
대신 현재 상태(취침/부재중/응답가능)를 화면에 같이 표시해준다.
"""

import sys
import datetime

from momotalk import persona_loader
from momotalk.gemini_client import load_config, parse_messages

QUESTIONS = [
    "지금 어디야? 뭐해?",
    "오늘 뭐했어?",
    "이따 뭐해?",
    "누구랑 같이있어?",
    "좋아해!",
    "언제나 고마워!",
    "생일 축하해!",
    "오늘 내 생일이야. 축하해줘!"
]

ALL_KEYS = ["shiroko", "hoshino", "serika", "ayane", "nonomi", "kuroko"]


def _call_gemini(api_key, model, system_prompt, contents):
    """GeminiWorker 와 동일한 호출을 동기(블로킹)로 수행. QThread 없이 CLI 에서 쓰기 위함."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            temperature=0.9,
        ),
    )
    return parse_messages(getattr(response, "text", None))


def _status_label(persona, now):
    status = persona_loader.availability_status(persona, now)
    return {None: "응답가능", "sleep": "취침중", "busy": "부재중(W)"}.get(status, str(status))


def main():
    args = [a for a in sys.argv[1:]]
    dry = "--dry" in args
    if dry:
        args.remove("--dry")

    now = datetime.datetime.now()
    if "--at" in args:
        i = args.index("--at")
        try:
            now = datetime.datetime.strptime(args[i + 1], "%Y-%m-%d %H:%M")
            del args[i:i + 2]
        except (IndexError, ValueError):
            print('[오류] --at 형식: --at "2026-08-03 14:30"')
            sys.exit(1)

    if "--all" in args:
        keys = list(ALL_KEYS)
        args.remove("--all")
    else:
        keys = args

    if not keys:
        print(__doc__)
        print("사용 가능한 학생 key:", ", ".join(ALL_KEYS))
        sys.exit(1)

    unknown = [k for k in keys if k not in ALL_KEYS]
    if unknown:
        print("[오류] 모르는 학생 key:", ", ".join(unknown))
        print("사용 가능:", ", ".join(ALL_KEYS))
        sys.exit(1)

    cfg = load_config()
    api_key = cfg.get("gemini_api_key", "").strip()
    if not dry and not api_key:
        print("[오류] config.json 에 gemini_api_key 가 없습니다. (--dry 로 프롬프트만 볼 수 있어요)")
        sys.exit(1)

    print("=" * 70)
    print("기준 시각: %s (%s요일)" % (
        now.strftime("%Y-%m-%d %H:%M"), "월화수목금토일"[now.weekday()]))
    print("대상 학생: %s" % ", ".join(keys))
    print("질문 %d개 × 학생 %d명 = 총 %d회 %s" % (
        len(QUESTIONS), len(keys), len(QUESTIONS) * len(keys),
        "(--dry: 호출 안 함)" if dry else "API 호출"))
    print("=" * 70)

    for key in keys:
        persona = persona_loader.load_persona(key)
        if persona is None:
            print("\n[건너뜀] %s: prompts/%s.json 을 찾을 수 없음" % (key, key))
            continue

        _, activity_desc = persona_loader.current_activity(persona, now)
        print("\n" + "─" * 70)
        print("■ %s (%s)" % (persona.get("name", key), key))
        print("  상태: %s" % _status_label(persona, now))
        print("  지금 하는 일: %s" % (activity_desc or "(스케줄 없음)"))
        print("─" * 70)

        for q in QUESTIONS:
            store_list = [("send", q, now.isoformat())]
            system_prompt, contents = persona_loader.assemble(key, store_list, now=now)
            if system_prompt is None:
                print("  [실패] 프롬프트 조립 실패")
                continue

            print("\n  선생님: %s" % q)
            if dry:
                print("  (--dry 모드: API 호출 안 함)")
                continue
            try:
                messages = _call_gemini(api_key, cfg.get("model", ""), system_prompt, contents)
            except Exception as e:
                print("  [API 오류] %r" % (e,))
                continue
            if not messages:
                print("  [빈 응답]")
                continue
            for m in messages:
                print("  %s: %s" % (persona.get("name", key), m))

    print("\n" + "=" * 70)
    print("완료. 문제 패턴 자동 검사는 python scan_log.py 로 (실제 대화 기록 대상)")


if __name__ == "__main__":
    main()
