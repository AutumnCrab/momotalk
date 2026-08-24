# -*- coding: utf-8 -*-
"""
OpenAI(GPT) 호출 담당.

gemini_client.GeminiWorker와 완전히 같은 신호(done/failed)를 내보내는 워커라서,
main.py 쪽 호출부는 config.json의 "provider" 값만 보고 어느 워커를 쓸지 고르면 된다
(호출 코드 자체를 provider별로 나눠 적지 않아도 됨). 응답 텍스트 파싱은
gemini_client.parse_messages()를 그대로 재사용한다 — 모델이 뭘 쓰든 지시한 JSON
포맷({"messages": [...]})은 똑같으므로 파싱 로직은 provider와 무관하다.
"""

import time

from PyQt5.QtCore import QThread, pyqtSignal

from .gemini_client import parse_messages, MAX_ATTEMPTS, RETRY_DELAY_SEC

DEFAULT_MODEL = "gpt-4o-mini"


def _to_openai_messages(system_prompt, contents):
    """Gemini contents 형식([{"role":"user"/"model","parts":[{"text":...}]}, ...])을
    OpenAI 채팅 형식({"role":"user"/"assistant","content":...})으로 변환."""
    messages = [{"role": "system", "content": system_prompt}]
    for turn in contents or []:
        role = "assistant" if turn.get("role") == "model" else "user"
        text = "".join(
            p.get("text", "") for p in (turn.get("parts") or []) if isinstance(p, dict)
        )
        messages.append({"role": role, "content": text})
    return messages


class OpenAIWorker(QThread):
    """백그라운드에서 OpenAI 한 번 호출. GeminiWorker와 동일한 인터페이스."""
    done = pyqtSignal(str, list)     # (char_key, messages)
    failed = pyqtSignal(str, str)    # (char_key, error_text)

    def __init__(self, char_key, api_key, model, system_prompt, contents, parent=None):
        super().__init__(parent)
        self.char_key = char_key
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.system_prompt = system_prompt
        self.contents = contents

    def run(self):
        # DNS 조회 실패 같은 순간적인 네트워크 오류는 재시도하면 대부분 바로 풀린다.
        last_error = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                from openai import OpenAI

                client = OpenAI(api_key=self.api_key)
                response = client.chat.completions.create(
                    model=self.model,
                    messages=_to_openai_messages(self.system_prompt, self.contents),
                    response_format={"type": "json_object"},
                    temperature=0.9,
                )
                text = response.choices[0].message.content
                messages = parse_messages(text)
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
