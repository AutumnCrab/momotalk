# 모모톡 데스크톱 위젯 (MomoTalk Desktop Widget)

블루 아카이브의 '모모톡' UI를 본뜬 바탕화면 위젯입니다. 화면 구석에 떠 있는 아이콘을 통해
게헨나·아비도스 학생 10명과 실제 AI(Gemini/OpenAI) 기반으로 대화를 나눌 수 있습니다.
학생마다 요일별 스케줄이 있어서, 지금 뭘 하고 있는지에 맞게 대답하거나 스스로 먼저 말을
걸어오기도 합니다.

---

## 1. 준비물

### 그냥 쓰기만 할 경우 (exe)
- Python 설치 필요 없음 — `dist/MomoTalk/MomoTalk.exe` 실행만 하면 됩니다.
- **AI API 키** 하나는 미리 발급해두세요(둘 중 하나만 있으면 됨):
  - **Gemini** — https://aistudio.google.com/ 에서 무료로 발급. 발화 규칙(캐릭터 말투)을
    더 잘 지키는 편이라 추천합니다.
  - **OpenAI** — https://platform.openai.com/ 에서 발급. 계정 등록과 크레딧 충전이
    선행되어야 합니다.
- (선택) **날씨 API 키** — https://openweathermap.org/ 에서 무료로 발급. 없어도 날씨
  연동 기능만 조용히 꺼질 뿐 나머지는 정상 동작합니다.

### 소스로 직접 돌릴 경우 (개발)
1. 파이썬 설치 — https://www.python.org/downloads/ (설치 시 **Add Python to PATH** 체크)
2. 이 폴더에서:
   ```
   pip install -r requirements.txt
   ```
3. 실행:
   ```
   python main.py
   ```

---

## 2. 사용 방법

### 첫 실행
API 키가 하나도 없는 상태로 실행하면(exe든 `python main.py`든) **초기 설정 창**이
자동으로 뜹니다. 여기서 생일, 대화 API 키(Gemini `AIza...` 또는 OpenAI `sk-...`를
붙여넣으면 자동으로 어느 쪽인지 인식합니다), 날씨 API 키(선택)를 넣고 저장하면 바로
위젯이 시작됩니다.

### 기본 조작

| 동작 | 방법 |
|------|------|
| 채팅창 열기 | 떠다니는 아이콘 **더블클릭** |
| 위치 옮기기 | 아이콘 드래그 (손을 떼면 가까운 화면 가장자리에 붙음, 듀얼 모니터도 지원) |
| 안읽음 배지 지우기(읽음 처리) | 아이콘 한 번 클릭 |
| 아이콘 숨기기 → 트레이로 | 아이콘 우클릭 → "아이콘 숨김" |
| 숨긴 아이콘 다시 꺼내기 | 트레이 아이콘 더블클릭, 또는 우클릭 메뉴 → "아이콘 보이기" |
| 채팅창 닫기 | 헤더의 ✕ 또는 Esc |
| 학생 목록 ↔ 채팅 전환 | 채팅창 좌측 레일의 메시지/학생 아이콘 |
| 종료 | 트레이 또는 아이콘 우클릭 → "종료" (확인창 뜸) |

채팅창의 "학생" 탭에서 학생을 누르면 프로필(소속·좋아하는 것·현재 상태등)을 볼 수 있고,
"메시지" 탭에서 실제 대화를 나눕니다. 자리를 비운 사이에도 학생이 메시지를 보내면
화면 우측 하단에 토스트 알림(+캐릭터 보이스, 파일이 있는 경우)이 뜹니다.

---

## 3. 어떤 식으로 동작하나 (간단히)

- **페르소나 = JSON 파일 하나씩** — `prompts/<학생key>.json`에 성격, 말투 규칙,
  대사 예시(few-shot), 요일별 시간대 스케줄(`activity`), 생일 등이 들어있습니다.
  대화할 때마다 이 정보 + 최근 대화 기록을 시스템 프롬프트로 조립해서
  Gemini/OpenAI에 보내고, 응답을 여러 개의 메신저 말풍선으로 쪼개 받습니다.
- **스케줄 기반 선톡** — 학생마다 요일별로 지금 뭘 하는지가 정해져 있고, 활동이
  바뀌는 시점마다 확률적으로 먼저 말을 걸어옵니다(하루 총량은 학생별로 제한됨).
  취침/근무 중이면 대신 대기함에 쌓아뒀다가 깨어나면 몰아서 답합니다.
- **기념일 이벤트** — 학생 본인 생일, 사용자(선생님) 생일, 계절 특별기간(여름휴가,
  겨울 제설작전, 잠입 임무, 신년 참배 등 `data/events/*.json`)마다 그날 전용
  스케줄과 별도 안내문이 시스템 프롬프트에 얹혀서, 평소와 다른 특별한 반응을
  보이게 됩니다.
