# -*- coding: utf-8 -*-
"""모모톡 테마(색상 / 크기 / 폰트) 상수 모음."""

# ────────────── 폰트 ──────────────
# 앱 시작 시 fonts.load_app_font() 가 실제 패밀리 이름으로 덮어씁니다.
FONT_FAMILY = "맑은 고딕"

# ────────────── 아이콘 색상 ──────────────
MOMO_PINK      = "#FFACC2"   # 포인트 컬러 (PNG 폴백)
HEART_WHITE    = "#FFFFFF"
BORDER_BLACK   = "#000000"
BORDER_WHITE   = "#FFFFFF"
BADGE_RED      = "#FF3B30"

# [상태 점등] 학생 목록(학생소개 탭)의 아바타에 겹쳐 그리는 상태 표시등 색상.
STATUS_AWAKE   = "#3DD16B"   # 초록: 지금 응답 가능(깨어있고 안 바쁨)
STATUS_SLEEP   = "#B0B4BA"   # 회색: 취침중
STATUS_BUSY    = "#FF3B30"   # 빨강: 부재중(일/알바 등으로 바쁨)
BADGE_TEXT     = "#FFFFFF"

# ────────────── 채팅창 색상 ──────────────
HEADER_PINK       = "#FFACC2"   # 포인트 컬러
HEADER_GRAD_TOP   = "#FF8FB1"   # 헤더 그라데이션 위(진함)
HEADER_GRAD_BOTTOM= "#FFB0C9"   # 헤더 그라데이션 아래(연함)
RAIL_BG           = "#4C5B6F"   # 좌측 레일 배경
RAIL_ACTIVE       = "#67788E"   # 좌측 레일 활성 버튼 배경
CHAT_BG           = "#FFFFFF"   # 대화 영역 배경
LIST_BG           = "#F3F7F8"   # 학생 목록 기본 배경
FRIEND_BG         = "#F3F7F8"   # 친구 목록 배경
LIST_SELECTED     = "#DAE5E9"   # 목록 선택된 행
RECV_BUBBLE       = "#4A5B6F"   # 상대 말풍선
RECV_TEXT         = "#FFFFFF"
SEND_BUBBLE       = "#4889C9"   # 선생님(나) 말풍선
SEND_TEXT         = "#FFFFFF"
NAME_GRAY         = "#8A94A6"
TEXT_DARK         = "#3A3A3A"
TEXT_GRAY         = "#9AA0A6"

# ────────────── 크기(px) ──────────────
ICON_SIZE        = 64
WINDOW_PADDING   = 14
BADGE_SIZE       = 24
SCREEN_MARGIN_X  = 30
SCREEN_MARGIN_Y  = 60
EDGE_SNAP_MARGIN = 18

FRIEND_W = 224   # (미사용) 친구 목록 너비
LIST_W   = 290   # 가운데 학생 목록 너비 (+약30%)
CHAT_W   = 1060  # 채팅창 전체 가로
CHAT_H   = 580   # 채팅창 전체 세로
