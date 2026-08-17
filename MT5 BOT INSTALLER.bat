@echo off
setlocal EnableExtensions
title MT5 BOT INSTALLER

rem ===========================================================================
rem  MT5 BOT INSTALLER  (Install / Update / Uninstall)
rem
rem  NOTE: delayed expansion (!var!) is intentionally NOT enabled. This repo's
rem  own path can contain "!" characters, and cmd.exe's delayed-expansion pass
rem  silently eats "!...!" pairs found anywhere in a line - including inside
rem  a %PROJECT_ROOT% value that itself contains "!". Every variable below
rem  uses plain %var% instead.
rem ===========================================================================

set "APP_VERSION=V1.0"
set "REPO_URL=https://github.com/JasonPieterK/MT5Bot.git"
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "LOG_DIR=%PROJECT_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

rem --- one log file per run ---
set "SESSION_ID="
for /f "usebackq delims=" %%S in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"`) do set "SESSION_ID=%%S"
if "%SESSION_ID%"=="" set "SESSION_ID=UNKNOWN"
set "MANAGE_LOG=%LOG_DIR%\installer-%SESSION_ID%.txt"

rem --- ANSI escape + 24-bit colors (each a single combined SGR sequence) ---
for /F %%A in ('echo prompt $E^| cmd') do set "ESC=%%A"
set "C_RESET=%ESC%[0m"
set "C_TITLE=%ESC%[1;38;2;219;230;76;48;2;0;31;63m"
set "C_SUB=%ESC%[1;38;2;116;195;101;48;2;0;31;63m"
set "C_BLUE=%ESC%[38;2;107;159;228m"
set "C_BLUEB=%ESC%[1;38;2;107;159;228m"
set "C_GREEN=%ESC%[38;2;116;195;101m"
set "C_GREENB=%ESC%[1;38;2;116;195;101m"
set "C_RED=%ESC%[38;2;232;68;90m"
set "C_REDB=%ESC%[1;38;2;232;68;90m"
set "C_WHITE=%ESC%[38;2;246;247;237m"
set "C_WHITEB=%ESC%[1;38;2;246;247;237m"

call :log "INFO" "=== Session started at %date% %time% - MT5 BOT INSTALLER %APP_VERSION% (session-%SESSION_ID%) ==="
goto :menu

rem ===========================================================================
rem  Logging
rem ===========================================================================
:log
    set "lvl=%~1"
    set "msg=%~2"
    echo [%SESSION_ID%] [%date% %time%] [%lvl%] %msg%>>"%MANAGE_LOG%"
    goto :eof

rem :fail CODE "short reason"  - prints a red error box, logs it, explains the fix
:fail
    set "code=%~1"
    set "reason=%~2"
    call :log "ERROR" "[%code%] %reason%"
    echo.
    echo %C_REDB%  [%code%] ERROR: %reason%%C_RESET%
    call :explain "1" "%code%"
    echo.
    pause
    goto :menu

rem ===========================================================================
rem  Banner
rem ===========================================================================
:menu
    cls
    echo %C_TITLE%==============================================================%C_RESET%
    echo %C_TITLE%                                                              %C_RESET%
    echo %C_TITLE%                     M T 5   B O T                            %C_RESET%
    echo %C_SUB%            multi-strategy trading robot installer             %C_RESET%
    echo %C_TITLE%                                                              %C_RESET%
    echo %C_TITLE%==============================================================%C_RESET%
    echo %C_BLUEB%--------------------------------------------------------------%C_RESET%
    echo.
    echo   %C_BLUEB%Version:%C_RESET%            %C_BLUE%%APP_VERSION%%C_RESET%
    echo   %C_BLUEB%Session:%C_RESET%            %C_BLUE%%SESSION_ID%%C_RESET%
    echo   %C_BLUEB%Install directory:%C_RESET% %C_BLUE%%PROJECT_ROOT%%C_RESET%
    echo   %C_BLUEB%Log file:%C_RESET%          %C_BLUE%%MANAGE_LOG%%C_RESET%
    echo.
    echo   %C_GREENB%[1]%C_RESET% %C_WHITE%Install%C_RESET%               - fresh install to a folder you choose
    echo   %C_GREENB%[2]%C_RESET% %C_WHITE%Update%C_RESET%                - pull latest from GitHub, keep logs ^& your data
    echo   %C_GREENB%[3]%C_RESET% %C_WHITE%Add desktop shortcut%C_RESET%  - (re)create the shortcut for this install
    echo   %C_REDB%[4]%C_RESET% %C_WHITE%Uninstall%C_RESET%             - delete this install completely
    echo   %C_BLUEB%[5]%C_RESET% %C_WHITE%Error code guide%C_RESET%      - self-troubleshooting reference
    echo   %C_WHITEB%[6]%C_RESET% %C_WHITE%Exit%C_RESET%
    echo.
    choice /c 123456 /n /m "  Select an option: "
    set "sel=%errorlevel%"
    if "%sel%"=="1" goto :install
    if "%sel%"=="2" goto :update
    if "%sel%"=="3" goto :add_shortcut
    if "%sel%"=="4" goto :uninstall
    if "%sel%"=="5" goto :show_errors
    if "%sel%"=="6" goto :end
    goto :menu

