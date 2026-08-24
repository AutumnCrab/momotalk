# -*- coding: utf-8 -*-
"""
학생 한 명(또는 여러 명)에게 고정 질문 세트를 던져 실제 Gemini 응답을 확인하는 디버깅 도구.

실행:  python test_persona.py hoshino
       python test_persona.py hoshino serika nonomi
       python test_persona.py --all
       python test_persona.py hoshino --at "2026-08-03 14:30"   (특정 시각 기준으로 테스트)
       python test_persona.py hoshino --dry                      (API 호출 없이 프롬프트만 확인)
       python test_persona.py hoshino --bday-own                  ("생일 축하해!" 만, 학생 자기 생일 날짜용)
       python test_persona.py hoshino --bday-teacher               ("오늘 내 생일이야!" 만, 선생님 생일 이벤트 자동 강제)

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
    "오늘 내 생일이야. 축하해줘!",
    "하 진짜 오늘 너무 힘들다",
    "ㅁㄴㅇㄹkjasdlkfj",
]

BDAY_OWN_QUESTIONS = ["생일 축하해!"]
BDAY_TEACHER_QUESTIONS = ["오늘 내 생일이야. 축하해줘!"]

ALL_KEYS = ["shiroko", "hoshino", "serika", "ayane", "nonomi", "kuroko",
            "aru", "mutsuki", "kayoko", "haruka"]


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


def _call_openai(api_key, model, system_prompt, contents):
    """OpenAIWorker 와 동일한 호출을 동기(블로킹)로 수행."""
    from openai import OpenAI
    from momotalk.openai_client import _to_openai_messages

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=_to_openai_messages(system_prompt, contents),
        response_format={"type": "json_object"},
        temperature=0.9,
    )
    return parse_messages(response.choices[0].message.content)


def _call_llm(cfg, system_prompt, contents):
    """config.json 의 provider 에 맞춰 Gemini/OpenAI 중 하나를 동기 호출."""
    if cfg.get("provider") == "openai":
        return _call_openai(cfg.get("openai_api_key", ""), cfg.get("openai_model", ""), system_prompt, contents)
    return _call_gemini(cfg.get("gemini_api_key", ""), cfg.get("model", ""), system_prompt, contents)


def _status_label(persona, now):
    status = persona_loader.availability_status(persona, now)
    return {None: "응답가능", "sleep": "취침중", "busy": "부재중(W)"}.get(status, str(status))


def main():
    args = [a for a in sys.argv[1:]]
    dry = "--dry" in args
    if dry:
        args.remove("--dry")

    questions = QUESTIONS
    teacher_bday = "--teacher-bday" in args
    if teacher_bday:
        args.remove("--teacher-bday")

    if "--bday-own" in args:
        questions = BDAY_OWN_QUESTIONS
        args.remove("--bday-own")
    elif "--bday-teacher" in args:
        questions = BDAY_TEACHER_QUESTIONS
        teacher_bday = True
        args.remove("--bday-teacher")

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
    provider = cfg.get("provider", "gemini")
    api_key = cfg.get("openai_api_key" if provider == "openai" else "gemini_api_key", "").strip()
    if not dry and not api_key:
        print("[오류] config.json 에 %s 가 없습니다. (--dry 로 프롬프트만 볼 수 있어요)"
              % ("openai_api_key" if provider == "openai" else "gemini_api_key"))
        sys.exit(1)

    print("=" * 70)
    print("기준 시각: %s (%s요일)" % (
        now.strftime("%Y-%m-%d %H:%M"), "월화수목금토일"[now.weekday()]))
    print("대상 학생: %s" % ", ".join(keys))
    print("질문 %d개 × 학생 %d명 = 총 %d회 %s" % (
        len(questions), len(keys), len(questions) * len(keys),
        "(--dry: 호출 안 함)" if dry else "API 호출"))
    print("=" * 70)

    for key in keys:
        persona = persona_loader.load_persona(key)
        if persona is None:
            print("\n[건너뜀] %s: prompts/%s.json 을 찾을 수 없음" % (key, key))
            continue

        _, entry = persona_loader.current_activity_entry(persona, now)
        activity_desc = persona_loader._entry_text(entry) if entry is not None else None
        activity_place = persona_loader._entry_place(entry) if entry is not None else None
        status = persona_loader.availability_status(persona, now)
        is_birthday = persona_loader.is_persona_birthday(persona, now)
        if is_birthday:
            event_note = persona_loader.build_event_note("own_birthday", persona=persona)
        elif teacher_bday:
            event_note = persona_loader.build_event_note("teacher_birthday", persona=persona)
        else:
            event_note = ""
        print("\n" + "─" * 70)
        print("■ %s (%s)" % (persona.get("name", key), key))
        print("  상태: %s" % _status_label(persona, now))
        print("  지금 하는 일: %s" % (activity_desc or "(스케줄 없음)"))
        print("  지금 있는 곳: %s" % (activity_place or "(이동 중)"))
        if is_birthday:
            print("  🎂 오늘은 이 학생의 생일입니다 (event_note 적용됨)")
        elif teacher_bday:
            print("  🎉 선생님 생일 이벤트로 강제 설정됨 (event_note 적용됨)")
        if status is not None:
            # 실제 앱은 이 상태면 답장을 안 하고 대기함에 넣는다. 여기서 답이 나오는 건
            # '그 상황이면 어떻게 말할까'를 보려고 일부러 강제로 물어보기 때문 — 앱 버그가 아니다.
            print("  ※ 실제 앱에서는 이 상태면 답장하지 않고 대기함에 저장한 뒤,")
            print("     깨어난 다음 몰아서 답합니다. 아래는 강제로 물어본 참고용 응답입니다.")
        print("─" * 70)

        for q in questions:
            store_list = [("send", q, now.isoformat())]
            system_prompt, contents = persona_loader.assemble(key, store_list, now=now, event_note=event_note)
            if system_prompt is None:
                print("  [실패] 프롬프트 조립 실패")
                continue

            print("\n  선생님: %s" % q)
            if dry:
                print("  (--dry 모드: API 호출 안 함)")
                continue
            try:
                messages = _call_llm(cfg, system_prompt, contents)
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
