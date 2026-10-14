@echo off
setlocal
cd /d "%~dp0"

rem Build a single-file, windowed exe into dist\GooglePhotosAlbumDownloader.exe
rem Requires: pip install -r requirements.txt
rem
rem The two --add-binary lines bundle the Tcl/Tk DLLs that _tkinter needs.
rem For Miniconda they live in Library\bin. Change TK_BIN if your Python is elsewhere.

set "TK_BIN=C:\ProgramData\miniconda3\Library\bin"

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name GooglePhotosAlbumDownloader ^
  --add-binary "%TK_BIN%\tcl86t.dll;." ^
  --add-binary "%TK_BIN%\tk86t.dll;." ^
  album_downloader_gui.py

if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

rem Remove PyInstaller's intermediate files; only dist\ is kept
rmdir /s /q build 2>nul
del /q GooglePhotosAlbumDownloader.spec 2>nul

echo.
echo Done: dist\GooglePhotosAlbumDownloader.exe
pause
