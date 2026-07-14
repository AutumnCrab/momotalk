# -*- coding: utf-8 -*-
"""
학생별 프롬프트 JSON(prompts/<key>.json)을 읽어
Gemini에 보낼 [시스템 프롬프트 문자열] + [대화 히스토리]로 조립한다.

- daily_context 는 요일별 '배열'이며, 답장할 때마다 그중 하나를 랜덤으로 뽑는다(B 방식).
- 실제 API 호출은 하지 않는다. (그건 gemini_client 단계에서)
- 파일명 key 는 dialogues.json 의 학생 key 와 같아야 한다. (shiroko.json ↔ "shiroko")
"""

import os
import json
import random
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # datetime.weekday(): 월=0


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


def current_activity(persona, now=None):
    """
    persona['activity'][요일] = {"HH:MM": "행동", ...} 에서
    지금 시각이 속한 구간(가장 최근에 시작된 항목)을 찾는다.
    자정을 넘겨 이어지는 경우(오늘 첫 항목보다 이른 시각)엔 어제의 마지막 항목을 이어서 본다.
    반환: (시작시각 문자열, 설명) 또는 (None, None) (activity 필드가 없거나 못 찾은 경우)
    """
    if now is None:
        now = datetime.datetime.now()
    activity = persona.get("activity")
    if not activity:
        return None, None

    def _sorted_entries(day_map):
        out = []
        for t, desc in (day_map or {}).items():
            try:
                out.append((_parse_hhmm(t), t, desc))
            except Exception:
                continue
        out.sort(key=lambda x: x[0])
        return out

    wd = now.weekday()
    cur = now.hour * 60 + now.minute

    today_entries = _sorted_entries(activity.get(WEEKDAY_KEYS[wd]))
    best = None
    for mins, t, desc in today_entries:
        if mins <= cur:
            best = (t, desc)
        else:
            break
    if best is not None:
        return best

    # 오늘 첫 항목보다 이른 시각(자정 근처)이면 어제의 마지막 항목이 이어지는 것으로 본다
    yest_entries = _sorted_entries(activity.get(WEEKDAY_KEYS[(wd - 1) % 7]))
    if yest_entries:
        _, t, desc = yest_entries[-1]
        return (t, desc)
    return None, None


def build_proactive_note(activity_desc):
    """활동 전환 시점에 학생이 먼저 말 거는(B안) 상황을 시스템 프롬프트에 얹을 안내문."""
    if not activity_desc:
        return ""
    return (
        "[선톡 상황]\n"
        "지금은 선생님이 아무 말도 하지 않았고, 네가 먼저 말을 거는 상황이다.\n"
        "지금 네가 하고 있는 일: %s\n"
        "너무 뜬금없이 네 상황부터 늘어놓지 말 것. 먼저 선생님을 부르거나 안부·근황을 묻는"
        " 짧은 한마디로 시작한 다음(예: 지금 뭐 하고 있는지 궁금해하는 식), 자연스럽게"
        " 네가 하고 있는 일이나 하고 싶은 말로 이어가라. 1~2개의 짧은 말풍선으로, 편하게"
        " 톡을 보내는 느낌이면 된다. 너무 격식 차리지 말 것."
        % activity_desc
    )


def is_persona_birthday(persona, now=None):
    """persona['birthday'] = 'MM-DD' 가 오늘이면 True."""
    bday = persona.get("birthday")
    if not bday:
        return False
    if now is None:
        now = datetime.datetime.now()
    return now.strftime("%m-%d") == bday


