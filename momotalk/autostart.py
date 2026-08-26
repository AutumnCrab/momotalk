# -*- coding: utf-8 -*-
"""
윈도우 '시작프로그램' 폴더(shell:startup)에 배치(.bat) 파일을 놓는 방식의
자동 시작 등록/해제. 레지스트리 대신 폴더 방식을 쓰는 이유: 관리자 권한이
필요 없고, 파일 하나 지우면 바로 해제되어 사용자가 직접 확인/제거하기 쉽다.
"""
import os
import sys
import winreg

from momotalk.paths import get_base_dir

_STARTUP_DIR = os.path.join(
    os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
)
_BAT_PATH = os.path.join(_STARTUP_DIR, "MomoTalk.bat")
_BAT_NAME = "MomoTalk.bat"
_STARTUP_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"


def is_enabled():
    return os.path.exists(_BAT_PATH)


def _force_enable_in_task_manager():
    """윈도우가 새로 생긴 시작프로그램 항목을 '작업 관리자 → 시작 앱'에서 자체적으로
    사용 안 함 처리해버리는 경우가 있다(레지스트리 값 첫 바이트가 0x02). bat 파일은
    멀쩡히 있어도 이 값 때문에 로그온 시 실행이 안 되므로, 등록 직후 첫 바이트를
    0x06(사용함)으로 강제 교정한다."""
    try:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _STARTUP_APPROVED_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_READ
            )
        except OSError:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _STARTUP_APPROVED_KEY)
        try:
            try:
                existing, _ = winreg.QueryValueEx(key, _BAT_NAME)
                data = bytearray(existing)
            except FileNotFoundError:
                data = bytearray(12)
            if len(data) < 12:
                data.extend([0] * (12 - len(data)))
            data[0] = 0x06
            winreg.SetValueEx(key, _BAT_NAME, 0, winreg.REG_BINARY, bytes(data))
        finally:
            winreg.CloseKey(key)
    except OSError:
        pass  # 레지스트리 접근 실패해도 bat 파일 자체는 이미 등록됐으니 조용히 넘어간다.


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
    _force_enable_in_task_manager()


def disable():
    if os.path.exists(_BAT_PATH):
        os.remove(_BAT_PATH)
