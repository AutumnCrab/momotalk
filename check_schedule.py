# -*- coding: utf-8 -*-
"""
스케줄 정합성 자동 검사기.
규칙:
  1. [이름 언급 불일치] A의 activity 텍스트에 B 이름이 나오는데, 같은 요일·시각(정확히 일치하는
     슬롯)에 B의 place가 A의 place와 다르면 경고. (같은 사건을 서로 다른 장소로 기록 중일 가능성)
  2. [장소 오타 의심] place 값이 data/places.json에 없는 새 값이면 경고.
앱 시작 시 or 이 스크립트 단독 실행으로 콘솔에 경고만 출력(강제 차단 없음).
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
KEYS = ["shiroko", "hoshino", "serika", "ayane", "nonomi", "kuroko",
        "aru", "mutsuki", "kayoko", "haruka",
        "momoi", "midori", "yuzu", "aris", "kei",
        "hina", "ako", "iori", "chinatsu"]
NAME_MAP = {
    "shiroko": "시로코", "hoshino": "호시노", "serika": "세리카",
    "ayane": "아야네", "nonomi": "노노미", "kuroko": "시로코*테러",
    "aru": "아루", "mutsuki": "무츠키", "kayoko": "카요코", "haruka": "하루카",
    "momoi": "모모이", "midori": "미도리", "yuzu": "유즈",
    "aris": "아리스", "kei": "케이", "hina": "히나", "ako": "아코",
    "iori": "이오리", "chinatsu": "치나츠",
}


def load_all():
    """평소 주간 스케줄. {학생: {요일: {시각: entry}}}"""
    data = {}
    for k in KEYS:
        with open(os.path.join(BASE, "prompts", k + ".json"), encoding="utf-8") as f:
            data[k] = json.load(f)["activity"]
    return data


def load_event_schedules():
    """특별기간 이벤트 스케줄을 주간 스케줄과 '같은 모양'으로 바꿔서 돌려준다.
    요일 자리에 'day1/day2/day3' 이 들어갈 뿐이라, 아래 검사 규칙 3개를 그대로 재사용할 수 있다.
    반환: [(이벤트이름, {학생: {day1: {시각: entry}}}), ...]. events 폴더가 없으면 빈 리스트."""
    events_dir = os.path.join(BASE, "data", "events")
    if not os.path.isdir(events_dir):
        return []
    out = []
    for fname in sorted(os.listdir(events_dir)):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(events_dir, fname), encoding="utf-8") as f:
                ev = json.load(f)
        except Exception as e:
            print("[이벤트] %s 읽기 실패: %r" % (fname, e))
            continue
        schedules = ev.get("schedules") or {}
        # 검사 루프가 KEYS 전부를 훑으므로, 참가 안 하는 학생은 빈 dict 로 채워둔다
        data = {k: schedules.get(k, {}) for k in KEYS}
        out.append((ev.get("name", ev.get("id", fname)), data))
    return out


def _parse_hhmm(s):
    h, m = s.strip().split(":")
    return int(h) * 60 + int(m)


def _travel_minutes(place_a, place_b, places_registry, travel_data):
    """place_a -> place_b 최소 이동시간(분). place_overrides 우선, 없으면 카테고리 매트릭스."""
    if place_a == place_b:
        return 0
    cat_a = places_registry.get(place_a, {}).get("category", "기타")
    cat_b = places_registry.get(place_b, {}).get("category", "기타")

    overrides = travel_data.get("place_overrides", {})
    for src, dst in ((place_a, place_b), (place_b, place_a)):
        if src in overrides:
            table = overrides[src]
            if dst in table:
                return table[dst]
            other_cat = cat_b if src == place_a else cat_a
            if other_cat in table:
                return table[other_cat]

    if cat_a == cat_b:
        return travel_data.get("_같은카테고리내부", {}).get(cat_a, 0)
    key1, key2 = "%s|%s" % (cat_a, cat_b), "%s|%s" % (cat_b, cat_a)
    matrix = travel_data.get("matrix", {})
    return matrix.get(key1, matrix.get(key2, 30))  # 매트릭스에 없으면 30분(보수적 기본값)


def check_schedule_set(data, label=""):
    """주간 스케줄이든 이벤트 스케줄이든 같은 규칙 3개로 검사한다.
    data 는 {학생: {구간키: {시각: entry}}} 형태(구간키 = 요일 또는 day1/day2/day3)."""
    prefix = ("[%s] " % label) if label else ""
    with open(os.path.join(BASE, "data", "places.json"), encoding="utf-8") as f:
        known_places = set(json.load(f).keys())

    warnings = []

    # 규칙 1: 이름 언급 있는데 같은 시각 place 불일치
    for me in KEYS:
        for day, day_map in data[me].items():
            for t, entry in day_map.items():
                place = entry.get("place")
                text = entry.get("text", "")
                for other, other_name in NAME_MAP.items():
                    if other == me:
                        continue
                    if other_name not in text:
                        continue
                    other_entry = data[other].get(day, {}).get(t)
                    if not other_entry:
                        continue  # 상대 쪽엔 이 정확한 시각 슬롯이 없음(다른 시각으로 기록) -> 스킵
                    other_place = other_entry.get("place")
                    if place != other_place:
                        warnings.append(
                            "%s[이름언급 불일치] %s(%s) %s %s: place=%r / 언급된 %s(%s)의 같은 시각 place=%r"
                            % (prefix, me, NAME_MAP[me], day, t, place, other, other_name, other_place)
                        )

    # 규칙 2: place가 마스터 목록에 없음(오타/신규)
    for me in KEYS:
        for day, day_map in data[me].items():
            for t, entry in day_map.items():
                place = entry.get("place")
                if place and place not in known_places:
                    warnings.append(
                        "%s[미등록 장소] %s %s %s: place=%r 가 data/places.json에 없음"
                        % (prefix, me, day, t, place)
                    )

    # 규칙 3: 이동시간 불가능(같은 학생, 같은 요일 내 연속 슬롯 간 장소가 바뀌었는데 시간이 부족)
    with open(os.path.join(BASE, "data", "places.json"), encoding="utf-8") as f:
        places_registry = json.load(f)
    with open(os.path.join(BASE, "data", "travel_times.json"), encoding="utf-8") as f:
        travel_data = json.load(f)

    for me in KEYS:
        for day, day_map in data[me].items():
            entries = []
            for t, entry in day_map.items():
                place = entry.get("place")
                if place is None:
                    continue  # 이동 중 슬롯(등교/하교)은 그 자체로 이동시간을 대변하므로 스킵
                entries.append((_parse_hhmm(t), t, place))
            entries.sort(key=lambda x: x[0])
            for (m1, t1, p1), (m2, t2, p2) in zip(entries, entries[1:]):
                if p1 == p2:
                    continue
                gap = m2 - m1
                need = _travel_minutes(p1, p2, places_registry, travel_data)
                if gap < need:
                    warnings.append(
                        "%s[이동시간 부족] %s %s: %s(%s) -> %s(%s) 간격 %d분, 필요 이동시간 %d분"
                        % (prefix, me, day, t1, p1, t2, p2, gap, need)
                    )

    return warnings


def check():
    """평소 주간 스케줄 + 모든 특별기간 이벤트 스케줄을 한꺼번에 검사한다."""
    warnings = check_schedule_set(load_all())
    for ev_name, ev_data in load_event_schedules():
        warnings += check_schedule_set(ev_data, label=ev_name)
    return warnings


def _slot_count(data):
    return sum(len(day_map) for student in data.values() for day_map in student.values())


if __name__ == "__main__":
    # '무엇을 검사했는지'를 먼저 보여준다. 경고 건수만 찍으면 이벤트를 조용히 건너뛴 건지
    # 검사했는데 문제가 없는 건지 구분이 안 돼서 헷갈린다.
    weekly = load_all()
    events = load_event_schedules()
    print("[검사 대상] 주간 스케줄 %d명 / %d슬롯" % (len(weekly), _slot_count(weekly)))
    if events:
        for ev_name, ev_data in events:
            print("            특별기간 '%s' / %d슬롯" % (ev_name, _slot_count(ev_data)))
    else:
        print("            (특별기간 이벤트 없음 - data/events/ 폴더가 비어있거나 없음)")

    warnings = check()
    print()
    if not warnings:
        print("[정합성 검사] 문제 없음")
    else:
        print("[정합성 검사] 경고 %d건" % len(warnings))
        for w in warnings:
            print(" -", w)
