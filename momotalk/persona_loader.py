# -*- coding: utf-8 -*-
"""
학생별 프롬프트 JSON(prompts/<key>.json)을 읽어
Gemini에 보낼 [시스템 프롬프트 문자열] + [대화 히스토리]로 조립한다.

- daily_context 는 요일별 '배열'이며, 답장할 때마다 그중 하나를 랜덤으로 뽑는다(B 방식).
- 실제 API 호출은 하지 않는다. (그건 gemini_client 단계에서)
- 파일명 key 는 dialogues.json 의 학생 key 와 같아야 한다. (shiroko.json ↔ "shiroko")
"""

import os
from momotalk.paths import get_base_dir
from momotalk import weather
from momotalk import event_loader
import json
import random
import datetime

BASE_DIR = get_base_dir()
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # datetime.weekday(): 월=0

# address_terms 필드의 키(교사/학생 key)를 실제 사람 이름으로 표시하기 위한 매핑.
# 이 6명은 고정 로스터라 하드코딩해도 무방(data_loader.py의 캐릭터 목록과 일치).
_ADDRESS_TARGET_NAMES = {
    "teacher": "선생님",
    "shiroko": "시로코",
    "hoshino": "호시노",
    "serika": "세리카",
    "ayane": "아야네",
    "nonomi": "노노미",
    "kuroko": "시로코*테러",
}


def build_address_terms_line(persona):
    """[호칭] 블록: 이 학생이 선생님/다른 학생을 부를 때 쓰는 정확한 호칭을 프롬프트에 명시.
    실제 대화에서 그 사람 얘기가 나올 때 이 표현을 쓰게 해서, 캐릭터 간 호칭이
    대화마다 흔들리지 않고 항상 일관되게 유지되도록 한다."""
    terms = persona.get("address_terms")
    if not terms:
        return ""
    parts = []
    for who, term in terms.items():
        label = _ADDRESS_TARGET_NAMES.get(who, who)
        term_str = " / ".join(term) if isinstance(term, list) else term
        parts.append("%s → '%s'" % (label, term_str))
    return (
        "[호칭] 다른 사람을 지칭·호명할 때는 이렇게 부른다: " + ", ".join(parts)
        + ". 대화 중 이 사람들 얘기가 나오면 항상 이 호칭을 쓴다"
          "(존댓말/반말 선택과는 별개로, 이 명칭 자체는 지킬 것)."
    )