rem ===========================================================================
rem  INSTALL - pick destination via folder dialog, clone repo, set up venv
rem ===========================================================================
:install
    call :log "INFO" "User selected Install"
    echo.
    echo %C_GREEN%Opening folder selector - choose where MT5 Bot should live...%C_RESET%
    call :pick_folder "Choose install folder for MT5 Bot" "TARGET_DIR"
    if "%TARGET_DIR%"=="" (
        call :fail "F001" "No folder selected - install cancelled."
        goto :menu
    )

    call :check_git
    if not "%errorlevel%"=="0" goto :menu

    echo.
    if exist "%TARGET_DIR%\.git" goto :install_pull
    goto :install_clone

:install_pull
    echo %C_WHITE%Pulling latest changes into "%TARGET_DIR%" - progress below:%C_RESET%
    call :log "INFO" "git pull started in %TARGET_DIR%"
    pushd "%TARGET_DIR%"
    git pull --progress
    set "GITERR=%errorlevel%"
    popd
    goto :install_fetch_done

:install_clone
    if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
    echo %C_WHITE%Cloning into "%TARGET_DIR%" - progress below:%C_RESET%
    call :log "INFO" "git clone started -> %TARGET_DIR%"
    git clone --progress --depth 1 "%REPO_URL%" "%TARGET_DIR%\__clone_tmp__"
    set "GITERR=%errorlevel%"
    if not "%GITERR%"=="0" goto :install_fetch_done
    echo %C_WHITE%Copying files into place - progress below:%C_RESET%
    robocopy "%TARGET_DIR%\__clone_tmp__" "%TARGET_DIR%" /E /XD .git
    rmdir /s /q "%TARGET_DIR%\__clone_tmp__" >nul 2>&1

:install_fetch_done
    if not "%GITERR%"=="0" (
        call :fail "U001" "Git clone/pull failed while installing."
        goto :menu
    )
    echo %C_GREENB%Done - repository is up to date.%C_RESET%
    call :log "SUCCESS" "git fetch finished (%TARGET_DIR%)"
    if not exist "%TARGET_DIR%\logs" mkdir "%TARGET_DIR%\logs" >nul 2>&1

    call :check_python
    if not "%errorlevel%"=="0" goto :menu

    echo %C_WHITE%Creating virtual environment...%C_RESET%
    pushd "%TARGET_DIR%"
    python -m venv venv >>"%MANAGE_LOG%" 2>&1
    if not exist "venv\Scripts\python.exe" (
        popd
        call :fail "E005" "Virtual environment creation failed."
        goto :menu
    )
    echo %C_WHITE%Installing Python dependencies (this can take a minute)...%C_RESET%
    venv\Scripts\python.exe -m pip install --upgrade pip >>"%MANAGE_LOG%" 2>&1
    if not "%errorlevel%"=="0" call :log "ERROR" "[E002] pip upgrade failed (non-fatal, continuing)"
    venv\Scripts\python.exe -m pip install -r requirements.txt >>"%MANAGE_LOG%" 2>&1
    set "PIPERR=%errorlevel%"
    popd
    if not "%PIPERR%"=="0" (
        call :fail "E003" "Installing requirements.txt failed."
        goto :menu
    )

    echo.
    choice /c YN /n /m "  Add a desktop shortcut? (Y/N): "
    if errorlevel 2 goto :install_no_shortcut
    call :make_shortcut "%TARGET_DIR%"
