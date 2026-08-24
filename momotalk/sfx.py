# -*- coding: utf-8 -*-
"""UI 효과음 재생. assets/sfx/<name>.mp3 를 재생한다.

on      - 플로팅 아이콘이 화면에 나타날 때(시작 시/트레이에서 다시 보이기)
off     - 대화창 닫을 때 / 아이콘 트레이로 숨길 때
touch   - 대화창 좌측 목록/탭에서 학생·세션 전환할 때
momotalk - 대화창이 열릴 때

QMediaPlayer 는 setMedia() 직후 바로 play() 하면 파일을 새로 로드하느라 매번 살짝 밀린다.
그래서 플레이어를 이름별로 한 번만 만들어 미리 로드해두고 재사용한다.
재생마다 stop() 후 setPosition(0) 을 부르고 play() 한다 — 이미 재생 중일 때 play() 만
다시 부르면(이미 PlayingState라) 아무 효과가 없어서, 아주 빠르게 연달아 트리거될 때
소리가 씹히는 문제가 있었다. stop() 으로 강제로 끊고 처음부터 다시 재생해서 매번 확실히
소리가 나게 한다.
"""
import os

from PyQt5.QtCore import QUrl
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer

from momotalk.paths import get_base_dir

SFX_DIR = os.path.join(get_base_dir(), "assets", "sfx")
_EXTS = (".mp3", ".wav", ".m4a", ".ogg")
NAMES = ("on", "off", "touch", "momotalk")

_players = {}   # name -> QMediaPlayer(로드 완료된 채로 재사용)


def _find(name):
    for ext in _EXTS:
        path = os.path.join(SFX_DIR, name + ext)
        if os.path.exists(path):
            return path
    return None


def _get_player(name):
    player = _players.get(name)
    if player is not None:
        return player
    path = _find(name)
    if path is None:
        return None
    try:
        player = QMediaPlayer()
        player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        player.setVolume(70)
    except Exception as e:
        print("[모모톡] 효과음 준비 실패:", name, repr(e))
        return None
    _players[name] = player
    return player


def preload():
    """앱 시작 시 한 번 불러서 첫 재생부터 지연 없게 한다."""
    for name in NAMES:
        _get_player(name)


def play(name):
    """name: 'on'/'off'/'touch'/'momotalk'. 파일이 없으면 조용히 무시."""
    player = _get_player(name)
    if player is None:
        return
    player.stop()
    player.setPosition(0)
    player.play()
