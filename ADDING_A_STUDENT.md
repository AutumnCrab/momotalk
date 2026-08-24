# 새 학생 추가 파이프라인

모모톡 위젯에 학생(캐릭터)을 새로 추가할 때 AI(Claude 등)에게 그대로 넘겨주는 작업 순서.
흥신소 68 4명(아루/무츠키/카요코/하루카) 추가 작업에서 실제로 밟은 순서를 기준으로 정리함.

## 0. 시작 전에 사용자가 정해야 하는 것

- **key** (영문, 소문자, JSON 파일명/코드 전역에서 쓰는 식별자, 예: `aru`)
- **이름/풀네임** (예: "아루" / "리쿠하치마 아루")
- **소속 그룹** — 기존 그룹(아비도스)에 넣을지, 새 그룹으로 분리할지. 그룹이 다르면 서로
  같은 장소에 있어도 마주치지 않게 만들 수 있음(아비도스 6명 vs 흥신소 68 4명이 그 예).
- **성격 / 말투 / 대사 예시(few_shot)** — 이건 AI가 임의로 창작하지 말고 사용자가 직접 제공한
  내용을 스키마에 맞춰 옮기기만 할 것. (흥신소 68 때 사용자가 명시적으로 요구한 원칙.)
- **생일**(MM-DD)
- **프로필 사진**은 나중에 사용자가 직접 `assets/profiles/<key>.png`에 넣는 걸로 미뤄도 됨.

## 1. `prompts/<key>.json` 작성

기존 캐릭터 파일(`prompts/aru.json` 등)을 템플릿으로 그대로 베껴서 채운다. 필드:

```json
{
  "key": "aru",
  "name": "아루",
  "age": 18,
  "persona": "성격 설명(문단, 배경/관계/성격 갭 등)",
  "speech_style": "말투 규칙 — 반말/존댓말, 말버릇, 자기 지칭, 생일 반응 패턴 등",
  "address_terms": {
    "teacher": ["선생님", "..."],
    "그룹원_key": "그 학생을 부르는 호칭"
  },
  "birthday_few_shot": {
    "own_birthday": ["...", "..."],
    "teacher_birthday": ["...", "..."]
  },
  "few_shot": [
    { "user": "...", "reply": ["...", "..."] }
  ],
  "awake": { "mon": ["08:00-00:00"], "tue": [...], ... },
  "activity": {
    "mon": {
      "08:00": { "text": "...", "place": "...", "with": ["다른_key"], "tag": null },
      ...
    },
    ...
  },
  "birthday": "MM-DD"
}
```

체크리스트:
- `awake`/`activity`는 요일 7개(mon~sun) 전부 채운다.
- `activity`의 `with`에는 **같은 그룹 소속 key만** 넣는다. 다른 그룹 학생 key를 넣지 않는다
  (co-presence를 그룹 간에 절대 엮지 않기 위함 — 아래 3번 항목 참고).
- `place`가 `null`이면 "이동 중이라 고정 장소 없음"으로 처리됨.
- 새 장소를 쓰면 4번 항목에서 `data/places.json`에도 등록해야 함.
- `tag`는 특별한 표식이 필요할 때만(`"O"`=단체 일정, `"W"`=부재중/자리 비움 등 기존 관례를
  다른 캐릭터 파일에서 확인하고 맞춰 씀). 없으면 `null`.
- 다 쓴 뒤 `python check_schedule.py`로 검증(4번 항목).

## 2. `data/dialogues.json` 에 항목 추가

`characters` 객체 안에 key로 추가한다(UI 학생 목록에 뜨는 최소 정보):

```json
"아루": {
  "name": "아루",
  "full_name": "리쿠하치마 아루",
  "profile_img": "assets/profiles/aru.png",
  "intro": "한 줄 소개",
  "schedule": [
    { "day": "everyday", "time": "08:00", "messages": ["아침 인사 대사"] }
  ]
}
```
(실제 최상위 키는 캐릭터의 `key` 문자열이 아니라 파일 내부 관례를 그대로 따를 것 — 기존
항목들 옆에 나란히 추가하면서 형식만 맞추면 됨.)