:install_no_shortcut

    call :log "SUCCESS" "Install completed to %TARGET_DIR%"
    echo.
    echo %C_GREENB%Install complete!%C_RESET% %C_WHITE%MT5 Bot is ready at %TARGET_DIR%%C_RESET%
    echo %C_WHITE%Next: open MT5, log into an account, then run start.bat.%C_RESET%
    explorer "%TARGET_DIR%"
    echo.
    pause
    goto :menu

rem ===========================================================================
rem  UPDATE - pull latest, overwrite everything except logs, venv, and local data
rem ===========================================================================
:update
    call :log "INFO" "User selected Update"
    call :check_git
    if not "%errorlevel%"=="0" goto :menu

    set "TMP_DIR=%TEMP%\mt5bot_update_%RANDOM%"
    echo.
    echo %C_WHITE%Fetching latest version from GitHub - progress below:%C_RESET%
    call :log "INFO" "git clone (update) started -> %TMP_DIR%"
    git clone --progress --depth 1 "%REPO_URL%" "%TMP_DIR%"
    set "GITERR=%errorlevel%"
    if not "%GITERR%"=="0" (
        call :fail "U001" "Git clone failed while updating."
        goto :menu
    )
    echo %C_GREENB%Download finished.%C_RESET%
    call :log "SUCCESS" "git clone (update) finished"

    echo %C_WHITE%Overwriting local files (logs, venv, and your saved data are kept) - progress below:%C_RESET%
    robocopy "%TMP_DIR%" "%PROJECT_ROOT%" /MIR /XD .git logs venv /XF app_state.json journal.json ml_weights.json trades.csv execution.csv events.jsonl events.jsonl.1
    set "RC=%errorlevel%"
    rmdir /s /q "%TMP_DIR%" >nul 2>&1

    rem robocopy exit codes 0-7 are all "success" (8+ means real failure)
    if %RC% geq 8 (
        call :fail "U002" "Update overwrite failed (robocopy code %RC%)."
        goto :menu
    )

    echo %C_WHITE%Refreshing Python dependencies...%C_RESET%
    if exist "%PROJECT_ROOT%\venv\Scripts\python.exe" (
        "%PROJECT_ROOT%\venv\Scripts\python.exe" -m pip install -r "%PROJECT_ROOT%\requirements.txt" >>"%MANAGE_LOG%" 2>&1
    )

    call :log "SUCCESS" "Update completed (robocopy code %RC%)"
    echo.
    echo %C_GREENB%Update complete!%C_RESET% %C_WHITE%You're on the latest version.%C_RESET%
    echo.
    choice /c YN /n /m "  Add/refresh the desktop shortcut? (Y/N): "
    if errorlevel 2 goto :update_no_shortcut
    call :make_shortcut "%PROJECT_ROOT%"
:update_no_shortcut
    echo.
    pause
    goto :menu

rem ===========================================================================
rem  ADD DESKTOP SHORTCUT - standalone, reuses :make_shortcut
rem ===========================================================================
:add_shortcut
    call :log "INFO" "User selected Add desktop shortcut"
    if not exist "%PROJECT_ROOT%\start.bat" (
        call :fail "S002" "Launcher (start.bat) not found in this folder."
        goto :menu
    )
    call :make_shortcut "%PROJECT_ROOT%"
    echo.
    pause
    goto :menu

rem ===========================================================================
rem  UNINSTALL - remove everything, including this folder and this .bat
rem ===========================================================================
:uninstall
    call :log "INFO" "User selected Uninstall"
    echo.
    echo %C_REDB%This will permanently delete:%C_RESET%
    echo   %C_RED%- %PROJECT_ROOT%  (all code, logs, and this script)%C_RESET%
    echo   %C_RED%- Desktop shortcut%C_RESET%
    echo.
    echo %C_WHITE%This does NOT touch your MT5 account or broker in any way - it only%C_RESET%
    echo %C_WHITE%removes this app's local files.%C_RESET%
    echo.
    choice /c YN /n /m "  Are you sure? (Y/N): "
    if errorlevel 2 goto :menu

    call :log "INFO" "Uninstall confirmed by user - deleting %PROJECT_ROOT%"
    set "SHORTCUT=%USERPROFILE%\Desktop\MT5 Bot.lnk"
    if exist "%SHORTCUT%" del /f /q "%SHORTCUT%" >nul 2>&1

    echo.
    echo %C_WHITE%Removing MT5 Bot...%C_RESET%
    rem Batch can't delete the folder it's running from while running,
    rem so hand off to a detached process that waits for us to exit first.
    start "" /min cmd /c "timeout /t 2 /nobreak >nul & rmdir /s /q "%PROJECT_ROOT%""
    echo %C_GREENB%Uninstall started.%C_RESET% %C_WHITE%This window will close now.%C_RESET%
    timeout /t 3 >nul
    exit /b 0

