# -*- coding: utf-8 -*-
"""
프로필 이미지를 동그랗게 잘라 QPixmap으로 돌려주는 헬퍼.

- 이미지가 있으면: 정사각형 중앙 기준으로 원형으로 잘라 반환.
- 이미지가 없으면: 연한 색 원 + 이름 첫 글자 대체 아바타.
- High-DPI 화면에서도 가장자리가 또렷하도록 화면 배율(devicePixelRatio)만큼
  더 크게 렌더한 뒤 배율을 설정한다 → 선택 시 모서리가 번져 보이는 문제 해결.
"""

import os
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont
from PyQt5.QtWidgets import QApplication


def _dpr():
    app = QApplication.instance()
    if app is not None:
        scr = app.primaryScreen()
        if scr is not None:
            return max(1.0, float(scr.devicePixelRatio()))
    return 1.0


def make_circular_avatar(image_path, size, name="", bg="#D2E3FC"):
    dpr = _dpr()
    px = max(1, int(round(size * dpr)))   # 실제 렌더 픽셀(고해상도)

    canvas = QPixmap(px, px)
    canvas.fill(Qt.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    clip = QPainterPath()
    clip.addEllipse(0.0, 0.0, float(px), float(px))
    painter.setClipPath(clip)

    pix = None
    if image_path and os.path.exists(image_path):
        loaded = QPixmap(image_path)
        if not loaded.isNull():
            pix = loaded

    if pix is not None:
        scaled = pix.scaled(
            px, px,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        ox = (scaled.width() - px) // 2
        oy = (scaled.height() - px) // 2
        painter.drawPixmap(-ox, -oy, scaled)
    else:
        painter.fillRect(0, 0, px, px, QColor(bg))
        painter.setPen(QColor("#5A6B8C"))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(px * 0.45))
        painter.setFont(font)
        initial = name[:1] if name else "?"
        painter.drawText(QRectF(0, 0, px, px), Qt.AlignCenter, initial)

    painter.end()
    canvas.setDevicePixelRatio(dpr)   # 라벨에선 논리 크기(size)로 또렷하게 표시
    return canvas
