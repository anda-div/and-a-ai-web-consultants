@echo off
rem ---------------------------------------------------------------------------
rem Runs gcloud so that it also works on a PC where security software inspects
rem HTTPS traffic. Neither gcloud nor the security software is modified; only
rem the startup settings of the Python that gcloud runs on.
rem
rem   CLOUDSDK_PYTHON              use a Python that has `truststore` installed,
rem                                not the one bundled with the Cloud SDK
rem   CLOUDSDK_PYTHON_SITEPACKAGES let that Python read site-packages
rem   PYTHONPATH                   add the folder holding sitecustomize.py,
rem                                which is imported automatically at startup
rem
rem Setup:  pip install truststore
rem Why:    see shared/TLS_INSPECTION.md (Japanese)
rem ---------------------------------------------------------------------------
setlocal enabledelayedexpansion

if defined CLOUDSDK_PYTHON call :verify "%CLOUDSDK_PYTHON%" || set "CLOUDSDK_PYTHON="

rem The py launcher knows the real installs and ignores stray files.
if not defined CLOUDSDK_PYTHON (
  for /f "delims=" %%i in ('py -c "import sys; sys.stdout.write(sys.executable)" 2^>nul') do (
    call :verify "%%i" && set "CLOUDSDK_PYTHON=%%i"
  )
)

rem `where` also matches a file named `python` sitting in the current folder,
rem and the Microsoft Store stub, so every candidate is verified before use.
if not defined CLOUDSDK_PYTHON (
  for /f "delims=" %%i in ('where python 2^>nul') do (
    if not defined CLOUDSDK_PYTHON call :verify "%%i" && set "CLOUDSDK_PYTHON=%%i"
  )
)

if not defined CLOUDSDK_PYTHON (
  echo [gcloud.cmd] No usable Python found. Install Python, or set CLOUDSDK_PYTHON
  echo              to the full path of python.exe.
  exit /b 1
)

set "CLOUDSDK_PYTHON_SITEPACKAGES=1"
set "PYTHONPATH=%~dp0_tls_shim;%PYTHONPATH%"

set "GCLOUD_CMD=%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
if not exist "%GCLOUD_CMD%" set "GCLOUD_CMD=%ProgramFiles(x86)%\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
if not exist "%GCLOUD_CMD%" set "GCLOUD_CMD=%ProgramFiles%\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
if not exist "%GCLOUD_CMD%" (
  echo [gcloud.cmd] Cloud SDK not found. Set GCLOUD_CMD to the real gcloud.cmd.
  exit /b 1
)

call "%GCLOUD_CMD%" %*
exit /b %errorlevel%

rem --- Succeeds only if the candidate is an executable that actually runs. ---
:verify
if "%~x1"=="" exit /b 1
if /i not "%~x1"==".exe" exit /b 1
if not exist "%~1" exit /b 1
"%~1" -c "pass" >nul 2>&1
exit /b %errorlevel%