rem ===========================================================================
rem  Error code guide
rem ===========================================================================
:show_errors
    cls
    echo %C_BLUEB%==============================================%C_RESET%
    echo %C_BLUEB%  ERROR CODE GUIDE - self-troubleshooting%C_RESET%
    echo %C_BLUEB%==============================================%C_RESET%
    echo.
    echo %C_GREENB%INSTALL / SETUP%C_RESET%
    call :explain "1" "E001"
    call :explain "2" "E002"
    call :explain "3" "E003"
    call :explain "4" "E004"
    call :explain "5" "E005"
    echo.
    echo %C_GREENB%UPDATE%C_RESET%
    call :explain "1" "U001"
    call :explain "2" "U002"
    echo.
    echo %C_GREENB%SHORTCUT%C_RESET%
    call :explain "1" "S001"
    call :explain "2" "S002"
    echo.
    echo %C_GREENB%FOLDER SELECTION%C_RESET%
    call :explain "1" "F001"
    echo.
    echo %C_GREENB%TRADING (inside the app, not this script)%C_RESET%
    echo   %C_WHITEB%1^)%C_RESET% Equity shows "-" or 0 in the dashboard
    echo      Fix: make sure MT5 is open and logged into an account before starting the app.
    echo   %C_WHITEB%2^)%C_RESET% "Auto" shows off after restarting the app, even though it was on before
    echo      Fix: intentional - trading never auto-resumes from a restart, re-arm it manually.
    echo.
    echo %C_BLUE%This session's log: %MANAGE_LOG%%C_RESET%
    echo   %C_WHITE%Full usage guide: see GUIDE in the install folder.%C_RESET%
    echo.
    pause
    goto :menu

rem :explain NUM CODE - prints one numbered, colored cause+fix line
:explain
    set "n=%~1"
    set "c=%~2"
    if "%c%"=="E001" (
        echo   %C_REDB%%n%^) E001%C_RESET% Python 3.11+ not found on PATH.
        echo      Fix: install from python.org, check "Add python.exe to PATH", re-run.
    )
    if "%c%"=="E002" (
        echo   %C_REDB%%n%^) E002%C_RESET% pip upgrade failed ^(non-fatal^).
        echo      Fix: check internet connection, or run "venv\Scripts\python -m pip install --upgrade pip" manually.
    )
    if "%c%"=="E003" (
        echo   %C_REDB%%n%^) E003%C_RESET% Installing requirements.txt failed.
        echo      Fix: check internet connection, try running this script as Administrator,
        echo           or temporarily disable antivirus/firewall blocking pip.
    )
    if "%c%"=="E004" (
        echo   %C_REDB%%n%^) E004%C_RESET% Git is not installed or not on PATH.
        echo      Fix: install Git for Windows from git-scm.com, then re-run.
    )
    if "%c%"=="E005" (
        echo   %C_REDB%%n%^) E005%C_RESET% Virtual environment creation failed.
        echo      Fix: confirm Python 3.11+ is installed correctly, then re-run.
    )
    if "%c%"=="U001" (
        echo   %C_REDB%%n%^) U001%C_RESET% Git clone/pull from GitHub failed.
        echo      Fix: check internet connection, firewall/proxy, and that github.com is reachable.
    )
    if "%c%"=="U002" (
        echo   %C_REDB%%n%^) U002%C_RESET% Update overwrite failed.
        echo      Fix: close MT5 Bot ^(and any file open from its folder^) first, then retry.
    )
    if "%c%"=="S001" (
        echo   %C_REDB%%n%^) S001%C_RESET% Desktop shortcut creation failed ^(non-fatal^).
        echo      Fix: create the shortcut manually, or re-run as Administrator.
    )
    if "%c%"=="S002" (
        echo   %C_REDB%%n%^) S002%C_RESET% "start.bat" launcher not found in this folder.
        echo      Fix: run Install first, or run this script from inside your install folder.
    )
    if "%c%"=="F001" (
        echo   %C_REDB%%n%^) F001%C_RESET% No install folder was chosen.
        echo      Fix: run Install again and pick a folder in the dialog ^(don't press Cancel^).
    )
    goto :eof

