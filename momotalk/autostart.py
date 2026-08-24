# -*- coding: utf-8 -*-
"""
윈도우 '시작프로그램' 폴더(shell:startup)에 배치(.bat) 파일을 놓는 방식의
자동 시작 등록/해제. 레지스트리 대신 폴더 방식을 쓰는 이유: 관리자 권한이
필요 없고, 파일 하나 지우면 바로 해제되어 사용자가 직접 확인/제거하기 쉽다.
"""
import os
import sys

from momotalk.paths import get_base_dir

_STARTUP_DIR = os.path.join(
    os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
)
_BAT_PATH = os.path.join(_STARTUP_DIR, "MomoTalk.bat")


def is_enabled():
    return os.path.exists(_BAT_PATH)


def enable():
    if getattr(sys, "frozen", False):
        # exe 배포판: exe를 그대로 실행
        cmd = 'start "" "%s"' % sys.executable
    else:
        # 개발 환경: pythonw로 실행해 콘솔 창이 뜨지 않게 함
        py_dir = os.path.dirname(sys.executable)
        pythonw = os.path.join(py_dir, "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable  # pythonw가 없으면 그냥 python으로
        main_py = os.path.join(get_base_dir(), "main.py")
        cmd = 'start "" "%s" "%s"' % (pythonw, main_py)

    os.makedirs(_STARTUP_DIR, exist_ok=True)
    with open(_BAT_PATH, "w", encoding="utf-8") as f:
        f.write("@echo off\r\n")
        f.write('cd /d "%s"\r\n' % get_base_dir())
        f.write(cmd + "\r\n")


def disable():
    if os.path.exists(_BAT_PATH):
        os.remove(_BAT_PATH)
