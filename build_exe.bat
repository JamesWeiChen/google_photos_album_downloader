@echo off
setlocal
cd /d "%~dp0"

rem Build a single-file, windowed exe into dist\GooglePhotosAlbumDownloader.exe
rem
rem Builds with a standalone Python 3.12 that uv downloads into .venv-build.
rem Do NOT build with Miniconda's Python: its OpenSSL aborts inside PyInstaller
rem builds ("OPENSSL_Uplink ... no OPENSSL_Applink"), so HTTPS downloads fail.
rem uv: https://docs.astral.sh/uv/
rem
rem UV_NATIVE_TLS makes uv trust the Windows certificate store, which is needed
rem on networks that intercept HTTPS (corporate proxies, some antivirus tools).
set UV_NATIVE_TLS=1

where uv >nul 2>nul
if errorlevel 1 (
  echo uv was not found. Install it first, for example: winget install astral-sh.uv
  pause
  exit /b 1
)

if not exist ".venv-build\Scripts\python.exe" (
  uv venv -p 3.12 .venv-build
  if errorlevel 1 goto :fail
  uv pip install -p .venv-build\Scripts\python.exe -r requirements.txt
  if errorlevel 1 goto :fail
)

.venv-build\Scripts\python.exe -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name GooglePhotosAlbumDownloader ^
  album_downloader_gui.py
if errorlevel 1 goto :fail

rem Remove PyInstaller's intermediate files; only dist\ is kept
rmdir /s /q build 2>nul
del /q GooglePhotosAlbumDownloader.spec 2>nul

echo.
echo Done: dist\GooglePhotosAlbumDownloader.exe
pause
exit /b 0

:fail
echo Build failed.
pause
exit /b 1
