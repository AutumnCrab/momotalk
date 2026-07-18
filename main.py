# -*- coding: utf-8 -*-
"""
모모톡 위젯 실행 진입점.

실행:  (이 폴더 안에서)  python main.py

구조:
  - data_loader : dialogues.json 을 읽어 캐릭터/스케줄 데이터로 변환
  - scheduler   : 요일/시각이 되면 message_ready 신호 발생
  - icon_widget : 우측 하단 떠다니는 아이콘 (배지/드래그/더블클릭)
  - chat_window : 더블클릭 시 열리는 채팅창
  - MomoApp     : 위 조각들을 연결하고 메시지 저장소(store)를 관리
"""

import sys
import os
import random
import datetime
import time

from PyQt5.QtCore import (
    Qt, QRect, QTimer, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
)
from PyQt5.QtWidgets import QApplication

from momotalk import theme
from momotalk import persona_loader
from momotalk import history_store
from momotalk import anniversary_loader
from momotalk.fonts import load_app_font
from momotalk.data_loader import load_characters
from momotalk.scheduler import Scheduler
from momotalk.icon_widget import MomoTalkIcon
from momotalk.chat_window import ChatWindow
from momotalk.gemini_client import GeminiWorker, load_config
from momotalk.student_state import StudentStateMachine


