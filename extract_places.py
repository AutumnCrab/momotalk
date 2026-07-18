# -*- coding: utf-8 -*-
"""
1단계+1.5단계: activity 자유텍스트 -> {"text","place","with","tag"} 구조화 + data/places.json 생성.
- place는 "상태기계"로 판정한다: 명시적 장소 단서가 나오면 갱신, 없으면 직전 상태를 이어간다.
- with는 이번 스텝에서는 이름 언급 기반으로만 보조 채움(최종 co-presence 판정은 place 일치가 기준).
- tag는 (O)/(X)/(S)/(W) 마커를 그대로 옮긴다. 여러 개면 우선순위 O>S>W>X.
"""
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
KEYS = ["shiroko", "hoshino", "serika", "ayane", "nonomi", "kuroko"]

# (canonical place, [keyword list], rank)  -- rank 2 = 항상 우선(명시적 이동), rank 1 = 일반 "학교"(하위 랭크에서만 승격)
SPECIFIC_RULES = [
    ("시바세키 라멘집", ["시바세키", "라멘집", "라멘 아르바이트", "라멘 알바", "라멘으로"]),
    ("동아리실", ["동아리실"]),
    ("사격장", ["사격 훈련", "사격훈련", "사격 준비", "사격장", "주특기 훈련"]),
    ("운동장", ["운동장"]),
    ("빈 창고", ["창고"]),
    ("빈 교실", ["옆 교실"]),
    ("마트", ["마트"]),
    ("시장", ["시장에서"]),
    ("슈퍼", ["슈퍼"]),
    ("카페", ["카페"]),
    ("자전거샵", ["자전거 샵"]),
    ("아비도스 사막", ["사막"]),
    ("번지 산책로", ["번지 산책", "자치구 산책", "자치구를 돌", "자치구 순회", "자치구를 걷다", "자치구 외곽", "주변 번지"]),
    ("아비도스 순찰로", ["순찰"]),
    ("식당", ["부원들과 식당으로 이동", "식당으로 이동"]),
]

SCHOOL_GENERIC_KEYWORDS = ["학교", "교실 도착"]
GO_TO_SCHOOL_KEYWORDS = ["등교"]
GO_HOME_KEYWORDS = ["하교", "귀가"]

RANK_HOME = 0
RANK_SCHOOL_GENERIC = 1
RANK_SPECIFIC = 2

NAME_MAP = {
    "shiroko": "시로코", "hoshino": "호시노", "serika": "세리카",
    "ayane": "아야네", "nonomi": "노노미", "kuroko": "시로코*테러",
}


def extract_tag(desc):
    # 우선순위: O > S > W > X (동시에 여럿이면 대표 하나만 tag로, 나머지는 text에 이미 남아있음)
    if "(O)" in desc:
        return "O"
    if "(S)" in desc or "(취침)" in desc:
        return "S"
    if "(W)" in desc:
        return "W"
    if "(X)" in desc:
        return "X"
    return None


def extract_with(desc, my_key):
    found = []
    for k, name in NAME_MAP.items():
        if k == my_key:
            continue
        if name in desc:
            found.append(k)
    return found


def classify_day(entries_sorted):
    """entries_sorted: [(mins, t, desc)] 시간순 -> [(t, desc, place, rank)]"""
    state_place = "집"
    state_rank = RANK_HOME
    out = []
    for mins, t, desc in entries_sorted:
        # 동물/고유명사 안에 장소 키워드 글자가 우연히 포함된 경우 예외 처리(예: '사막여우'는 장소 '사막'이 아님)
        FALSE_POSITIVE_SUBSTR = ["사막여우"]
        desc_for_match = desc
        for fp in FALSE_POSITIVE_SUBSTR:
            desc_for_match = desc_for_match.replace(fp, "")

        matched_place = None
        for place, kws in SPECIFIC_RULES:
            if any(kw in desc_for_match for kw in kws):
                matched_place = place
                break
        if matched_place:
            state_place, state_rank = matched_place, RANK_SPECIFIC
            out.append((t, desc, matched_place))
            continue

        if any(kw in desc for kw in SCHOOL_GENERIC_KEYWORDS) or any(kw in desc for kw in GO_TO_SCHOOL_KEYWORDS):
            if state_rank < RANK_SCHOOL_GENERIC:
                state_place, state_rank = "학교", RANK_SCHOOL_GENERIC
            # 이미 특정 서브공간(동아리실 등)에 있었다면 그 상태를 유지(강등 안 함)
            out.append((t, desc, state_place))
            continue

        if any(kw in desc for kw in GO_HOME_KEYWORDS):
            # 이동 중 = 고정 장소 없음. 이후 상태는 집으로 리셋.
            out.append((t, desc, None))
            state_place, state_rank = "집", RANK_HOME
            continue

        # 단서 없음 -> 직전 상태 이어감
        out.append((t, desc, state_place))
    return out


def _parse_hhmm(s):
    h, m = s.strip().split(":")
    return int(h) * 60 + int(m)


def main():
    place_registry = {}
    for key in KEYS:
        path = os.path.join(BASE, "prompts", key + ".json")
        with open(path, encoding="utf-8") as f:
            persona = json.load(f)
        new_activity = {}
        for day, day_map in persona["activity"].items():
            entries = []
            for t, desc in day_map.items():
                entries.append((_parse_hhmm(t), t, desc))
            entries.sort(key=lambda x: x[0])
            classified = classify_day(entries)
            new_day = {}
            for t, desc, place in classified:
                new_day[t] = {
                    "text": desc,
                    "place": place,
                    "with": extract_with(desc, key),
                    "tag": extract_tag(desc),
                }
                if place:
                    place_registry.setdefault(place, 0)
                    place_registry[place] += 1
            new_activity[day] = new_day
        persona["activity"] = new_activity
        out_path = os.path.join(BASE, "prompts", key + ".json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(persona, f, ensure_ascii=False, indent=2)
        print("[OK]", key)

    # 카테고리 대략 분류(수동 큐레이션 필요하면 나중에 손보기 쉽게 최소 정보만)
    CATEGORY_MAP = {
        "집": "집", "동아리실": "학교", "사격장": "학교", "운동장": "학교", "학교": "학교",
        "빈 창고": "학교", "빈 교실": "학교",
        "시바세키 라멘집": "식당", "식당": "식당", "카페": "카페",
        "마트": "상점", "시장": "상점", "슈퍼": "상점", "자전거샵": "상점",
        "아비도스 사막": "야외", "번지 산책로": "야외", "아비도스 순찰로": "야외",
    }
    places_json = {}
    for place, count in sorted(place_registry.items(), key=lambda x: -x[1]):
        places_json[place] = {"category": CATEGORY_MAP.get(place, "기타"), "entry_count": count}
    with open(os.path.join(BASE, "data", "places.json"), "w", encoding="utf-8") as f:
        json.dump(places_json, f, ensure_ascii=False, indent=2)
    print("[OK] data/places.json (%d개 장소)" % len(places_json))


if __name__ == "__main__":
    main()
