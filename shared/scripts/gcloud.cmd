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
setlocal

if not defined CLOUDSDK_PYTHON (
  for /f "delims=" %%i in ('where python 2^>nul') do (
    if not defined CLOUDSDK_PYTHON set "CLOUDSDK_PYTHON=%%i"
  )
)
if not defined CLOUDSDK_PYTHON (
  echo [gcloud.cmd] Python not found on PATH. Set CLOUDSDK_PYTHON to python.exe.
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
