# Google Photos Album Downloader

## 下載

到 [Releases](../../releases) 頁面下載最新版：

- **Windows**：`GooglePhotosAlbumDownloader-Windows.exe`，雙擊即可開啟。
- **macOS**：`GooglePhotosAlbumDownloader-macOS.zip`，解壓後得到 `GooglePhotosAlbumDownloader.app`。
  - 第一次開啟時 macOS 可能顯示「無法驗證開發者」。請在 App 上按右鍵 →「打開」，或到「系統設定 → 隱私權與安全性」點「仍要打開」。
  - 此版本為 Apple Silicon（M1 以後）建置，Intel Mac 可透過 Rosetta 2 執行。

## 使用方式

開啟程式（不需要安裝 Python，也不會跳出命令列視窗）。

貼上包含日期、活動描述與 Google Photos 分享連結的整段文字後按「開始下載」。ZIP 會輸出到程式旁邊的 `zip_output` 資料夾（可在視窗中更改）。

## 檔案說明

- `GooglePhotosAlbumDownloader.exe`（位於 `dist\`）：單一執行檔，主程式。
- `album_downloader_gui.py`：GUI 程式，即 exe 的進入點。
- `album_downloader.py`：下載與解析邏輯。
- `test_album_downloader.py`：單元測試（`python -m unittest test_album_downloader`）。
- `build_exe.bat`：重新打包 exe 的腳本。
- `requirements.txt`：執行與打包所需套件。

## 自行打包

1. 安裝套件：`pip install -r requirements.txt`
2. 打包：
   - **Windows**：執行 `build_exe.bat`，產出 `dist\GooglePhotosAlbumDownloader.exe`。
     若 Python 不是 Miniconda 安裝，請修改 `build_exe.bat` 中的 `TK_BIN`，指向該 Python 的 `Library\bin`（內含 `tcl86t.dll`、`tk86t.dll`）。
   - **macOS**：在 Mac 終端機執行
     `python3 -m PyInstaller --noconfirm --clean --onefile --windowed --name GooglePhotosAlbumDownloader album_downloader_gui.py`，
     產出 `dist/GooglePhotosAlbumDownloader.app`。
     Homebrew 安裝的 Python 若沒有 tkinter，需先 `brew install python-tk`。

## 自動建置與發布

`.github/workflows/build.yml` 會在 GitHub 上同時建置 Windows 與 macOS 版本：

- 推送到 `main` 或開 Pull Request 時：執行測試並建置。
- 推送版本標籤（例如 `git tag v1.0.0 && git push origin v1.0.0`）時：建置後自動建立 GitHub Release 並附上兩個下載檔。

因為 PyInstaller 無法跨平台打包，macOS 版必須在 macOS runner 上建置，這也是使用 GitHub Actions 的原因。

## GUI 輸入格式

可以使用原本的簡短格式，每行輸入日期及分享網址。也可以直接貼上活動描述，例如：

```text
115/08/03 主題時間：走到社區裡聽見了什麼聲音。英語融入。學習區時間。
[Google Photos Markdown 分享連結]

115/08/04操作時間。大肌肉運動時間。畫自畫像。
[Google Photos 純文字分享網址]
```

網址可以放在日期與描述的同一行或下一行，也可以是 Markdown 連結或純網址。

每筆資料須以行首日期開始。支援 `115/08/03`、`115/8/3`、`3/9`，以及使用 `.` 或 `-` 分隔的日期。程式會把下一個日期之前的文字視為同一筆資料，並自動忽略 Markdown 連結中重複出現的網址。

ZIP 檔名會自動使用 Google Photos 相簿名稱，並移除尾端日期說明。預設輸出資料夾是本資料夾底下的 `zip_output`。

## 斷線續傳

- 下載時遇到連線逾時、連線中斷或 Google 暫時性錯誤（429、5xx）時，會等待 60 秒後自動重試，最多 20 次。
- 每下載完一張照片就會記錄進度到輸出資料夾內的 `.download_progress.json`。
- 重新執行時，已完整下載的相簿（ZIP 項目數與相簿照片數相同）會直接略過；下載到一半的相簿則從還沒下載的照片接續。
- 重試仍失敗時會停止並顯示「已記錄進度：第 N/M 張完成」。之後重新執行程式，會從下一張接續，不必整本重下。
- 等待秒數與重試次數可在 `album_downloader.py` 開頭的 `RETRY_WAIT_SECONDS`、`MAX_RETRIES` 調整。