## 3. `momotalk/persona_loader.py` — 그룹/co-presence 등록

- 새 그룹을 만드는 경우: 파일 상단 근처의 그룹 상수(`_ABYDOS_KEYS`, `_HUNGSINSO68_KEYS` 같은
  리스트들과 `_STUDENT_GROUPS`)에 새 그룹 리스트를 만들어 추가한다. 이미 있는 그룹에 합류시키는
  경우엔 해당 그룹 리스트에 key만 추가한다.
- `_group_peers(char_key)`가 이 그룹 정보를 읽어서 "같은 학원/동아리끼리만" co-presence(같은
  장소에 같이 있다고 서로 언급하는 것)를 판정하므로, 그룹을 잘못 넣으면 마주치면 안 되는
  학생들이 서로 아는 척하게 됨.
- `_ADDRESS_TARGET_NAMES`에 `key: "이름"` 매핑 추가 (다른 학생이 이 학생을 대화 중에 이름으로
  부를 때 쓰는 표시용 이름).

## 4. `check_schedule.py` — 검증기에 등록

- `KEYS` 리스트에 새 key 추가.
- `NAME_MAP`에 `key: "이름"` 추가.
- 새 장소를 썼다면 `data/places.json`에 수동으로 등록한다(카테고리 + entry_count):
  ```json
  "새 장소 이름": { "category": "집|야외|상점|학교 등", "entry_count": 0 }
  ```
  `entry_count`는 정확한 값이 아니어도 되지만, 실제 activity에서 그 place가 몇 번 쓰였는지
  세서 넣는 게 관례. **`extract_places.py`로 재생성하지 말 것** — 이미 구조화된(text/place/with/tag
  dict) activity에 그 스크립트를 돌리면 옛날 자유텍스트 시절 로직이라 깨진다(1회성
  마이그레이션 도구, 재사용 불가).
- 실행: `python check_schedule.py` — 이름 언급 불일치, 장소 오타 의심을 콘솔에 경고로만
  출력한다(강제 차단 없음). 경고 뜨면 해당 슬롯만 수동으로 고친다.

## 5. `test_persona.py` — 테스트 CLI에 등록

- `ALL_KEYS` 리스트에 새 key 추가. 이후 `python test_persona.py <key>` 같은 식으로 개별
  캐릭터 응답을 실제로 테스트할 수 있음(정확한 CLI 인자는 파일 안 사용법 참고).

## 6. 마무리

- `assets/profiles/<key>.png` — 프로필 사진(사용자가 직접 준비).
- `assets/voices/<key>_sensei.<mp3|wav|m4a|ogg>` — 선택 사항, 없으면 조용히 무시됨.
- 생일/기념일 이벤트(`data/events/*.json`)에 이 학생도 낄지 여부는 이벤트 성격에 따라
  별도 판단(예: 그룹 전체가 참여하는 이벤트면 참여 인원 리스트에 key 추가).
- 전부 끝나면 `python check_schedule.py` 마지막으로 한 번 더 돌려서 경고 없는지 확인 →
  `python main.py`로 실제 채팅 테스트 → 문제 없으면 exe 재빌드(`build_exe.bat`).

## 순서 요약

1. `prompts/<key>.json` 작성 (성격/말투/few_shot은 사용자 제공 내용 그대로 옮기기)
2. `data/dialogues.json`에 UI 노출용 항목 추가
3. `momotalk/persona_loader.py`의 그룹 상수 + `_ADDRESS_TARGET_NAMES`에 등록
4. `check_schedule.py`의 `KEYS`/`NAME_MAP` 추가, 새 장소는 `data/places.json`에도 등록, 검증 실행
5. `test_persona.py`의 `ALL_KEYS`에 추가
6. 프로필 사진/보이스 파일, 실제 대화 테스트, exe 재빌드