rem ===========================================================================
rem  Helpers
rem ===========================================================================

rem :check_git - if git missing, ASK to install it. If the user says no, git is
rem optional: show the manual "download ZIP from GitHub" steps and abort (exit 1).
:check_git
    where git >nul 2>&1
    if "%errorlevel%"=="0" exit /b 0
    echo.
    echo %C_REDB%  Git is not installed on this PC.%C_RESET%
    echo   %C_WHITE%Git lets this installer download and update MT5 Bot automatically.%C_RESET%
    echo   %C_WHITE%It is optional - you can also download the project as a ZIP by hand.%C_RESET%
    echo.
    choice /c YN /n /m "  Install Git now (recommended)? (Y/N): "
    if errorlevel 2 goto :git_declined
    call :install_git
    where git >nul 2>&1
    if "%errorlevel%"=="0" exit /b 0
    call :fail "E004" "Git install did not complete - close and reopen this installer, then retry."
    exit /b 1
:git_declined
    call :log "INFO" "User declined Git install"
    call :manual_zip_steps
    exit /b 1

rem :install_git - install Git for Windows via winget, then add it to this
rem session's PATH so the very next `where git` finds it without a restart.
:install_git
    echo %C_WHITE%Installing Git for Windows...%C_RESET%
    where winget >nul 2>&1
    if not "%errorlevel%"=="0" (
        echo %C_RED%winget is not available - opening the Git download page instead.%C_RESET%
        start "" "https://git-scm.com/download/win"
        echo %C_WHITE%Install Git ^(default options are fine^), then re-run this option.%C_RESET%
        pause
        goto :eof
    )
    winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements >>"%MANAGE_LOG%" 2>&1
    call :log "INFO" "Attempted Git install via winget"
    rem winget doesn't refresh PATH for the running shell - add the default install dirs
    set "PATH=%PATH%;%ProgramFiles%\Git\cmd;%ProgramFiles%\Git\bin"
    goto :eof

rem :manual_zip_steps - detailed, no-Git download instructions
:manual_zip_steps
    cls
    echo %C_BLUEB%============================================================%C_RESET%
    echo %C_BLUEB%  MANUAL DOWNLOAD  (no Git required)%C_RESET%
    echo %C_BLUEB%============================================================%C_RESET%
    echo.
    echo   %C_WHITE%You can install without Git by downloading the project ZIP:%C_RESET%
    echo.
    echo   %C_GREENB%1)%C_RESET% %C_WHITE%Open this link in your web browser:%C_RESET%
    echo        %C_BLUE%%REPO_URL:.git=%%C_RESET%
    echo   %C_GREENB%2)%C_RESET% %C_WHITE%Click the green %C_GREENB%[ ^<^> Code ]%C_WHITE% button (upper-right of the file list).%C_RESET%
    echo   %C_GREENB%3)%C_RESET% %C_WHITE%In the dropdown, click %C_GREENB%Download ZIP%C_WHITE%.%C_RESET%
    echo   %C_GREENB%4)%C_RESET% %C_WHITE%Find the downloaded .zip, right-click it -^> %C_GREENB%Extract All...%C_RESET%
    echo   %C_GREENB%5)%C_RESET% %C_WHITE%Choose (or create) the folder where you want the app to live.%C_RESET%
    echo   %C_GREENB%6)%C_RESET% %C_WHITE%Open that folder and double-click %C_GREENB%MT5 BOT INSTALLER.bat%C_WHITE% and choose Install.%C_RESET%
    echo.
    echo   %C_WHITE%Note: Python is still required to run the app. This installer's%C_RESET%
    echo   %C_WHITE%%C_GREENB%[1] Install%C_WHITE% step will offer to set Python up for you.%C_RESET%
    echo.
    choice /c YN /n /m "  Open the download page in your browser now? (Y/N): "
    if errorlevel 2 goto :manual_zip_done
    start "" "%REPO_URL:.git=%"
:manual_zip_done
    echo.
    pause
    goto :eof