def build_event_note(kind, extra=None):
    """기념일 종류별 시스템 프롬프트 지시문. AI가 알아서 자연스럽게 표현하도록만 지시하고,
    구체적 대사는 하나도 미리 정해두지 않는다."""
    if kind == "own_birthday":
        return (
            "[오늘의 특별한 날]\n"
            "오늘은 너의 생일이다. 대화 중 자연스럽게 그 사실이 드러나도 좋고, 선생님이 먼저 축하해주면"
            " 기쁘게 반응해라. 너무 호들갑 떨 필요 없이 딱 너다운 방식으로 받아들이면 된다."
        )
    if kind == "teacher_birthday":
        return (
            "[오늘의 특별한 날]\n"
            "오늘은 선생님의 생일이다. 진심을 담아 축하 인사를 건네라. 너의 성격과 말투에 맞는 방식으로"
            " 축하하면 된다."
        )
    if kind == "world_holiday":
        name = extra or "특별한 날"
        return (
            "[오늘의 특별한 날]\n"
            "오늘은 %s다. 이 날에 어울리는 화제나 인사를 자연스럽게 꺼내라." % name
        )
    return ""


def pick_random_awake_datetime(persona, date):
    """
    지정한 날짜(date: datetime.date)의 awake 구간 중 하나를 골라 그 안의 임의 시각을 반환.
    기념일 메시지를 '그 학생이 깨어있는 시간 중 아무 때나'에 보내기 위한 용도.
    구간이 없으면 None. 자정을 넘기는 구간은 '오늘' 몫(자정까지)만 대상으로 삼는다.
    """
    wd = date.weekday()
    raw = (persona.get("awake") or {}).get(WEEKDAY_KEYS[wd], [])
    ranges = []
    for part in raw:
        try:
            s, e = part.split("-")
            sm, em = _parse_hhmm(s), _parse_hhmm(e)
            if em <= sm:
                em = 24 * 60      # 자정 넘김 구간은 오늘 몫(자정까지)만 사용
            if em > sm:
                ranges.append((sm, em))
        except Exception:
            continue
    if not ranges:
        return None

    total = sum(e - s for s, e in ranges)
    pick = random.uniform(0, total)
    acc = 0
    chosen = ranges[-1]
    for s, e in ranges:
        if acc + (e - s) >= pick:
            chosen = (s, e)
            break
        acc += (e - s)
    minute = min(random.randint(chosen[0], chosen[1] - 1), 23 * 60 + 59)
    return datetime.datetime.combine(date, datetime.time(minute // 60, minute % 60))


def _awake_ranges(persona, weekday_idx):
    """persona['awake'][요일] = ['HH:MM-HH:MM', ...] → [(start_분,end_분), ...]. 필드 없으면 None(=제한 없음)."""
    awake = persona.get("awake")
    if not awake:
        return None
    wk = WEEKDAY_KEYS[weekday_idx % 7]
    raw = awake.get(wk)
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

    wd = now.weekday()
    cur = now.hour * 60 + now.minute

    today_ranges = _awake_ranges(persona, wd)
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
    yest_ranges = _awake_ranges(persona, wd - 1) or []
    for start, end in yest_ranges:
        if start > end and cur < end:
            return True

    return False


def build_wake_note(pending_msgs, now=None):
    """
    수면 중 쌓인 메시지를 '깨어나서 확인한 메시지' 안내 블록으로 조립.
    pending_msgs: [{"text": str, "at": ISO 시각 문자열}, ...]
    """
    if not pending_msgs:
        return ""
    lines = [
        "[깨어나서 확인한 메시지]",
        "네가 자는 동안 선생님이 아래 메시지를 보냈다. 지금 막 깨어나 그것들을 몰아서 확인한 상황이다.",
        "첫 마디를 네가 지금 뭘 하고 있었는지, 어디 있는지 같은 네 얘기로 시작하지 말 것."
        " 자다가 이제 막 확인했다는 걸 자연스럽게 티내면서, 선생님이 무슨 일로 불렀는지"
        " 되묻거나 선생님이 보낸 내용에 먼저 반응하는 것으로 시작해라. 네 얘기는 그다음에 이어가도 된다.",
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
    _, activity_desc = current_activity(persona, now)
    # activity(시간 단위 정밀 스케줄)가 있으면 그것만 쓰고, 없을 때만 daily_context(요일별 랜덤 상황)로 대체.
    # 서로 다른 상황 정보를 동시에 주면 혼란스러우니 항상 하나만 쓴다.
    today = None if activity_desc else pick_daily_context(persona, weekday=now.weekday())

    lines = [
        "너는 '%s'(이)라는 학생이고, 메신저 앱(모모톡)으로 선생님과 1:1로 대화하고 있다." % name,
        "",
        "[성격] %s" % persona.get("persona", ""),
        "[말투] %s" % persona.get("speech_style", ""),
        "[지금 시각] %s" % time_label,
    ]
    if activity_desc:
        lines.append("[지금 하는 일] %s" % activity_desc)
    elif today:
        lines.append("[오늘의 상황] %s" % today)
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
        "- 선생님의 마지막 메시지에 자연스럽게 이어서 답한다.",
        "- 선생님이 용건 없이 이름만 부르거나 가볍게 인사만 했을 때는, 네 용건을 먼저 꺼내지 말고"
        " 짧게 되묻거나 인사로만 반응한다. 매번 같은 문구를 쓰지 말고 그때그때 다르게 표현한다.",
        "- 대화 기록에 이미 오간 대화가 있다면, 처음 만난 것처럼 인사하거나 자기소개를 다시 하지 않는다."
        " 이미 진행 중인 대화의 흐름을 자연스럽게 이어간다. 특히 네가 먼저 말을 건 뒤 선생님이 답했다면,"
        " 그 답에 자연스럽게 이어서 말하되 대화를 처음부터 다시 시작하지 않는다.",
        "- 위 [대화 예시]는 말투·길이를 보여주는 참고일 뿐이다. 예시 속 상황이나 용건을"
        " 현재 대화에 그대로 가져와 말하지 말고, 지금 맥락과 선생님의 마지막 말에 맞춰 답한다.",
        "- 먼저 꺼낼 용건이 있더라도, 선생님이 묻지 않았다면 매번 들이밀지 말고 자연스러운 흐름에서만 꺼낸다.",
        "- 지금은 [지금 시각]에 적힌 시각/시간대다. 그 시간대(새벽/아침/점심/오후/저녁/밤)에"
        " 어울리게 행동하고, 시간을 묻거나 시간 관련 얘기가 나오면 이 시각을 기준으로 답한다.",
        "- [지금 하는 일]이 있다면 그게 지금 네 상태를 나타내는 가장 정확한 정보다. [성격]에 적힌"
        " 평소 특징(예: 낮잠을 좋아한다, 게으르다 등)은 성향일 뿐이니, 지금 실제로 하는 일과 안 맞으면"
        " 그 특징 단어를 억지로 끌어다 쓰지 말고 [지금 하는 일]에 맞게 말한다.",
        "- [지금 하는 일]에 적힌 문구 이상의 상황을 스스로 지어내지 않는다. 예를 들어 '등교'라고만"
        " 적혀 있으면 그건 등교와 관련된 일을 하고 있다는 뜻일 뿐, '이동 중이다'/'아직 도착 전이다'/"
        "'이미 도착했다' 같은 세부 상황을 마음대로 상상해서 덧붙이지 않는다. 애매하면 문구 그대로만"
        " 담백하게 반영해 말한다.",
        "- 메신저답게 1~3개의 짧은 말풍선으로 나눠 답한다. (한 말풍선은 너무 길지 않게)",
        "- 해설, 지문, 따옴표, 영어 라벨 없이 '%s'가 실제로 보낼 대사만 쓴다." % name,
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
    return "\n".join(lines)


def build_history(store_list, limit=20):
    """
    store[key] = [(sender, text), ...]  (sender: 'recv'=학생, 'send'=선생님, 'absent'=부재중 안내)
    → Gemini contents 형식 [{"role": "user"/"model", "parts": [{"text": ...}]}, ...]
    선생님 = user, 학생(나 자신) = model.
    'absent' 는 실제 대화가 아닌 UI 전용 시스템 문구라 히스토리에서 제외한다.
    """
    contents = []
    for sender, text in store_list[-limit:]:
        if sender == "absent":
            continue
        role = "model" if sender == "recv" else "user"
        contents.append({"role": role, "parts": [{"text": text}]})
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