class MomoApp:
    def __init__(self):
        self.characters = load_characters()
        print("[모모톡] 캐릭터 로드:", [c["name"] for c in self.characters])
        # 캐릭터별 대화 저장소: key -> [(sender, text), ...]
        self.store = {c["key"]: [] for c in self.characters}
        # 학생별 안 읽은 메시지 수 (목록 배지용)
        self.unread = {c["key"]: 0 for c in self.characters}

        # 학생이 자는 동안 보낸 메시지 대기함: key -> [{"text":..., "at": ISO시각}, ...]
        self.pending = {c["key"]: [] for c in self.characters}

        # 저장된 이전 대화 복원 (현재 존재하는 학생 key 만)
        saved_store, saved_unread, saved_pending = history_store.load()
        if saved_store is not None:
            for k in self.store:
                if k in saved_store:
                    self.store[k] = saved_store[k]
            for k in self.unread:
                if isinstance(saved_unread, dict) and k in saved_unread:
                    self.unread[k] = saved_unread[k]
            for k in self.pending:
                if isinstance(saved_pending, dict) and k in saved_pending:
                    self.pending[k] = saved_pending[k]
            print("[모모톡] 이전 대화를 불러왔어요.")

            # 과거에 어떤 이유로든 대화 기록에 쌓인 '학생 발화 반복'을 시작 시 1회 청소한다.
            # (반복된 기록이 다음 프롬프트에 들어가 또 반복을 유발하는 악순환을 끊기 위함)
            cleaned = history_store.clean_repeated_recv(self.store)
            if cleaned:
                print("[모모톡] 반복된 과거 답장 %d개를 정리했어요." % cleaned)
                history_store.save(self.store, self.unread, self.pending)

        self.icon = MomoTalkIcon()
        self.icon.open_requested.connect(self.open_chat)
        self.icon.hide_requested.connect(self.hide_icon)

        self.window = None
        self._open_anim = None
        self._tray = None

        self._setup_tray()

        # Gemini 답장 관련
        self.config = load_config()
        self._workers = []          # QThread 참조 보관(GC 방지)
        self.GEMINI_TIMEOUT_MS = 25 * 1000   # 이 시간 안에 응답이 없으면 클라이언트 쪽에서 포기 처리
        self._abandoned_workers = set()      # 타임아웃으로 포기한 워커(뒤늦게 응답 와도 무시하기 위함)

        # ── 학생별 동시성 상태(상태머신) ──
        # 예전의 _waiting(전역)·_proactive_busy(set)를 하나로 통합.
        # "이 학생에게 지금 새 요청을 걸어도 되는가"는 오직 이 상태로만 판정한다.
        # 서로 다른 학생은 서로를 막지 않는다(A 답장 대기 중에도 B에겐 말 걸 수 있음).
        self.state = StudentStateMachine([c["key"] for c in self.characters])

        # 여러 톡이 한꺼번에 오지 않도록: 큐에 넣고 [입력중...] 표시 후 하나씩
        self._msg_queue = []
        self._delivering = False
        self.TYPING_MS = 1800        # 한 톡당 '입력 중' 표시 시간(간격)
        # 선생님이 톡을 연달아 보내거나(또는 다음 말을 타이핑 중) 이 시간(ms) 동안 조용해지면
        # 그제서야 학생이 답장을 시작한다. 그 사이 온 톡은 전부 한 번에 맥락으로 반영됨.
        self.BATCH_QUIET_MS = 5000
        self._batch_timers = {}     # char_key -> QTimer (5초 조용함 대기용)
        # 완전히 동일한 메시지 묶음이 이 시간(초) 안에 다시 배달되면 중복으로 보고 막는다.
        # 예전엔 20초였는데, 원인 불명의 근접/원거리 중복 재발 방지를 위해 넉넉하게 늘림.
        self.DEDUPE_WINDOW_SEC = 120
        self._last_delivered = {}    # key -> (직전에 배달한 메시지 묶음(tuple), 배달 시각) 중복 방지용
        self._last_spoken = {}       # key -> 마지막으로 그 학생 톡이 온 시각 (선톡 쿨다운용)
        self.PROACTIVE_COOLDOWN_SEC = 5 * 60   # 방금 무슨 톡이든 받은 학생은 이 시간 동안 선톡 쉼

        # persona(prompts/<key>.json)에 'activity' 가 있는 학생은 B안(활동 전환 시 AI 선톡)이 전담.
        # 없는 학생만 예전처럼 dialogues.json 의 고정 스케줄을 그대로 쓴다(호환 유지).
        self.PROACTIVE_PROB = 0.50     # 활동이 바뀔 때 실제로 선톡을 보낼 확률
        self._activity_keys = set()
        for c in self.characters:
            p = persona_loader.load_persona(c["key"])
            if p is not None and p.get("activity"):
                self._activity_keys.add(c["key"])
        legacy_keys = {c["key"] for c in self.characters if c["key"] not in self._activity_keys}
        print("[모모톡] AI 선톡(B안) 대상:", sorted(self._activity_keys) or "없음")
        print("[모모톡] 기존 고정 스케줄 대상:", sorted(legacy_keys) or "없음")

        self.scheduler = Scheduler(self.characters, enabled_keys=legacy_keys)
        self.scheduler.message_ready.connect(
            lambda k, m: self.on_message(k, m, reason="legacy_schedule")
        )
        self.scheduler.start()

        # 자는 동안 쌓인 톡 → 기상 후 학생별로 순서대로(겹치면 한 명씩 텀 두고) 일괄 답장
        self._wake_queue = []
        self._wake_processing = False
        self._wake_timer = QTimer()
        self._wake_timer.setInterval(60 * 1000)     # 1분마다 '방금 깬 학생 있는지' 체크
        self._wake_timer.timeout.connect(self._check_wakeups)
        self._wake_timer.start()
        QTimer.singleShot(1500, self._check_wakeups)  # 앱을 켰을 때 이미 깨어있는 학생도 체크

        # B안: 활동 구간이 바뀌면 확률적으로 AI가 먼저 말을 건다
        self._last_activity_slot = {}   # key -> (시작시각, 설명)  직전에 기록해둔 활동 구간
        self._proactive_log = []        # [(보낸시각, 학생key), ...] 최근 1시간 내 선톡 기록(인원 제한용)
        self.PROACTIVE_MAX_PER_HOUR = 4  # 굴러가는 1시간 동안 선톡 보낼 수 있는 서로 다른 학생 수 상한
        # 활동이 바뀐 걸 감지해도 정각에 우르르 몰리지 않도록, 그 활동 구간 시작 후
        # 이 범위(초) 안에서 학생별로 랜덤한 시점에 (그때 조건을 다시 확인하고) 선톡을 시도한다.
        self.PROACTIVE_DELAY_MIN_SEC = 15 * 60
        self.PROACTIVE_DELAY_MAX_SEC = 45 * 60
        self._activity_timer = QTimer()
        self._activity_timer.setInterval(60 * 1000)   # 1분마다 활동 전환 체크
        self._activity_timer.timeout.connect(self._check_activity_transitions)
        self._activity_timer.start()
        QTimer.singleShot(1500, self._check_activity_transitions)  # 시작 시 기준점만 세팅(선톡 X)

        # 기념일(생일/세계 기념일): 매일 자정에 오늘의 대상/랜덤 발송 시각을 다시 뽑는다
        self._event_day = None                # 마지막으로 이벤트를 계산해둔 날짜(datetime.date)
        self._event_schedule = {}             # key -> {"kind", "extra", "at"(datetime), "sent"(bool)}
        self._event_participants_today = set()  # 오늘 기념일 대상인 학생 key (이날은 B안을 쉼)
        self._event_cancelled = set()         # 본인 생일인데 선생님이 먼저 축하해서 예약 발송이 취소된 key
        self._event_timer = QTimer()
        self._event_timer.setInterval(60 * 1000)   # 1분마다 '오늘의 기념일 발송 시각' 체크
        self._event_timer.timeout.connect(self._check_daily_events)
        self._event_timer.start()
        QTimer.singleShot(1500, self._check_daily_events)

        # 안전망: end() 호출이 어쩌다 누락돼 학생이 영영 GENERATING 으로 굳는 사고 방지.
        # 타임아웃(25초)보다 넉넉히 오래 굳어있으면 강제로 IDLE 로 되돌린다.
        self._reaper_timer = QTimer()
        self._reaper_timer.setInterval(30 * 1000)
        self._reaper_timer.timeout.connect(self._reap_stalled_states)
        self._reaper_timer.start()

        # [상태 점등] 학생소개 탭 아바타의 초록/회색/빨강 점을 주기적으로 최신화.
        # Gemini 호출 없는 순수 로컬 계산이라 가볍게 자주 돌려도 됨.
        self._presence_timer = QTimer()
        self._presence_timer.setInterval(30 * 1000)
        self._presence_timer.timeout.connect(self._update_presence_dots)
        self._presence_timer.start()

        self.icon.show()
        self.icon.raise_()
        self.icon.activateWindow()

        geo = QApplication.primaryScreen().availableGeometry()
        print("[모모톡] 화면 영역  : x=%d y=%d w=%d h=%d"
              % (geo.x(), geo.y(), geo.width(), geo.height()))
        print("[모모톡] 아이콘 위치: x=%d y=%d (크기 %dx%d)"
              % (self.icon.x(), self.icon.y(), self.icon.width(), self.icon.height()))
        print("[모모톡] 준비 완료! 화면 '우측 하단'을 확인하세요.")
        print("[모모톡] (종료: 아이콘 우클릭 → 종료  /  또는 이 터미널에서 Ctrl+C)")

    # ─────────────── 시스템 트레이 (상시 상주) ───────────────
    def _setup_tray(self):
        import os
        from PyQt5.QtWidgets import QSystemTrayIcon, QMenu
        from PyQt5.QtGui import QIcon

        # ▼▼ 트레이 아이콘 이미지: 여기를 바꾸면 트레이 그림이 바뀝니다 ▼▼
        tray_png = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "assets", "momotalk.png"
        )
        # ▲▲ 기본값: assets/momotalk.png ▲▲

        icon = QIcon(tray_png) if os.path.exists(tray_png) else QIcon()
        self._tray = QSystemTrayIcon(icon)
        self._tray.setToolTip("모모톡")

        menu = QMenu()
        menu.addAction("아이콘 보이기", self.show_icon)
        menu.addAction("채팅창 열기", lambda: self.open_chat(None))
        menu.addSeparator()
        menu.addAction("종료", QApplication.quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        from PyQt5.QtWidgets import QSystemTrayIcon
        # 트레이 더블클릭 → 떠다니는 아이콘 다시 표시 (A안 1번)
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_icon()

    def hide_icon(self):
        """바탕화면의 떠다니는 아이콘만 숨김. 앱·트레이는 계속 살아있음."""
        from PyQt5.QtWidgets import QSystemTrayIcon
        self.icon.hide()
        if self._tray is not None:
            self._tray.showMessage(
                "모모톡",
                "아이콘을 숨겼어요. 트레이 아이콘을 더블클릭하면 다시 나타나요.",
                QSystemTrayIcon.Information,
                3000,
            )

    def show_icon(self):
        """숨긴 떠다니는 아이콘을 다시 표시."""
        self.icon.show()
        self.icon.raise_()
        self.icon.activateWindow()
        self._update_tray_tooltip()

    def _update_tray_tooltip(self):
        """트레이 아이콘에 마우스를 올렸을 때 안 읽은 메시지 수가 보이게 툴팁을 갱신."""
        if self._tray is None:
            return
        total = sum(self.unread.values())
        self._tray.setToolTip("모모톡 (안 읽은 메시지 %d)" % total if total > 0 else "모모톡")

    def _notify_tray_message(self, char_key, text):
        """플로팅 아이콘이 숨겨져 있을 때도 놓치지 않도록, 새 메시지를 윈도우 알림으로 띄운다."""
        if self._tray is None:
            return
        from PyQt5.QtWidgets import QSystemTrayIcon
        name = next((c["name"] for c in self.characters if c["key"] == char_key), char_key)
        preview = text if len(text) <= 60 else text[:57] + "..."
        self._tray.showMessage(name, preview, QSystemTrayIcon.Information, 4000)

    def _save_history(self):
        """대화/안읽음/대기메시지를 파일로 저장."""
        history_store.save(self.store, self.unread, self.pending)


    def on_message(self, char_key, messages, reason="unknown"):
        # 어떤 경로로든(선톡/기상답장/기념일 등이 겹치는 등) 방금 배달한 것과 완전히 같은
        # 메시지 묶음이 짧은 시간 안에 다시 들어오면 중복으로 보고 무시한다.
        now_ts = time.time()
        batch = tuple(messages)
        last = self._last_delivered.get(char_key)
        if last is not None and last[0] == batch and (now_ts - last[1]) < self.DEDUPE_WINDOW_SEC:
            print("[모모톡] 중복 메시지 감지 → 무시:", char_key, "| 이유:", reason,
                  "| 이전 배달과의 간격: %.1f초" % (now_ts - last[1]))
            return
        self._last_delivered[char_key] = (batch, now_ts)
        self._last_spoken[char_key] = now_ts   # 선톡 쿨다운 판정용

        idle = (len(self._msg_queue) == 0 and not self._delivering)
        for m in messages:
            self._msg_queue.append((char_key, m, reason))
        if idle:
            self._begin_typing()

    def _begin_typing(self):
        if not self._msg_queue:
            self._delivering = False
            return
        self._delivering = True
        char_key = self._msg_queue[0][0]
        # 지금 그 학생 대화를 보고 있을 때만 '입력 중...' 점이 화면에 보임
        if (self.window is not None and self.window.isVisible()
                and getattr(self.window, "selected_key", None) == char_key):
            self.window.set_typing(char_key)
        QTimer.singleShot(self.TYPING_MS, self._deliver_after_typing)

    def _deliver_after_typing(self):
        if not self._msg_queue:
            self._delivering = False
            if self.window is not None:
                self.window.clear_typing()
            return
        char_key, text, reason = self._msg_queue.pop(0)
        if self.window is not None:
            self.window._typing_key = None        # 점 제거(아래 refresh가 새로 그림)
        self.store.setdefault(char_key, []).append(
            ("recv", text, datetime.datetime.now().isoformat(), reason)
        )

        viewing = (
            self.window is not None and self.window.isVisible()
            and getattr(self.window, "selected_key", None) == char_key
        )
        if not viewing:
            self.unread[char_key] = self.unread.get(char_key, 0) + 1
            self.icon.receive_message(1)
            self._update_tray_tooltip()
            if not self.icon.isVisible():
                self._notify_tray_message(char_key, text)

        if self.window is not None and self.window.isVisible():
            self.window.refresh()

        self._save_history()                      # 대화 변동 저장

        if self._msg_queue:
            self._begin_typing()                  # 다음 톡도 입력중 → 전달
        else:
            self._delivering = False

    # ───────────────── 내가 보낸 톡 → Gemini 답장 ─────────────────
    def on_user_message(self, char_key):
        """선생님이 톡을 보낼 때마다 호출됨. 바로 답장을 부르지 않고,
        5초간 조용해질 때까지(추가 전송·타이핑 모두) 기다렸다가 한 번에 처리한다.
        그 사이 저장은 즉시 하므로 대화창엔 보낸 순서대로 바로바로 뜬다."""
        self._save_history()                       # 방금 보낸 내 톡 저장(화면 표시는 즉시)
        self._arm_batch_timer(char_key)

    def _arm_batch_timer(self, char_key):
        """이 학생에 대한 '5초 조용함' 타이머를 (재)시작한다.
        이미 돌고 있으면 처음부터 다시 5초 카운트(= 매번 활동이 있을 때마다 연장)."""
        timer = self._batch_timers.get(char_key)
        if timer is None:
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(lambda k=char_key: self._process_user_message(k))
            self._batch_timers[char_key] = timer
        timer.start(self.BATCH_QUIET_MS)

    def _on_typing_activity(self, char_key):
        """선생님이 입력창에 실제로 타이핑 중(텍스트 변경)이면, 아직 전송 전이라도
        그 학생에 대한 답장 타이머를 계속 연장한다(= 다 쓰기 전엔 학생이 안 옴)."""
        # 이 학생에게 아직 처리 대기 중인 배치가 있을 때만 연장 의미가 있음.
        # (배치가 없는데 그냥 타이핑만 하는 경우까지 타이머를 새로 만들 필요는 없음)
        if char_key in self._batch_timers and self._batch_timers[char_key].isActive():
            self._arm_batch_timer(char_key)

    def _process_user_message(self, char_key):
        """5초간 조용해진 뒤 실제로 실행되는 처리부(예전 on_user_message 본문 그대로)."""
        if not self.state.is_idle(char_key):
            # 이 학생에 대해 이미 요청이 진행 중(이전 답장/선톡/기상/기념일 중 무엇이든).
            # 겹쳐서 두 번 호출되면 답장이 겹쳐 보이니, 살짝 기다렸다 한 번 다시 시도한다.
            # (다른 학생은 여기에 걸리지 않는다 — 학생별 상태이므로.)
            QTimer.singleShot(800, lambda: self._process_user_message(char_key))
            return

        persona = persona_loader.load_persona(char_key)
        if persona is None:
            self.on_message(char_key, ["(prompts/%s.json 이 없어요.)" % char_key], reason="live_error")
            return

        now = datetime.datetime.now()
        status = persona_loader.availability_status(persona, now)
        if status is not None:
            self._queue_pending(char_key, now, reason=status)   # 취침/부재중: 호출 안 하고 대기함에 저장
            return

        api_key = self.config.get("gemini_api_key", "").strip()
        if not api_key:
            self.on_message(char_key, ["(config.json 에 API 키를 넣어주세요.)"], reason="live_error")
            return

        self._refresh_daily_events()   # 혹시 아직 오늘 기념일 계산 전이면 지금 해둠
        event_note = ""
        ev = self._event_schedule.get(char_key)
        if ev is not None:
            event_note = persona_loader.build_event_note(ev["kind"], ev.get("extra"), persona=persona)

        system_prompt, contents = persona_loader.assemble(
            char_key, self.store.get(char_key, []), now=now, event_note=event_note
        )
        if system_prompt is None:
            self.on_message(char_key, ["(prompts/%s.json 이 없어요.)" % char_key], reason="live_error")
            return

        self.state.begin(char_key, "live")
        self._sync_input_lock()                    # 보고 있는 학생이면 입력창 잠금
        if self.window is not None:
            if self.window.isVisible() and self.window.selected_key == char_key:
                self.window.set_typing(char_key)   # 응답 기다리는 동안 입력중 점

        worker = GeminiWorker(
            char_key, api_key, self.config.get("model", ""), system_prompt, contents
        )
        worker.done.connect(lambda k, m, w=worker: self._on_reply(k, m, w))
        worker.failed.connect(lambda k, e, w=worker: self._on_reply_failed(k, e, w))
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._workers.append(worker)
        worker.start()
        QTimer.singleShot(
            self.GEMINI_TIMEOUT_MS, lambda w=worker, k=char_key: self._check_live_timeout(w, k)
        )

    def _on_reply(self, char_key, messages, worker=None):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)   # 타임아웃 처리 후 뒤늦게 온 응답 → 무시
            return
        self.state.end(char_key)
        self._sync_input_lock()
        if self.window is not None:
            self.window._typing_key = None
        self.on_message(char_key, messages, reason="live")         # 기존 입력중→간격 전달로 출력

    def _on_reply_failed(self, char_key, error, worker=None):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)
            return
        print("[Gemini 실패]", char_key, error)
        self.state.end(char_key)
        self._sync_input_lock()
        if self.window is not None:
            self.window._typing_key = None
        if error == "SAFETY_BLOCKED":
            self.on_message(char_key, ["(부적절한 내용이 감지되어 응답할 수 없어요.)"], reason="live_blocked")
        else:
            self.on_message(char_key, ["지금은 답장하기 어려워요.", "잠시 후 다시 말 걸어줘요."], reason="live_failed")

    def _check_live_timeout(self, worker, char_key):
        """일정 시간 안에 응답이 없으면 응답을 포기하고 UI 잠금을 풀어준다(무한 로딩 방지)."""
        if worker not in self._workers:
            return   # 이미 끝났음 → 정상 처리된 것이니 아무 것도 안 함
        print("[모모톡] 응답 시간 초과 →", char_key)
        self._abandoned_workers.add(worker)
        self.state.end(char_key)
        self._sync_input_lock()
        if self.window is not None:
            self.window._typing_key = None
            if self.window.isVisible():
                self.window.clear_typing()
        self.on_message(char_key, ["지금은 답장하기 어려워요.", "잠시 후 다시 말 걸어줘요."], reason="live_timeout")

    def _cleanup_worker(self, worker):
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    def _sync_input_lock(self):
        """입력창 잠금을 '지금 보고 있는 학생'의 상태에 맞춘다.
        예전처럼 앱 전체를 잠그는 게 아니라, 지금 화면에 열려 있는 학생이 답장 생성 중일 때만 잠근다.
        → 시로코 답장을 기다리는 동안에도 호시노 대화로 넘어가면 입력이 가능하다."""
        if self.window is None:
            return
        key = getattr(self.window, "selected_key", None)
        locked = key is not None and self.state.is_generating(key)
        self.window.set_input_enabled(not locked)

    def _reap_stalled_states(self):
        """혹시 end() 가 누락돼 학생이 영영 GENERATING 으로 굳었으면 자동 해제(안전망)."""
        freed = self.state.reap_stalled(self.GEMINI_TIMEOUT_MS / 1000 + 15)
        if freed:
            print("[모모톡] 상태 스톨 자동 해제 →", freed)
            self._sync_input_lock()

    def _update_presence_dots(self):
        """학생소개 탭의 초록/회색/빨강 상태점을 최신 availability_status 로 갱신.
        Gemini 호출 없는 로컬 계산이라 부담 없이 자주 돌린다."""
        if self.window is None:
            return
        now = datetime.datetime.now()
        for key in self._activity_keys:
            persona = persona_loader.load_persona(key)
            if persona is None:
                continue
            status = persona_loader.availability_status(persona, now)
            self.window.set_presence(key, status)

    # ───────────────── 취침/부재중: 대기 저장 + 안내 표시 ─────────────────
    ABSENT_LABELS = {"sleep": "(취침중)", "busy": "(부재중)"}

    def _queue_pending(self, char_key, now, reason="sleep"):
        """학생이 취침/부재중일 때 온 톡: API 호출 없이 대기함에 저장하고 상태별 안내만 띄운다.
        reason: 'sleep'(취침중) 또는 'busy'(부재중, 일하는 중)."""
        last_text = ""
        conv = self.store.get(char_key, [])
        if conv and conv[-1][0] == "send":
            last_text = conv[-1][1]
        self.pending.setdefault(char_key, []).append(
            {"text": last_text, "at": now.isoformat(), "reason": reason}
        )
        self._deliver_absent_notice(char_key, reason)
        self._save_history()

    def _deliver_absent_notice(self, char_key, reason="sleep"):
        """'(취침중)' 또는 '(부재중)' 안내를 즉시(타이핑 표시 없이) 붙인다. API 실패 폴백과는 별개."""
        label = self.ABSENT_LABELS.get(reason, self.ABSENT_LABELS["sleep"])
        self.store.setdefault(char_key, []).append(
            ("absent", label, datetime.datetime.now().isoformat(), reason)
        )

        viewing = (
            self.window is not None and self.window.isVisible()
            and getattr(self.window, "selected_key", None) == char_key
        )
        if not viewing:
            self.unread[char_key] = self.unread.get(char_key, 0) + 1
            self.icon.receive_message(1)
        if self.window is not None and self.window.isVisible():
            self.window.refresh()

    # ───────────── 기상 감지 → 밀린 톡 학생별로 순서대로 일괄 답장 ─────────────
    def _check_wakeups(self):
        """1분마다(및 시작 시 한 번) 지금 깨어있고 대기 메시지가 있는 학생을 찾아 순서대로 처리."""
        if self._wake_processing:
            return
        now = datetime.datetime.now()
        ready = []
        for key, msgs in self.pending.items():
            if not msgs:
                continue
            persona = persona_loader.load_persona(key)
            # 지금 다른 요청(실시간 답장 등)이 진행 중인 학생은 이번엔 건너뛴다(다음 체크 때 다시).
            # '완전히 가능한' 상태(취침도 부재중도 아님)여야 밀린 톡을 처리한다.
            if (persona is not None
                    and persona_loader.availability_status(persona, now) is None
                    and self.state.is_idle(key)):
                ready.append(key)
        if not ready:
            return
        self._wake_queue = ready
        self._process_next_wake()

    def _process_next_wake(self):
        if not self._wake_queue:
            self._wake_processing = False
            return
        self._wake_processing = True
        char_key = self._wake_queue.pop(0)
        msgs = self.pending.get(char_key, [])
        if not msgs:
            self._process_next_wake()
            return
        # 이 학생이 그새 다른 요청 중이 되었으면(예: 실시간 답장 시작) 이번엔 건너뛴다.
        # pending 은 건드리지 않으므로 다음 _check_wakeups(1분) 때 다시 처리된다.
        if not self.state.begin(char_key, "wake"):
            self._process_next_wake()
            return
        self.pending[char_key] = []
        self._save_history()

        api_key = self.config.get("gemini_api_key", "").strip()
        if not api_key:
            self.on_message(char_key, ["(어, 미안. 이제 봤어. 근데 config.json에 키가 없어서 답장을 못 만들겠어.)"], reason="wake_error")
            QTimer.singleShot(1200, self._process_next_wake)
            return

        wake_reason = msgs[-1].get("reason", "sleep") if msgs else "sleep"
        wake_note = persona_loader.build_wake_note(msgs, reason=wake_reason)
        self._refresh_daily_events()
        event_note = ""
        ev = self._event_schedule.get(char_key)
        if ev is not None:
            persona = persona_loader.load_persona(char_key)
            event_note = persona_loader.build_event_note(ev["kind"], ev.get("extra"), persona=persona)

        system_prompt, contents = persona_loader.assemble(
            char_key, self.store.get(char_key, []), wake_note=wake_note, event_note=event_note
        )
        if system_prompt is None:
            self._process_next_wake()
            return

        worker = GeminiWorker(
            char_key, api_key, self.config.get("model", ""), system_prompt, contents
        )
        worker.done.connect(lambda k, m, w=worker: self._on_wake_reply(k, m, w))
        worker.failed.connect(lambda k, e, w=worker: self._on_wake_reply_failed(k, e, w))
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._workers.append(worker)
        worker.start()
        QTimer.singleShot(
            self.GEMINI_TIMEOUT_MS, lambda w=worker, k=char_key: self._check_wake_timeout(w, k)
        )

    def _on_wake_reply(self, char_key, messages, worker=None):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)
            return
        self.state.end(char_key)
        self.on_message(char_key, messages, reason="wake")
        self._poll_wake_continue()

    def _on_wake_reply_failed(self, char_key, error, worker=None):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)
            return
        print("[기상 답장 실패]", char_key, error)
        self.state.end(char_key)
        if error == "SAFETY_BLOCKED":
            self.on_message(char_key, ["(부적절한 내용이 감지되어 응답할 수 없어요.)"], reason="wake_blocked")
        else:
            self.on_message(char_key, ["지금은 답장하기 어려워요.", "잠시 후 다시 말 걸어줘요."], reason="wake_failed")
        self._poll_wake_continue()

    def _check_wake_timeout(self, worker, char_key):
        if worker not in self._workers:
            return
        print("[모모톡] 기상 답장 시간 초과 →", char_key)
        self._abandoned_workers.add(worker)
        self.state.end(char_key)
        print("[기상 답장 실패]", char_key, "시간 초과")
        self.on_message(char_key, ["지금은 답장하기 어려워요.", "잠시 후 다시 말 걸어줘요."], reason="wake_timeout")
        self._poll_wake_continue()

    def _poll_wake_continue(self):
        """지금 학생의 톡 전달(타이핑 간격 포함)이 다 끝난 뒤에야 다음 학생으로 넘어간다."""
        if self._delivering or self._msg_queue:
            QTimer.singleShot(400, self._poll_wake_continue)
        else:
            QTimer.singleShot(1200, self._process_next_wake)   # 학생 사이 텀

    # ───────── B안: 활동 전환 시 확률적으로 AI가 먼저 말을 건다 ─────────
    def _proactive_window_allows(self, char_key, now):
        """굴러가는 1시간 동안 이미 PROACTIVE_MAX_PER_HOUR 명이 다 찼거나,
        이 학생이 그 시간 안에 이미 한 번 보냈으면 이번엔 보내지 않는다(대상은 매번 달라야 함)."""
        cutoff = now - datetime.timedelta(hours=1)
        self._proactive_log = [(t, k) for (t, k) in self._proactive_log if t >= cutoff]
        senders = {k for _, k in self._proactive_log}
        if char_key in senders:
            return False
        if len(senders) >= self.PROACTIVE_MAX_PER_HOUR:
            return False
        return True

    def _check_activity_transitions(self):
        for key in self._activity_keys:
            if key in self._event_participants_today:
                continue   # 오늘 기념일 대상이면 B안(잡담 선톡)은 쉰다
            persona = persona_loader.load_persona(key)
            if persona is None:
                continue
            now = datetime.datetime.now()
            slot = persona_loader.current_activity(persona, now)
            if slot[0] is None:
                continue

            prev = self._last_activity_slot.get(key)
            self._last_activity_slot[key] = slot
            if prev is None or prev == slot:
                continue   # 첫 기준점이거나 아직 같은 활동 구간 → 발신 안 함

            # 활동이 막 바뀐 순간 발견. 여기서 바로 보내지 않고, 정각에 여러 학생이
            # 한꺼번에 몰리는 걸 피하기 위해 15~45분 사이 랜덤한 시점으로 미뤄서 시도한다.
            # (조건 재확인은 그 예약된 시각에 전부 다시 함 — 아래 _attempt_delayed_proactive)
            delay_sec = random.uniform(self.PROACTIVE_DELAY_MIN_SEC, self.PROACTIVE_DELAY_MAX_SEC)
            QTimer.singleShot(
                int(delay_sec * 1000),
                lambda k=key, s=slot: self._attempt_delayed_proactive(k, s)
            )

    def _attempt_delayed_proactive(self, key, slot):
        """_check_activity_transitions 에서 예약해둔 지연 선톡 시도.
        15~45분이나 지난 뒤라 상황이 달라졌을 수 있으니, 보내도 되는지 조건을 전부 다시 확인한다."""
        if key in self._event_participants_today:
            return
        persona = persona_loader.load_persona(key)
        if persona is None:
            return
        now = datetime.datetime.now()
        # 예약해둔 그 활동 구간이 지금도 유효한지(그 사이 다음 구간으로 넘어가지 않았는지) 확인.
        # 넘어갔다면 이제 와서 그 얘기를 하면 어색하므로 이번 선톡은 조용히 포기한다.
        current_slot = persona_loader.current_activity(persona, now)
        if current_slot != slot:
            return
        # 활동이 바뀌는 순간 발견. 이런저런 이유로 지금은 선톡을 보내면 안 되는 경우들 거르기.
        # 취침중이든 부재중(W)이든 지금은 응답 불가 상태이므로 선톡도 쉰다.
        if persona_loader.availability_status(persona, now) is not None:
            return
        # 이 학생이 지금 다른 요청(실시간 답장/기상/기념일/이전 선톡) 중이면 건너뜀.
        # (다른 학생이 바쁜 것과는 무관 — 학생별 상태이므로.)
        if not self.state.is_idle(key):
            return
        last_spoken = self._last_spoken.get(key)
        if last_spoken is not None and (time.time() - last_spoken) < self.PROACTIVE_COOLDOWN_SEC:
            return   # 방금 무슨 톡이든(실시간 답장/기상 답장 등) 받은 학생은 잠깐 쉼
        if not self._proactive_window_allows(key, now):
            return
        if random.random() > self.PROACTIVE_PROB:
            return

        self._send_proactive(key, slot[1], now)

    def _debug_force_proactive_all(self):
        """[디버그 전용] F8 단축키로 호출됨.
        실제 활동 전환(slot 변경)이나 5분 쿨다운, 시간당 인원 상한을 전부 건너뛰고,
        '지금' 깨어있는 학생 전원을 대상으로 각자 현재 activity 기준 50% 확률로 즉시 선톡을 발동시킨다.
        원래 버그(여러 학생이 겹쳐서 중복 응답)를 실제 대기 없이 즉시 재현해보기 위한 도구.
        상태머신(state.begin)은 그대로 통하므로, 이미 다른 요청이 진행 중인 학생은 여전히 조용히 건너뛴다.
        """
        now = datetime.datetime.now()
        print("[디버그] F8 강제 선톡 트리거 실행 —", now.strftime("%H:%M:%S"))
        picked = []
        for key in self._activity_keys:
            if key in self._event_participants_today:
                continue   # 기념일 대상은 디버그에서도 제외(실제 흐름과 충돌 방지)
            persona = persona_loader.load_persona(key)
            if persona is None:
                continue
            if persona_loader.availability_status(persona, now) is not None:
                continue   # 취침/부재중(W) 학생은 디버그에서도 대상 아님(실제 동작과 일관성 유지)
            slot = persona_loader.current_activity(persona, now)
            if slot[0] is None:
                continue
            if random.random() > self.PROACTIVE_PROB:
                continue   # 여기서도 50% 확률 굴림(실제와 동일한 조건 재현)
            picked.append((key, slot[1]))
            self._send_proactive(key, slot[1], now, debug=True)
        if picked:
            print("[디버그] 이번에 선톡 시도한 학생:", [k for k, _ in picked])
        else:
            print("[디버그] 이번엔 확률/조건에 걸려 아무도 선택 안 됨(다시 눌러보세요)")

    def _send_proactive(self, char_key, activity_desc, now, debug=False):
        api_key = self.config.get("gemini_api_key", "").strip()
        if not api_key:
            return   # 선톡은 조용히 스킵(키 없다고 안내문까지 띄울 필요는 없음)

        persona = persona_loader.load_persona(char_key)
        schedule_context = persona_loader.recent_schedule_context(persona, now, hours=12) if persona else ""
        proactive_note = persona_loader.build_proactive_note(activity_desc, schedule_context)
        # 선톡은 대화 원문(build_history)을 넘기지 않는다 — 73분 전 실시간답장 문구를
        # 그대로 재활용해 반복하는 사고가 실제로 있었음(라이브 확인됨). 애정도/기억은
        # chat_history.json 파일엔 그대로 남으니, 다음 실시간 답장 때는 정상적으로 다시 쓰인다.
        # 선톡은 이제 recent_schedule_context(스케줄 사실)만으로 판단하므로, 구조적으로
        # 과거 대화 문구를 재사용할 수 있는 재료 자체가 없다.
        system_prompt, contents = persona_loader.assemble(
            char_key, [], now=now, proactive_note=proactive_note
        )
        if system_prompt is None:
            return

        if not self.state.begin(char_key, "proactive"):
            return   # 그새 다른 요청이 시작됐으면 이번 선톡은 포기(중복 방지)
        worker = GeminiWorker(
            char_key, api_key, self.config.get("model", ""), system_prompt, contents
        )
        worker.done.connect(lambda k, m, w=worker: self._on_proactive_reply(k, m, w, debug=debug))
        worker.failed.connect(lambda k, e, w=worker: self._on_proactive_failed(k, e, w))
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._workers.append(worker)
        worker.start()
        QTimer.singleShot(
            self.GEMINI_TIMEOUT_MS, lambda w=worker, k=char_key: self._check_proactive_timeout(w, k)
        )

    def _on_proactive_reply(self, char_key, messages, worker=None, debug=False):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)
            return
        self.state.end(char_key)
        self._proactive_log.append((datetime.datetime.now(), char_key))
        self.on_message(char_key, messages, reason="proactive_debug" if debug else "proactive")

    def _on_proactive_failed(self, char_key, error, worker=None):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)
            return
        print("[선톡 실패]", char_key, error)
        self.state.end(char_key)
        # 선톡은 실패해도 사용자에게 폴백 문구를 띄우지 않는다(원래 없던 톡이니 조용히 스킵).

    def _check_proactive_timeout(self, worker, char_key):
        # 타임아웃 시 busy 를 꼭 풀어줘야 한다. 안 풀면 그 학생은 이후 선톡/실시간 답장 모두
        # 영영 막혀버린다(on_user_message 가 proactive_busy 를 보고 계속 양보만 하게 됨).
        if worker not in self._workers:
            return
        print("[모모톡] 선톡 시간 초과 →", char_key)
        self._abandoned_workers.add(worker)
        print("[선톡 실패]", char_key, "시간 초과")
        self.state.end(char_key)

    # ───────── 기념일(학생 생일 / 선생님 생일 / 세계 기념일) ─────────
    def _refresh_daily_events(self):
        """날짜가 바뀌면 오늘 누가 기념일 대상인지, 각자 몇 시에 보낼지 다시 뽑는다."""
        today = datetime.date.today()
        if self._event_day == today:
            return
        self._event_day = today
        self._event_schedule = {}
        self._event_participants_today = set()
        self._event_cancelled = set()

        anniversaries = anniversary_loader.load()
        is_user_bday = anniversary_loader.is_user_birthday_today(anniversaries)
        holiday_name = anniversary_loader.todays_world_holiday(anniversaries)

        for c in self.characters:
            key = c["key"]
            persona = persona_loader.load_persona(key)
            if persona is None:
                continue
            if persona_loader.is_persona_birthday(persona):
                kind, extra = "own_birthday", None
            elif is_user_bday:
                kind, extra = "teacher_birthday", None
            elif holiday_name:
                kind, extra = "world_holiday", holiday_name
            else:
                continue

            self._event_participants_today.add(key)
            if kind == "own_birthday":
                # 자기 생일은 선제적으로 선톡하지 않는다(실시간 답장에서만 다룸) —
                # 그래도 [오늘의 특별한 날] 사실은 필요하니 스케줄엔 등록해둔다(발송 시각은 의미 없음).
                self._event_schedule[key] = {"kind": kind, "extra": extra, "at": None, "sent": True}
                continue
            at = persona_loader.pick_random_awake_datetime(persona, today)
            if at is not None:
                self._event_schedule[key] = {"kind": kind, "extra": extra, "at": at, "sent": False}

        if self._event_participants_today:
            print("[모모톡] 오늘의 기념일 대상:", sorted(self._event_participants_today))

    def _check_daily_events(self):
        self._refresh_daily_events()
        now = datetime.datetime.now()
        for key, ev in list(self._event_schedule.items()):
            if ev["sent"] or key in self._event_cancelled:
                continue
            if now < ev["at"]:
                continue
            persona = persona_loader.load_persona(key)
            if persona is None or persona_loader.availability_status(persona, now) is not None:
                continue   # 아직 취침/부재중이면 다음에 가능해질 때 다시 시도
            if not self.state.is_idle(key):
                continue   # 이 학생이 지금 다른 요청 중이면 다음 체크 때 다시
            self._send_event_message(key, ev)

    def _send_event_message(self, char_key, ev):
        api_key = self.config.get("gemini_api_key", "").strip()
        if not api_key:
            ev["sent"] = True
            return

        persona = persona_loader.load_persona(char_key)
        note = persona_loader.build_event_note(ev["kind"], ev.get("extra"), persona=persona)
        system_prompt, contents = persona_loader.assemble(
            char_key, self.store.get(char_key, []), now=datetime.datetime.now(), event_note=note
        )
        if system_prompt is None:
            ev["sent"] = True
            return

        if not self.state.begin(char_key, "event"):
            return   # 그새 다른 요청이 시작됐으면 sent 표시하지 말고 다음 체크 때 다시 시도
        ev["sent"] = True   # begin 성공 후에만 표시(재시도로 인한 중복 발송 방지)
        worker = GeminiWorker(
            char_key, api_key, self.config.get("model", ""), system_prompt, contents
        )
        worker.done.connect(lambda k, m, w=worker: self._on_event_reply(k, m, w))
        worker.failed.connect(lambda k, e, w=worker: self._on_event_failed(k, e, w))
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._workers.append(worker)
        worker.start()
        QTimer.singleShot(
            self.GEMINI_TIMEOUT_MS, lambda w=worker, k=char_key: self._check_event_timeout(w, k)
        )

    def _on_event_reply(self, char_key, messages, worker=None):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)
            return
        self.state.end(char_key)
        self.on_message(char_key, messages, reason="event")

    def _on_event_failed(self, char_key, error, worker=None):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)
            return
        print("[기념일 메시지 실패]", char_key, error)
        self.state.end(char_key)

    def _check_event_timeout(self, worker, char_key):
        if worker not in self._workers:
            return
        print("[모모톡] 기념일 메시지 시간 초과 →", char_key)
        self._abandoned_workers.add(worker)
        print("[기념일 메시지 실패]", char_key, "시간 초과")
        self.state.end(char_key)

    # ───────────────── 채팅창 열기 ─────────────────
    def open_chat(self, origin=None):
        self.icon.mark_as_read()

        if self.window is None:
            self._refresh_daily_events()   # 오늘 생일 대상이 아직 계산 안 됐으면 지금 해둠
            birthday_keys = {
                k for k, ev in self._event_schedule.items() if ev["kind"] == "own_birthday"
            }
            self.window = ChatWindow(self.characters, self.store, self.unread, birthday_keys)
            self.window.message_sent.connect(self.on_user_message)
            # 학생 전환 시 입력창 잠금을 새 학생 상태에 맞춰 갱신
            self.window.selection_changed.connect(lambda k: self._sync_input_lock())
            # [디버그] F8: 즉시 선톡 강제 트리거
            self.window.debug_proactive_requested.connect(self._debug_force_proactive_all)
            self.window.typing_changed.connect(self._on_typing_activity)
            self._update_presence_dots()   # 창 만들자마자 상태점 첫 반영(30초 타이머 기다리지 않게)

        win = self.window
        if win.selected_key is not None:
            self.unread[win.selected_key] = 0    # 보고 있는 학생은 읽음
        win.refresh()
        self._sync_input_lock()                  # 열 때 현재 학생 상태에 맞춰 입력창 잠금 동기화
        self._update_tray_tooltip()
        if win.isVisible():
            win.raise_()
            win.activateWindow()
            return

        screen = QApplication.primaryScreen().availableGeometry()
        w = min(theme.CHAT_W, screen.width() - 40)
        h = min(theme.CHAT_H, screen.height() - 40)

        icon_center = self.icon.frameGeometry().center()
        # 더블클릭한 좌표를 확대 기준점으로 사용 (없으면 아이콘 중심)
        if origin is None:
            origin = icon_center

        on_left = icon_center.x() < screen.center().x()
        margin = 24
        x = screen.left() + margin if on_left else screen.right() - w - margin
        y = int(screen.center().y() - h / 2)
        y = max(screen.top() + margin, min(y, screen.bottom() - h - margin))
        final = QRect(x, y, w, h)

        # 최종 중앙을 기준으로 작게 시작 → 확대 (슬라이드 없이 zoom)
        sw, sh = int(w * 0.62), int(h * 0.62)
        cx, cy = final.center().x(), final.center().y()
        start = QRect(int(cx - sw / 2), int(cy - sh / 2), sw, sh)
        win.setGeometry(start)
        win.setWindowOpacity(0.0)
        win.show()
        win.raise_()
        win.activateWindow()
        self._animate_open(win, start, final)

    def _animate_open(self, win, start, final):
        geo = QPropertyAnimation(win, b"geometry")
        geo.setDuration(300)
        geo.setStartValue(start)
        geo.setEndValue(final)
        curve = QEasingCurve(QEasingCurve.OutBack)   # 살짝 튀어나왔다 안착(back out)
        curve.setOvershoot(1.4)
        geo.setEasingCurve(curve)

        fade = QPropertyAnimation(win, b"windowOpacity")
        fade.setDuration(160)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup()
        group.addAnimation(geo)
        group.addAnimation(fade)
        group.start()
        self._open_anim = group


