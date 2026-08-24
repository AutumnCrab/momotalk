# -*- coding: utf-8 -*-
"""
Windows 자체 토스트 대신 쓰는 모모톡 커스텀 알림 팝업.

화면 우측 하단에 최대 3개까지 쌓인다(제일 최근 게 코너에 제일 가깝게, 오래된 게 위로).
4번째가 오면 제일 오래된(제일 위) 게 오른쪽으로 페이드되며 사라지고 나머지가 자리를 당긴다.
5초 뒤 자동으로 같은 방식(오른쪽 페이드)으로 사라진다. 클릭하면 즉시 사라지면서 콜백 실행.
알림이 연달아 들어오면 한꺼번에 뜨지 않고 STAGGER_MS 간격을 두고 하나씩 나타난다.

캐릭터 말풍선 알림(ChatToast)과 앱 상태 알림(StatusToast, 흰 배경 검은 글씨)이 같은 스택을 공유한다.
"""
import time

from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QLinearGradient, QFont, QFontMetrics
from PyQt5.QtWidgets import QWidget, QApplication, QLabel

from . import theme
from .avatar import make_circular_avatar

WIDTH = 374    # 원래 크기(340)에서 10% 키움
MARGIN_X = 16
MARGIN_Y = 16
GAP = 11
DURATION_MS = 5000
ANIM_MS = 220
MAX_VISIBLE = 3
EVICT_SLIDE_PX = 66
STAGGER_MS = 2300   # 알림이 연달아 오면 이 간격을 두고 하나씩 표시(동시에 우르르 뜨지 않게)

# 채팅창 헤더(theme.HEADER_GRAD_TOP/BOTTOM)와는 별개로, 알림 팝업 전용으로 위쪽을
# 더 연하게 뺀 그라데이션(위쪽이 너무 짙어 보인다는 피드백 반영).
TOAST_GRAD_TOP = "#FFAEC7"
TOAST_GRAD_BOTTOM = "#FFC3D6"


class _ToastBase(QWidget):
    clicked = pyqtSignal()

    def __init__(self, height):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(WIDTH, height)
        self._manager = None
        self._anims = []   # QPropertyAnimation GC 방지용 참조 보관
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._on_timeout)

    def start_timer(self):
        self._dismiss_timer.start(DURATION_MS)

    def _on_timeout(self):
        if self._manager is not None:
            self._manager.dismiss(self)

    def mousePressEvent(self, e):
        self._dismiss_timer.stop()
        self.clicked.emit()
        if self._manager is not None:
            self._manager.dismiss(self)


class ChatToast(_ToastBase):
    """학생 메시지 알림 — 채팅 말풍선 스타일(핑크 그라데이션 + 아바타).
    메시지 길이(1~2줄)에 따라 세로 높이를 계산해서, 아바타 열과 텍스트 열 둘 다
    위/아래 여백이 항상 같게(가운데 정렬) 맞춘다 — 짧은 메시지에서 아래쪽만
    허전하게 남는 문제 방지."""

    PAD_LEFT = 18
    PAD_RIGHT = 20
    PAD_V = 18
    AVATAR_SIZE = 46
    CONTENT_LEFT = 77   # PAD_LEFT + AVATAR_SIZE + 13
    NAME_H = 20
    NAME_GAP = 4
    NAME_PX = 14
    MSG_PX = 13

    def __init__(self, char_key, name, profile_img, text):
        preview = text if len(text) <= 46 else text[:43] + "..."
        box_w = WIDTH - self.CONTENT_LEFT - self.PAD_RIGHT
        msg_h = self._wrapped_height(preview, box_w, self.MSG_PX)
        text_block_h = self.NAME_H + self.NAME_GAP + msg_h
        content_h = max(text_block_h, self.AVATAR_SIZE)
        height = content_h + self.PAD_V * 2
        super().__init__(height)
        self.char_key = char_key

        av = QLabel(self)
        av.setPixmap(make_circular_avatar(profile_img, self.AVATAR_SIZE, name))
        av.setGeometry(
            self.PAD_LEFT, self.PAD_V + (content_h - self.AVATAR_SIZE) // 2,
            self.AVATAR_SIZE, self.AVATAR_SIZE,
        )

        text_top = self.PAD_V + (content_h - text_block_h) // 2
        name_lbl = QLabel(name, self)
        name_lbl.setStyleSheet(
            "color: %s; font-weight: 700; font-size: %dpx; background: transparent;"
            % (theme.TEXT_DARK, self.NAME_PX)
        )
        name_lbl.setGeometry(self.CONTENT_LEFT, text_top, box_w, self.NAME_H)

        msg_lbl = QLabel(preview, self)
        msg_lbl.setStyleSheet(
            "color: %s; font-size: %dpx; background: transparent;" % (theme.TEXT_DARK, self.MSG_PX)
        )
        msg_lbl.setGeometry(self.CONTENT_LEFT, text_top + self.NAME_H + self.NAME_GAP, box_w, msg_h)
        msg_lbl.setWordWrap(True)
        msg_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)

    @staticmethod
    def _wrapped_height(text, width, pixel_size):
        font = QFont(theme.FONT_FAMILY)
        font.setPixelSize(pixel_size)
        fm = QFontMetrics(font)
        rect = fm.boundingRect(QRect(0, 0, width, 10000), Qt.TextWordWrap, text)
        return max(rect.height(), fm.height())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0, QColor(TOAST_GRAD_TOP))
        grad.setColorAt(1, QColor(TOAST_GRAD_BOTTOM))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(self.rect(), 18, 18)


