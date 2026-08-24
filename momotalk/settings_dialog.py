# -*- coding: utf-8 -*-
"""
초기 설정 화면 — 유저 생일 + API 키 2개(Gemini/날씨) 입력.
아이콘 우클릭 메뉴 '초기 설정'에서 언제든 다시 열어 값을 확인/수정할 수 있다.
모모톡 채팅창과 같은 헤더 그라데이션/폰트를 써서 룩을 맞췄다.
"""

import calendar
import json
import os

from PyQt5.QtWidgets import (
    QDialog, QWidget, QFrame, QLabel, QLineEdit, QComboBox, QPushButton,
    QVBoxLayout, QHBoxLayout, QMessageBox, QApplication
)
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPainter, QPainterPath, QColor, QPen, QPixmap, QRegion, QIcon

from momotalk.paths import get_base_dir
from momotalk import theme

BASE_DIR = get_base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ANNIV_PATH = os.path.join(BASE_DIR, "anniversaries.json")

DEFAULT_WORLD_HOLIDAYS = {
    "01-01": "새해", "02-14": "발렌타인데이", "03-14": "화이트데이",
    "10-31": "할로윈", "12-25": "크리스마스",
}


def _detect_provider(key):
    """키 형식으로 provider 를 알아낸다. Gemini(AI Studio) 키는 'AIza'로, OpenAI 키는
    'sk-'로 시작하는 게 고정 포맷이라 이것만으로 충분히 구분됨. 못 알아보면 None."""
    k = key.strip()
    if k.startswith("sk-"):
        return "openai"
    if k.startswith("AIza"):
        return "gemini"
    return None


_PROVIDER_LABEL = {"gemini": "Gemini", "openai": "OpenAI(GPT)"}

_INPUT_STYLE = (
    "border:1px solid #DDE1E7;border-radius:14px;padding:9px 13px;"
    "font-size:13px;background:#F5F6F8;font-family:'%s';" % theme.FONT_FAMILY
)

# 콤보박스: OS 기본 화살표는 QSS 로 지우고, _ChevronCombo 가 라운드 캡 셰브론을 직접 그린다.
_COMBO_STYLE = (
    "QComboBox{border:1px solid #DDE1E7;border-radius:14px;padding:9px 13px;"
    "font-size:13px;background:#F5F6F8;font-family:'%s';}"
    "QComboBox::drop-down{border:none;background:transparent;width:26px;}"
    "QComboBox::down-arrow{image:none;width:0;height:0;}"
    "QComboBox QAbstractItemView{border:1px solid #DDE1E7;border-radius:10px;"
    "background:#FFFFFF;selection-background-color:%s;selection-color:%s;"
    "outline:none;padding:4px;font-family:'%s';font-size:13px;}"
    "QComboBox QAbstractItemView::item{padding:12px 10px;border-radius:8px;min-height:22px;margin:2px 0;}"
    "QComboBox QAbstractItemView::item:hover{background:#F0F1F3;}"
    "QComboBox QAbstractItemView QScrollBar:vertical{width:8px;background:transparent;"
    "margin:4px 2px;}"
    "QComboBox QAbstractItemView QScrollBar::handle:vertical{background:#DADFE6;"
    "border-radius:4px;min-height:20px;}"
    "QComboBox QAbstractItemView QScrollBar::add-line:vertical,"
    "QComboBox QAbstractItemView QScrollBar::sub-line:vertical{height:0;}"
    "QComboBox QAbstractItemView QScrollBar::add-page:vertical,"
    "QComboBox QAbstractItemView QScrollBar::sub-page:vertical{background:transparent;}"
    % (theme.FONT_FAMILY, theme.LIST_SELECTED, theme.TEXT_DARK, theme.FONT_FAMILY)
)


class _ChevronCombo(QComboBox):
    """OS 기본/테두리-트릭 화살표 대신, 끝이 둥근(RoundCap/RoundJoin) 셰브론을 직접 그린다."""
    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = 8, 5
        cx = self.width() - 19
        cy = self.height() / 2.0
        pen = QPen(QColor(theme.NAME_GRAY), 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(cx - w / 2.0, cy - h / 2.0)
        path.lineTo(cx, cy + h / 2.0)
        path.lineTo(cx + w / 2.0, cy - h / 2.0)
        p.drawPath(path)


def _asset(name):
    return os.path.join(BASE_DIR, "assets", name)


class _DragHeader(QFrame):
    """헤더 드래그로 창 이동 — 프레임리스 창엔 OS 타이틀바가 없어서 직접 구현."""
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


def _section_label(text):
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color:%s;font-weight:bold;font-size:12px;font-family:'%s';"
        % (theme.TEXT_DARK, theme.FONT_FAMILY)
    )
    return lbl


