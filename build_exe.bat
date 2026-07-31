@echo off
echo === MomoTalk build start ===

python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [install] pyinstaller not found, installing...
    python -m pip install pyinstaller
)

echo === backing up runtime files (chat history / api key) before clean rebuild ===
if exist dist\MomoTalk\config.json copy /Y dist\MomoTalk\config.json _backup_config.json >nul
if exist dist\MomoTalk\chat_history.json copy /Y dist\MomoTalk\chat_history.json _backup_chat_history.json >nul
if exist dist\MomoTalk\anniversaries.json copy /Y dist\MomoTalk\anniversaries.json _backup_anniversaries.json >nul
if exist dist\MomoTalk\event_dates.json copy /Y dist\MomoTalk\event_dates.json _backup_event_dates.json >nul

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

python -m PyInstaller MomoTalk.spec

if not exist dist\MomoTalk\MomoTalk.exe (
    echo [FAILED] build output not found. check the errors above.
    echo [NOTE] if MomoTalk.exe was still running, close it first and try again.
    if exist _backup_config.json del _backup_config.json
    if exist _backup_chat_history.json del _backup_chat_history.json
    if exist _backup_anniversaries.json del _backup_anniversaries.json
    if exist _backup_event_dates.json del _backup_event_dates.json
    pause
    exit /b 1
)

echo === copying code-related data (always overwritten) ===
xcopy /E /I /Y prompts dist\MomoTalk\prompts
xcopy /E /I /Y data dist\MomoTalk\data
xcopy /E /I /Y assets dist\MomoTalk\assets

echo === restoring runtime files (chat history / api key take priority over backups) ===
if exist _backup_config.json (
    move /Y _backup_config.json dist\MomoTalk\config.json >nul
    echo   config.json restored from previous build
) else (
    copy /Y config.json dist\MomoTalk\config.json
    echo   config.json seeded fresh - remember to put your API key in dist\MomoTalk\config.json
)
if exist _backup_chat_history.json (
    move /Y _backup_chat_history.json dist\MomoTalk\chat_history.json >nul
    echo   chat_history.json restored - your chat progress is safe
) else (
    if exist chat_history.json copy /Y chat_history.json dist\MomoTalk\chat_history.json
)
if exist _backup_anniversaries.json (
    move /Y _backup_anniversaries.json dist\MomoTalk\anniversaries.json >nul
) else (
    if exist anniversaries.json copy /Y anniversaries.json dist\MomoTalk\anniversaries.json
)
if exist _backup_event_dates.json (
    move /Y _backup_event_dates.json dist\MomoTalk\event_dates.json >nul
    echo   event_dates.json restored - this year's event dates stay the same
) else (
    if exist event_dates.json copy /Y event_dates.json dist\MomoTalk\event_dates.json
)

echo.
echo === DONE ===
echo Run dist\MomoTalk\MomoTalk.exe
echo Edit prompts\*.json inside dist\MomoTalk\ from now on - not the project root copy.
pause
