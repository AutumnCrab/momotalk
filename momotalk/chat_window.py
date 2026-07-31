# -*- coding: utf-8 -*-
"""
모모톡 채팅창.

[맨 왼쪽] 세로 아이콘 레일: '메시지' / '학생' 전환 (아이콘 크게).
[가운데]  학생 목록. 선택 행은 모서리부터 모서리까지 꽉 찬 강조(라운드 없음).
          잘리는 글은 ··· 로 말줄임.
[오른쪽]  대화 + 하단 입력창(엔터/보내기). 말풍선/폰트/프로필 크게.
"""

import os
from momotalk.paths import get_base_dir
import datetime

from PyQt5.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout,
    QScrollArea, QSizePolicy, QStackedWidget,
)
from PyQt5.QtCore import (
    Qt, QRectF, QPointF, QTimer, pyqtSignal, pyqtProperty,
    QPropertyAnimation, QEasingCurve
)
from PyQt5.QtGui import (
    QPainter, QPainterPath, QColor, QPen, QPolygonF, QPixmap, QRegion, QFont, QFontMetrics, QIcon
)

from . import theme
from .avatar import make_circular_avatar

BASE_DIR = get_base_dir()


def _asset(name):
    return os.path.join(BASE_DIR, "assets", name)


def _load_png(name):
    path = _asset(name)
    if os.path.exists(path):
        pm = QPixmap(path)
        if not pm.isNull():
            return pm
    return None


def _font(px, bold=False):
    f = QFont(theme.FONT_FAMILY)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


class _ElideLabel(QLabel):
    """고정 너비를 넘는 텍스트를 ··· 로 잘라 보여주는 라벨."""
    def __init__(self, text, width, font, color):
        super().__init__()
        self._full = text or ""
        self.setFont(font)
        self.setFixedWidth(width)
        self.setStyleSheet("color:%s;background:transparent;" % color)
        self._apply()

    def setText(self, text):
        self._full = text or ""
        self._apply()

    def _apply(self):
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, Qt.ElideRight, self.width()))


class _BounceScroll(QScrollArea):
    """스크롤바를 숨기고, 부드러운 휠 스크롤 + 끝에서 고무줄(바운스) 효과."""
    def __init__(self):
        super().__init__()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._bounce = 0
        self._bounce_anim = QPropertyAnimation(self, b"bounce", self)
        self._bounce_anim.setEasingCurve(QEasingCurve.OutQuad)

    def getBounce(self):
        return self._bounce

    def setBounce(self, v):
        self._bounce = v
        w = self.widget()
        if w is not None:
            # 현재 스크롤 위치에 바운스 오프셋을 더해 내부 위젯을 살짝 밀었다 되돌림
            w.move(0, -self.verticalScrollBar().value() + v)

    bounce = pyqtProperty(int, fget=getBounce, fset=setBounce)

    def _start_bounce(self, direction):
        # direction: +1(위쪽 끝에서 아래로 당김) / -1(아래쪽 끝에서 위로 당김)
        if self._bounce_anim.state() == QPropertyAnimation.Running:
            return
        self._bounce_anim.stop()
        self._bounce_anim.setDuration(280)
        self._bounce_anim.setStartValue(0)
        self._bounce_anim.setKeyValueAt(0.35, direction * 34)
        self._bounce_anim.setEndValue(0)
        self._bounce_anim.start()

    def wheelEvent(self, e):
        bar = self.verticalScrollBar()
        delta = e.angleDelta().y()
        if delta == 0:
            e.accept()
            return
        cur = bar.value()
        at_top = cur <= bar.minimum()
        at_bottom = cur >= bar.maximum()

        # 끝에 닿은 상태에서 더 굴리면 → 고무줄 바운스
        if (at_top and delta > 0) or (at_bottom and delta < 0):
            self._start_bounce(1 if delta > 0 else -1)
            e.accept()
            return

        # 부드러운 스크롤 (목표값으로 애니메이션)
        target = cur - delta
        target = max(bar.minimum(), min(bar.maximum(), target))
        self._anim.stop()
        self._anim.setDuration(170)
        self._anim.setStartValue(cur)
        self._anim.setEndValue(target)
        self._anim.start()
        e.accept()


