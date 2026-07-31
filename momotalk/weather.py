# -*- coding: utf-8 -*-
"""
날씨 조회 + 캐싱.

- config.json 의 weather_api_key 를 쓴다(없으면 조용히 비활성 — 앱은 정상 동작).
- OpenWeatherMap 현재 날씨 API 하나만 쓴다. 신규 패키지 없이 표준 urllib 로 호출.
- 00시 기준 3시간 블록(00/03/06/09/12/15/18/21)마다 한 번 + 앱 시작 시 한 번만 부른다.
  학생이 답장을 몇 번 하든 이 캐시를 재사용하므로 API 호출량은 하루 8~10회 수준.
- persona_loader 는 네트워크를 절대 건드리지 않고 이 모듈의 '캐시'만 읽는다.
"""

import json
import datetime
import urllib.request
import urllib.parse
import urllib.error

from PyQt5.QtCore import QThread, pyqtSignal

CITY = "Seoul,KR"
API_URL = "https://api.openweathermap.org/data/2.5/weather"
TIMEOUT_SEC = 10

# OpenWeatherMap 의 weather[0].main → (한국어 표기, 궂은 날씨인가)
_CONDITION_MAP = {
    "Thunderstorm": ("천둥번개", True),
    "Drizzle": ("이슬비", True),
    "Rain": ("비", True),
    "Snow": ("눈", True),
    "Clear": ("맑음", False),
    "Clouds": ("흐림", False),
    "Mist": ("안개", False),
    "Fog": ("안개", False),
    "Haze": ("옅은 안개", False),
    "Dust": ("먼지", False),
    "Sand": ("모래바람", False),
    "Squall": ("돌풍", True),
    "Tornado": ("토네이도", True),
}

# 모듈 수준 캐시: {"condition","temp","bad","fetched_at"} 또는 None
_cache = None


def _slot_index(dt):
    """00시 기준 3시간 블록 번호(0~7). 블록이 바뀌면 갱신 대상."""
    return dt.hour // 3


def fetch(api_key):
    """실제 네트워크 호출(블로킹). 실패하면 None. 호출부에서 워커 스레드로 감쌀 것."""
    if not api_key:
        return None
    params = urllib.parse.urlencode({
        "q": CITY,
        "appid": api_key,
        "units": "metric",
        "lang": "kr",
    })
    url = "%s?%s" % (API_URL, params)
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # 키 오타뿐 아니라 '방금 발급받아 아직 활성화 안 됨'도 401 로 온다.
            # 신규 키는 보통 10분~2시간 뒤부터 동작하므로, 그때까지는 이 메시지가 반복될 수 있다.
            print("[날씨] 키가 아직 활성화되지 않았거나 잘못된 키입니다(401)."
                  " 방금 발급받은 키라면 10분~2시간 뒤 자동으로 동작합니다.")
        else:
            print("[날씨] 조회 실패: HTTP %s" % e.code)
        return None
    except Exception as e:
        print("[날씨] 조회 실패:", repr(e))
        return None

    try:
        main = (data.get("weather") or [{}])[0].get("main", "")
        temp = data.get("main", {}).get("temp")
        label, bad = _CONDITION_MAP.get(main, (main or "알 수 없음", False))
        return {
            "condition": label,
            "temp": None if temp is None else int(round(float(temp))),
            "bad": bad,
            "fetched_at": datetime.datetime.now(),
        }
    except Exception as e:
        print("[날씨] 응답 해석 실패:", repr(e))
        return None


def set_cache(result):
    global _cache
    if result is not None:
        _cache = result
        print("[날씨] 갱신:", result["condition"], "%s도" % result["temp"],
              "(%s)" % result["fetched_at"].strftime("%H:%M"))


def get_cached():
    """캐시된 날씨(dict) 또는 None. 네트워크를 타지 않는다."""
    return _cache


def needs_refresh(now=None):
    """아직 한 번도 못 받았거나, 3시간 블록이 바뀌었으면 True."""
    if now is None:
        now = datetime.datetime.now()
    if _cache is None:
        return True
    prev = _cache["fetched_at"]
    if prev.date() != now.date():
        return True
    return _slot_index(prev) != _slot_index(now)


def is_bad_weather():
    """지금 비/눈 등 야외 일정에 지장이 있는 날씨인가. 정보가 없으면 False(=평소 스케줄 유지)."""
    return bool(_cache and _cache.get("bad"))


def describe():
    """프롬프트에 넣을 짧은 표기. 예: '비, 18도'. 정보가 없으면 ''."""
    if not _cache:
        return ""
    temp = _cache.get("temp")
    if temp is None:
        return _cache.get("condition", "")
    return "%s, %d도" % (_cache.get("condition", ""), temp)


def minutes_since_fetch(now=None):
    """마지막 조회로부터 몇 분 지났는지. 정보가 없으면 None."""
    if not _cache:
        return None
    if now is None:
        now = datetime.datetime.now()
    return int((now - _cache["fetched_at"]).total_seconds() // 60)


class WeatherWorker(QThread):
    """UI 를 막지 않도록 백그라운드에서 날씨 한 번 조회."""
    done = pyqtSignal(object)   # dict 또는 None

    def __init__(self, api_key, parent=None):
        super().__init__(parent)
        self.api_key = api_key

    def run(self):
        self.done.emit(fetch(self.api_key))