class StatusToast(_ToastBase):
    """앱 상태 알림(설정 저장/아이콘 숨김 등) — 흰 배경 + 검은 글씨, 아바타 없음."""
    HEIGHT = 53
    PAD_H = 18

    def __init__(self, text):
        super().__init__(self.HEIGHT)
        lbl = QLabel(text, self)
        lbl.setStyleSheet("color: #333333; font-size: 13px; background: transparent;")
        lbl.setGeometry(self.PAD_H, 0, WIDTH - self.PAD_H * 2, self.HEIGHT)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignVCenter)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(self.rect(), 13, 13)


class ToastManager:
    """알림 스택 관리자. main.py 에서 하나만 만들어 재사용한다.
    self._stack[0] = 코너에 제일 가까운(=제일 최근) 알림, 마지막 = 제일 오래된(=제일 위)."""

    def __init__(self):
        self._stack = []
        self._queue = []
        self._pump_timer = QTimer()
        self._pump_timer.setSingleShot(True)
        self._pump_timer.timeout.connect(self._pump)
        self._last_shown_ts = 0.0

    def _screen(self):
        return QApplication.primaryScreen().availableGeometry()

    def show_chat_toast(self, char_key, name, profile_img, text, on_click, on_shown=None):
        t = ChatToast(char_key, name, profile_img, text)
        t.clicked.connect(on_click)
        t._on_shown = on_shown
        self._enqueue(t)

    def show_status_toast(self, text):
        self._enqueue(StatusToast(text))

    def _enqueue(self, widget):
        self._queue.append(widget)
        if not self._pump_timer.isActive():
            self._pump()

    def _pump(self):
        if not self._queue:
            return
        now = time.monotonic()
        wait_left = STAGGER_MS / 1000.0 - (now - self._last_shown_ts)
        if wait_left > 0:
            self._pump_timer.start(int(wait_left * 1000))
            return
        widget = self._queue.pop(0)
        self._add(widget)
        self._last_shown_ts = time.monotonic()
        if self._queue:
            self._pump_timer.start(STAGGER_MS)

    def _add(self, widget):
        widget._manager = self
        widget.show()
        on_shown = getattr(widget, "_on_shown", None)
        if on_shown is not None:
            on_shown()
        self._stack.insert(0, widget)
        overflow = self._stack.pop() if len(self._stack) > MAX_VISIBLE else None
        self._reflow(entering=widget)
        if overflow is not None:
            self._evict(overflow)
        widget.start_timer()

    def dismiss(self, widget):
        """클릭 또는 타임아웃으로 알림 하나를 없앤다. 나머지는 자리를 당긴다."""
        if widget not in self._stack:
            return
        self._stack.remove(widget)
        self._evict(widget)
        self._reflow()

    def _reflow(self, entering=None):
        screen = self._screen()
        x = screen.right() - MARGIN_X - WIDTH
        y = screen.bottom() - MARGIN_Y
        for w in self._stack:
            y -= w.height()
            target = QRect(x, y, w.width(), w.height())
            if w is entering:
                start = QRect(x + EVICT_SLIDE_PX, y, w.width(), w.height())
                w.setGeometry(start)
                w.setWindowOpacity(0.0)
                self._animate(w, start, target, fade_in=True)
            else:
                self._animate(w, w.geometry(), target, fade_in=False)
            y -= GAP

    def _animate(self, widget, start, end, fade_in):
        geo = QPropertyAnimation(widget, b"geometry", widget)
        geo.setDuration(ANIM_MS)
        geo.setStartValue(start)
        geo.setEndValue(end)
        geo.setEasingCurve(QEasingCurve.OutCubic)
        widget._anims.append(geo)
        geo.start(QPropertyAnimation.DeleteWhenStopped)
        if fade_in:
            op = QPropertyAnimation(widget, b"windowOpacity", widget)
            op.setDuration(ANIM_MS)
            op.setStartValue(0.0)
            op.setEndValue(1.0)
            widget._anims.append(op)
            op.start(QPropertyAnimation.DeleteWhenStopped)

    def _evict(self, widget):
        """오른쪽으로 슬라이드 + 페이드아웃 시키며 제거."""
        widget._dismiss_timer.stop()
        rect = widget.geometry()
        end = QRect(rect.x() + EVICT_SLIDE_PX, rect.y(), rect.width(), rect.height())
        geo = QPropertyAnimation(widget, b"geometry", widget)
        geo.setDuration(ANIM_MS)
        geo.setStartValue(rect)
        geo.setEndValue(end)
        geo.setEasingCurve(QEasingCurve.OutCubic)
        op = QPropertyAnimation(widget, b"windowOpacity", widget)
        op.setDuration(ANIM_MS)
        op.setStartValue(1.0)
        op.setEndValue(0.0)
        op.finished.connect(widget.deleteLater)
        widget._anims.extend([geo, op])
        geo.start(QPropertyAnimation.DeleteWhenStopped)
        op.start(QPropertyAnimation.DeleteWhenStopped)