- **정합성 검사** — `check_schedule.py`로 학생들 스케줄에 이동시간이 말이 되는지,
  등록 안 된 장소를 쓰진 않았는지 등을 미리 검사해둡니다.
- **UI는 전부 PyQt5** — 프레임 없는 위젯 + 커스텀 애니메이션(GDI가 아니라 QPainter
  로 직접 그림)으로 실제 Windows 창처럼 안 보이게 만들었습니다.

---

## 4. 캐릭터/대사 편집하기

`prompts/<key>.json` 을 메모장(또는 VS Code)으로 직접 편집합니다. 주요 필드:

```json
{
  "persona": "성격 설명",
  "speech_style": "말투 규칙(반말/존댓말, 말버릇 등)",
  "address_terms": { "teacher": "선생님", "다른학생key": "그 학생 부르는 호칭" },
  "few_shot": [ { "user": "...", "reply": ["...", "..."] } ],
  "birthday_few_shot": { "own_birthday": [...], "teacher_birthday": [...] },
  "awake": { "mon": ["07:00-23:00"], ... },
  "activity": { "mon": { "07:00": { "text": "...", "place": "...", "with": [], "tag": null } } },
  "birthday": "MM-DD"
}
```

- `activity`의 `place`가 `null`이면 "이동 중이라 고정 장소 없음"으로 처리됩니다.
- 새 장소를 쓰면 `data/places.json`에도 등록해야 `check_schedule.py`가 오타로
  오인하지 않습니다.
- 편집 후엔 `python check_schedule.py`로 한 번 검사해보는 걸 권장합니다.

새 캐릭터를 통째로 추가하려면 `data/dialogues.json`(UI 목록용 기본 정보)과
`prompts/<key>.json`을 같이 만들고, 프로필 사진을 `assets/profiles/`에 넣으면 됩니다.

---

## 5. 폴더 구조

```
momotalk/
├── main.py                  # 실행 진입점 (컨트롤러, 이벤트/스케줄 타이머, 트레이)
├── MomoTalk.spec             # PyInstaller 빌드 스펙
├── build_exe.bat              # exe 빌드 스크립트 (dist/MomoTalk/ 생성)
├── requirements.txt
├── momotalk/                 # 앱 코드
│   ├── persona_loader.py     # 시스템 프롬프트 조립(페르소나+스케줄+기념일+규칙)
│   ├── gemini_client.py / openai_client.py   # 두 provider의 API 호출 워커
│   ├── chat_window.py        # 채팅창(학생 목록 + 대화 + 프로필)
│   ├── icon_widget.py        # 떠다니는 아이콘 위젯
│   ├── toast.py               # 커스텀 알림 팝업
│   ├── voice.py / sfx.py      # 캐릭터 보이스 / UI 효과음
│   ├── settings_dialog.py    # 초기 설정 창
│   ├── scheduler.py / event_loader.py / anniversary_loader.py
│   ├── history_store.py      # 대화 기록 저장/복원
│   └── theme.py               # 색상·크기 상수
├── prompts/                   # 학생별 페르소나 JSON (10명)
├── data/
│   ├── dialogues.json         # UI 목록용 기본 정보(이름/프로필/소개)
│   ├── places.json / travel_times.json   # 장소 목록 + 이동시간 매트릭스
│   └── events/                # 특별기간 이벤트(여름휴가, 잠입 임무 등)
├── assets/
│   ├── profiles/               # 학생 프로필 사진
│   ├── voices/                 # 캐릭터별 "선생님" 알림 보이스(선택)
│   └── sfx/                    # UI 효과음(on/off/touch/momotalk)
├── check_schedule.py           # 스케줄 정합성 검사기
└── test_persona.py             # 캐릭터별 응답 테스트용 CLI
```

---

## 6. exe로 빌드하기

```
build_exe.bat
```

`dist/MomoTalk/` 안에 실행파일과 필요한 데이터가 통째로 만들어집니다.
설정/대화기록이 이미 있으면 재빌드해도 그대로 유지됩니다(백업 후 복원).
빌드된 폴더를 다른 컴퓨터로 그대로 복사해서 배포할 수 있습니다(포터블).

---

## 7. 문제 해결

- 실행하면 `momotalk.log`(exe 옆 또는 프로젝트 루트)에 로그가 남습니다 — 창이 안 뜨거나
  이상하면 이 파일부터 확인하세요.
- API 키를 넣었는데 응답이 안 오면: 키 형식이 맞는지(Gemini는 `AIza...`, OpenAI는
  `sk-...`), 그리고 OpenAI는 계정에 크레딧이 있는지 확인하세요.
- 종료: 트레이/아이콘 우클릭 → 종료, 또는 (개발 모드는) 터미널에서 Ctrl+C.

---

## 8. 추후 추가사항

- 학생 10명 추가 예정(선도부, 게임 개발부, 세미나 등)
- 피드백 들어오는 대로 반영
- 발견되는 버그는 계속 수정
