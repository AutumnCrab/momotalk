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
KEYS = ["shiroko", "hoshino", "serika", "ayane", "nonomi", "kuroko"]
NAME_MAP = {
    "shiroko": "시로코", "hoshino": "호시노", "serika": "세리카",
    "ayane": "아야네", "nonomi": "노노미", "kuroko": "시로코*테러",
}


def load_all():
    data = {}
    for k in KEYS:
        with open(os.path.join(BASE, "prompts", k + ".json"), encoding="utf-8") as f:
            data[k] = json.load(f)["activity"]
    return data


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


def check():
    data = load_all()
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
                            "[이름언급 불일치] %s(%s) %s %s: place=%r / 언급된 %s(%s)의 같은 시각 place=%r"
                            % (me, NAME_MAP[me], day, t, place, other, other_name, other_place)
                        )

    # 규칙 2: place가 마스터 목록에 없음(오타/신규)
    for me in KEYS:
        for day, day_map in data[me].items():
            for t, entry in day_map.items():
                place = entry.get("place")
                if place and place not in known_places:
                    warnings.append(
                        "[미등록 장소] %s %s %s: place=%r 가 data/places.json에 없음"
                        % (me, day, t, place)
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
                        "[이동시간 부족] %s %s: %s(%s) -> %s(%s) 간격 %d분, 필요 이동시간 %d분"
                        % (me, day, t1, p1, t2, p2, gap, need)
                    )

    return warnings


if __name__ == "__main__":
    warnings = check()
    if not warnings:
        print("[정합성 검사] 문제 없음")
    else:
        print("[정합성 검사] 경고 %d건" % len(warnings))
        for w in warnings:
            print(" -", w)
