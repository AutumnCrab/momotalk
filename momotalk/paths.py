# -*- coding: utf-8 -*-
"""
프로젝트 루트(BASE_DIR)를 개발 환경(python main.py)과 exe(PyInstaller 빌드) 양쪽에서
동일하게 올바른 곳으로 계산해주는 공용 헬퍼.

- 개발 환경: 이 파일 기준 두 단계 위(momotalk/paths.py -> momotalk/ -> 프로젝트 루트)
- exe(frozen) 환경: PyInstaller가 sys.frozen=True를 심어준다. 이때는 exe 파일이 있는
  폴더를 루트로 써야, config.json/prompts/*.json/chat_history.json 을 exe 옆에서
  그대로 읽고 쓸 수 있다(exe 내부 임시 압축 해제 폴더를 보면 안 됨 — 편집이 반영 안 됨).
"""
import os
import sys


def get_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
