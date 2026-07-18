@echo off
chcp 65001 >nul
echo === MomoTalk exe 빌드 시작 ===

REM 1) PyInstaller 설치 확인
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [설치] pyinstaller가 없어서 설치합니다...
    pip install pyinstaller
)

REM 2) 이전 빌드 정리
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM 3) 빌드 (onedir 모드)
pyinstaller MomoTalk.spec

if not exist dist\MomoTalk\MomoTalk.exe (
    echo [실패] 빌드 결과물이 없습니다. 위 에러 메시지를 확인하세요.
    pause
    exit /b 1
)

REM 4) 데이터 파일들을 exe 옆으로 복사
echo === 데이터 폴더 복사 중 ===
xcopy /E /I /Y prompts dist\MomoTalk\prompts
xcopy /E /I /Y data dist\MomoTalk\data
xcopy /E /I /Y assets dist\MomoTalk\assets
copy /Y config.json dist\MomoTalk\config.json
copy /Y anniversaries.json dist\MomoTalk\anniversaries.json
if exist chat_history.json copy /Y chat_history.json dist\MomoTalk\chat_history.json

echo.
echo === 완료! ===
echo dist\MomoTalk\MomoTalk.exe 를 더블클릭하면 실행됩니다.
echo 앞으로 prompts\*.json 이나 config.json 은 dist\MomoTalk\ 폴더 안의 파일을 직접 고치시면 됩니다.
pause
