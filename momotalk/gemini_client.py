# -*- coding: utf-8 -*-
"""
Gemini 호출 담당.

- config.json 에서 API 키 / 모델명을 읽는다. (키는 코드 밖, GitHub 에 안 올라가게)
- persona_loader 가 만든 (시스템 프롬프트, 대화 히스토리)를 받아 Gemini 를 부른다.
- 네트워크 대기로 UI 가 멈추지 않도록 QThread 워커에서 호출한다.
- 응답 JSON {"messages": [...]} 를 파싱해 메시지 리스트로 돌려준다.
"""

import os
from momotalk.paths import get_base_dir
import json
import re
import time

from PyQt5.QtCore import QThread, pyqtSignal

BASE_DIR = get_base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

MAX_ATTEMPTS = 3       # DNS/연결 일시 오류 대비 재시도 횟수(맨 처음 시도 포함)
RETRY_DELAY_SEC = 1.5

DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def load_config():
    """config.json 읽기. 없거나 깨지면 빈 키로 안전하게 반환.
    weather_api_key 는 선택 항목 — 없으면 날씨 기능만 조용히 꺼진다.
    provider 는 "gemini"(기본) 또는 "openai" — 대화 응답을 어느 쪽 API로 받을지."""
    cfg = {
        "gemini_api_key": "", "model": DEFAULT_MODEL, "weather_api_key": "",
        "provider": "gemini", "openai_api_key": "", "openai_model": DEFAULT_OPENAI_MODEL,
    }
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg["gemini_api_key"] = str(data.get("gemini_api_key", "")).strip()
            cfg["model"] = str(data.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
            cfg["weather_api_key"] = str(data.get("weather_api_key", "")).strip()
            provider = str(data.get("provider", "gemini")).strip().lower()
            cfg["provider"] = provider if provider in ("gemini", "openai") else "gemini"
            cfg["openai_api_key"] = str(data.get("openai_api_key", "")).strip()
            cfg["openai_model"] = str(data.get("openai_model", DEFAULT_OPENAI_MODEL)).strip() or DEFAULT_OPENAI_MODEL
    except FileNotFoundError:
        print("[Gemini] config.json 이 없습니다. (루트에 만들어 키를 넣어주세요)")
    except Exception as e:
        print("[Gemini] config.json 읽기 실패:", e)
    return cfg


def _strip_to_braces(raw):
    """앞뒤에 잡음(설명 등)이 섞여 있으면 첫 '{' ~ 마지막 '}' 만 잘라낸다."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end + 1]
    return raw


def _basic_unescape(s):
    return (
        s.replace("\\r\\n", "\n")
         .replace("\\n", "\n")
         .replace("\\t", "\t")
         .replace('\\"', '"')
         .replace("\\\\", "\\")
    )


def _regex_extract_messages(raw):
    """json.loads 가 완전히 실패했을 때, "messages" 배열 속 문자열만 정규식으로 건져낸다."""
    m = re.search(r'"messages"\s*:\s*\[(.*?)\]', raw, re.DOTALL)
    if not m:
        return []
    body = m.group(1)
    items = re.findall(r'"((?:[^"\\]|\\.)*)"', body, re.DOTALL)
    out = []
    for it in items:
        s = _basic_unescape(it).strip()
        if s:
            out.append(s)
    return out


def _split_slash_joined(items):
    """모델이 프롬프트 지시를 어기고 '/' 로 여러 톡을 한 문자열에 이어붙여 보내는 경우,
    코드 단에서 확실하게 별도 메시지로 쪼갠다(프롬프트 규칙만으로는 100% 보장이 안 되므로)."""
    out = []
    for s in items:
        if " / " in s:
            for part in s.split(" / "):
                part = part.strip()
                if part:
                    out.append(part)
        else:
            out.append(s)
    return out


def _dedupe_within_batch(items):
    """한 번의 응답(messages 배열) 안에 완전히 동일한 문장이 중복으로 들어있으면 하나만 남긴다.
    (모델이 한 응답 안에서 스스로 내용을 반복해서 보내는 경우를 걸러내기 위함)"""
    seen = set()
    out = []
    for s in items:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def parse_messages(text):
    """모델 응답 텍스트 → 메시지 문자열 리스트. 끝까지 파싱 실패하면 빈 리스트(호출부가 실패로 처리)."""
    if text is None:
        return []
    raw = text.strip()
    # 혹시 ```json ... ``` 으로 감싸져 오면 벗겨낸다
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    data = None
    try:
        data = json.loads(raw)
    except Exception:
        try:
            data = json.loads(_strip_to_braces(raw))
        except Exception:
            data = None

    if data is not None:
        if isinstance(data, dict):
            msgs = data.get("messages", [])
        elif isinstance(data, list):
            msgs = data
        else:
            msgs = [str(data)]
    else:
        # JSON 구조 자체가 깨졌을 때: "messages" 배열의 문자열들만 정규식으로 구제 시도
        msgs = _regex_extract_messages(raw)

    out = []
    for m in msgs:
        if m is None:
            continue
        s = str(m).strip()
        if s:
            out.append(s)
    out = _split_slash_joined(out)
    out = _dedupe_within_batch(out)
    # 여기까지도 못 건지면 원본을 노출하지 않고 빈 리스트 반환
    # → GeminiWorker 가 실패로 간주해 기존 "지금은 답장하기 어려워요" 폴백으로 넘어간다.
    return out[:5]   # 안전상 최대 5개


def _sanitize_contents(contents):
    """Gemini 는 첫 turn 이 user 여야 안전 → 앞쪽 model turn 제거."""
    c = list(contents or [])
    while c and c[0].get("role") != "user":
        c = c[1:]
    return c


class GeminiWorker(QThread):
    """백그라운드에서 Gemini 한 번 호출."""
    done = pyqtSignal(str, list)     # (char_key, messages)
    failed = pyqtSignal(str, str)    # (char_key, error_text)

    def __init__(self, char_key, api_key, model, system_prompt, contents, parent=None):
        super().__init__(parent)
        self.char_key = char_key
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.system_prompt = system_prompt
        self.contents = _sanitize_contents(contents)

    def run(self):
        # DNS 조회 실패(getaddrinfo failed) 같은 순간적인 네트워크 오류는 재시도하면
        # 대부분 바로 풀린다 — 오류 종류를 세세히 가리지 않고 그냥 몇 번 더 시도한다.
        last_error = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.api_key)
                response = client.models.generate_content(
                    model=self.model,
                    contents=self.contents,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_prompt,
                        response_mime_type="application/json",
                        temperature=0.9,
                    ),
                )
                messages = parse_messages(getattr(response, "text", None))
                if not messages:
                    self.failed.emit(self.char_key, "빈 응답")
                    return
                self.done.emit(self.char_key, messages)
                return
            except Exception as e:
                last_error = e
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(RETRY_DELAY_SEC)
        self.failed.emit(self.char_key, repr(last_error))
