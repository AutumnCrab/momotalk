# -*- coding: utf-8 -*-
"""
우측 하단에 떠 있는 '모모톡 로고' 아이콘 위젯.

- 원 + 꼬리를 처음부터 '하나의 연속 외곽선'으로 그려, 테두리가 끊김 없이 이어집니다.
  (path.united() 같은 불리언 연산을 쓰지 않아 환경 영향이 없습니다.)
- 그 외곽선을 큰→작은 순으로 3번 채워 [검정→흰색] 2단 테두리 + 핑크 본체.
- 안 읽은 메시지가 있으면 우측 상단 빨간 배지(숫자).
- 드래그 이동 / 손 떼면 좌·우 가장자리 스냅 / 더블클릭 시 채팅창 열기.
"""

import math
import os

from PyQt5.QtWidgets import QWidget, QApplication, QMenu
from PyQt5.QtCore import (
    Qt, QRectF, QPointF, QPoint, QTimer,
    QPropertyAnimation, QEasingCurve, pyqtSignal
)
from PyQt5.QtGui import QPainter, QColor, QPainterPath, QFont, QPen, QPixmap

from . import theme

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGO_PNG = os.path.join(BASE_DIR, "assets", "momotalk.png")


class MomoTalkIcon(QWidget):
    open_requested = pyqtSignal(QPoint)     # 더블클릭한 전역 좌표를 함께 전달 (8번)
    hide_requested = pyqtSignal()           # 우클릭 '아이콘 숨김' → 트레이로

    # 드래그 따라오는 정도 (0에 가까울수록 잔상↑/느림, 1에 가까울수록 즉각적)
    DRAG_FOLLOW = 0.4

    def __init__(self):
        super().__init__()
        self.unread_count = 0
        self._press_global = None
        self._press_winpos = None
        self._moved = False
        self._snap_anim = None
        self._logo = self._load_logo()

        # 부드러운 드래그(보간 따라오기)용
        self._target_pos = None
        self._dragging = False
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(16)          # ~60fps
        self._follow_timer.timeout.connect(self._follow_step)

        self._init_window()

    def _load_logo(self):
        if os.path.exists(LOGO_PNG):
            pm = QPixmap(LOGO_PNG)
            if not pm.isNull():
                return pm
        return None

    # ───────────────────────── 창 설정 ─────────────────────────
    def _init_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        size = theme.ICON_SIZE + theme.WINDOW_PADDING * 2
        self.setFixedSize(size, size)
        self.setToolTip("모모톡 · 더블클릭: 열기 / 클릭: 읽음 / 드래그: 이동")
        self._move_to_corner()

    def _move_to_corner(self):
        geo = QApplication.primaryScreen().availableGeometry()
        x = geo.right() - self.width() - theme.SCREEN_MARGIN_X
        y = geo.bottom() - self.height() - theme.SCREEN_MARGIN_Y
        self.move(x, y)

    # ───────────────────────── 그리기 ─────────────────────────
    def _bubble_path(self, body):
        """원 + 왼쪽 아래 꼬리를 '하나의 연속 외곽선'으로 만든 path."""
        R = body.width() / 2.0
        cx, cy = body.center().x(), body.center().y()

        a_start = 238.0   # 꼬리가 원에 붙는 각도(시작)
        a_end = 198.0     # 꼬리가 원에 붙는 각도(끝)
        tip_ang = 216.0   # 꼬리 끝 방향(두 각도 사이)
        tip_r = R * 1.55  # 꼬리 끝 길이

        path = QPainterPath()
        path.arcMoveTo(body, a_start)                 # 시작점 = 원의 a_start
        path.arcTo(body, a_start, -(360 - (a_start - a_end)))  # 긴 쪽으로 한 바퀴 → a_end
        # 현재점(원의 a_end) → 꼬리 끝
        tx = cx + tip_r * math.cos(math.radians(tip_ang))
        ty = cy - tip_r * math.sin(math.radians(tip_ang))
        path.lineTo(tx, ty)
        path.closeSubpath()                            # 꼬리 끝 → 시작점(원의 a_start)
        return path

    def _fill_scaled(self, painter, path, color, scale, center):
        painter.save()
        painter.translate(center)
        painter.scale(scale, scale)
        painter.translate(-center)
        painter.fillPath(path, QColor(color))
        painter.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        pad = theme.WINDOW_PADDING
        icon = theme.ICON_SIZE
        body = QRectF(pad, pad, icon, icon)
        R = icon / 2.0
        center = body.center()

        if self._logo is not None:
            # PNG 로고: 배지 자리 남기고 창을 거의 채워서 그림
            target = QRectF(3, 3, self.width() - 6, self.height() - 6)
            p.drawPixmap(target, self._logo, QRectF(self._logo.rect()))
        else:
            path = self._bubble_path(body)
            self._fill_scaled(p, path, theme.BORDER_BLACK, 1.0, center)
            self._fill_scaled(p, path, theme.BORDER_WHITE, (R - 2) / R, center)
            self._fill_scaled(p, path, theme.MOMO_PINK,   (R - 4) / R, center)
            self._draw_heart(p, body)

        if self.unread_count > 0:
            self._draw_badge(p)

    def _draw_heart(self, painter, rect):
        heart = QPainterPath()
        heart.moveTo(50, 30)
        heart.cubicTo(50, 27, 46, 16, 32, 16)
        heart.cubicTo(10, 16, 10, 44, 10, 44)
        heart.cubicTo(10, 60, 30, 74, 50, 86)
        heart.cubicTo(70, 74, 90, 60, 90, 44)
        heart.cubicTo(90, 16, 68, 16, 68, 16)
        heart.cubicTo(54, 16, 50, 27, 50, 30)

        br = heart.boundingRect()
        target = rect.width() * 0.50
        scale = target / max(br.width(), br.height())
        painter.save()
        painter.translate(rect.center())
        painter.scale(scale, scale)
        painter.translate(-br.center())
        painter.fillPath(heart, QColor(theme.HEART_WHITE))
        painter.restore()

    def _draw_badge(self, painter):
        bsize = theme.BADGE_SIZE
        pad = theme.WINDOW_PADDING
        icon = theme.ICON_SIZE
        bx = pad + icon - bsize * 0.55
        by = pad - bsize * 0.40
        rect = QRectF(bx, by, bsize, bsize)

        painter.setPen(QPen(QColor("white"), 2))
        painter.setBrush(QColor(theme.BADGE_RED))
        painter.drawEllipse(rect)

        text = "9+" if self.unread_count > 9 else str(self.unread_count)
        painter.setPen(QColor(theme.BADGE_TEXT))
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, text)

    # ──────────────────── 메시지 개수 제어 ────────────────────
    def receive_message(self, n=1):
        self.unread_count += n
        self.update()

    def mark_as_read(self):
        self.unread_count = 0
        self.update()

    # ───────────────────── 마우스 동작 ─────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_global = e.globalPos()
            self._press_winpos = self.pos()
            self._target_pos = self.pos()
            self._moved = False
            self._dragging = False
            e.accept()
        elif e.button() == Qt.RightButton:
            self._show_menu(e.globalPos())

    def mouseMoveEvent(self, e):
        if self._press_global is not None and (e.buttons() & Qt.LeftButton):
            delta = e.globalPos() - self._press_global
            if delta.manhattanLength() > 3:
                self._moved = True
                self._dragging = True
            # 곧장 move() 하지 않고 목표만 갱신 → 타이머가 부드럽게 따라감
            self._target_pos = self._press_winpos + delta
            if self._dragging and not self._follow_timer.isActive():
                self._follow_timer.start()
            e.accept()

    def _follow_step(self):
        """목표 위치로 일정 비율씩 다가가 부드러운 이동 + 약한 잔상감을 만든다."""
        if self._target_pos is None:
            return
        cur = self.pos()
        nx = cur.x() + (self._target_pos.x() - cur.x()) * self.DRAG_FOLLOW
        ny = cur.y() + (self._target_pos.y() - cur.y()) * self.DRAG_FOLLOW
        self.move(int(round(nx)), int(round(ny)))
        # 드래그가 끝났고 목표에 충분히 도달했으면 정지
        if not self._dragging:
            if abs(self._target_pos.x() - self.x()) <= 1 and abs(self._target_pos.y() - self.y()) <= 1:
                self.move(self._target_pos)
                self._follow_timer.stop()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._press_global is not None:
            self._dragging = False
            if self._moved:
                self._follow_timer.stop()
                self._snap_to_edge()
            else:
                self.mark_as_read()
            self._press_global = None
            e.accept()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._follow_timer.stop()
            self.open_requested.emit(e.globalPos())   # 클릭한 좌표 전달 (8번)
            e.accept()

    def _show_menu(self, global_pos):
        menu = QMenu(self)
        act_open = menu.addAction("채팅창 열기")
        act_read = menu.addAction("모두 읽음")
        act_hide = menu.addAction("아이콘 숨김 (트레이로)")
        menu.addSeparator()
        act_quit = menu.addAction("종료")
        chosen = menu.exec_(global_pos)
        if chosen == act_open:
            self.open_requested.emit(self.frameGeometry().center())
        elif chosen == act_read:
            self.mark_as_read()
        elif chosen == act_hide:
            self.hide_requested.emit()
        elif chosen == act_quit:
            QApplication.quit()

    # ───────────────────── 가장자리 스냅 ─────────────────────
    def _snap_to_edge(self):
        geo = QApplication.primaryScreen().availableGeometry()
        center_x = self.x() + self.width() / 2.0
        if center_x < geo.center().x():
            target_x = geo.left() + theme.EDGE_SNAP_MARGIN
        else:
            target_x = geo.right() - self.width() - theme.EDGE_SNAP_MARGIN
        target_y = max(
            geo.top() + theme.EDGE_SNAP_MARGIN,
            min(self.y(), geo.bottom() - self.height() - theme.EDGE_SNAP_MARGIN),
        )
        self._animate_to(QPoint(int(target_x), int(target_y)))

    def _animate_to(self, point):
        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(220)
        anim.setStartValue(self.pos())
        anim.setEndValue(point)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._snap_anim = anim
