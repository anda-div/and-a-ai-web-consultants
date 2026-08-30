@echo off
rem ---------------------------------------------------------------------------
rem One-time sign-in for Application Default Credentials.
rem A browser window opens; sign in with the account that can read the
rem analytics property, then close it. Run once per PC, and again if ADC expires.
rem
rem The scopes are written here on purpose. Typing them on a command line goes
rem wrong easily: shells split the long URLs, and MSYS/Git Bash rewrites a bare
rem `/c` into a Windows path. One short command avoids both.
rem
rem Usage:  shared\scripts\adc_login.cmd [quota-project-id]
rem Why:    see shared/TLS_INSPECTION.md (Japanese)
rem ---------------------------------------------------------------------------
setlocal
set "SCOPES=https://www.googleapis.com/auth/analytics.readonly,https://www.googleapis.com/auth/cloud-platform"

echo.
echo [1/2] Signing in. A browser window will open.
call "%~dp0gcloud.cmd" auth application-default login --scopes=%SCOPES%
if errorlevel 1 goto :failed

if "%~1"=="" (
  echo.
  echo Done. No quota project given, so that step was skipped.
  echo Set it later with:
  echo   shared\scripts\gcloud.cmd auth application-default set-quota-project ^<id^>
  exit /b 0
)

echo.
echo [2/2] Setting the quota project: %~1
call "%~dp0gcloud.cmd" auth application-default set-quota-project %~1
if errorlevel 1 goto :failed

echo.
echo Done.
exit /b 0

:failed
echo.
echo Failed. See the message above.
exit /b 1
