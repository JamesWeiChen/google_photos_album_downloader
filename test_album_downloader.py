import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import requests

import album_downloader
from album_downloader import AlbumInput, DownloadError, download_albums, parse_album_inputs


PAGE_HTML = (
    '<meta property="og:title" content="測試相簿 · 115/09/04 📸">'
    '["https://lh3.googleusercontent.com/item1",1,1]'
    '["https://lh3.googleusercontent.com/item2",1,1]'
    '["https://lh3.googleusercontent.com/item3",1,1]'
)
SHARE_URL = "https://photos.app.goo.gl/testAlbum"


class FakeResponse:
    def __init__(self, text: str = "", content: bytes = b"", filename: str | None = None) -> None:
        self.text = text
        self._content = content
        self.headers = {"content-disposition": f'attachment; filename="{filename}"'} if filename else {}
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self._content), 2):
            yield self._content[start : start + 2]

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        pass


class FakeSession:
    """Serves the album page and media files; `failures` maps a URL to errors raised before success."""

    def __init__(self, failures: dict[str, list[Exception]] | None = None) -> None:
        self.failures = failures or {}
        self.requested: list[str] = []

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.requested.append(url)
        base = url.removesuffix("=d")
        if url == SHARE_URL:
            return FakeResponse(text=PAGE_HTML)
        pending = self.failures.get(base)
        if pending:
            raise pending.pop(0)
        return FakeResponse(content=f"data-{base[-1]}".encode(), filename=f"{base[-5:]}.jpg")

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        pass


class ResumableDownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.tmp.name)
        self.albums = [AlbumInput(date_label="115.09.04", share_url=SHARE_URL)]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_retries_a_timeout_and_finishes_the_album(self) -> None:
        failing_url = "https://lh3.googleusercontent.com/item2"
        session = FakeSession({failing_url: [requests.ConnectionError("Read timed out")]})

        with mock.patch.object(album_downloader, "RETRY_WAIT_SECONDS", 0), \
                mock.patch.object(album_downloader, "create_session", return_value=session):
            results = download_albums(self.albums, self.output_dir)

        self.assertEqual(len(results), 1)
        with zipfile.ZipFile(results[0].zip_path) as zip_file:
            self.assertEqual(len(zip_file.namelist()), 3)
        self.assertFalse((self.output_dir / album_downloader.PROGRESS_FILE_NAME).exists())

    def test_stops_after_retries_and_resumes_from_the_recorded_item(self) -> None:
        failing_url = "https://lh3.googleusercontent.com/item2"
        always_failing = [requests.ConnectionError("Read timed out")] * 3
        logs: list[str] = []

        session = FakeSession({failing_url: always_failing})
        with mock.patch.object(album_downloader, "RETRY_WAIT_SECONDS", 0), \
                mock.patch.object(album_downloader, "MAX_RETRIES", 2), \
                mock.patch.object(album_downloader, "create_session", return_value=session):
            with self.assertRaises(requests.ConnectionError):
                download_albums(self.albums, self.output_dir, log=logs.append)

        progress = album_downloader.load_progress(self.output_dir)
        self.assertEqual(progress[SHARE_URL], {"completed": 1, "total": 3})
        self.assertTrue(any("已記錄進度：第 1/3 張完成" in line for line in logs))

        # Second run (e.g. after the user restarts the program) picks up at item 2.
        resumed_session = FakeSession()
        with mock.patch.object(album_downloader, "create_session", return_value=resumed_session):
            results = download_albums(self.albums, self.output_dir)

        media_requests = [url for url in resumed_session.requested if url != SHARE_URL]
        self.assertEqual(
            media_requests,
            ["https://lh3.googleusercontent.com/item2=d", "https://lh3.googleusercontent.com/item3=d"],
        )
        with zipfile.ZipFile(results[0].zip_path) as zip_file:
            self.assertEqual(len(zip_file.namelist()), 3)
            self.assertEqual(zip_file.read(zip_file.namelist()[1]), b"data-2")
        self.assertFalse((self.output_dir / album_downloader.PROGRESS_FILE_NAME).exists())
        self.assertFalse(list(self.output_dir.glob("*.part")))

    def test_skips_an_album_that_is_already_complete(self) -> None:
        zip_path = self.output_dir / "測試相簿.zip"
        with zipfile.ZipFile(zip_path, "w") as complete:
            for name in ("a.jpg", "b.jpg", "c.jpg"):
                complete.writestr(name, b"done")
        session = FakeSession()

        with mock.patch.object(album_downloader, "create_session", return_value=session):
            results = download_albums(self.albums, self.output_dir)

        self.assertEqual(session.requested, [SHARE_URL])  # only the album page was requested
        self.assertEqual(results[0].zip_path, zip_path)
        with zipfile.ZipFile(zip_path) as zip_file:
            self.assertEqual(zip_file.namelist(), ["a.jpg", "b.jpg", "c.jpg"])

    def test_non_retryable_error_is_raised_immediately(self) -> None:
        failing_url = "https://lh3.googleusercontent.com/item1"
        not_found = requests.HTTPError("404")
        not_found.response = mock.Mock(status_code=404)
        session = FakeSession({failing_url: [not_found]})

        with mock.patch.object(album_downloader, "RETRY_WAIT_SECONDS", 0), \
                mock.patch.object(album_downloader, "create_session", return_value=session):
            with self.assertRaises(requests.HTTPError):
                download_albums(self.albums, self.output_dir)

        self.assertEqual(len(session.requested), 2)  # page + item1, no retry


