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
        self._waiting = False       # 답장 대기 중(쿨다운)
        self.GEMINI_TIMEOUT_MS = 25 * 1000   # 이 시간 안에 응답이 없으면 클라이언트 쪽에서 포기 처리
        self._abandoned_workers = set()      # 타임아웃으로 포기한 워커(뒤늦게 응답 와도 무시하기 위함)

        # 여러 톡이 한꺼번에 오지 않도록: 큐에 넣고 [입력중...] 표시 후 하나씩
        self._msg_queue = []
        self._delivering = False
        self.TYPING_MS = 1800        # 한 톡당 '입력 중' 표시 시간(간격)
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
        self.scheduler.message_ready.connect(self.on_message)
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
        self._proactive_busy = set()    # 지금 선톡 생성 중인 학생 key (중복 호출 방지)
        self._proactive_log = []        # [(보낸시각, 학생key), ...] 최근 1시간 내 선톡 기록(인원 제한용)
        self.PROACTIVE_MAX_PER_HOUR = 4  # 굴러가는 1시간 동안 선톡 보낼 수 있는 서로 다른 학생 수 상한
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


    def on_message(self, char_key, messages):
        # 어떤 경로로든(선톡/기상답장/기념일 등이 겹치는 등) 방금 배달한 것과 완전히 같은
        # 메시지 묶음이 짧은 시간 안에 다시 들어오면 중복으로 보고 무시한다.
        now_ts = time.time()
        batch = tuple(messages)
        last = self._last_delivered.get(char_key)
        if last is not None and last[0] == batch and (now_ts - last[1]) < 20:
            print("[모모톡] 중복 메시지 감지 → 무시:", char_key, batch)
            return
        self._last_delivered[char_key] = (batch, now_ts)
        self._last_spoken[char_key] = now_ts   # 선톡 쿨다운 판정용

        idle = (len(self._msg_queue) == 0 and not self._delivering)
        for m in messages:
            self._msg_queue.append((char_key, m))
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
        char_key, text = self._msg_queue.pop(0)
        if self.window is not None:
            self.window._typing_key = None        # 점 제거(아래 refresh가 새로 그림)
        self.store.setdefault(char_key, []).append(("recv", text))

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
        self._save_history()                       # 방금 보낸 내 톡 저장
        if self._waiting:
            return                                 # 쿨다운: 답장 받는 중엔 무시
        if char_key in self._proactive_busy:
            # 마침 이 학생에게 선톡/기념일 메시지가 만들어지고 있는 중.
            # 그대로 같이 호출하면 답장이 겹쳐 보이니, 살짝 기다렸다가 한 번만 다시 시도한다.
            QTimer.singleShot(800, lambda: self.on_user_message(char_key))
            return

        persona = persona_loader.load_persona(char_key)
        if persona is None:
            self.on_message(char_key, ["(prompts/%s.json 이 없어요.)" % char_key])
            return

        now = datetime.datetime.now()
        if not persona_loader.is_awake(persona, now):
            self._queue_pending(char_key, now)      # 자는 시간: 호출 안 하고 대기함에 저장
            return

        api_key = self.config.get("gemini_api_key", "").strip()
        if not api_key:
            self.on_message(char_key, ["(config.json 에 API 키를 넣어주세요.)"])
            return

        self._refresh_daily_events()   # 혹시 아직 오늘 기념일 계산 전이면 지금 해둠
        event_note = ""
        ev = self._event_schedule.get(char_key)
        if ev is not None:
            event_note = persona_loader.build_event_note(ev["kind"], ev.get("extra"))
            if ev["kind"] == "own_birthday" and not ev["sent"]:
                # 선생님이 먼저 말을 걸었으니, 예약해둔 '학생이 먼저 생일 알리기'는 취소
                self._event_cancelled.add(char_key)

        system_prompt, contents = persona_loader.assemble(
            char_key, self.store.get(char_key, []), now=now, event_note=event_note
        )
        if system_prompt is None:
            self.on_message(char_key, ["(prompts/%s.json 이 없어요.)" % char_key])
            return

        self._waiting = True
        if self.window is not None:
            self.window.set_input_enabled(False)
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
        self._waiting = False
        if self.window is not None:
            self.window.set_input_enabled(True)
            self.window._typing_key = None
        self.on_message(char_key, messages)        # 기존 입력중→간격 전달로 출력

    def _on_reply_failed(self, char_key, error, worker=None):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)
            return
        print("[Gemini 실패]", char_key, error)
        self._waiting = False
        if self.window is not None:
            self.window.set_input_enabled(True)
            self.window._typing_key = None
        self.on_message(char_key, ["지금은 답장하기 어려워요.", "잠시 후 다시 말 걸어줘요."])

    def _check_live_timeout(self, worker, char_key):
        """일정 시간 안에 응답이 없으면 응답을 포기하고 UI 잠금을 풀어준다(무한 로딩 방지)."""
        if worker not in self._workers:
            return   # 이미 끝났음 → 정상 처리된 것이니 아무 것도 안 함
        print("[모모톡] 응답 시간 초과 →", char_key)
        self._abandoned_workers.add(worker)
        self._waiting = False
        if self.window is not None:
            self.window.set_input_enabled(True)
            self.window._typing_key = None
            if self.window.isVisible():
                self.window.clear_typing()
        self.on_message(char_key, ["지금은 답장하기 어려워요.", "잠시 후 다시 말 걸어줘요."])

    def _cleanup_worker(self, worker):
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    # ───────────────── 수면 중: 대기 저장 + 부재중 안내 ─────────────────
    def _queue_pending(self, char_key, now):
        """학생이 자는 시간에 온 톡: API 호출 없이 대기함에 저장하고 부재중 안내만 띄운다."""
        last_text = ""
        conv = self.store.get(char_key, [])
        if conv and conv[-1][0] == "send":
            last_text = conv[-1][1]
        self.pending.setdefault(char_key, []).append(
            {"text": last_text, "at": now.isoformat()}
        )
        self._deliver_absent_notice(char_key)
        self._save_history()

    def _deliver_absent_notice(self, char_key):
        """'(지금은 부재중입니다.)' 안내를 즉시(타이핑 표시 없이) 붙인다. API 실패 폴백과는 별개."""
        self.store.setdefault(char_key, []).append(("absent", "(지금은 부재중입니다.)"))

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
            if persona is not None and persona_loader.is_awake(persona, now):
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
        self.pending[char_key] = []
        self._save_history()

        api_key = self.config.get("gemini_api_key", "").strip()
        if not api_key:
            self.on_message(char_key, ["(어, 미안. 이제 봤어. 근데 config.json에 키가 없어서 답장을 못 만들겠어.)"])
            QTimer.singleShot(1200, self._process_next_wake)
            return

        wake_note = persona_loader.build_wake_note(msgs)
        self._refresh_daily_events()
        event_note = ""
        ev = self._event_schedule.get(char_key)
        if ev is not None:
            event_note = persona_loader.build_event_note(ev["kind"], ev.get("extra"))
            if ev["kind"] == "own_birthday" and not ev["sent"]:
                self._event_cancelled.add(char_key)   # 선생님이 자는 동안 보낸 톡에 답하는 것도 '대화 발생'으로 취급

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
        self.on_message(char_key, messages)
        self._poll_wake_continue()

    def _on_wake_reply_failed(self, char_key, error, worker=None):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)
            return
        print("[기상 답장 실패]", char_key, error)
        self.on_message(char_key, ["지금은 답장하기 어려워요.", "잠시 후 다시 말 걸어줘요."])
        self._poll_wake_continue()

    def _check_wake_timeout(self, worker, char_key):
        if worker not in self._workers:
            return
        print("[모모톡] 기상 답장 시간 초과 →", char_key)
        self._abandoned_workers.add(worker)
        print("[기상 답장 실패]", char_key, "시간 초과")
        self.on_message(char_key, ["지금은 답장하기 어려워요.", "잠시 후 다시 말 걸어줘요."])
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

            # 활동이 바뀌는 순간 발견. 이런저런 이유로 지금은 선톡을 보내면 안 되는 경우들 거르기.
            if not persona_loader.is_awake(persona, now):
                continue
            if self._waiting or self._wake_processing:
                continue
            if key in self._proactive_busy:
                continue
            last_spoken = self._last_spoken.get(key)
            if last_spoken is not None and (time.time() - last_spoken) < self.PROACTIVE_COOLDOWN_SEC:
                continue   # 방금 무슨 톡이든(실시간 답장/기상 답장 등) 받은 학생은 잠깐 쉼
            if not self._proactive_window_allows(key, now):
                continue
            if random.random() > self.PROACTIVE_PROB:
                continue

            self._send_proactive(key, slot[1], now)

    def _send_proactive(self, char_key, activity_desc, now):
        api_key = self.config.get("gemini_api_key", "").strip()
        if not api_key:
            return   # 선톡은 조용히 스킵(키 없다고 안내문까지 띄울 필요는 없음)

        proactive_note = persona_loader.build_proactive_note(activity_desc)
        system_prompt, contents = persona_loader.assemble(
            char_key, self.store.get(char_key, []), now=now, proactive_note=proactive_note
        )
        if system_prompt is None:
            return

        self._proactive_busy.add(char_key)
        worker = GeminiWorker(
            char_key, api_key, self.config.get("model", ""), system_prompt, contents
        )
        worker.done.connect(lambda k, m, w=worker: self._on_proactive_reply(k, m, w))
        worker.failed.connect(lambda k, e, w=worker: self._on_proactive_failed(k, e, w))
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._workers.append(worker)
        worker.start()
        QTimer.singleShot(
            self.GEMINI_TIMEOUT_MS, lambda w=worker, k=char_key: self._check_proactive_timeout(w, k)
        )

    def _on_proactive_reply(self, char_key, messages, worker=None):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)
            return
        self._proactive_busy.discard(char_key)
        self._proactive_log.append((datetime.datetime.now(), char_key))
        self.on_message(char_key, messages)

    def _on_proactive_failed(self, char_key, error, worker=None):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)
            return
        print("[선톡 실패]", char_key, error)
        self._proactive_busy.discard(char_key)
        # 선톡은 실패해도 사용자에게 폴백 문구를 띄우지 않는다(원래 없던 톡이니 조용히 스킵).

    def _check_proactive_timeout(self, worker, char_key):
        # 타임아웃 시 busy 를 꼭 풀어줘야 한다. 안 풀면 그 학생은 이후 선톡/실시간 답장 모두
        # 영영 막혀버린다(on_user_message 가 proactive_busy 를 보고 계속 양보만 하게 됨).
        if worker not in self._workers:
            return
        print("[모모톡] 선톡 시간 초과 →", char_key)
        self._abandoned_workers.add(worker)
        print("[선톡 실패]", char_key, "시간 초과")
        self._proactive_busy.discard(char_key)

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
            if persona is None or not persona_loader.is_awake(persona, now):
                continue   # 아직 안 깨어났으면 다음에 깨어있을 때 다시 시도
            if key in self._proactive_busy or self._waiting or self._wake_processing:
                continue
            self._send_event_message(key, ev)

    def _send_event_message(self, char_key, ev):
        api_key = self.config.get("gemini_api_key", "").strip()
        if not api_key:
            ev["sent"] = True
            return

        note = persona_loader.build_event_note(ev["kind"], ev.get("extra"))
        system_prompt, contents = persona_loader.assemble(
            char_key, self.store.get(char_key, []), now=datetime.datetime.now(), event_note=note
        )
        if system_prompt is None:
            ev["sent"] = True
            return

        ev["sent"] = True   # 먼저 표시해서 재시도로 중복 발송되지 않게 함
        self._proactive_busy.add(char_key)
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
        self._proactive_busy.discard(char_key)
        self.on_message(char_key, messages)

    def _on_event_failed(self, char_key, error, worker=None):
        if worker is not None and worker in self._abandoned_workers:
            self._abandoned_workers.discard(worker)
            return
        print("[기념일 메시지 실패]", char_key, error)
        self._proactive_busy.discard(char_key)

    def _check_event_timeout(self, worker, char_key):
        if worker not in self._workers:
            return
        print("[모모톡] 기념일 메시지 시간 초과 →", char_key)
        self._abandoned_workers.add(worker)
        print("[기념일 메시지 실패]", char_key, "시간 초과")
        self._proactive_busy.discard(char_key)

    # ───────────────── 채팅창 열기 ─────────────────
    def open_chat(self, origin=None):
        self.icon.mark_as_read()

        if self.window is None:
            self.window = ChatWindow(self.characters, self.store, self.unread)
            self.window.message_sent.connect(self.on_user_message)

        win = self.window
        if win.selected_key is not None:
            self.unread[win.selected_key] = 0    # 보고 있는 학생은 읽음
        win.refresh()
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

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

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
