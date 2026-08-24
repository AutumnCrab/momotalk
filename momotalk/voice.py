# -*- coding: utf-8 -*-
"""
캐릭터별 '선생님' 알림 보이스 재생.

우측 하단 토스트 알림이 뜰 때(그 학생의 '첫 안읽음' 메시지일 때만) 짧게 재생한다.
채팅창을 직접 보고 있을 때나, 이미 안읽음이 쌓여있는 상태에서 추가로 오는 메시지에는 울리지 않는다.

보이스 파일은 assets/voices/<char_key>_sensei.<확장자> — 파일이 없으면(캐릭터 녹음이 아직
없으면) 조용히 무시한다.

플레이어를 캐릭터별로 한 번만 만들어 미리 로드해두고 재사용한다(sfx.py 와 같은 이유 —
매번 새로 로드하면 재생이 계속 살짝 밀린다).
"""
import os

from PyQt5.QtCore import QUrl
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer

from momotalk.paths import get_base_dir

VOICES_DIR = os.path.join(get_base_dir(), "assets", "voices")
_EXTS = (".mp3", ".wav", ".m4a", ".ogg")

_players = {}   # char_key -> QMediaPlayer(로드 완료된 채로 재사용)


def _find_voice_file(char_key):
    for ext in _EXTS:
        path = os.path.join(VOICES_DIR, "%s_sensei%s" % (char_key, ext))
        if os.path.exists(path):
            return path
    return None


def _get_player(char_key):
    player = _players.get(char_key)
    if player is not None:
        return player
    path = _find_voice_file(char_key)
    if path is None:
        return None
    try:
        player = QMediaPlayer()
        player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        player.setVolume(80)
    except Exception as e:
        print("[모모톡] 보이스 준비 실패:", char_key, repr(e))
        return None
    _players[char_key] = player
    return player


def preload(char_keys):
    """앱 시작 시 한 번 불러서 첫 재생부터 지연 없게 한다."""
    for key in char_keys:
        _get_player(key)


def play_sensei_voice(char_key):
    """char_key의 '선생님' 보이스를 한 번 재생한다. 파일이 없으면(=아직 더미) 조용히 무시."""
    player = _get_player(char_key)
    if player is None:
        return
    player.stop()
    player.setPosition(0)
    player.play()
