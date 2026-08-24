# -*- coding: utf-8 -*-
"""
프로필 이미지를 동그랗게 잘라 QPixmap으로 돌려주는 헬퍼.

- 이미지가 있으면: 정사각형 중앙 기준으로 원형으로 잘라 반환.
- 이미지가 없으면: 연한 색 원 + 이름 첫 글자 대체 아바타.
- High-DPI 화면에서도 가장자리가 또렷하도록 화면 배율(devicePixelRatio)만큼
  더 크게 렌더한 뒤 배율을 설정한다 → 선택 시 모서리가 번져 보이는 문제 해결.
"""

import os
import zlib
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


# 프로필 사진 없는 캐릭터가 전부 똑같은 파란 원+글자로 보이던 문제 수정.
# 이름을 해시해 팔레트에서 고르니, 같은 캐릭터는 항상 같은 색이면서 서로는 구분됨.
_AVATAR_PALETTE = [
    "#FFD3DC", "#D3E4FF", "#D3F3E0", "#FFEBB0", "#E4D6FF",
    "#FFDCC0", "#C7EFF5", "#F6D3EE", "#DDE8B8", "#C9DCEB",
]


def _palette_color(seed):
    if not seed:
        return _AVATAR_PALETTE[0]
    return _AVATAR_PALETTE[zlib.crc32(seed.encode("utf-8")) % len(_AVATAR_PALETTE)]


def make_circular_avatar(image_path, size, name="", bg=None):
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
        painter.fillRect(0, 0, px, px, QColor(bg or _palette_color(name)))
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
