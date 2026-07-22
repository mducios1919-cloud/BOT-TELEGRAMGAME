"""
NewOCR.com client — free web flow + official REST API.

Official REST API docs: https://www.newocr.com/api/
  Base: http://api.newocr.com/v1/   (HTTPS cert on api.newocr.com is broken)

Free website flow (no API key):
  1) POST multipart  /  {preview=1, userfile=<file>}  -> preview page + file id `u`
  2) POST form       /  {ocr=1, u, l2[]=eng, psm, r, x1,y1,x2,y2} -> #ocr-result text
"""

from __future__ import annotations

import os
import re
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional, Union

import requests
import urllib3
from requests.adapters import HTTPAdapter

# Windows OpenSSL / local MITM proxy often breaks cert chain.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WEB_BASE = "https://www.newocr.com"
API_BASE = "http://api.newocr.com/v1"  # HTTPS hostname cert mismatch

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class _InsecureHTTPAdapter(HTTPAdapter):
    """HTTPS adapter that never verifies certificates (SSL context level)."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        return super().proxy_manager_for(*args, **kwargs)


def _strip_broken_ca_env() -> None:
    """Bad CA env vars force verification against a broken bundle."""
    for key in (
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    ):
        if key in os.environ:
            os.environ.pop(key, None)


def _make_session(session: Optional[requests.Session] = None) -> requests.Session:
    _strip_broken_ca_env()
    s = session or requests.Session()
    s.verify = False
    adapter = _InsecureHTTPAdapter()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def _request(session: requests.Session, method: str, url: str, **kwargs):
    """Always pass verify=False so nothing re-enables cert checks."""
    kwargs.setdefault("verify", False)
    return session.request(method, url, **kwargs)


PathOrBytes = Union[str, Path, bytes]


class NewOcrError(RuntimeError):
    pass


@dataclass(slots=True)
class NewOcrResult:
    text: str
    file_id: Optional[str] = None
    raw_html: str = ""
    source: str = "web"  # web | api

    @property
    def clean(self) -> str:
        """Lowercase letters-only (handy for zefoy-style captchas)."""
        return re.sub(r"[^a-zA-Z]", "", self.text or "").lower()


def _read_bytes(image: PathOrBytes) -> tuple[bytes, str]:
    if isinstance(image, bytes):
        return image, "image.png"
    path = Path(image)
    return path.read_bytes(), path.name


class NewOcrWeb:
    """
    Free website OCR (no API key).

    Example:
        client = NewOcrWeb()
        result = client.ocr("captcha.png", lang="eng")
        print(result.text)   # e.g. shout
    """

    def __init__(
        self,
        base_url: str = WEB_BASE,
        user_agent: str = DEFAULT_UA,
        session: Optional[requests.Session] = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = _make_session(session)
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Referer": f"{self.base_url}/",
                "Origin": self.base_url,
            }
        )

    def ensure_session(self) -> None:
        _request(self.session, "GET", f"{self.base_url}/", timeout=self.timeout)

    def preview(self, image: PathOrBytes) -> dict:
        """
        Step 1: upload file for preview.

        Returns dict with file_id (u), crop box x1/y1/x2/y2, and preview html.
        """
        self.ensure_session()
        data, filename = _read_bytes(image)
        resp = _request(
            self.session,
            "POST",
            f"{self.base_url}/",
            data={"preview": "1"},
            files={"userfile": (filename, data, "application/octet-stream")},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        html = resp.text

        file_id = self._parse_file_id(html)
        if not file_id:
            raise NewOcrError("Preview succeeded but file id `u` not found")

        crop = {
            "x1": self._attr_value(html, "x1", "0"),
            "y1": self._attr_value(html, "y1", "0"),
            "x2": self._attr_value(html, "x2", "100"),
            "y2": self._attr_value(html, "y2", "100"),
        }
        return {"file_id": file_id, "crop": crop, "html": html}

    def recognize(
        self,
        file_id: str,
        *,
        lang: str = "eng",
        psm: str = "6",
        rotate: str = "0",
        x1: str = "0",
        y1: str = "0",
        x2: str = "100",
        y2: str = "100",
    ) -> NewOcrResult:
        """Step 2: run OCR on uploaded file id."""
        data = {
            "l3": "",
            "l2[]": lang,
            "r": rotate,
            "psm": psm,
            "u": file_id,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "ocr": "1",
        }
        resp = _request(
            self.session,
            "POST",
            f"{self.base_url}/",
            data=data,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        text = self._parse_result_text(resp.text)
        return NewOcrResult(text=text, file_id=file_id, raw_html=resp.text, source="web")

    def ocr(
        self,
        image: PathOrBytes,
        *,
        lang: str = "eng",
        psm: str = "6",
        rotate: str = "0",
    ) -> NewOcrResult:
        """Full free flow: preview upload + OCR."""
        prev = self.preview(image)
        crop = prev["crop"]
        return self.recognize(
            prev["file_id"],
            lang=lang,
            psm=psm,
            rotate=rotate,
            **crop,
        )

    @staticmethod
    def _parse_file_id(html: str) -> Optional[str]:
        # HTML sometimes has space: name ="u"
        m = re.search(
            r'name\s*=\s*["\']?u["\']?\s+value\s*=\s*["\']([a-f0-9]{32})["\']',
            html,
            re.I,
        )
        if m:
            return m.group(1)
        m = re.search(r'name\s*=\s*["\']u["\'][^>]*value\s*=\s*["\']([^"\']+)', html, re.I)
        return m.group(1) if m else None

    @staticmethod
    def _attr_value(html: str, field: str, default: str) -> str:
        m = re.search(
            rf'id=["\']{re.escape(field)}["\'][^>]*value=["\']([^"\']*)["\']',
            html,
            re.I,
        )
        if m:
            return m.group(1)
        m = re.search(
            rf'name=["\']{re.escape(field)}["\'][^>]*value=["\']([^"\']*)["\']',
            html,
            re.I,
        )
        return m.group(1) if m else default

    @staticmethod
    def _parse_result_text(html: str) -> str:
        m = re.search(
            r'<textarea[^>]*id=["\']ocr-result["\'][^>]*>([\s\S]*?)</textarea>',
            html,
            re.I,
        )
        if m:
            return m.group(1).strip()
        # fallback: first large textarea
        for m in re.finditer(r"<textarea[^>]*>([\s\S]*?)</textarea>", html, re.I):
            body = m.group(1).strip()
            if body:
                return body
        raise NewOcrError("OCR response missing #ocr-result text")


class NewOcrApi:
    """
    Official REST API (requires free API key from https://www.newocr.com/api/).

    Free tier: 20 pages. Use HTTP base URL — HTTPS cert for api.newocr.com is invalid.

    Example:
        api = NewOcrApi(api_key="YOUR_KEY")
        print(api.ocr("captcha.png").text)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = API_BASE,
        timeout: float = 60.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = _make_session(session)

    def key_status(self) -> dict:
        r = _request(
            self.session,
            "GET",
            f"{self.base_url}/key/status",
            params={"key": self.api_key},
            timeout=self.timeout,
        )
        return r.json()

    def upload(self, image: PathOrBytes) -> dict:
        data, filename = _read_bytes(image)
        r = _request(
            self.session,
            "POST",
            f"{self.base_url}/upload",
            params={"key": self.api_key},
            files={"file": (filename, data, "application/octet-stream")},
            headers={"Expect": ""},
            timeout=self.timeout,
        )
        payload = r.json()
        if payload.get("status") != "success":
            raise NewOcrError(f"Upload failed: {payload}")
        return payload["data"]

    def recognize(
        self,
        file_id: str,
        *,
        page: int = 1,
        lang: str = "eng",
        psm: int = 6,
        rotate: int = 0,
    ) -> NewOcrResult:
        r = _request(
            self.session,
            "GET",
            f"{self.base_url}/ocr",
            params={
                "key": self.api_key,
                "file_id": file_id,
                "page": page,
                "lang": lang,
                "psm": psm,
                "rotate": rotate,
            },
            timeout=self.timeout,
        )
        payload = r.json()
        if payload.get("status") != "success":
            raise NewOcrError(f"OCR failed: {payload}")
        text = (payload.get("data") or {}).get("text") or ""
        return NewOcrResult(text=text.strip(), file_id=file_id, source="api")

    def ocr(
        self,
        image: PathOrBytes,
        *,
        lang: str = "eng",
        psm: int = 6,
        rotate: int = 0,
    ) -> NewOcrResult:
        up = self.upload(image)
        file_id = up.get("file_id") or up.get("id")
        if not file_id:
            raise NewOcrError(f"Upload missing file_id: {up}")
        return self.recognize(file_id, lang=lang, psm=psm, rotate=rotate)


def ocr_newocr(
    image: PathOrBytes,
    *,
    api_key: Optional[str] = None,
    lang: str = "eng",
) -> NewOcrResult:
    if api_key:
        return NewOcrApi(api_key).ocr(image, lang=lang)
    return NewOcrWeb().ocr(image, lang=lang)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OCR via newocr.com")
    parser.add_argument("image")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--lang", default="eng")
    args = parser.parse_args()
    result = ocr_newocr(args.image, api_key=args.api_key, lang=args.lang)
    print(result.text)