class SettingsDialog(QDialog):
    """config 는 MainApp.config (dict) — 저장 성공 시 그 자리에서 바로 갱신해
    호출부가 재시작 없이 바로 새 키를 쓰게 한다."""

    def __init__(self, config, birthday, parent=None, is_first_run=False):
        super().__init__(parent)
        self.config = config
        self._initial_birthday = birthday or ""
        self._is_first_run = is_first_run
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedWidth(380)
        icon_path = _asset("momotalk.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self._build_ui()
        self._load_existing()
        self.adjustSize()
        self._update_mask()
        self._center_on_screen()

    # ───────────────────── 둥근 모서리(채팅창과 동일 방식) ─────────────────────
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

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(e)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2,
                  screen.center().y() - self.height() // 2)

    # ───────────────────── UI ─────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        outer.addWidget(self._build_body())

    def _build_header(self):
        header = _DragHeader(self)
        header.setFixedHeight(50)
        header.setStyleSheet(
            "QFrame{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 %s, stop:1 %s);"
            "border-top-left-radius:16px;border-top-right-radius:16px;}"
            % (theme.HEADER_GRAD_TOP, theme.HEADER_GRAD_BOTTOM)
        )
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 0, 12, 0)
        h.setSpacing(8)

        logo = QLabel()
        pm = QPixmap(_asset("logo.png"))
        if not pm.isNull():
            logo.setPixmap(pm.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            logo.setText("⚙")
            logo.setStyleSheet("color:white;font-size:16px;")

        title = QLabel("선생님, 환영합니다!" if self._is_first_run else "초기 설정")
        title.setStyleSheet(
            "color:white;font-weight:bold;font-size:16px;font-family:'%s';" % theme.FONT_FAMILY
        )

        close = QPushButton("✕")
        close.setFixedSize(28, 28)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(
            "QPushButton{color:white;border:none;font-size:14px;background:transparent;}"
            "QPushButton:hover{background:rgba(255,255,255,0.25);border-radius:14px;}"
        )
        close.clicked.connect(self.reject)

        h.addWidget(logo)
        h.addWidget(title)
        h.addStretch(1)
        h.addWidget(close)
        return header

    def _build_body(self):
        body = QFrame()
        body.setStyleSheet("background:#FFFFFF;border-bottom-left-radius:16px;border-bottom-right-radius:16px;")
        v = QVBoxLayout(body)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(16)

        if self._is_first_run:
            welcome = QLabel("모모톡 접속을 환영합니다! 원활한 실행을 위해 정보를 입력해주세요!")
            welcome.setWordWrap(True)
            welcome.setAlignment(Qt.AlignCenter)
            welcome.setStyleSheet(
                "color:%s;font-size:12px;font-family:'%s';" % (theme.TEXT_DARK, theme.FONT_FAMILY)
            )
            v.addWidget(welcome)

        v.addWidget(self._birthday_group())
        v.addWidget(self._llm_key_group())
        v.addWidget(self._field_group("날씨 API 키 (선택)", self._make_weather_input()))
        v.addLayout(self._button_row())
        return body

    def _llm_key_group(self):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addWidget(_section_label("대화 API 키"))
        v.addWidget(self._make_llm_key_input())
        self._provider_hint = QLabel("")
        self._provider_hint.setStyleSheet(
            "color:%s;font-size:11px;font-family:'%s';" % (theme.TEXT_GRAY, theme.FONT_FAMILY)
        )
        v.addWidget(self._provider_hint)
        self._llm_key.textChanged.connect(self._update_provider_hint)
        return box

    def _birthday_group(self):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addWidget(_section_label("생일"))

        self._month = _ChevronCombo()
        self._month.addItems(["%d월" % m for m in range(1, 13)])
        self._day = _ChevronCombo()
        self._month.setStyleSheet(_COMBO_STYLE)
        self._day.setStyleSheet(_COMBO_STYLE)
        self._refill_days()   # 월을 아직 안 건드려도(기본 1월) 일 목록이 처음부터 채워져 있게
        self._month.currentIndexChanged.connect(self._refill_days)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._month, 1)
        row.addWidget(self._day, 1)
        v.addLayout(row)
        return box

    def _make_llm_key_input(self):
        self._llm_key = QLineEdit()
        self._llm_key.setEchoMode(QLineEdit.Password)
        self._llm_key.setPlaceholderText("Gemini(AIza...) 또는 OpenAI(sk-...) 키")
        self._llm_key.setStyleSheet(_INPUT_STYLE)
        return self._llm_key

    def _make_weather_input(self):
        self._weather = QLineEdit()
        self._weather.setEchoMode(QLineEdit.Password)
        self._weather.setPlaceholderText("OpenWeatherMap API 키")
        self._weather.setStyleSheet(_INPUT_STYLE)
        return self._weather

    def _field_group(self, label_text, field_widget):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addWidget(_section_label(label_text))
        v.addWidget(field_widget)
        return box

    def _button_row(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)

        cancel = QPushButton("취소")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            "QPushButton{color:%s;border:none;background:transparent;"
            "padding:9px 16px;font-size:13px;font-family:'%s';}"
            "QPushButton:hover{background:#F0F1F3;border-radius:14px;}"
            % (theme.TEXT_GRAY, theme.FONT_FAMILY)
        )
        cancel.clicked.connect(self.reject)

        save = QPushButton("저장")
        save.setCursor(Qt.PointingHandCursor)
        save.setDefault(True)
        save.setStyleSheet(
            "QPushButton{background:%s;color:white;border:none;border-radius:14px;"
            "padding:9px 22px;font-size:13px;font-weight:bold;font-family:'%s';}"
            "QPushButton:hover{background:#3F79B4;}"
            % (theme.SEND_BUBBLE, theme.FONT_FAMILY)
        )
        save.clicked.connect(self._save)

        row.addWidget(cancel)
        row.addWidget(save)
        return row

    # ───────────────────── 동작 ─────────────────────
    def _refill_days(self):
        month = self._month.currentIndex() + 1
        days_in_month = calendar.monthrange(2000, month)[1]  # 2000년은 윤년 → 2월도 29일까지 허용
        cur = self._day.currentIndex()
        self._day.blockSignals(True)
        self._day.clear()
        self._day.addItems(["%d일" % d for d in range(1, days_in_month + 1)])
        self._day.setCurrentIndex(min(cur, days_in_month - 1) if cur >= 0 else 0)
        self._day.blockSignals(False)

    def _update_provider_hint(self, text):
        provider = _detect_provider(text)
        if not text.strip():
            self._provider_hint.setText("")
        elif provider is not None:
            self._provider_hint.setText("→ %s 키로 인식됨" % _PROVIDER_LABEL[provider])
        else:
            self._provider_hint.setText("→ 알아보지 못한 형식이에요")

    def _load_existing(self):
        b = self._initial_birthday.strip()
        if len(b) == 5 and b[2] == "-":
            try:
                m, d = int(b[:2]), int(b[3:])
                self._month.setCurrentIndex(m - 1)
                self._refill_days()
                self._day.setCurrentIndex(d - 1)
            except Exception:
                pass

        provider = self.config.get("provider", "gemini")
        key = self.config.get("openai_api_key" if provider == "openai" else "gemini_api_key", "")
        self._llm_key.setText(key)
        self._weather.setText(self.config.get("weather_api_key", ""))

    def _save(self):
        key = self._llm_key.text().strip()
        if not key:
            QMessageBox.warning(self, "확인", "대화 API 키는 비워둘 수 없어요.")
            return
        provider = _detect_provider(key)
        if provider is None:
            QMessageBox.warning(
                self, "확인",
                "API 키 형식을 알아보지 못했어요.\nGemini 키는 'AIza...', OpenAI 키는 'sk-...'로 시작해요."
            )
            return
        # 안 쓰는 쪽 provider의 기존 키는 지우지 않고 그대로 둔다 — 나중에 그 키로
        # 다시 바꿔 넣으면 재입력 없이 바로 인식되도록.
        other_provider = "openai" if provider == "gemini" else "gemini"
        other_key = self.config.get("%s_api_key" % other_provider, "")
        weather = self._weather.text().strip()
        month = self._month.currentIndex() + 1
        day = self._day.currentIndex() + 1
        birthday = "%02d-%02d" % (month, day)

        cfg = {
            "gemini_api_key": key if provider == "gemini" else other_key,
            "model": self.config.get("model", "gemini-3.1-flash-lite"),
            "weather_api_key": weather,
            "provider": provider,
            "openai_api_key": key if provider == "openai" else other_key,
            "openai_model": self.config.get("openai_model", "gpt-4o-mini"),
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "저장 실패", "config.json 저장 실패: %s" % e)
            return

        anniv = {}
        if os.path.exists(ANNIV_PATH):
            try:
                with open(ANNIV_PATH, encoding="utf-8") as f:
                    anniv = json.load(f)
            except Exception:
                anniv = {}
        anniv["user_birthday"] = birthday
        anniv.setdefault("world_holidays", dict(DEFAULT_WORLD_HOLIDAYS))
        try:
            with open(ANNIV_PATH, "w", encoding="utf-8") as f:
                json.dump(anniv, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "저장 실패", "anniversaries.json 저장 실패: %s" % e)
            return

        self.config["gemini_api_key"] = cfg["gemini_api_key"]
        self.config["openai_api_key"] = cfg["openai_api_key"]
        self.config["provider"] = provider
        self.config["weather_api_key"] = weather
        self.accept()
