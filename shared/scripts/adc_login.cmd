@echo off
rem ---------------------------------------------------------------------------
rem One-time sign-in for Application Default Credentials.
rem
rem Google no longer lets the gcloud built-in client ID request
rem analytics.readonly, so an OAuth client of our own is required:
rem
rem   gcloud warns: "The following scopes will be blocked soon for the default
rem   client ID: https://www.googleapis.com/auth/analytics.readonly"
rem   and the browser shows "This app is blocked".
rem
rem Create a Desktop-app OAuth client in the Cloud console (consent screen must
rem be Internal, or refresh tokens expire after 7 days), download the JSON, and
rem save it at %USERPROFILE%\.and-a\oauth_client.json -- or pass its path as the
rem second argument. Full steps: shared/GA4_LOCAL_FETCH.md (Japanese).
rem
rem The scopes are written here on purpose. Typing them on a command line goes
rem wrong easily: shells split the long URLs, and MSYS/Git Bash rewrites a bare
rem `/c` into a Windows path. One short command avoids both.
rem
rem Usage:  shared\scripts\adc_login.cmd [quota-project-id] [client-json-path]
rem ---------------------------------------------------------------------------
setlocal
set "SCOPES=https://www.googleapis.com/auth/analytics.readonly,https://www.googleapis.com/auth/webmasters.readonly,https://www.googleapis.com/auth/cloud-platform"

set "CLIENT=%~2"
if "%CLIENT%"=="" set "CLIENT=%USERPROFILE%\.and-a\oauth_client.json"

if not exist "%CLIENT%" (
  echo.
  echo The OAuth client file was not found:
  echo   %CLIENT%
  echo.
  echo Google blocks analytics.readonly for the gcloud built-in client, so a
  echo Desktop-app OAuth client of our own is required. Create one in the Cloud
  echo console, download the JSON, and save it at the path above.
  echo Steps: shared/GA4_LOCAL_FETCH.md
  exit /b 1
)

echo.
echo [1/2] Signing in. A browser window will open.
echo       OAuth client: %CLIENT%
call "%~dp0gcloud.cmd" auth application-default login --client-id-file="%CLIENT%" --scopes=%SCOPES%
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
echo If it says "CSRF Warning! State not equal", a previous sign-in is still
echo listening on port 8085. See shared/GA4_LOCAL_FETCH.md.
exit /b 1