def main():
    import platform
    from PyQt5.QtCore import QT_VERSION_STR

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    # [UX] 작업표시줄에 '파이썬'이 아니라 모모톡으로 뜨게 하기.
    # Windows는 taskbar 항목을 실행파일(python.exe) 기준으로 묶기 때문에,
    # AppUserModelID를 직접 지정해줘야 별도의 앱으로 인식하고 아이콘도 따로 표시한다.
    if platform.system() == "Windows":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("momotalk.widget")
        except Exception as e:
            print("[모모톡] 작업표시줄 아이콘 설정 실패(무시 가능):", e)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("모모톡")
    _icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "momotalk.png")
    if os.path.exists(_icon_path):
        from PyQt5.QtGui import QIcon
        app.setWindowIcon(QIcon(_icon_path))

    # 앱 전용 폰트 로드 후 전체 기본 폰트로 지정
    from PyQt5.QtGui import QFont
    family = load_app_font()
    app.setFont(QFont(family))

    print("[모모톡] 시작합니다... (Python %s / Qt %s)"
          % (platform.python_version(), QT_VERSION_STR))
    try:
        # ★ 중요: 반드시 변수에 담아둔다.
        #   담지 않으면 객체가 곧바로 가비지 컬렉션되어 아이콘 창이 사라진다.
        controller = MomoApp()
    except Exception:
        import traceback
        print("[모모톡] !! 시작 중 오류가 발생했습니다 !!")
        traceback.print_exc()
        input("Enter 키를 누르면 종료합니다...")
        return

    app.aboutToQuit.connect(controller._save_history)   # 종료 시 대화 저장
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
