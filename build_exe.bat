@echo off
echo === MomoTalk build start ===

python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [install] pyinstaller not found, installing...
    python -m pip install pyinstaller
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

python -m PyInstaller MomoTalk.spec

if not exist dist\MomoTalk\MomoTalk.exe (
    echo [FAILED] build output not found. check the errors above.
    pause
    exit /b 1
)

echo === copying code-related data (always overwritten) ===
xcopy /E /I /Y prompts dist\MomoTalk\prompts
xcopy /E /I /Y data dist\MomoTalk\data
xcopy /E /I /Y assets dist\MomoTalk\assets

echo === seeding runtime files (only if missing, will NOT overwrite existing progress) ===
if not exist dist\MomoTalk\config.json (
    copy /Y config.json dist\MomoTalk\config.json
    echo   config.json seeded - remember to put your API key in dist\MomoTalk\config.json
) else (
    echo   config.json already exists in dist, kept as-is
)
if not exist dist\MomoTalk\anniversaries.json (
    if exist anniversaries.json copy /Y anniversaries.json dist\MomoTalk\anniversaries.json
) else (
    echo   anniversaries.json already exists in dist, kept as-is
)
if not exist dist\MomoTalk\chat_history.json (
    if exist chat_history.json copy /Y chat_history.json dist\MomoTalk\chat_history.json
) else (
    echo   chat_history.json already exists in dist, kept as-is - your chat progress is safe
)

echo.
echo === DONE ===
echo Run dist\MomoTalk\MomoTalk.exe
echo Edit prompts\*.json inside dist\MomoTalk\ from now on - not the project root copy.
pause
