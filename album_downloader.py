import html
import json
import os
import re
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, TypeVar

import requests


T = TypeVar("T")


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
META_TITLE_RE = re.compile(
    r'<meta[^>]+(?:property|name)="og:title"[^>]+content="([^"]*)"',
    re.IGNORECASE,
)
MEDIA_URL_RE = re.compile(r'\["(https://lh3\.googleusercontent\.com/[^"]+)",\d+,\d+')
INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*]+')
DATE_LINE_RE = re.compile(
    r"^[^\S\r\n]*(?P<label>\d{1,3}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2})(?=$|[^\d./-])",
    re.MULTILINE,
)
SHARE_URL_RE = re.compile(
    r"https://photos\.app\.goo\.gl/[A-Za-z0-9_-]+",
    re.IGNORECASE,
)
PROGRESS_FILE_NAME = ".download_progress.json"
# 遇到連線錯誤時，每次等待的秒數與最多重試次數（單一步驟）
RETRY_WAIT_SECONDS = 60
MAX_RETRIES = 20
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class DownloadError(RuntimeError):
    pass


def app_dir() -> Path:
    """Folder that holds the program: the exe's folder when frozen, else the script's folder.

    PyInstaller onefile builds unpack to a temp folder, so __file__ cannot be used there.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


@dataclass(frozen=True)
class AlbumInput:
    date_label: str
    share_url: str


@dataclass(frozen=True)
class AlbumResult:
    zip_path: Path
    title: str
    item_count: int


def sanitize_filename(name: str) -> str:
    cleaned = INVALID_FILENAME_RE.sub("_", name).strip().rstrip(".")
    return cleaned or "album"


def clean_album_zip_name(title: str) -> str:
    base = html.unescape(title).strip()
    base = re.sub(r"\s+·\s+.*$", "", base)
    base = re.sub(r"\s*📸\s*$", "", base)
    return f"{sanitize_filename(base)}.zip"


def parse_album_inputs(raw_text: str) -> list[AlbumInput]:
    """Parse dated album entries from either compact lines or descriptive blocks.

    Each entry starts with a date at the beginning of a line.  Everything until
    the next dated line belongs to that entry, so descriptions and a link may be
    on the same line or on following lines.  Markdown links contain the same URL
    twice (label and target), which is why URLs are de-duplicated.
    """

    date_matches = list(DATE_LINE_RE.finditer(raw_text))
    if not date_matches:
        if SHARE_URL_RE.search(raw_text):
            raise DownloadError("有讀到相簿連結，但找不到放在行首的日期。")
        raise DownloadError("沒有讀到任何相簿連結。")

    albums: list[AlbumInput] = []
    missing_urls: list[str] = []
    seen_urls: set[str] = set()

    if SHARE_URL_RE.search(raw_text[: date_matches[0].start()]):
        raise DownloadError("第一個相簿連結前找不到日期。")

    for index, match in enumerate(date_matches):
        block_end = date_matches[index + 1].start() if index + 1 < len(date_matches) else len(raw_text)
        block = raw_text[match.end() : block_end]
        urls = list(dict.fromkeys(SHARE_URL_RE.findall(block)))
        label = re.sub(r"[/-]", ".", match.group("label"))

        if not urls:
            missing_urls.append(label)
            continue

        for url in urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            albums.append(AlbumInput(date_label=label, share_url=url))

    if missing_urls:
        raise DownloadError(f"以下日期後找不到 Google Photos 相簿連結：{', '.join(missing_urls)}")
    if not albums:
        raise DownloadError("沒有讀到任何相簿連結。")
    return albums


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def parse_title(page_text: str) -> str:
    match = META_TITLE_RE.search(page_text)
    if not match:
        raise DownloadError("找不到相簿標題。")
    return html.unescape(match.group(1)).strip()


def extract_media_urls(page_text: str) -> list[str]:
    seen: set[str] = set()
    media_urls: list[str] = []
    for url in MEDIA_URL_RE.findall(page_text):
        if url not in seen:
            seen.add(url)
            media_urls.append(url)
    if not media_urls:
        raise DownloadError("找不到相片或影片下載網址。")
    return media_urls


def filename_from_headers(headers: requests.structures.CaseInsensitiveDict, fallback_index: int) -> str:
    disposition = headers.get("content-disposition", "")
    match = re.search(r'filename="([^"]+)"', disposition)
    if match:
        return match.group(1)

    content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    ext = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/heic": ".heic",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
    }.get(content_type, ".bin")
    return f"file_{fallback_index:03d}{ext}"


def unique_name(name: str, used: set[str]) -> str:
    candidate = name
    stem, suffix = os.path.splitext(name)
    counter = 2
    while candidate in used:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    used.add(candidate)
    return candidate


def iter_download_chunks(response: requests.Response) -> Iterable[bytes]:
    for chunk in response.iter_content(chunk_size=1024 * 256):
        if chunk:
            yield chunk


def is_retryable(exc: Exception) -> bool:
    """Connection problems and temporary HTTP errors are retried; others fail at once."""
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        return response is not None and response.status_code in RETRYABLE_STATUS_CODES
    return isinstance(exc, requests.RequestException)


def run_with_retries(
    action: Callable[[], T],
    description: str,
    log: Callable[[str], None] | None = None,
) -> T:
    attempt = 0
    while True:
        try:
            return action()
        except Exception as exc:
            if not is_retryable(exc) or attempt >= MAX_RETRIES:
                raise
            attempt += 1
            if log:
                log(
                    f"{description} 連線失敗（{exc}），"
                    f"{RETRY_WAIT_SECONDS} 秒後重試（第 {attempt}/{MAX_RETRIES} 次）"
                )
            time.sleep(RETRY_WAIT_SECONDS)


def load_progress(output_dir: Path) -> dict[str, dict[str, int]]:
    path = output_dir / PROGRESS_FILE_NAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_progress(output_dir: Path, progress: dict[str, dict[str, int]]) -> None:
    path = output_dir / PROGRESS_FILE_NAME
    if not progress:
        path.unlink(missing_ok=True)
        return
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def get_page(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response


def fetch_media_file(session: requests.Session, media_url: str, index: int, target: Path) -> str:
    """Download one item into a temporary file and return the name suggested by the server."""
    with session.get(f"{media_url}=d", stream=True, timeout=120) as media_response:
        media_response.raise_for_status()
        with target.open("wb") as file:
            for chunk in iter_download_chunks(media_response):
                file.write(chunk)
        return filename_from_headers(media_response.headers, index)


def read_zip_names(zip_path: Path) -> list[str] | None:
    """Return the entry names of a finished ZIP, or None if it is missing or unreadable."""
    if not zip_path.exists():
        return None
    try:
        with zipfile.ZipFile(zip_path) as existing:
            return existing.namelist()
    except zipfile.BadZipFile:
        return None


def find_resume_point(
    zip_path: Path,
    state: dict[str, int] | None,
    total: int,
) -> tuple[int, set[str]]:
    """Return how many items are safely stored in an existing partial ZIP, and their names.

    If the saved progress does not match the ZIP on disk, the album starts over.
    """
    names = read_zip_names(zip_path)
    if names is None or not state or state.get("total") != total or len(names) != state.get("completed"):
        return 0, set()
    return len(names), set(names)


def download_album(
    session: requests.Session,
    album: AlbumInput,
    output_dir: Path,
    progress: dict[str, dict[str, int]],
    log: Callable[[str], None] | None = None,
) -> AlbumResult:
    page_response = run_with_retries(
        lambda: get_page(session, album.share_url),
        f"[{album.date_label}] 讀取相簿頁面",
        log,
    )
    title = parse_title(page_response.text)
    media_urls = extract_media_urls(page_response.text)
    total = len(media_urls)
    zip_path = output_dir / clean_album_zip_name(title)
    part_path = zip_path.with_suffix(".part")

    existing_names = read_zip_names(zip_path)
    if existing_names is not None and len(existing_names) == total:
        progress.pop(album.share_url, None)
        save_progress(output_dir, progress)
        if log:
            log(f"[{album.date_label}] {title}：已完整下載過，略過")
        return AlbumResult(zip_path=zip_path, title=title, item_count=total)

    completed, used_names = find_resume_point(zip_path, progress.get(album.share_url), total)

    if log:
        if completed:
            log(f"[{album.date_label}] {title}：從第 {completed + 1:03d}/{total:03d} 張接續下載")
        else:
            log(f"[{album.date_label}] {title}：{total} 個項目")

    try:
        mode = "a" if completed else "w"
        with zipfile.ZipFile(zip_path, mode, compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zip_file:
            for index in range(completed + 1, total + 1):
                media_url = media_urls[index - 1]
                raw_name = run_with_retries(
                    lambda: fetch_media_file(session, media_url, index, part_path),
                    f"  {index:03d}/{total:03d}",
                    log,
                )
                # 先完整下載到暫存檔，成功後才寫入 ZIP，避免留下不完整的項目
                safe_name = unique_name(sanitize_filename(raw_name), used_names)
                zip_file.write(part_path, arcname=safe_name)
                progress[album.share_url] = {"completed": index, "total": total}
                save_progress(output_dir, progress)
                if log:
                    log(f"  {index:03d}/{total:03d} {safe_name}")
    except Exception:
        done = progress.get(album.share_url, {}).get("completed", 0)
        if log:
            log(
                f"[{album.date_label}] 已記錄進度：第 {done}/{total} 張完成，"
                f"下次會從第 {done + 1} 張接續。"
            )
        raise
    finally:
        part_path.unlink(missing_ok=True)

    progress.pop(album.share_url, None)
    save_progress(output_dir, progress)
    return AlbumResult(zip_path=zip_path, title=title, item_count=total)


def download_albums(
    albums: list[AlbumInput],
    output_dir: Path,
    log: Callable[[str], None] | None = None,
) -> list[AlbumResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    progress = load_progress(output_dir)
    results: list[AlbumResult] = []
    started_at = time.time()
    with create_session() as session:
        for album in albums:
            results.append(download_album(session, album, output_dir, progress, log=log))
    if log:
        log(f"完成，共 {len(results)} 本相簿，耗時 {time.time() - started_at:.1f} 秒。")
    return results


def start_download_thread(
    albums: list[AlbumInput],
    output_dir: Path,
    on_log: Callable[[str], None],
    on_done: Callable[[list[AlbumResult]], None],
    on_error: Callable[[Exception], None],
) -> threading.Thread:
    def runner() -> None:
        try:
            results = download_albums(albums, output_dir, log=on_log)
        except Exception as exc:  # pragma: no cover - GUI callback path
            on_error(exc)
            return
        on_done(results)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return thread