class _Header(QFrame):
    def __init__(self, window):
        super().__init__()
        self._win = window
        self._offset = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._offset = e.globalPos() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._offset is not None and (e.buttons() & Qt.LeftButton):
            self._win.move(e.globalPos() - self._offset)

    def mouseReleaseEvent(self, e):
        self._offset = None


class _RailButton(QFrame):
    """세로 레일의 아이콘 버튼 (kind: 'friend' / 'message'). 아이콘 30% 확대."""
    clicked = pyqtSignal(str)
    PNG_NAME = {"message": "message.png", "friend": "student.png"}

    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.selected = False
        self._png = _load_png(self.PNG_NAME.get(kind, ""))
        self.setFixedSize(56, 56)
        self.setCursor(Qt.PointingHandCursor)

    def set_selected(self, sel):
        self.selected = sel
        self.update()

    def mousePressEvent(self, e):
        self.clicked.emit(self.kind)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self.selected:
            p.fillRect(self.rect(), QColor(theme.RAIL_ACTIVE))
        p.setOpacity(1.0 if self.selected else 0.5)

        if self._png is not None:
            side = 34  # 26 → 34 (약 +30%)
            x = (self.width() - side) / 2.0
            y = (self.height() - side) / 2.0
            p.drawPixmap(QRectF(x, y, side, side), self._png, QRectF(self._png.rect()))
            return

        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        cx, cy = self.width() / 2.0, self.height() / 2.0
        if self.kind == "friend":
            p.drawEllipse(QRectF(cx - 6.5, cy - 15.5, 13, 13))
            dome = QPainterPath()
            dome.moveTo(cx - 13, cy + 12)
            dome.arcTo(QRectF(cx - 13, cy - 4, 26, 31), 180, -180)
            dome.closeSubpath()
            p.drawPath(dome)
        else:
            p.drawRoundedRect(QRectF(cx - 14, cy - 11, 28, 21), 6, 6)
            tail = QPolygonF([
                QPointF(cx - 8, cy + 7), QPointF(cx - 13, cy + 15), QPointF(cx - 1, cy + 7)
            ])
            p.drawPolygon(tail)


class _Row(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, key):
        super().__init__()
        self._key = key

    def mousePressEvent(self, e):
        self.clicked.emit(self._key)


