# -*- coding: utf-8 -*-
"""
앱 전용 폰트(경기천년제목 Light) 로더.

assets/fonts/GyeonggiMillenniumTitle.ttf 를 불러와 Qt 에 등록하고,
실제 패밀리 이름을 theme.FONT_FAMILY 에 기록합니다.
파일이 없으면 기본 폰트를 그대로 씁니다.
"""

import os
from PyQt5.QtGui import QFontDatabase

from . import theme

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_PATH = os.path.join(BASE_DIR, "assets", "fonts", "GyeonggiMillenniumTitle.ttf")


def load_app_font():
    if os.path.exists(FONT_PATH):
        font_id = QFontDatabase.addApplicationFont(FONT_PATH)
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            theme.FONT_FAMILY = families[0]
            print("[모모톡] 폰트 적용:", theme.FONT_FAMILY)
        else:
            print("[모모톡] 폰트 파일은 있으나 등록 실패 — 기본 폰트 사용")
    else:
        print("[모모톡] 폰트 파일 없음 — 기본 폰트 사용:", FONT_PATH)
    return theme.FONT_FAMILY
