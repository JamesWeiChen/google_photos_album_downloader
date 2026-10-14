import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from album_downloader import DownloadError, app_dir, parse_album_inputs, start_download_thread


SAMPLE_TEXT = """115/08/03 主題時間。英語融入。學習區時間。
[https://photos.app.goo.gl/exampleAlbum1](https://photos.app.goo.gl/exampleAlbum1)

115/08/04 操作時間。大肌肉運動時間。畫自畫像。
https://photos.app.goo.gl/exampleAlbum2
"""


class DownloaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Google Photos 相簿 ZIP 下載器")
        self.root.geometry("900x700")
        self.download_thread = None
        default_output_dir = app_dir() / "zip_output"

        self.output_dir_var = tk.StringVar(value=str(default_output_dir))
        self.status_var = tk.StringVar(value="準備就緒")

        self._build_ui()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)

        ttk.Label(
            frame,
            text="貼上含有日期、活動描述與 Google Photos 分享連結的文字",
            font=("Microsoft JhengHei UI", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            frame,
            text="支援網址另起一行、Markdown 連結，以及日期後沒有空格的格式",
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        self.input_text = tk.Text(frame, wrap="word", height=12, font=("Consolas", 11))
        self.input_text.grid(row=2, column=0, sticky="nsew")
        self.input_text.insert("1.0", SAMPLE_TEXT)

        output_frame = ttk.Frame(frame)
        output_frame.grid(row=3, column=0, sticky="ew", pady=(12, 8))
        output_frame.columnconfigure(1, weight=1)

        ttk.Label(output_frame, text="ZIP 輸出資料夾").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(output_frame, textvariable=self.output_dir_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(output_frame, text="選擇資料夾", command=self.choose_output_dir).grid(row=0, column=2, padx=(8, 0))

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(button_frame, text="開始下載", command=self.start_download).pack(side="left")
        ttk.Button(button_frame, text="清空輸入", command=self.clear_input).pack(side="left", padx=(8, 0))
        ttk.Button(button_frame, text="帶入範例", command=self.load_sample).pack(side="left", padx=(8, 0))

        ttk.Label(frame, textvariable=self.status_var).grid(row=5, column=0, sticky="w", pady=(0, 6))

        self.log_text = tk.Text(frame, wrap="word", height=16, font=("Consolas", 10), state="disabled")
        self.log_text.grid(row=6, column=0, sticky="nsew")
        frame.rowconfigure(6, weight=1)

    def choose_output_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.output_dir_var.get() or None)
        if chosen:
            self.output_dir_var.set(chosen)

    def clear_input(self) -> None:
        self.input_text.delete("1.0", "end")

    def load_sample(self) -> None:
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", SAMPLE_TEXT)

    def append_log(self, message: str) -> None:
        def write() -> None:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        self.root.after(0, write)

    def set_status(self, message: str) -> None:
        self.root.after(0, lambda: self.status_var.set(message))

    def start_download(self) -> None:
        if self.download_thread and self.download_thread.is_alive():
            messagebox.showinfo("下載中", "目前已有下載工作在進行。")
            return

        raw_text = self.input_text.get("1.0", "end").strip()
        output_dir = Path(self.output_dir_var.get().strip())
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            albums = parse_album_inputs(raw_text)
        except DownloadError as exc:
            messagebox.showerror("輸入格式錯誤", str(exc))
            return

        self.append_log(f"已解析 {len(albums)} 個相簿，開始下載...")
        self.set_status("下載中")
        self.download_thread = start_download_thread(
            albums=albums,
            output_dir=output_dir,
            on_log=self.append_log,
            on_done=self.on_done,
            on_error=self.on_error,
        )

    def on_done(self, results) -> None:
        def finish() -> None:
            self.status_var.set(f"完成，共 {len(results)} 個 ZIP")
            self.append_log("輸出檔案：")
            for result in results:
                self.append_log(str(result.zip_path))
            messagebox.showinfo("完成", f"已完成 {len(results)} 個相簿 ZIP。")

        self.root.after(0, finish)

    def on_error(self, exc: Exception) -> None:
        def fail() -> None:
            self.status_var.set("下載失敗")
            self.append_log(f"錯誤：{exc}")
            messagebox.showerror("下載失敗", str(exc))

        self.root.after(0, fail)


def main() -> None:
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except tk.TclError:
        pass
    DownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