class ParseAlbumInputsTests(unittest.TestCase):
    def test_parses_descriptions_multiline_markdown_and_missing_spaces(self) -> None:
        raw_text = """115/08/03 主題時間。英語融入。學習區時間。
[https://photos.app.goo.gl/albumOne](https://photos.app.goo.gl/albumOne)

115/08/20 操作時間。主題時間。[https://photos.app.goo.gl/albumTwo](https://photos.app.goo.gl/albumTwo)

115/08/26晨間操作。戶外運動時間。
https://photos.app.goo.gl/albumThree

115/8/27 戶外運動時間。英語融入。[https://photos.app.goo.gl/albumFour](https://photos.app.goo.gl/albumFour)
"""

        albums = parse_album_inputs(raw_text)

        self.assertEqual(
            [(album.date_label, album.share_url) for album in albums],
            [
                ("115.08.03", "https://photos.app.goo.gl/albumOne"),
                ("115.08.20", "https://photos.app.goo.gl/albumTwo"),
                ("115.08.26", "https://photos.app.goo.gl/albumThree"),
                ("115.8.27", "https://photos.app.goo.gl/albumFour"),
            ],
        )

    def test_keeps_support_for_compact_input(self) -> None:
        albums = parse_album_inputs(
            "3/9 https://photos.app.goo.gl/firstAlbum\n"
            "3-10 https://photos.app.goo.gl/secondAlbum"
        )

        self.assertEqual([album.date_label for album in albums], ["3.9", "3.10"])

    def test_reports_every_dated_block_without_a_link(self) -> None:
        with self.assertRaisesRegex(DownloadError, r"115\.08\.04"):
            parse_album_inputs(
                "115/08/03 活動。 https://photos.app.goo.gl/firstAlbum\n"
                "115/08/04 只有活動說明，沒有連結。"
            )

    def test_rejects_a_link_before_the_first_date(self) -> None:
        with self.assertRaisesRegex(DownloadError, "第一個相簿連結前找不到日期"):
            parse_album_inputs(
                "https://photos.app.goo.gl/orphanAlbum\n"
                "115/08/03 活動。 https://photos.app.goo.gl/datedAlbum"
            )


if __name__ == "__main__":
    unittest.main()
