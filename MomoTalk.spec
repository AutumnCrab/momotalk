# -*- mode: python ; coding: utf-8 -*-
# MomoTalk PyInstaller 빌드 스펙.
#
# onedir(폴더) 모드로 빌드합니다. onefile(exe 하나) 모드는 매 실행마다 임시 폴더에
# 압축을 풀기 때문에, prompts/*.json 을 메모장으로 고쳐도 다음 실행에 반영이 안 됩니다.
# onedir 모드는 dist/MomoTalk/ 폴더 안에 실행파일 + 라이브러리가 나오고,
# 그 옆에 prompts/, data/, assets/, config.json 등을 "그대로 복사"해서 두면
# momotalk/paths.py 의 get_base_dir() 가 exe 옆 폴더를 정확히 찾습니다.

import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],  # 데이터 파일은 spec에 안 넣고, 빌드 뒤 폴더째로 복사(아래 build_exe.bat 참고)
    hiddenimports=collect_submodules('google.genai'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MomoTalk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 콘솔창 없이 실행(디버그 필요하면 True로 잠깐 바꾸세요)
    icon='assets/momotalk.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='MomoTalk',
)