rem :check_python - if python < 3.11, ASK before installing. Decline = show manual
rem python.org steps and abort. Accept = winget install + add to this session PATH.
:check_python
    python -c "import sys; exit(0) if sys.version_info >= (3,11) else exit(1)" >nul 2>&1
    if "%errorlevel%"=="0" exit /b 0
    echo.
    echo %C_REDB%  Python 3.11+ was not found.%C_RESET%
    echo   %C_WHITE%MT5 Bot needs Python to run.%C_RESET%
    echo.
    choice /c YN /n /m "  Install Python now (recommended)? (Y/N): "
    if errorlevel 2 goto :python_declined
    echo %C_WHITE%Installing Python via winget...%C_RESET%
    where winget >nul 2>&1
    if not "%errorlevel%"=="0" goto :python_manual
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements >>"%MANAGE_LOG%" 2>&1
    call :log "INFO" "Attempted Python install via winget"
    rem winget doesn't refresh PATH for the running shell - add default per-user install dirs
    set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts"
    python -c "import sys; exit(0) if sys.version_info >= (3,11) else exit(1)" >nul 2>&1
    if "%errorlevel%"=="0" exit /b 0
    goto :python_manual
:python_declined
    call :log "INFO" "User declined Python install"
    echo.
    echo   %C_WHITE%No problem. To install Python yourself:%C_RESET%
    echo   %C_GREENB%1)%C_RESET% %C_WHITE%Go to %C_BLUE%https://www.python.org/downloads/%C_RESET%
    echo   %C_GREENB%2)%C_RESET% %C_WHITE%Download the latest Python 3 for Windows.%C_RESET%
    echo   %C_GREENB%3)%C_RESET% %C_WHITE%Run it and CHECK the box %C_GREENB%"Add python.exe to PATH"%C_WHITE% before installing.%C_RESET%
    echo   %C_GREENB%4)%C_RESET% %C_WHITE%Finish, then re-run this installer.%C_RESET%
    call :fail "E001" "Python 3.11+ not found (install declined)."
    exit /b 1
:python_manual
    echo %C_RED%Automatic Python install did not complete.%C_RESET%
    echo   %C_WHITE%Install it manually from https://www.python.org/downloads/ (check "Add to PATH"), then re-run.%C_RESET%
    call :fail "E001" "Python 3.11+ not found."
    exit /b 1

rem :pick_folder "dialog title" RESULT_VAR - opens a Windows folder browser dialog
:pick_folder
    set "title=%~1"
    set "resultvar=%~2"
    set "PS1=%TEMP%\mt5bot_folder_picker_%RANDOM%.ps1"
    >"%PS1%" echo Add-Type -AssemblyName System.Windows.Forms ^| Out-Null
    >>"%PS1%" echo $f = New-Object System.Windows.Forms.FolderBrowserDialog
    >>"%PS1%" echo $f.Description = "%title%"
    >>"%PS1%" echo $f.SelectedPath = "%USERPROFILE%\MT5 Bot"
    >>"%PS1%" echo if ($f.ShowDialog() -eq 'OK') { Write-Output $f.SelectedPath }
    set "PICKED="
    for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"`) do set "PICKED=%%P"
    del /f /q "%PS1%" >nul 2>&1
    set "%resultvar%=%PICKED%"
    goto :eof

rem :make_shortcut TARGET_DIR - creates/refreshes the Desktop shortcut pointing at TARGET_DIR's launcher
:make_shortcut
    set "SC_DIR=%~1"
    set "SHORTCUT=%USERPROFILE%\Desktop\MT5 Bot.lnk"
    powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath='%SC_DIR%\start.bat'; $s.WorkingDirectory='%SC_DIR%'; $s.Save()" >>"%MANAGE_LOG%" 2>&1
    if not "%errorlevel%"=="0" (
        call :log "ERROR" "[S001] Desktop shortcut creation failed"
        echo %C_RED%Shortcut creation failed - see Error code guide (S001).%C_RESET%
    ) else (
        call :log "SUCCESS" "Desktop shortcut created/updated -> %SC_DIR%"
        echo %C_GREENB%Desktop shortcut ready.%C_RESET%
    )
    goto :eof

:end
    call :log "INFO" "=== Session ended at %date% %time% (session-%SESSION_ID%) ==="
    exit /b 0