class _TypingDots(QWidget):
    """학생이 입력 중일 때 보여줄 '···' 통통 튀는 말풍선."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(60, 40)
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(200)

    def _tick(self):
        self._phase = (self._phase + 1) % 3
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.RECV_BUBBLE))
        p.drawRoundedRect(QRectF(self.rect()), 16, 16)
        cy = self.height() / 2.0
        gap = 13
        cx0 = self.width() / 2.0 - gap
        for i in range(3):
            up = 3 if i == self._phase else 0
            if i == self._phase:
                p.setBrush(QColor(255, 255, 255))
            else:
                p.setBrush(QColor(200, 206, 214))
            p.drawEllipse(QPointF(cx0 + i * gap, cy - up), 4.0, 4.0)


class ChatWindow(QWidget):
    message_sent = pyqtSignal(str)     # 선생님이 톡을 보냄 (char key)
    selection_changed = pyqtSignal(str)  # 다른 학생 대화로 전환함 (char key) — 입력창 잠금 재동기화용
    debug_proactive_requested = pyqtSignal()  # [디버그] F8: 깨어있는 학생 전원 대상 즉시 선톡 트리거
    typing_changed = pyqtSignal(str)   # 입력창에 실제 텍스트 변경(타이핑)이 있음 (char key)
    window_hidden = pyqtSignal()       # 대화창이 닫힘(숨겨짐) — 플로팅 아이콘 배지 재동기화용

    def __init__(self, characters, store, unread=None, birthday_keys=None):
        super().__init__()
        self.characters = characters
        self.store = store
        self.unread = unread if unread is not None else {}
        self.birthday_keys = birthday_keys or set()   # 오늘 생일인 학생 key 집합(정적, 하루 단위)
        self.selected_key = characters[0]["key"] if characters else None
        self.mode = "message"
        self._typing_key = None
        self._rail_buttons = {}
        self._friend_rows = {}
        self._msg_rows = {}
        self._msg_snippets = {}
        self._badges = {}              # key -> [배지 라벨들(메시지/학생 양쪽)]
        self._status_dots = {}         # key -> 상태 점등 QLabel (학생소개 탭)
        self._presence = {}            # key -> None/'sleep'/'busy' (마지막으로 받은 상태, 재구성 대비용)
        self._init_window()
        self._build_ui()
        self.refresh()

    def _init_window(self):
        # 일반 창처럼 동작(다른 앱 클릭 시 뒤로 감) → StaysOnTop/Tool 제거
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setWindowTitle("MomoTalk")
        # [UX] 작업표시줄에 파이썬 기본 아이콘 대신 모모톡 아이콘이 뜨도록.
        import os
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "momotalk.png"
        )
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(theme.CHAT_W, theme.CHAT_H)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 16, 16)
        p.fillPath(path, QColor("#FFFFFF"))
        p.setPen(QPen(QColor("#E3E3EA"), 1))
        p.drawPath(path)

    def _update_mask(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 16, 16)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, e):
        self._update_mask()

    def hideEvent(self, e):
        # 대화창이 닫히는 순간, 열려 있는 동안 안 띄웠던 안읽음 개수를
        # 플로팅 아이콘 배지에 반영할 수 있도록 알린다.
        super().hideEvent(e)
        self.window_hidden.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
        elif e.key() == Qt.Key_F8:
            # [디버그 전용] 실제 대기 없이 즉시 선톡 트리거 재현용. 배포판에선 몰라도 무해함.
            self.debug_proactive_requested.emit()

    # ───────────────────────── UI ─────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_rail())
        body.addWidget(self._build_stack())
        body.addWidget(self._build_conversation_panel(), 1)
        outer.addLayout(body, 1)

    def _build_header(self):
        header = _Header(self)
        header.setObjectName("hdr")
        header.setFixedHeight(50)
        header.setStyleSheet(
            "#hdr{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 %s, stop:1 %s);"
            "border-top-left-radius:16px;border-top-right-radius:16px;}"
            % (theme.HEADER_GRAD_TOP, theme.HEADER_GRAD_BOTTOM)
        )
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 0, 12, 0)
        h.setSpacing(8)

        logo = QLabel()
        logo_pm = _load_png("logo.png")
        if logo_pm is not None:
            logo.setPixmap(logo_pm.scaled(26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            logo.setText("\u2665")
            logo.setStyleSheet("color:white;font-size:17px;")

        title = QLabel("MomoTalk")
        title.setStyleSheet(
            "color:white;font-weight:bold;font-size:17px;font-family:'%s';" % theme.FONT_FAMILY
        )
        close = QPushButton("\u2715")
        close.setFixedSize(28, 28)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(
            "QPushButton{color:white;border:none;font-size:14px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.25);border-radius:14px;}"
        )
        close.clicked.connect(self.hide)
        h.addWidget(logo)
        h.addWidget(title)
        h.addStretch(1)
        h.addWidget(close)
        return header

    def _build_rail(self):
        rail = QFrame()
        rail.setFixedWidth(58)
        rail.setStyleSheet("background:%s;" % theme.RAIL_BG)
        v = QVBoxLayout(rail)
        v.setContentsMargins(0, 10, 0, 10)
        v.setSpacing(2)
        for kind in ("message", "friend"):
            btn = _RailButton(kind)
            btn.clicked.connect(self._switch_mode)
            self._rail_buttons[kind] = btn
            v.addWidget(btn, 0, Qt.AlignHCenter)
        v.addStretch(1)
        self._rail_buttons["message"].set_selected(True)
        return rail

    def _build_stack(self):
        self.stack = QStackedWidget()
        self.stack.setFixedWidth(theme.LIST_W)
        self.stack.addWidget(self._build_msg_page())     # index 0
        self.stack.addWidget(self._build_friend_page())  # index 1
        self.stack.setCurrentIndex(0)
        return self.stack

    def _list_scaffold(self, caption_text, bg):
        page = QFrame()
        page.setStyleSheet("background:%s;" % bg)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        cap = QLabel(caption_text)
        cap.setStyleSheet(
            "color:%s;font-weight:bold;font-size:13px;padding:11px 14px;font-family:'%s';"
            % (theme.TEXT_DARK, theme.FONT_FAMILY)
        )
        outer.addWidget(cap)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;background:%s;}" % bg)
        inner = QWidget()
        inner.setStyleSheet("background:%s;" % bg)
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 4, 0, 8)   # 좌우 0 → 선택 행이 끝→끝까지
        v.setSpacing(0)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        return page, v

    def _build_msg_page(self):
        page, v = self._list_scaffold("메시지", theme.LIST_BG)
        for ch in self.characters:
            v.addWidget(self._char_row(ch, ch["snippet"], self._msg_rows,
                                       snippet_store=self._msg_snippets, show_status=True))
        v.addStretch(1)
        return page

    def _build_friend_page(self):
        page, v = self._list_scaffold("학생 (%d)" % len(self.characters), theme.FRIEND_BG)
        for ch in self.characters:
            v.addWidget(self._char_row(ch, ch.get("intro") or "소개글 없음",
                                       self._friend_rows, show_status=True))
        v.addStretch(1)
        return page

    def _char_row(self, ch, secondary, rows_dict, snippet_store=None, show_status=False):
        row = _Row(ch["key"])
        row.setCursor(Qt.PointingHandCursor)
        row.clicked.connect(self._select)
        rows_dict[ch["key"]] = row

        h = QHBoxLayout(row)
        h.setContentsMargins(14, 9, 12, 9)
        h.setSpacing(10)
        av = QLabel()
        av.setFixedSize(42, 42)
        av.setStyleSheet("background:transparent;")
        av.setPixmap(make_circular_avatar(ch["profile_img"], 42, ch["name"]))

        if show_status:
            # [상태 점등] 아바타 위에 작은 원을 겹쳐서 지금 응답 가능/취침중/부재중을 표시.
            # 절대좌표(move)로 아바타 오른쪽 아래 모서리에 얹는 방식(오버레이 컨테이너).
            av_wrap = QWidget()
            av_wrap.setFixedSize(42, 42)
            av_wrap.setStyleSheet("background:transparent;")  # 원형 밖 모서리에 각진 배경 안 비치게
            av.setParent(av_wrap)
            av.move(0, 0)
            dot = QLabel(av_wrap)
            dot.setFixedSize(12, 12)
            dot.move(28, 28)
            dot.setStyleSheet(
                "background:%s;border-radius:6px;border:2px solid white;" % theme.STATUS_SLEEP
            )
            self._status_dots.setdefault(ch["key"], []).append(dot)

            if ch["key"] in self.birthday_keys:
                # [생일 배지] 상태점(오른쪽 아래)과 안 겹치게 왼쪽 위 모서리에 케이크 아이콘.
                # 하루 단위라 굳이 동적 갱신 안 하고, 창 만들 때 한 번만 표시.
                cake = QLabel("🎂", av_wrap)
                cake.setFixedSize(18, 18)
                cake.move(-3, -3)
                cake.setAlignment(Qt.AlignCenter)
                # 앱 전체 커스텀 폰트(GyeonggiTitle 등)엔 이모지 글리프가 없어서 깨져 보임.
                # 이 배지만 Windows 기본 컬러 이모지 폰트로 강제 지정해서 제대로 그려지게 함.
                cake.setFont(QFont("Segoe UI Emoji", 10))
                cake.setStyleSheet("background:transparent;")

            av_widget = av_wrap
        else:
            av_widget = av

        text_w = theme.LIST_W - 14 - 12 - 42 - 10 - 40   # 배지 자리(40) 확보
        tv = QVBoxLayout()
        tv.setSpacing(2)
        name = _ElideLabel(ch["name"], text_w, _font(13, bold=True), theme.TEXT_DARK)
        sub = _ElideLabel(secondary, text_w, _font(11), theme.TEXT_GRAY)
        if snippet_store is not None:
            snippet_store[ch["key"]] = sub
        tv.addWidget(name)
        tv.addWidget(sub)

        badge = QLabel()
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedHeight(20)
        badge.setMinimumWidth(20)
        badge.setStyleSheet(
            "background:%s;color:%s;border-radius:9px;padding:0 6px;"
            "font-size:11px;font-weight:bold;font-family:'%s';"
            % (theme.BADGE_RED, theme.BADGE_TEXT, theme.FONT_FAMILY)
        )
        self._badges.setdefault(ch["key"], []).append(badge)

        h.addWidget(av_widget)
        h.addLayout(tv, 1)
        h.addStretch(1)
        h.addWidget(badge, 0, Qt.AlignVCenter)
        self._style_row(rows_dict, ch["key"])
        self._update_badge(ch["key"])
        return row

    def _update_badge(self, key):
        count = self.unread.get(key, 0)
        text = "99+" if count > 99 else str(count)
        for b in self._badges.get(key, []):
            b.setText(text)
            b.setVisible(count > 0)

    def set_presence(self, key, status):
        """모든 탭(메시지/학생소개)의 아바타 상태 점등을 갱신.
        status: None(초록, 응답 가능) / 'sleep'(회색, 취침중) / 'busy'(빨강, 부재중).
        main.py 가 주기적으로 호출해서 최신 상태를 밀어넣는다."""
        self._presence[key] = status
        color = {
            None: theme.STATUS_AWAKE,
            "sleep": theme.STATUS_SLEEP,
            "busy": theme.STATUS_BUSY,
        }.get(status, theme.STATUS_SLEEP)
        for dot in self._status_dots.get(key, []):
            dot.setStyleSheet("background:%s;border-radius:6px;border:2px solid white;" % color)

    def _build_conversation_panel(self):
        panel = QFrame()
        panel.setStyleSheet("background:%s;" % theme.CHAT_BG)
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._scroll = _BounceScroll()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea{border:none;background:%s;}" % theme.CHAT_BG)
        container = QWidget()
        container.setStyleSheet("background:%s;" % theme.CHAT_BG)
        self._convo_layout = QVBoxLayout(container)
        self._convo_layout.setContentsMargins(20, 16, 20, 16)
        self._convo_layout.setSpacing(8)
        self._convo_layout.addStretch(1)
        self._scroll.setWidget(container)
        v.addWidget(self._scroll, 1)

        # 하단 입력창
        bar = QFrame()
        bar.setStyleSheet("background:#FFFFFF;border-top:1px solid #ECECEC;")
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(14, 10, 14, 12)
        hb.setSpacing(8)
        self._input = QLineEdit()
        self._input.setPlaceholderText("메시지를 입력하세요...")
        self._input.setStyleSheet(
            "QLineEdit{border:1px solid #DDE1E7;border-radius:18px;padding:9px 15px;"
            "font-size:14px;background:#F5F6F8;font-family:'%s';}" % theme.FONT_FAMILY
        )
        self._input.returnPressed.connect(self._send_my_message)
        self._input.textChanged.connect(self._on_input_text_changed)
        self._sendbtn = QPushButton("보내기")
        self._sendbtn.setCursor(Qt.PointingHandCursor)
        self._sendbtn.setStyleSheet(
            "QPushButton{background:%s;color:white;border:none;border-radius:18px;"
            "padding:9px 18px;font-size:13px;font-weight:bold;font-family:'%s';}"
            "QPushButton:hover{background:#3F79B4;}"
            "QPushButton:disabled{background:#B9C4D0;}" % (theme.SEND_BUBBLE, theme.FONT_FAMILY)
        )
        self._sendbtn.clicked.connect(self._send_my_message)
        hb.addWidget(self._input, 1)
        hb.addWidget(self._sendbtn)
        v.addWidget(bar)
        return panel

    def set_input_enabled(self, enabled):
        """답장 대기 중 입력 잠금(쿨다운)."""
        self._input.setEnabled(enabled)
        self._sendbtn.setEnabled(enabled)
        self._input.setPlaceholderText(
            "메시지를 입력하세요..." if enabled else "답장을 기다리는 중..."
        )

    # ───────────────────────── 동작 ─────────────────────────
    def _switch_mode(self, kind):
        self.mode = kind
        self.stack.setCurrentIndex(0 if kind == "message" else 1)
        for k, btn in self._rail_buttons.items():
            btn.set_selected(k == kind)

    def _select(self, key):
        self.selected_key = key
        self.unread[key] = 0          # 대화를 열어 봤으니 읽음 처리
        for k in self._friend_rows:
            self._style_row(self._friend_rows, k)
        for k in self._msg_rows:
            self._style_row(self._msg_rows, k)
        self.refresh()
        self.selection_changed.emit(key)

    def _style_row(self, rows, key):
        row = rows.get(key)
        if row is None:
            return
        if key == self.selected_key:
            # 라운드 없이 끝→끝 전체 강조
            row.setStyleSheet("_Row{background:%s;}" % theme.LIST_SELECTED)
        else:
            row.setStyleSheet("_Row{background:transparent;} _Row:hover{background:#EAEFF1;}")

    def _char_by_key(self, key):
        for c in self.characters:
            if c["key"] == key:
                return c
        return self.characters[0]

    def _send_my_message(self):
        text = self._input.text().strip()
        if not text or self.selected_key is None:
            return
        key = self.selected_key
        self.store.setdefault(key, []).append(("send", text, datetime.datetime.now().isoformat()))
        self._input.clear()
        self.refresh()
        self.message_sent.emit(key)     # main 이 받아서 Gemini 답장 요청

    def _on_input_text_changed(self, text):
        """입력창에 실제 텍스트 변경(자판 입력·삭제·붙여넣기 등)이 있을 때만 발생.
        커서 깜빡임( | )은 여기 안 걸림 — Qt가 포커스만 있으면 자동으로 그리는 애니메이션이라
        타이핑 여부와 무관하기 때문. textChanged 는 내용이 실제로 바뀔 때만 발생하는 진짜 신호."""
        if self.selected_key is not None:
            self.typing_changed.emit(self.selected_key)

    def refresh(self):
        while self._convo_layout.count():
            item = self._convo_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        convo = self.store.get(self.selected_key, [])
        char = self._char_by_key(self.selected_key)

        typing_here = (self._typing_key is not None and self._typing_key == self.selected_key)

        if not convo and not typing_here:
            empty = QLabel("아직 받은 메시지가 없어요.\n예정된 시간이 되면 도착합니다.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color:#AEB4BE;font-size:13px;")
            self._convo_layout.addWidget(empty)
        else:
            prev = None
            for i, entry in enumerate(convo):
                sender, text = entry[0], entry[1]
                ts = entry[2] if len(entry) > 2 else None
                new_group = (sender != prev)
                next_sender = convo[i + 1][0] if i + 1 < len(convo) else None
                is_last_in_group = (next_sender != sender)
                time_label = self._format_time(ts) if (is_last_in_group and ts) else None
                if sender == "send":
                    self._convo_layout.addWidget(self._send_bubble(text, time_label))
                else:
                    if new_group:
                        self._convo_layout.addWidget(self._name_label(char["name"]))
                    self._convo_layout.addWidget(
                        self._recv_bubble(text, char, show_avatar=new_group, time_label=time_label))
                prev = sender
            if typing_here:
                self._convo_layout.addWidget(self._typing_row(char))
        self._convo_layout.addStretch(1)

        for c in self.characters:
            msgs = self.store.get(c["key"], [])
            lbl = self._msg_snippets.get(c["key"])
            if lbl is not None and msgs:
                lbl.setText(msgs[-1][1])
            self._update_badge(c["key"])

        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        """대화 갱신 직후 항상 맨 아래로 스냅.
        - 진행 중인 휠 스크롤/바운스 애니메이션이 있으면 먼저 멈춘다(안 그러면 애니메이션이
          이후에도 값을 계속 밀어붙여서 setValue 가 무시된 것처럼 보임 = '스크롤이 안 따라감').
        - 위젯을 방금 새로 갈아끼운 직후라 레이아웃이 아직 다 안 잡혔을 수 있으므로,
          지금 한 번 + 다음 이벤트 루프 틱에 한 번 더(총 2번) 맨 아래로 맞춘다."""
        bar = self._scroll.verticalScrollBar()
        self._scroll._anim.stop()
        self._scroll._bounce_anim.stop()
        bar.setValue(bar.maximum())
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def _format_time(self, iso_str):
        """ISO 시각 문자열 → '오전/오후 H:MM' 표시용 텍스트. 실패하거나 옛 데이터(시각 없음)면 None."""
        if not iso_str:
            return None
        try:
            dt = datetime.datetime.fromisoformat(iso_str)
        except Exception:
            return None
        period = "오전" if dt.hour < 12 else "오후"
        h12 = dt.hour % 12
        if h12 == 0:
            h12 = 12
        return "%s %d:%02d" % (period, h12, dt.minute)

    def _name_label(self, name):
        lbl = QLabel(name)
        lbl.setStyleSheet(
            "color:%s;font-size:13px;margin-left:54px;margin-top:5px;font-family:'%s';"
            % (theme.NAME_GRAY, theme.FONT_FAMILY)
        )
        return lbl

    def set_typing(self, key):
        """학생 key 가 '입력 중'임을 표시 (보고 있는 학생일 때만 화면에 나타남)."""
        self._typing_key = key
        self.refresh()

    def clear_typing(self):
        self._typing_key = None
        self.refresh()

    def _typing_row(self, char):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        v.addWidget(self._name_label(char["name"]))
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        av = QLabel()
        av.setFixedSize(44, 44)
        av.setStyleSheet("background:transparent;")
        av.setPixmap(make_circular_avatar(char["profile_img"], 44, char["name"]))
        h.addWidget(av, 0, Qt.AlignTop)
        h.addWidget(_TypingDots())
        h.addStretch(1)
        v.addWidget(row)
        return box

    def _bubble_width(self, text):
        """한 줄에 다 들어가면 그 폭, 넘으면 최대폭(약 23자)에서 줄바꿈."""
        fm = QFontMetrics(_font(14))
        pad = 44                       # 좌우 패딩(30) + 넉넉한 여유
        maxw = 375                     # 약 23~24자에서 줄바꿈
        longest_line = max((fm.horizontalAdvance(seg) for seg in text.split("\n")), default=0)
        return int(min(longest_line + pad, maxw))

    def _recv_bubble(self, text, char, show_avatar, time_label=None):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        av = QLabel()
        av.setFixedSize(44, 44)
        av.setStyleSheet("background:transparent;")
        if show_avatar:
            av.setPixmap(make_circular_avatar(char["profile_img"], 44, char["name"]))
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setFixedWidth(self._bubble_width(text))
        bubble.setStyleSheet(
            "background:%s;color:%s;border-radius:16px;padding:11px 15px;"
            "font-size:14px;font-family:'%s';"
            % (theme.RECV_BUBBLE, theme.RECV_TEXT, theme.FONT_FAMILY)
        )
        h.addWidget(av, 0, Qt.AlignTop)
        h.addWidget(bubble)
        if time_label:
            t = QLabel(time_label)
            t.setStyleSheet(
                "color:%s;font-size:10px;font-family:'%s';background:transparent;"
                % (theme.NAME_GRAY, theme.FONT_FAMILY)
            )
            h.addWidget(t, 0, Qt.AlignBottom)
        h.addStretch(1)
        return row

    def _send_bubble(self, text, time_label=None):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setFixedWidth(self._bubble_width(text))
        bubble.setStyleSheet(
            "background:%s;color:%s;border-radius:16px;padding:11px 15px;"
            "font-size:14px;font-family:'%s';"
            % (theme.SEND_BUBBLE, theme.SEND_TEXT, theme.FONT_FAMILY)
        )
        h.addStretch(1)
        if time_label:
            t = QLabel(time_label)
            t.setStyleSheet(
                "color:%s;font-size:10px;font-family:'%s';background:transparent;"
                % (theme.NAME_GRAY, theme.FONT_FAMILY)
            )
            h.addWidget(t, 0, Qt.AlignBottom)
        h.addWidget(bubble)
        return row