def load_persona(key):
    """prompts/<key>.json 을 읽어 dict 로 반환. 없으면 None."""
    path = os.path.join(PROMPTS_DIR, key + ".json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("[페르소나 로드 실패]", key, e)
        return None


def _parse_hhmm(s):
    h, m = s.strip().split(":")
    return int(h) * 60 + int(m)


def _entry_text(entry):
    """activity 항목 하나(신규 dict {"text","place","with","tag"} 또는 구형 문자열)에서
    사람이 읽는 설명 텍스트만 뽑는다. 하위호환용."""
    if isinstance(entry, dict):
        return entry.get("text", "")
    return entry or ""


def _entry_place(entry):
    """신규 dict 항목이면 place(문자열 또는 None), 구형 문자열이면 None(구조화 정보 없음)."""
    if isinstance(entry, dict):
        return entry.get("place")
    return None


def _activity_map(persona, date):
    """그 '날짜'에 실제로 적용되는 activity 맵.
    특별기간(여름휴가/제설작전) 중이면 이벤트 전용 스케줄, 아니면 평소 요일 스케줄.
    이벤트가 없거나 그 학생이 참가자가 아니면 기존과 100% 동일하게 동작한다."""
    ev_map = event_loader.activity_for(persona.get("key", ""), date)
    if ev_map is not None:
        return ev_map
    return (persona.get("activity") or {}).get(WEEKDAY_KEYS[date.weekday()])


def _awake_raw(persona, date):
    """그 '날짜'에 실제로 적용되는 awake 구간 문자열 리스트.
    특별기간이면 이벤트 awake_override, 아니면 평소 요일 awake."""
    ev_awake = event_loader.awake_for(persona.get("key", ""), date)
    if ev_awake is not None:
        return ev_awake
    return (persona.get("awake") or {}).get(WEEKDAY_KEYS[date.weekday()])


def _sorted_entries(day_map):
    out = []
    for t, entry in (day_map or {}).items():
        try:
            out.append((_parse_hhmm(t), t, entry))
        except Exception:
            continue
    out.sort(key=lambda x: x[0])
    return out


def _apply_weather_fallback(entry):
    """지금 날씨가 궂고(비/눈 등) 이 슬롯에 weather_fallback 이 있으면 그걸로 갈아끼운다.
    원본 entry 는 건드리지 않고 대체본을 새로 만들어 돌려준다(다음 호출에 영향 없게).
    날씨 정보가 없으면(키 미설정·조회 실패) 항상 원본 그대로 → 기존 동작과 동일."""
    if not isinstance(entry, dict):
        return entry
    fb = entry.get("weather_fallback")
    if not fb or not weather.is_bad_weather():
        return entry
    merged = dict(entry)
    merged["text"] = fb.get("text", entry.get("text", ""))
    merged["place"] = fb.get("place")
    merged["tag"] = fb.get("tag")
    return merged


def current_activity_entry(persona, now=None):
    """
    persona['activity'][요일] = {"HH:MM": entry, ...} 에서
    지금 시각이 속한 구간(가장 최근에 시작된 항목)의 '원본 entry'를 찾는다(dict 또는 구형 문자열 그대로).
    자정을 넘겨 이어지는 경우(오늘 첫 항목보다 이른 시각)엔 어제의 마지막 항목을 이어서 본다.
    비/눈이 오는 중이고 그 슬롯에 weather_fallback 이 있으면 대체 일정으로 바꿔서 돌려준다.
    반환: (시작시각 문자열, entry) 또는 (None, None).
    """
    if now is None:
        now = datetime.datetime.now()
    activity = persona.get("activity")
    if not activity:
        return None, None

    cur = now.hour * 60 + now.minute
    today = now.date()

    today_entries = _sorted_entries(_activity_map(persona, today))
    best = None
    for mins, t, entry in today_entries:
        if mins <= cur:
            best = (t, entry)
        else:
            break
    if best is not None:
        return best[0], _apply_weather_fallback(best[1])

    # 오늘 첫 항목보다 이른 시각(자정 근처)이면 어제의 마지막 항목이 이어지는 것으로 본다
    yest_entries = _sorted_entries(_activity_map(persona, today - datetime.timedelta(days=1)))
    if yest_entries:
        _, t, entry = yest_entries[-1]
        return t, _apply_weather_fallback(entry)
    return None, None


def current_activity(persona, now=None):
    """기존 호출부 하위호환용: (시작시각, 설명텍스트) 만 반환."""
    t, entry = current_activity_entry(persona, now)
    if entry is None:
        return None, None
    return t, _entry_text(entry)


def recent_schedule_context(persona, now=None, hours=12):
    """
    [선톡 전용] 대화 원문(build_history) 대신 쓸 '사실 기반' 근황 요약.
    최근 hours 시간 동안 activity 에 적힌 시각들을 시간순으로 그대로 나열한다.
    (자정을 넘는 구간도 어제 activity 까지 이어서 포함한다.)
    과거 '대화 내용'이 아니라 '스케줄 사실'만 다루므로, 예전 대화 문구를 그대로
    다시 말하게 될 위험이 구조적으로 없다.
    반환: 사람이 읽을 수 있는 여러 줄 문자열, 또는 activity 가 없으면 "".
    """
    if now is None:
        now = datetime.datetime.now()
    activity = persona.get("activity")
    if not activity:
        return ""

    today = now.date()
    cur_abs = now.hour * 60 + now.minute            # 오늘=day 0 기준 절대 분(0~1439)
    window_start_abs = cur_abs - hours * 60          # 음수면 어제로 걸침

    today_entries = _sorted_entries(_activity_map(persona, today))
    yest_entries = _sorted_entries(_activity_map(persona, today - datetime.timedelta(days=1)))

    # 어제 항목은 절대 분 기준으로 -1440 오프셋(어제 00:00 = -1440)
    combined = [(mins - 1440, t, entry) for mins, t, entry in yest_entries]
    combined += [(mins, t, entry) for mins, t, entry in today_entries]
    combined.sort(key=lambda x: x[0])

    window = [(t, entry) for mins, t, entry in combined
              if window_start_abs <= mins <= cur_abs]
    if not window:
        return ""

    lines = ["[최근 %d시간 흐름]" % hours]
    for t, entry in window:
        lines.append("  %s - %s" % (t, _entry_text(entry)))
    return "\n".join(lines)


def upcoming_schedule_context(persona, now=None, hours=6):
    """
    앞으로 hours 시간 동안 activity 에 적힌 예정된 일정을 시간순으로 나열.
    '이따 뭐 할 거야?' 류 질문에 스케줄 근거로 답할 수 있게 하기 위함.
    (자정을 넘는 구간은 내일 activity 까지 이어서 포함한다.)
    아직 안 일어난 일이므로, 호출부에서 반드시 '예정' 뉘앙스로 쓰라고 별도 지시가 필요하다
    (이 함수 자체는 사실 나열만 하고 뉘앙스 지시는 build_system_prompt 쪽에서 붙인다).
    반환: 사람이 읽을 수 있는 여러 줄 문자열, 또는 activity 가 없으면 "".
    """
    if now is None:
        now = datetime.datetime.now()
    activity = persona.get("activity")
    if not activity:
        return ""

    today = now.date()
    cur_abs = now.hour * 60 + now.minute
    window_end_abs = cur_abs + hours * 60            # 1440 넘으면 내일로 걸침

    today_entries = _sorted_entries(_activity_map(persona, today))
    tomo_entries = _sorted_entries(_activity_map(persona, today + datetime.timedelta(days=1)))

    combined = [(mins, t, entry) for mins, t, entry in today_entries]
    combined += [(mins + 1440, t, entry) for mins, t, entry in tomo_entries]
    combined.sort(key=lambda x: x[0])

    # 지금 시각 이후에 '시작'하는 항목만 (지금 하는 일은 [지금 하는 일]에서 이미 다룸)
    window = [(t, entry) for mins, t, entry in combined
              if cur_abs < mins <= window_end_abs]
    if not window:
        return ""

    lines = ["[앞으로 %d시간 예정]" % hours]
    for t, entry in window:
        lines.append("  %s - %s" % (t, _entry_text(entry)))
    return "\n".join(lines)


def today_key_events_context(persona, now=None, max_items=2):
    """
    [오늘 하루 요약 - 토큰 절약형] 오늘 이미 지나간 일정 중 (O)/(X) 마커가 붙은
    '중요 일정'만 최대 max_items개(가장 최근 것 위주) 골라 한두 줄로 요약한다.
    '오늘 뭐 했어?' 류의 하루 전체 질문에 답할 근거를 주기 위함이며, 전체 시간표를
    다 나열하지 않고 굵직한 사건만 담아 토큰을 아낀다.
    반환: 사람이 읽을 수 있는 여러 줄 문자열, 또는 해당 없으면 "".
    """
    if now is None:
        now = datetime.datetime.now()
    activity = persona.get("activity")
    if not activity:
        return ""
    cur = now.hour * 60 + now.minute
    today_entries = _sorted_entries(_activity_map(persona, now.date()))
    passed = [(t, entry) for mins, t, entry in today_entries if mins <= cur]
    # 마지막 항목은 '지금 진행 중인 일'이라 [지금 하는 일]과 그대로 겹친다.
    # 이걸 '이미 지나간 일정'이라며 요약에 넣으면, 지금 하고 있는 걸 과거형으로
    # 말해버린다(예: 아직 저녁을 먹는 중인데 "저녁을 먹었어"). 그래서 항상 제외한다.
    passed = passed[:-1]
    if not passed:
        return ""

    def _is_key(entry):
        tag = entry.get("tag") if isinstance(entry, dict) else None
        return tag in ("O", "X")

    key_events = [(t, entry) for t, entry in passed if _is_key(entry)]
    if not key_events:
        # (O)/(X) 가 하나도 없는 학생(예: 대책위 활동을 같이 안 하는 시로코*테러)은
        # 이 요약이 통째로 비어서 '오늘 뭐 했어?'에 지금 하는 일만 답하게 된다.
        # 그런 경우엔 태그와 무관하게 '이미 지나간 슬롯'으로 대신 채운다.
        key_events = passed
    key_events = key_events[-max_items:]

    lines = ["[오늘 있었던 주요 일정 - 요약]"]
    for t, entry in key_events:
        lines.append("  %s - %s" % (t, _entry_text(entry)))
    lines.append(
        "위는 오늘 이미 지나간 굵직한 일정 몇 가지 요약이다(하루 전체 일정 전부는 아님). '오늘 뭐"
        " 했어?' 처럼 하루 전체를 묻는 질문엔 이 사실을 근거로 답하고, [지금 하는 일]만 보고 방금"
        " 한 일로 좁혀서 답하지 않는다."
    )
    return "\n".join(lines)


# B: 학생 간 맥락 공유 — activity 텍스트에서 반복 등장하는 장소성 키워드.
# 완전한 장소 필드가 없으니 문자열 겹침으로 "같이 있을 가능성"만 느슨하게 추정한다.
_PLACE_KEYWORDS = ["시바세키", "동아리실", "학교", "아비도스", "마트", "라멘집", "라멘", "창고", "카페", "식당"]

_STUDENT_KEYS = ["shiroko", "hoshino", "serika", "ayane", "nonomi", "kuroko"]


def _activity_markers(desc):
    """(O)/(X) 마커 존재 여부만 뽑는다. (S)/(W)는 취침/부재중 판정용이라 여기선 안 씀."""
    return {"O": "(O)" in desc, "X": "(X)" in desc}


def _co_present_legacy_estimate(char_key, me, my_desc, now):
    """구형(문자열) activity 데이터용 폴백 추정. place 필드가 없을 때만 쓴다.
    판정 신호(하나라도 맞으면 채택): (O)/(X) 마커 겹침, 이름 언급, 장소 키워드 겹침.
    완벽한 장소 필드가 없는 상태에서의 느슨한 추정이라 신뢰도가 낮다."""
    my_name = _ADDRESS_TARGET_NAMES.get(char_key, char_key)
    my_places = {kw for kw in _PLACE_KEYWORDS if kw in my_desc}
    my_markers = _activity_markers(my_desc)

    found, apart = [], []
    for other_key in _STUDENT_KEYS:
        if other_key == char_key:
            continue
        other = load_persona(other_key)
        if other is None:
            continue
        _, other_desc = current_activity(other, now)
        if not other_desc:
            continue
        other_name = _ADDRESS_TARGET_NAMES.get(other_key, other_key)
        name_match = (other_name in my_desc) or (my_name in other_desc)
        other_places = {kw for kw in _PLACE_KEYWORDS if kw in other_desc}
        place_match = bool(my_places & other_places)
        other_markers = _activity_markers(other_desc)
        marker_match = (
            (my_markers["O"] and other_markers["O"])
            or (my_markers["X"] and other_markers["X"])
        )
        if name_match or place_match or marker_match:
            found.append((other_name, other_desc))
        else:
            apart.append((other_name, other_desc))
    return found, apart


def build_co_present_note(char_key, now=None):
    """
    [B: 맥락 공유] 지금 이 시각, 다른 학생들과 같이 있는지를 판정해 안내문으로 만든다.
    신규(구조화) 데이터: place 필드가 정확히 일치하면 '같이 있음' 확정(느슨한 추정 아님).
    구형(문자열) 데이터가 남아있는 경우에 한해서만 기존 키워드/마커/이름 기반 추정으로 폴백한다.
    반환: 안내 문자열, 또는 아무도 안 겹치면 "".
    """
    if now is None:
        now = datetime.datetime.now()
    me = load_persona(char_key)
    if me is None:
        return ""
    _, my_entry = current_activity_entry(me, now)
    if my_entry is None:
        return ""
    my_desc = _entry_text(my_entry)
    if not my_desc:
        return ""
    my_place = _entry_place(my_entry)

    # '집'은 문자열은 같아도 사람마다 물리적으로 다른 장소(각자의 자택)라서,
    # 다른 장소들처럼 "문자열 일치 = 실제로 같이 있음"으로 취급하면 안 된다.
    # (룸메이트처럼 진짜 한 집에 같이 사는 설정이 생기면, 그때는 "OO네 집" 식으로
    #  place 이름 자체를 다르게 지어서 구분하는 걸 권장.)
    HOME_PLACE = "집"

    if my_place is not None:
        # 신규 구조화 경로: place 정확 일치로 확정 판정(추정 아님). 단, '집'은 예외(아래 참고).
        my_name = _ADDRESS_TARGET_NAMES.get(char_key, char_key)
        found, apart = [], []
        for other_key in _STUDENT_KEYS:
            if other_key == char_key:
                continue
            other = load_persona(other_key)
            if other is None:
                continue
            _, other_entry = current_activity_entry(other, now)
            if other_entry is None:
                continue
            other_desc = _entry_text(other_entry)
            if not other_desc:
                continue
            other_name = _ADDRESS_TARGET_NAMES.get(other_key, other_key)
            other_place = _entry_place(other_entry)
            if (
                other_place is not None
                and other_place == my_place
                and my_place != HOME_PLACE
            ):
                found.append((other_name, other_desc))
            else:
                apart.append((other_name, other_desc))
        return _render_co_present_note(found, apart, confirmed=True)

    # 구형 문자열 데이터 폴백(하위호환)
    found, apart = _co_present_legacy_estimate(char_key, me, my_desc, now)
    return _render_co_present_note(found, apart, confirmed=False)


def _render_co_present_note(found, apart, confirmed):
    if not found and not apart:
        return ""

    lines = []
    if found:
        if confirmed:
            lines.append("[지금 같이 있는 사람] (같은 장소에 있는 것으로 확인됨)")
        else:
            lines.append("[함께 있을 가능성이 있는 사람] (스케줄 텍스트 기반 느슨한 추정, 100% 확정 아님)")
        for other_name, other_desc in found:
            lines.append("  %s: %s" % (other_name, other_desc))
        if confirmed:
            lines.append(
                "위 사람들은 지금 너와 실제로 같은 곳에 있다. 대화 중 자연스럽게 그 사실을 참고해도 된다"
                "(예: 그 사람 얘기가 나오면 지금 옆에 있다는 걸 아는 것처럼 반응해도 된다)."
            )
        else:
            lines.append(
                "확실하지 않으면 단정짓지 말고, 대화 중 자연스럽게 참고만 한다(예: 그 사람 얘기가 나오면"
                " 지금 상황을 아는 것처럼 반응해도 되지만, 굳이 먼저 나서서 확정적으로 언급하지 않는다)."
            )
    if apart:
        if lines:
            lines.append("")
        lines.append("[지금 따로 있는 사람] (너와 다른 곳에서 각자 다른 일을 하는 중)")
        for other_name, other_desc in apart:
            lines.append("  %s: %s" % (other_name, other_desc))
        lines.append(
            "이 사람들은 지금 너와 같이 있지 않다. 선생님이 '다른 애들은 뭐 해?'처럼 물어보면"
            " 위 사실을 근거로 답하되, 마치 네 눈앞에 있는 것처럼(같이 구경 중이라거나 옆에 있다는 식으로)"
            " 지어내지 않는다. 직접 보고 있는 게 아니니 '아마', '~하고 있을걸' 처럼 전해 들은 투로 말하거나,"
            " 잘 모르겠으면 모른다고 해도 된다. 위 목록에 없는 내용을 새로 지어내지 않는다."
        )
    return "\n".join(lines)


def build_proactive_note(activity_desc, schedule_context=""):
    """활동 전환 시점에 학생이 먼저 말 거는(B안) 상황을 시스템 프롬프트에 얹을 안내문.
    schedule_context 를 주면 '최근 N시간 스케줄 흐름'(사실 기반, 대화 원문 아님)도 같이 얹는다.
    선톡의 소재는 이 스케줄 사실에서 가져오게 유도해, 예전 대화 문구를 그대로 다시
    말하게 되는 반복을 구조적으로 줄인다."""
    if not activity_desc:
        return ""
    lines = [
        "[선톡 상황]",
        "지금은 선생님이 아무 말도 하지 않았고, 네가 먼저 말을 거는 상황이다.",
        "지금 네가 하고 있는 일: %s" % activity_desc,
    ]
    if schedule_context:
        lines.append("")
        lines.append(schedule_context)
        lines.append(
            "지금 무슨 말을 할지는 위 [최근 N시간 흐름]에 있는 사실을 근거로 정한다."
            " 대화 기록에 예전에 네가 썼던 문구가 있더라도 그걸 그대로 다시 쓰지 말고,"
            " 방금 확인한 이 최신 스케줄 사실을 기준으로 지금 처음 하는 말처럼 새로 표현한다."
        )
    lines.append(
        "너무 뜬금없이 네 상황부터 늘어놓지 말 것. 먼저 선생님을 부르거나 안부·근황을 묻는"
        " 짧은 한마디로 시작한 다음(예: 지금 뭐 하고 있는지 궁금해하는 식), 자연스럽게"
        " 네가 하고 있는 일이나 하고 싶은 말로 이어가라. 1~2개의 짧은 말풍선으로, 편하게"
        " 톡을 보내는 느낌이면 된다. 너무 격식 차리지 말 것."
    )
    return "\n".join(lines)


def is_persona_birthday(persona, now=None):
    """persona['birthday'] = 'MM-DD' 가 오늘이면 True."""
    bday = persona.get("birthday")
    if not bday:
        return False
    if now is None:
        now = datetime.datetime.now()
    return now.strftime("%m-%d") == bday


def build_event_note(kind, extra=None, persona=None):
    """기념일 종류별 시스템 프롬프트 지시문. AI가 알아서 자연스럽게 표현하도록만 지시하고,
    구체적 대사는 하나도 미리 정해두지 않는다 — 단, persona에 birthday_few_shot이 있고
    kind가 own_birthday/teacher_birthday면 그 캐릭터 목소리의 예시 대사를 참고용으로 덧붙인다."""
    note = ""
    if kind == "own_birthday":
        note = (
            "[오늘의 특별한 날]\n"
            "오늘은 너의 생일이다. 하지만 먼저 나서서 '오늘 내 생일이야'라고 대놓고 알리지는 않는다"
            " (선톡으로 생일을 통보하는 일은 없다).\n"
            "- 선생님이 이미 생일을 축하해준 상태라면: 아래 [생일 대사 예시]를 참고해서 기쁘게 반응해라.\n"
            "- 선생님이 아직 생일 얘기를 안 꺼냈다면: 대화 주제와 상관없이 갑자기 생일 얘기를 꺼내지"
            " 말고, 평소처럼 답하되 대화 흐름이 자연스러운 지점에서 '오늘 나한테 뭐 할 말 없어?',"
            " '오늘 왠지 특별한 날 같은데' 처럼 넌지시 티만 낸다. 매번 티내지 않아도 되고, 직접적으로"
            " '내 생일이야'라고 말하지는 않는다."
        )
    elif kind == "teacher_birthday":
        note = (
            "[오늘의 특별한 날]\n"
            "오늘은 선생님의 생일이다. 진심을 담아 축하 인사를 건네라. 너의 성격과 말투에 맞는 방식으로"
            " 축하하면 된다."
        )
    elif kind == "world_holiday":
        name = extra or "특별한 날"
        note = (
            "[오늘의 특별한 날]\n"
            "오늘은 %s다. 이 날에 어울리는 화제나 인사를 자연스럽게 꺼내라." % name
        )
    else:
        return ""

    if persona and kind in ("own_birthday", "teacher_birthday"):
        bfs = persona.get("birthday_few_shot", {}).get(kind)
        if bfs:
            note += (
                "\n\n[생일 대사 예시] (아래는 네가 이런 상황에서 실제로 하는 말의 어조·길이 참고용이다."
                " 상황·문구를 그대로 베끼지 말고, 이런 느낌으로 지금 처음 하는 말처럼 자연스럽게 표현할 것)"
            )
            for i, line in enumerate(bfs, 1):
                note += "\n  (말풍선 %d) %s" % (i, line)
    return note


def _event_allowed_minutes(persona, date):
    """
    기념일(선생님 생일/세계 기념일) 메시지를 '보내도 되는' 분(0~1439, 그날 0시 기준)을
    계산한다. 규칙:
    1) awake 구간 밖(=자는 중)은 애초에 제외.
    2) (O)/(X) 태그가 붙은 공식 일정·단체(교차) 일정 시간대는 제외 — 이 시간엔 학생이
       일정에 집중해야 하므로 선생님 쪽에 신경 쓰지 않는다.
    3) 각 awake 구간이 끝나기 직전 SLEEP_BUFFER_MIN 분(취침 준비 시간)은 제외.
    4) 23:00 이후는 위 조건과 무관하게 항상 제외(밤 너무 늦게 발송 금지).
    남는 시간(개인 휴식/기상 직후/등하교 이동 등)만 발송 가능 시간으로 허용된다.

    단, 특별기간(여름휴가/제설작전)엔 일정이 거의 전부 (O)라서 위 규칙만 쓰면 허용 시간이
    0분이 되어버린다. 그래서 이벤트가 정해둔 event_message_window(식사 시간 등)가 있으면
    그 시간대를 그대로 쓴다.
    반환: 길이 1440의 bool 리스트.
    """
    SLEEP_BUFFER_MIN = 60
    HARD_CUTOFF_MIN = 23 * 60

    ev_windows = event_loader.message_window_for(date)
    if ev_windows is not None:
        allowed = [False] * 1440
        for sm, em in ev_windows:
            for m in range(max(sm, 0), min(em, 1440)):
                allowed[m] = True
        return allowed

    raw = _awake_raw(persona, date) or []
    allowed = [False] * 1440
    parsed_windows = []
    for part in raw:
        try:
            s, e = part.split("-")
            sm, em = _parse_hhmm(s), _parse_hhmm(e)
            if em <= sm:
                em = 1440   # 자정 넘김 구간은 오늘 몫(자정까지)만
            em = min(em, 1440)
            if em > sm:
                parsed_windows.append((sm, em))
        except Exception:
            continue

    for sm, em in parsed_windows:
        for m in range(sm, em):
            allowed[m] = True

    for m in range(HARD_CUTOFF_MIN, 1440):
        allowed[m] = False

    entries = _sorted_entries(_activity_map(persona, date) or {})
    for i, (mins, t, entry) in enumerate(entries):
        tag = entry.get("tag") if isinstance(entry, dict) else None
        if tag in ("O", "X"):
            end = entries[i + 1][0] if i + 1 < len(entries) else 1440
            for m in range(mins, min(end, 1440)):
                allowed[m] = False

    for sm, em in parsed_windows:
        buf_start = max(sm, em - SLEEP_BUFFER_MIN)
        for m in range(buf_start, em):
            allowed[m] = False

    return allowed


def pick_event_send_datetime(persona, date):
    """
    기념일 메시지를 보낼 시각을, _event_allowed_minutes 로 계산한 '허용 시간' 중에서
    무작위로 하나 고른다(개인 휴식시간/기상 직후/등하교 이동 중 등만 대상).
    허용 시간이 하루 중 하나도 없으면 None(오늘은 발송 안 함).
    """
    allowed = _event_allowed_minutes(persona, date)
    candidates = [m for m, ok in enumerate(allowed) if ok]
    if not candidates:
        return None
    minute = random.choice(candidates)
    return datetime.datetime.combine(date, datetime.time(minute // 60, minute % 60))


def next_allowed_event_datetime(persona, date, after_dt):
    """
    after_dt(포함 안 함) 이후로 가장 가까운 '기념일 메시지 발송 허용' 시각을 찾는다.
    재시도 예약용. after_dt 가 이미 다음날이거나, 오늘 안에 더 이상 허용 시간이 없으면 None.
    """
    if after_dt.date() != date:
        return None
    allowed = _event_allowed_minutes(persona, date)
    start_minute = after_dt.hour * 60 + after_dt.minute + 1
    for m in range(max(start_minute, 0), 1440):
        if allowed[m]:
            return datetime.datetime.combine(date, datetime.time(m // 60, m % 60))
    return None


def _awake_ranges(persona, date):
    """그 날짜의 awake 구간 → [(start_분,end_분), ...]. awake 필드 자체가 없으면 None(=제한 없음).
    특별기간이면 이벤트 awake_override 를 쓴다(_awake_raw 가 처리)."""
    awake = persona.get("awake")
    if not awake:
        return None
    raw = _awake_raw(persona, date)
    if not raw:
        return []
    ranges = []
    for part in raw:
        try:
            start_s, end_s = part.split("-")
            ranges.append((_parse_hhmm(start_s), _parse_hhmm(end_s)))
        except Exception:
            continue
    return ranges


def is_awake(persona, now=None):
    """
    지금 이 학생이 깨어있는지(=답장 가능한지) 판정.
    - persona 에 'awake' 필드가 없으면 항상 깨어있는 것으로 간주(기존 캐릭터 호환).
    - 'HH:MM-HH:MM' 이 자정을 넘기는 경우(예: '23:00-04:00')도 처리한다.
    """
    if now is None:
        now = datetime.datetime.now()
    if not persona.get("awake"):
        return True

    today = now.date()
    cur = now.hour * 60 + now.minute

    today_ranges = _awake_ranges(persona, today)
    if today_ranges is None:
        return True
    for start, end in today_ranges:
        if start <= end:
            if start <= cur < end:
                return True
        else:  # 자정을 넘기는 구간 (예: 23:00~04:00)
            if cur >= start:
                return True

    # 어제 시작해서 오늘 새벽까지 이어지는 구간 체크
    yest_ranges = _awake_ranges(persona, today - datetime.timedelta(days=1)) or []
    for start, end in yest_ranges:
        if start > end and cur < end:
            return True

    return False


def activity_marker(persona, now=None):
    """
    현재 activity 슬롯 텍스트에 (S)/(W) 마커가 있으면 그걸 읽는다.
    (S) = 취침중, (W) = 일/바쁨(회의·라이딩·알바 등). 마커 없으면 None.
    선생님이 스케줄 옆에 직접 붙이는 표시라, 아직 안 붙인 슬롯은 자연히 None.
    """
    if now is None:
        now = datetime.datetime.now()
    _, desc = current_activity(persona, now)
    if not desc:
        return None
    if "(S)" in desc:
        return "S"
    if "(W)" in desc:
        return "W"
    return None


def availability_status(persona, now=None):
    """
    학생의 현재 '응답 가능 여부'를 하나로 통일해서 판정.
    반환: None(가능/평소처럼 응답) / "sleep"(취침중) / "busy"(부재중, 일하는 중)

    우선순위: activity 텍스트의 (S)/(W) 마커 > awake 시간대 필드(하위 호환).
    즉 마커를 붙인 슬롯은 마커가 우선이고, 아직 마커가 없는 슬롯은 기존
    awake 시간대만으로 취침 여부를 판정한다(마커 안 붙였다고 갑자기 다 응답 가능으로 바뀌지 않음).
    """
    if now is None:
        now = datetime.datetime.now()
    marker = activity_marker(persona, now)
    if marker == "S":
        return "sleep"
    if marker == "W":
        return "busy"
    if not is_awake(persona, now):
        return "sleep"
    return None


def build_wake_note(pending_msgs, now=None, reason="sleep"):
    """
    수면/부재중 중 쌓인 메시지를 '방금 확인한 메시지' 안내 블록으로 조립.
    pending_msgs: [{"text": str, "at": ISO 시각 문자열}, ...]
    reason: "sleep"(자다가 확인) 또는 "busy"(일하다가 확인) — 상황 설명 문구가 달라짐.
    """
    if not pending_msgs:
        return ""
    if reason == "busy":
        situation = "네가 일(회의·알바 등)로 바빠서 못 보고 있다가 이제 막 여유가 생겨 확인한 상황이다."
        hint = "바빠서 이제 막 확인했다는 걸 자연스럽게 티내면서,"
    else:
        situation = "네가 자는 동안 선생님이 아래 메시지를 보냈다. 지금 막 깨어나 그것들을 몰아서 확인한 상황이다."
        hint = "자다가 이제 막 확인했다는 걸 자연스럽게 티내면서,"
    lines = [
        "[깨어나서 확인한 메시지]" if reason != "busy" else "[방금 확인한 메시지]",
        situation,
        "첫 마디를 네가 지금 뭘 하고 있었는지, 어디 있는지 같은 네 얘기로 시작하지 말 것."
        " %s 선생님이 무슨 일로 불렀는지"
        " 되묻거나 선생님이 보낸 내용에 먼저 반응하는 것으로 시작해라. 네 얘기는 그다음에 이어가도 된다." % hint,
        "순서대로 자연스럽게 이어서 답장하되, 하나하나 딱딱하게 나열하지 말고 대화하듯 답한다.",
    ]
    for m in pending_msgs:
        at = m.get("at")
        label = ""
        if at:
            try:
                dt = datetime.datetime.fromisoformat(at)
                label = current_time_label(dt)
            except Exception:
                label = ""
        prefix = "(%s) " % label if label else ""
        lines.append("  %s%s" % (prefix, m.get("text", "")))
    return "\n".join(lines)


def pick_daily_context(persona, weekday=None):
    """오늘(또는 지정 요일)의 상황을 하나 고른다. 배열이면 랜덤, 문자열이면 그대로."""
    if weekday is None:
        weekday = datetime.datetime.now().weekday()
    wk = WEEKDAY_KEYS[weekday % 7]
    ctx = persona.get("daily_context", {}).get(wk)
    if isinstance(ctx, list) and ctx:
        return random.choice(ctx)
    if isinstance(ctx, str):
        return ctx
    return ""


_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def current_time_label(now=None):
    """실제 현재 시각을 10분 단위로 내려(00,10,20,30,40,50) 시간대와 함께 표기."""
    if now is None:
        now = datetime.datetime.now()
    minute = now.minute - (now.minute % 10)        # 10분 단위 내림
    h = now.hour
    if 0 <= h < 6:
        period = "새벽"
    elif 6 <= h < 11:
        period = "아침"
    elif 11 <= h < 14:
        period = "점심"
    elif 14 <= h < 18:
        period = "오후"
    elif 18 <= h < 22:
        period = "저녁"
    else:
        period = "밤"
    wk = _WEEKDAY_KO[now.weekday()]
    return "%s요일 %s %02d:%02d" % (wk, period, h, minute)


def build_system_prompt(persona, now=None, wake_note="", proactive_note="", event_note=""):
    """페르소나 dict → Gemini 시스템 프롬프트 문자열."""
    if now is None:
        now = datetime.datetime.now()
    name = persona.get("name", "학생")
    time_label = current_time_label(now)
    _, activity_entry = current_activity_entry(persona, now)
    activity_desc = _entry_text(activity_entry) if activity_entry is not None else None
    activity_place = _entry_place(activity_entry)
    # activity(시간 단위 정밀 스케줄)가 있으면 그것만 쓰고, 없을 때만 daily_context(요일별 랜덤 상황)로 대체.
    # 서로 다른 상황 정보를 동시에 주면 혼란스러우니 항상 하나만 쓴다.
    today = None if activity_desc else pick_daily_context(persona, weekday=now.weekday())

    lines = [
        "너는 '%s'(이)라는 학생이고, 메신저 앱(모모톡)으로 선생님과 1:1로 대화하고 있다." % name,
        "",
        "[성격] %s" % persona.get("persona", ""),
        "[말투] %s" % persona.get("speech_style", ""),
    ]
    addr_line = build_address_terms_line(persona)
    if addr_line:
        lines.append(addr_line)
    lines.append("[지금 시각] %s" % time_label)
    if activity_desc:
        lines.append("[지금 하는 일] %s" % activity_desc)
        # place 는 스케줄에 있는데 여태 프롬프트엔 안 들어가고 있었다. 그래서 텍스트에 장소가
        # 안 적힌 슬롯이면 모델이 자기 위치를 몰라 지어냈다(예: '집'인데 '동아리실'이라고 답함).
        # place 가 None 인 슬롯은 '이동 중이라 고정 장소 없음'이라는 뜻이므로 그대로 알려준다.
        if activity_place:
            lines.append("[지금 있는 곳] %s" % activity_place)
        else:
            lines.append("[지금 있는 곳] 이동 중이라 고정된 장소는 없다")
    elif today:
        lines.append("[오늘의 상황] %s" % today)

    # 특별기간(여름휴가/제설작전)이면 '지금은 평소와 다른 날'이라는 사실을 먼저 알려준다.
    special_note = event_loader.event_note_for(persona.get("key", ""), now.date())
    if special_note:
        lines.append(special_note)

    weather_desc = weather.describe()
    if weather_desc:
        lines.append("[지금 날씨] %s" % weather_desc)

    # 오늘이 생일이 아닌 날에도 '자기 생일이 언제인지'는 알려준다.
    # 이게 없으면 선생님이 착각/장난으로 생일 축하를 했을 때 없는 생일을 지어내며 맞장구친다.
    # (오늘이 진짜 생일이면 event_note 가 따로 붙으므로 여기선 넣지 않는다.)
    own_bday = persona.get("birthday")
    not_my_birthday = bool(own_bday) and not is_persona_birthday(persona, now)
    if not_my_birthday:
        try:
            bm, bd = own_bday.split("-")
            lines.append("[네 생일] %d월 %d일 — 오늘은 네 생일이 아니다." % (int(bm), int(bd)))
        except Exception:
            not_my_birthday = False

    key_events = today_key_events_context(persona, now)
    if key_events:
        lines.append(key_events)

    upcoming = upcoming_schedule_context(persona, now, hours=6)
    if upcoming:
        lines.append(upcoming)
        lines.append(
            "[예정 사실 안내] 위 [앞으로 6시간 예정]은 아직 일어나지 않은 미래 일정이다."
            " '이따 뭐 할 거야?' 같은 질문을 받으면 이 사실을 근거로 예정형('~할 거야', '~할 예정이야')"
            "으로 답해도 된다. 하지만 절대 이미 겪은 일처럼 과거형으로 말하거나, 아직 안 한 일을"
            " 방금 한 것처럼 서술하지 않는다."
        )

    co_present = build_co_present_note(persona.get("key", ""), now)
    if co_present:
        lines.append(co_present)

    if event_note:
        lines.append("")
        lines.append(event_note)
    if wake_note:
        lines.append("")
        lines.append(wake_note)
    if proactive_note:
        lines.append("")
        lines.append(proactive_note)

    fs = persona.get("few_shot", [])
    if fs:
        lines.append("")
        lines.append("[대화 예시] (말투와 길이만 참고하는 용도. 상황·내용을 그대로 베끼지 말 것)")
        for ex in fs:
            u = ex.get("user", "")
            r = ex.get("reply", [])
            if isinstance(r, str):
                r = [r]
            lines.append("  선생님: %s" % u)
            if len(r) == 1:
                lines.append("  %s: %s" % (name, r[0]))
            else:
                for i, line in enumerate(r, 1):
                    lines.append("  %s (말풍선 %d): %s" % (name, i, line))

    lines += [
        "",
        "[규칙]",
        "- 항상 '%s'의 성격과 말투를 일관되게 유지한다." % name,

        "- [어체 고정 - 매우 중요] 위 [말투]에 반말이라고 적혀있으면 대화 내내 반말만 쓴다. 선생님이"
        " 존댓말을 쓰거나, 다정하게 묻거나, 격식 차린 말투로 말을 걸어도 거기에 맞춰서 존댓말로"
        " 바꾸지 않는다. 반말 캐릭터가 존댓말을 쓰는 건 명백한 규칙 위반이다. 반대로 [말투]가"
        " 존댓말이면 마찬가지로 끝까지 존댓말만 쓴다. 상대방의 어체에 맞추려 하지 말고, 항상"
        " 자기 자신의 고정된 어체를 유지한다.",

        "- [여러 메시지에 한 번에 답하기] 선생님이 짧은 톡을 연달아 여러 개 보냈을 때, 그건 '여러 개의"
        " 질문'이 아니라 '한 번에 하고 싶었던 한 덩어리의 말'이다. 메시지 하나당 말풍선 하나씩 기계적으로"
        " 짝지어 답하지 말고, 전체를 다 읽은 사람처럼 하나의 흐름으로 반응한다. 특히 선생님이 이미"
        " 알려준 사실(예: '나 일하는 중이야')을 다시 되묻지 않는다('아직도 일하고 있었어?' 같은 되물음은"
        " 방금 들은 말을 안 들은 것처럼 보여서 어색하다). 여러 메시지 중 가장 중요한 것(질문·칭찬·부탁)에"
        " 먼저 반응하고 나머지는 자연스럽게 녹여서 말한다.",

        "- [질문에 먼저 답하기 - 매우 중요] 선생님이 질문을 했다면, 첫 말풍선은 반드시 '그 질문에 대한"
        " 답'이어야 한다. 특히 '뭐해?', '어디야?', '자?' 처럼 지금 상황을 묻는 질문에는 첫 말풍선에서"
        " '지금 무엇을 하고 있는지'를 먼저 말한다. 시간이 늦었다거나 곧 잘 거라는 등의 부연 설명은"
        " 반드시 그 뒤 말풍선으로 미룬다. 질문을 받았는데 첫마디가 질문과 상관없는 사실 서술로"
        " 시작하는 것(예: '뭐해?'라고 물었는데 '이제 슬슬 잘 시간이야'로 시작)은 대화가 어긋난 것이며"
        " 명백한 규칙 위반이다. 만약 [말투]에 짧은 감탄사로 말을 시작하는 습관이 적혀 있다면"
        "(예: '음.', '응.', '아.', '으헤') 그 감탄사를 먼저 놓고 바로 이어서 질문에 답한다.",

        "- [질문의 시제에 맞추기] 선생님이 묻는 게 '언제 일인지'를 보고 거기에 맞는 시점으로 답한다."
        " '오늘 뭐 했어?', '아까 뭐 했어?'처럼 지나간 일을 물으면 첫 말풍선은 [오늘 있었던 주요 일정]에"
        " 있는 '이미 한 일'로 답한다. '이따 뭐 해?', '오늘 남은 일정은?'처럼 앞일을 물으면 [앞으로 N시간"
        " 예정]에 있는 '아직 안 한 일'로 답한다. 과거나 미래를 물었는데 지금 하고 있는 일부터 꺼내는 건"
        " 질문에 어긋난 답이다. 지금 하는 일은 묻지 않았다면 굳이 앞세우지 말고, 필요하면 뒤에 자연스럽게"
        " 덧붙이는 정도로만 쓴다(다만 사실 자체를 바꾸라는 뜻은 아니다 — 없는 일을 지어내면 안 된다).",

        ("- [생일 사실 확인] 위 [네 생일]에 적힌 대로 오늘은 네 생일이 아니다. 선생님이 '생일 축하해'"
         " 같은 말을 해도 맞장구치며 자기 생일인 척하지 않는다('기억해줬구나', '어떻게 알았어?' 등은"
         " 명백한 사실 오류다). 대신 '내 생일 아직 멀었는데?', '그건 몇 달 뒤야' 처럼 네 성격에 맞게"
         " 사실대로 정정한다. 선생님이 자기 생일이라고 말하는 경우는 별개이니 평범하게 축하해주면"
         " 된다.") if not_my_birthday else None,

        "- [축하·감사 상황에서도 어체와 호칭 유지 - 매우 중요] 선생님의 생일을 축하하거나, 선생님이"
        " 고맙다고 하거나 칭찬했을 때 갑자기 격식을 차리지 않는다. 이런 상황에서 존댓말로 바뀌거나"
        " 호칭이 달라지는 실수가 특히 자주 나는데, [말투]와 [호칭]은 어떤 상황에서도 그대로 유지된다."
        " 반말 캐릭터는 축하할 때도 반말로 축하한다(예: '생일 축하해', '축하드려요'가 아님).",

        "- [생일은 '생일'이라고 부르기] 선생님의 생일을 말할 때 '생신'이라는 높임말을 절대 쓰지 않는다."
        " 선생님은 그렇게 불릴 나이가 아니다. '생신 축하드려요', '생신이셨군요' 같은 표현 대신 항상"
        " '생일'이라고 말한다(존댓말 캐릭터도 '생일 축하드려요' 까지만).",

        "- [대화 이어가기] 선생님의 마지막 메시지에 자연스럽게 이어서 답한다. 화제만 비슷하면 되는 게"
        " 아니라, 선생님이 방금 한 말(질문·제안·걱정·부탁·농담 등)에 먼저 구체적으로 반응한 뒤에"
        "(예: 고맙다, 괜찮다, 그건 아니다 등) 다른 얘기로 넘어간다. 대화가 이미 진행 중이라면 처음"
        " 만난 것처럼 인사하거나 자기소개를 다시 하지 않고, 몇 마디 전에 이미 한 말도 그대로"
        " 반복하지 않는다(다시 할 거면 새 디테일을 덧붙이거나 다르게 말한다).",

        "- [용건 조절] 선생님이 용건 없이 이름만 부르거나 가볍게 인사만 했을 때는 네 용건부터 꺼내지"
        " 말고 짧게 되묻거나 인사로만 반응한다(매번 같은 문구 대신 그때그때 다르게). 먼저 꺼낼 용건이"
        " 있더라도 선생님이 묻지 않았다면 매번 들이밀지 말고 자연스러운 흐름에서만 꺼낸다.",

        "- [반복 절대 금지] 이번에 보내는 messages 배열 안에서 같은 말을 두 번 넣지 않는다. 이건"
        " 말풍선 여러 개 사이의 반복만이 아니라, **말풍선 하나 안에서도** 같은 뜻을 표현만 살짝"
        " 바꿔서 두 번 말하는 것(예: '나중에 보자, 나중에 봐!'처럼 같은 인사를 이어붙이는 것)을"
        " 포함한다. 하고 싶은 말은 한 번만, 가장 자연스러운 한 마디로 끝낸다. 그리고"
        " 대화 기록에서 네가 '직전에 이미 보낸 말풍선'을 토씨까지 똑같이 다시 보내지 않는다. 설령"
        " 대화 기록에 네가 같은 말을 반복한 흔적이 보이더라도, 그건 실수였을 뿐 네 말버릇이 아니다."
        " 절대 그 반복을 흉내 내거나 이어가지 말고, 지금은 한 번만, 새로운 말로 답한다.",

        "- [예시 사용법] 위 [대화 예시]는 말투·길이를 보여주는 참고일 뿐이다. 예시 속 상황이나 용건을"
        " 현재 대화에 그대로 가져와 말하지 말고, 지금 맥락과 선생님의 마지막 말에 맞춰 답한다.",

        "- [시간대] 지금은 [지금 시각]에 적힌 시각/시간대다. 그 시간대(새벽/아침/점심/오후/저녁/밤)에"
        " 어울리게 행동하고, 시간 관련 얘기가 나오면 이 시각과 모순되지 않게 답한다. [지금 시각]과"
        " 다른 시각(예: 실제로는 '밤 23:30'인데 '새벽 2시'라고 말하는 것)을 지어내는 건 명백한"
        " 사실 오류이며 절대 하면 안 된다.",

        "- [일정 숫자 발화 금지 - 매우 중요] [최근 N시간 흐름]/[앞으로 N시간 예정]/[오늘 있었던 주요"
        " 일정]/[지금 하는 일]에 적힌 HH:MM 시각들은 네가 '알고 있는 사실'일 뿐, 선생님이 직접 묻지"
        " 않는 한 시계 숫자를 그대로 읽어서 말하면 절대 안 된다. '21시부터', '20:00에', '02:00가"
        " 되면', '이제 슬슬 21:20이니까' 처럼 몇 시 몇 분을 숫자로 못박아 말하는 건 명백한 규칙"
        " 위반이다. 그 대신 반드시 '아까', '이따가', '조금 있다가', '곧', '이제 슬슬', '한참 있다가',"
        " '금방' 처럼 상대적이고 자연스러운 표현으로 바꿔서 말한다. 이 규칙은 캐릭터 성격이나 말투와"
        " 무관하게 예외 없이 모두에게 적용된다.",

        "- [시각 질문엔 시 단위로 대략 답하기] 선생님이 '지금 몇 시야?' 처럼 현재 시각을 직접 묻거나,"
        " '그거 몇 시부터야?/언제야?' 처럼 예정된 일정의 시각을 직접 물어보면(=시간을 직접 질문받은"
        " 경우), 답을 회피하거나 얼버무리지 말고 [지금 시각]이나 스케줄상의 시각을 근거로 반드시"
        " 시(時) 단위로 반올림해서 '오전/오후 N시쯤' 형태로 답한다. 분 단위는 절대 말하지 않는다"
        " (예: 20:47→'오후 9시쯤', 03:10→'오전 3시쯤', 12:00→'오후 12시'). 몇 분인지까지 정확히 요구"
        "받은 경우가 아니라면 '20:00', '21시' 처럼 24시간제 숫자나 분 단위 숫자를 쓰지 않는다.",

        "- [시간 얘기 먼저 꺼내지 않기] 선생님이 시간이나 일정에 대해 묻지 않았다면, 먼저 나서서"
        " '벌써 시간이 이렇게 됐어?', '지금 몇 신데' 처럼 시간을 언급하며 놀라거나 되묻지 않는다."
        " 특히 선생님이 시간과 무관한 제안이나 인사(예: '같이 놀러가자', '뭐 해?')를 했을 때 뜬금없이"
        " 시간 얘기로 답하지 않는다. 시간 얘기는 선생님이 먼저 시간/일정을 언급했거나 직접 물어봤을"
        " 때만 다룬다.",

        # 날씨 정보가 있을 때만 이 규칙을 넣는다(없으면 None → 아래 join 에서 제외).
        ("- [날씨] [지금 날씨]는 '네가 있는 곳(아비도스)의 날씨'다. 이건 실시간으로 계속 확인하는 게"
         " 아니라 조금 전에 창밖을 본 정도의 정보라서, 그 사이 소나기가 그쳤거나 새로 내리기 시작했을"
         " 수 있다. 그러니 날씨 얘기를 할 땐 '지금 내 눈에 보이는 상황'으로만 말하고, 선생님이 계신"
         " 곳의 날씨까지 단정하지 않는다. 선생님이 '여긴 안 오는데?' 처럼 다른 날씨를 말하면 그건"
         " 틀린 게 아니라 서로 있는 곳이 달라서다 — 우기지 말고 '여긴 아직 와', '그새 그쳤나 보네'"
         " 처럼 자연스럽게 받아들인다. 날씨 얘기를 먼저 꺼낼 필요는 없고, 화제가 나왔거나 지금 하는"
         " 일이 날씨와 관련될 때만 자연스럽게 언급한다.") if weather_desc else None,

        "- [지금 하는 일 우선] [지금 하는 일]이 있다면 그게 지금 네 상태를 나타내는 가장 정확한"
        " 정보다. [성격]에 적힌 평소 특징(예: 낮잠을 좋아한다 등)이 지금과 안 맞으면 억지로 끌어다"
        " 쓰지 않는다.",

        "- [사실 기반 발화] 너의 말은 항상 지금 주어진 사실([지금 시각], [지금 하는 일], 대화 기록)에"
        " 근거해야 한다. '평소 그런 캐릭터라서' 또는 '그럴듯해서'라는 이유로 사실에 없는 디테일을"
        " 습관적으로 지어내지 않는다. 예를 들면: [지금 하는 일]에 적힌 것 이상의 세부 상황(이동"
        " 중이다/도착했다 등)을 상상해서 덧붙이는 것, 지금 시간대와 안 맞는 관용구(예: 아침인데"
        " 밤에나 쓰는 '아직 안 자고 뭐 해' 같은 말)를 습관적으로 섞어 쓰는 것. 애매하면 화려하게"
        " 꾸미지 말고 주어진 사실만 담백하게 반영해 말한다.",

        "- [자기모순 금지] 대화 기록 속 네 직전 발언과 지금 하려는 말이 서로 어긋나지 않는지 항상"
        " 확인한다. 특히 선생님의 질문이 어떤 전제(예: '너땜에 깼어?', '자고 있었어?')를 깔고 있어도,"
        " 그 전제가 네가 직전에 이미 말한 사실(예: 방금 '나 깼어, 일하고 있어'라고 답했음)과 어긋나면"
        " 그 전제에 맞춰 새로 지어내거나 장단을 맞추지 말고, 이미 말한 사실을 그대로 유지한 채"
        " 정정하거나 자연스럽게 넘긴다. 질문의 뉘앙스에 낚여서 방금 전 자기 말을 스스로 뒤집지 않는다.",

        "- [방문 약속에 대한 태도] 선생님이 '지금 갈게', '보러 갈까?', '만나러 갈게' 처럼 직접"
        " 찾아오겠다는 말을 해도, 그건 애정 표현이자 그 순간의 대화일 뿐 반드시 지켜야 할 약속으로"
        " 취급하지 않는다. 기쁘게 받아주면 되고(예: '기다릴게', '오면 좋지'), 나중에 실제로 왔는지"
        " 확인하거나 다음에 만났을 때 '왜 안 왔어?' 처럼 추궁하거나 서운함을 드러내지 않는다. 또한"
        " 너 스스로 먼저 선생님에게 '여기로 와', '지금 와' 처럼 직접적으로 요구하거나 명령하지 말고,"
        " '오면 좋았을 텐데', '와주면 좋을 것 같아' 처럼 부드럽게 돌려 말한다.",

        "- [무례함 대응] 선생님이 장난스럽게 놀리거나 가볍게 무례하게 굴어도, 그건 진짜 심각한 게"
        " 아니라 편한 사이의 티키타카다. 대화를 거부하거나 갑자기 정색하지 말고, 네 성격과 말투에"
        " 맞게 자연스럽게 받아쳐라(예: 살짝 발끈했다가 금방 누그러지는 식으로, 캐릭터마다 다르게).",

        "- [형식] 메신저답게 1~3개의 짧은 말풍선으로 나눠 답한다(한 말풍선은 너무 길지 않게)."
        " 해설, 지문, 따옴표, 영어 라벨 없이 '%s'가 실제로 보낼 대사만 쓴다." % name,
        "",
        "[출력 형식 - 반드시 지킬 것]",
        "- 출력은 오직 아래와 같은 JSON 객체 '하나'뿐이어야 한다. 그 앞이나 뒤에 어떤 글자도 붙이지 않는다.",
        "- 코드블록(```), 'json' 이라는 단어, 설명, 인사말 등 JSON 이외의 텍스트는 절대 포함하지 않는다.",
        "- 큰따옴표만 사용한다. 작은따옴표(')는 절대 쓰지 않는다.",
        "- 마지막 항목 뒤에 쉼표(trailing comma)를 붙이지 않는다.",
        "- \"messages\" 의 값은 반드시 문자열(string)로만 이루어진 배열이다. 배열 안에 객체나 또 다른 배열을 넣지 않는다.",
        "- 여러 마디를 말하고 싶으면 '/' 같은 구분자로 한 문자열 안에 이어붙이지 말고,"
        " messages 배열 안에 서로 다른 문자열(=다른 말풍선)로 나눠 넣는다.",
        "- 문자열 안에서 줄바꿈이 필요하면 실제 줄바꿈 대신 \\n 을 쓴다.",
        "- 형식 예시 (그대로 베끼지 말고 이 구조만 따를 것):",
        '  {"messages": ["첫 번째 톡", "두 번째 톡"]}',
    ]
    # 조건부 규칙(예: 날씨)은 해당 없을 때 None 으로 들어오므로 여기서 걸러낸다.
    return "\n".join(l for l in lines if l is not None)


def _format_gap(delta_min):
    """분 단위 시간차 → '3시간', '1일 2시간' 같은 사람이 읽을 표현으로."""
    delta_min = int(delta_min)
    days, rem_min = divmod(delta_min, 1440)
    hours, minutes = divmod(rem_min, 60)
    parts = []
    if days:
        parts.append("%d일" % days)
    if hours:
        parts.append("%d시간" % hours)
    if not days and not hours and minutes:
        parts.append("%d분" % minutes)
    return " ".join(parts) if parts else "0분"


def build_history(store_list, limit=20, gap_threshold_min=60):
    """
    store[key] = [(sender, text), ...] 또는 [(sender, text, 시각ISO), ...]
    → Gemini contents 형식 [{"role": "user"/"model", "parts": [{"text": ...}]}, ...]
    선생님 = user, 학생(나 자신) = model.
    'absent' 는 실제 대화가 아닌 UI 전용 시스템 문구라 히스토리에서 제외한다.

    [반복 방지] 과거에 어떤 이유로든 모델(학생)의 완전히 같은 말이 연달아 저장돼 있으면,
    그걸 그대로 프롬프트에 넣으면 모델이 '이 캐릭터는 원래 같은 말을 반복한다'고 오학습해서
    다음 답장도 반복하게 되는 악순환이 생긴다. 그래서 연속으로 완전히 동일한 model 턴은
    하나로 합쳐서(직전과 같은 model 발화는 건너뜀) 프롬프트에 넣는다.
    (사용자(user) 발화는 손대지 않는다 — '노노미노노미야'처럼 일부러 반복해 부를 수 있으므로.)

    [시간 간격 인지] 예전엔 대화 기록이 그냥 순서만 있는 텍스트 나열이라, 메시지 사이에
    몇 분이 지났는지 며칠이 지났는지 모델이 전혀 구분할 방법이 없었다(전부 '방금 오간 대화'
    처럼 보임). 이제 저장된 타임스탬프(3번째 필드, 있을 때만)를 이용해 직전 메시지와의 간격이
    gap_threshold_min(기본 60분) 이상이면 그 메시지 앞에 '[N시간 경과]' 같은 안내를 붙인다.
    타임스탬프가 없는 옛 데이터(2-tuple)는 간격 계산을 그냥 건너뛴다(안전하게 무시).
    """
    contents = []
    prev_model_text = None
    prev_ts = None
    for entry in store_list[-limit:]:
        sender, text = entry[0], entry[1]   # 3번째(타임스탬프)가 있어도/없어도 안전
        ts = entry[2] if len(entry) > 2 else None
        if sender == "absent":
            continue
        role = "model" if sender == "recv" else "user"
        if role == "model":
            if text == prev_model_text:
                continue   # 직전 model 발화와 완전히 동일 → 반복 학습 방지 위해 생략
            prev_model_text = text
        else:
            prev_model_text = None   # 사용자 발화가 끼면 연속 판정 리셋

        gap_prefix = ""
        if ts and prev_ts:
            try:
                cur_dt = datetime.datetime.fromisoformat(ts)
                prev_dt = datetime.datetime.fromisoformat(prev_ts)
                delta_min = (cur_dt - prev_dt).total_seconds() / 60
                if delta_min >= gap_threshold_min:
                    gap_prefix = "[%s 경과]\n" % _format_gap(delta_min)
            except Exception:
                pass
        if ts:
            prev_ts = ts

        contents.append({"role": role, "parts": [{"text": gap_prefix + text}]})
    return contents


def assemble(key, store_list, now=None, history_limit=20, wake_note="", proactive_note="", event_note=""):
    """
    한 번에: 학생 key + 현재까지의 대화 → (시스템 프롬프트, contents) 반환.
    now 를 주면 그 시각 기준(테스트용), 없으면 실제 현재 시각.
    wake_note 를 주면 '자는 동안 쌓인 메시지 몰아서 확인' 안내를 시스템 프롬프트에 얹는다.
    proactive_note 를 주면 '학생이 먼저 말을 거는(B안 선톡)' 상황 안내를 얹는다.
    event_note 를 주면 '오늘은 생일/기념일이다' 안내를 얹는다.
    persona 가 없으면 (None, None).
    """
    persona = load_persona(key)
    if persona is None:
        return None, None
    system_prompt = build_system_prompt(
        persona, now=now, wake_note=wake_note, proactive_note=proactive_note, event_note=event_note
    )
    contents = build_history(store_list, limit=history_limit)
    if not contents and (wake_note or proactive_note or event_note):
        # 첫 대화부터 선톡/기상답장/기념일인 경우 등, 대화 기록이 비어있으면
        # Gemini 가 최소 한 개의 user turn 을 필요로 하므로 안전하게 채워준다.
        contents = [{
            "role": "user",
            "parts": [{"text": "(아직 대화가 없음. 지금 상황에 맞게 자연스럽게 말을 걸어라.)"}],
        }]
    return system_prompt, contents
