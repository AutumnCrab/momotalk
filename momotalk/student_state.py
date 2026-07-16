# -*- coding: utf-8 -*-
"""
학생별 동시성 상태를 '한 곳에서' 관리하는 상태머신.

이 파일은 PyQt 에 의존하지 않는 순수 파이썬이라 단독 테스트가 가능하다.
(예전에는 _waiting / _proactive_busy / _wake_processing 등 플래그가 여러 개로 흩어져
 앱 전체가 '한 번에 한 명'처럼 묶였고, 학생 A 답장 대기 중엔 B 에게 말도 못 걸었다.
 그 흩어진 상태들을 이 모듈 하나로 통합한다.)

각 학생은 항상 다음 두 상태 중 하나:
  IDLE       : 아무 요청도 진행 중이지 않음  → 새 요청을 시작해도 됨
  GENERATING : 그 학생에 대한 Gemini 요청이 진행 중  → 새 요청은 양보(중복 방지)

실시간 답장 / 선톡(B안) / 기상 답장 / 기념일 — 네 가지 트리거 모두
"지금 이 학생에게 새 요청을 걸어도 되는가?" 를 이 상태 하나로만 판정한다.
서로 다른 학생끼리는 서로를 막지 않는다(진짜 학생별 동시성).
"""

import time

IDLE = "idle"
GENERATING = "generating"


class StudentStateMachine:
    def __init__(self, keys):
        self._state = {}
        self._reason = {}     # 무슨 트리거로 generating 인지(로그/디버그용): 'live'/'proactive'/'wake'/'event'
        self._since = {}      # generating 진입 시각(스톨 감시용). IDLE 이면 0.0
        for k in keys:
            self.ensure(k)

    def ensure(self, key):
        """저장된 대화 복원 등으로 뒤늦게 등장한 key 도 안전하게 등록."""
        if key not in self._state:
            self._state[key] = IDLE
            self._reason[key] = None
            self._since[key] = 0.0

    # ── 조회 ──────────────────────────────────────────────
    def state(self, key):
        self.ensure(key)
        return self._state[key]

    def is_idle(self, key):
        return self.state(key) == IDLE

    def is_generating(self, key):
        return self.state(key) == GENERATING

    def reason(self, key):
        self.ensure(key)
        return self._reason[key]

    def busy_keys(self):
        """지금 요청이 진행 중인 학생 key 집합."""
        return {k for k, s in self._state.items() if s == GENERATING}

    # ── 전이 ──────────────────────────────────────────────
    def begin(self, key, reason):
        """요청 시작 시도.
        이미 GENERATING 이면 False(=양보해야 함). IDLE 이라 시작에 성공하면 True.
        호출부는 반드시 True 일 때만 실제 워커를 띄운다."""
        self.ensure(key)
        if self._state[key] != IDLE:
            return False
        self._state[key] = GENERATING
        self._reason[key] = reason
        self._since[key] = time.time()
        return True

    def end(self, key):
        """요청 종료(성공/실패/타임아웃 무엇이든). 항상 IDLE 로 되돌린다.
        이미 IDLE 이어도 안전(idempotent)."""
        self.ensure(key)
        self._state[key] = IDLE
        self._reason[key] = None
        self._since[key] = 0.0

    # ── 안전망 ────────────────────────────────────────────
    def reap_stalled(self, max_age_sec, now=None):
        """end() 호출이 어쩌다 누락돼 학생이 영영 GENERATING 에 굳는 사고를 막는 자동 해제.
        (예전 코드 주석에도 있듯, busy 를 못 풀면 그 학생은 이후 모든 톡이 막혀버린다.)
        max_age_sec 보다 오래 GENERATING 이던 학생을 강제로 IDLE 로 돌린다.
        반환: 이번에 강제 해제된 key 리스트."""
        if now is None:
            now = time.time()
        freed = []
        for k, s in list(self._state.items()):
            if s == GENERATING and self._since[k] and (now - self._since[k]) > max_age_sec:
                self._state[k] = IDLE
                self._reason[k] = None
                self._since[k] = 0.0
                freed.append(k)
        return freed
