"""
Fetch the login captcha image from https://zefoy.com/

Flow (from site JS):
  1. GET /  -> establish PHPSESSID cookie
  2. GET /?getcapthca=<unix_ts>  -> JSON { md5(User-Agent): double_b64(path) }
  3. Decode path, GET image URL -> PNG bytes
"""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping, Optional
from urllib.parse import parse_qs, urlparse

import requests

DEFAULT_BASE_URL = "https://zefoy.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class ZefoyCaptchaError(RuntimeError):
    """Raised when captcha cannot be retrieved or decoded."""


@dataclass(slots=True)
class CaptchaResult:
    """One captcha challenge tied to a browser session."""

    image_bytes: bytes
    image_url: str
    image_path: str
    captcha_token: Optional[str]
    timestamp: Optional[str]
    session_id: Optional[str]
    user_agent: str
    user_agent_md5: str
    cookies: dict[str, str] = field(default_factory=dict)
    raw_payload: Mapping[str, Any] = field(default_factory=dict)
    # Double-base64 payload from ?getcapthca= (image path token stream)
    challenge_encoded: Optional[str] = None

    def save(self, path: str) -> str:
        """Write captcha PNG to disk and return the path."""
        with open(path, "wb") as f:
            f.write(self.image_bytes)
        return path

    @property
    def content_type(self) -> str:
        if self.image_bytes.startswith(b"\x89PNG"):
            return "image/png"
        if self.image_bytes[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        return "application/octet-stream"


class ZefoyCaptcha:
    """
    Session-aware captcha fetcher for zefoy.com.

    Example:
        client = ZefoyCaptcha()
        captcha = client.get()
        captcha.save("captcha.png")
        print(captcha.session_id, captcha.captcha_token)
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        session: Optional[requests.Session] = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.verify = False
        self.session.headers.update(self._default_headers())

    def _default_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{self.base_url}/",
            "Origin": self.base_url,
        }

    @property
    def user_agent_md5(self) -> str:
        return hashlib.md5(self.user_agent.encode("utf-8")).hexdigest()

    @property
    def cookies(self) -> dict[str, str]:
        return self.session.cookies.get_dict()

    @property
    def session_id(self) -> Optional[str]:
        return self.cookies.get("PHPSESSID")

    def ensure_session(self) -> str:
        """Hit homepage so PHPSESSID exists. Returns session id."""
        resp = self.session.get(f"{self.base_url}/", timeout=self.timeout)
        resp.raise_for_status()
        # Site JS sets zf/za cookies on load — mimic that for captcha submit.
        try:
            from .fingerprint import apply_session_guard_cookies

            apply_session_guard_cookies(self.session)
        except Exception:
            pass
        sid = self.session_id
        if not sid:
            raise ZefoyCaptchaError("No PHPSESSID cookie after loading homepage")
        return sid

    def fetch_challenge_payload(self, unix_ts: Optional[int] = None) -> dict[str, Any]:
        """
        Call captcha bootstrap endpoint.

        Site builds: GET /?getcapthca=<Math.floor(Date.now()/1000)>
        Response: { "<md5(userAgent)>": "<base64(base64(image_path))>" }
        """
        if not self.session_id:
            self.ensure_session()

        ts = int(time.time()) if unix_ts is None else int(unix_ts)
        url = f"{self.base_url}/?getcapthca={ts}"
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.base_url}/",
        }
        resp = self.session.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError as exc:
            raise ZefoyCaptchaError(
                f"Captcha endpoint did not return JSON (status={resp.status_code})"
            ) from exc
        if not isinstance(data, dict) or not data:
            raise ZefoyCaptchaError(f"Unexpected captcha payload: {data!r}")
        return data

    @staticmethod
    def decode_image_path(encoded: str) -> str:
        """Double base64-decode site payload into relative image path."""
        try:
            once = base64.b64decode(encoded, validate=False)
            twice = base64.b64decode(once, validate=False)
            path = twice.decode("utf-8").strip()
        except Exception as exc:  # noqa: BLE001
            raise ZefoyCaptchaError("Failed to decode captcha image path") from exc
        if not path.startswith("/"):
            path = "/" + path
        return path

    def resolve_encoded_value(self, payload: Mapping[str, Any]) -> str:
        """Pick the field keyed by md5(User-Agent), with single-key fallback."""
        key = self.user_agent_md5
        if key in payload:
            value = payload[key]
        elif len(payload) == 1:
            value = next(iter(payload.values()))
        else:
            raise ZefoyCaptchaError(
                f"Payload key {key} missing; keys={list(payload.keys())}"
            )
        if not isinstance(value, str) or not value:
            raise ZefoyCaptchaError("Captcha payload value is empty")
        return value

    def download_image(self, image_path: str) -> bytes:
        """Download captcha PNG for the current session."""
        if image_path.startswith("http://") or image_path.startswith("https://"):
            url = image_path
        else:
            url = f"{self.base_url}{image_path}"
        headers = {
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": f"{self.base_url}/",
        }
        resp = self.session.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        if not resp.content:
            raise ZefoyCaptchaError("Captcha image response is empty")
        return resp.content

    @staticmethod
    def parse_path_meta(image_path: str) -> tuple[Optional[str], Optional[str]]:
        """Extract _CAPTCHA token and t= timestamp from image path query."""
        parsed = urlparse(image_path)
        qs = parse_qs(parsed.query)
        token = (qs.get("_CAPTCHA") or qs.get("captcha") or [None])[0]
        ts = (qs.get("t") or [None])[0]
        return token, ts

    def get(self, *, refresh_session: bool = False) -> CaptchaResult:
        """
        Full captcha fetch: session -> challenge JSON -> image bytes.

        Args:
            refresh_session: force a new homepage hit even if cookie exists.
        """
        if refresh_session or not self.session_id:
            self.ensure_session()

        payload = self.fetch_challenge_payload()
        encoded = self.resolve_encoded_value(payload)
        image_path = self.decode_image_path(encoded)
        image_bytes = self.download_image(image_path)
        token, ts = self.parse_path_meta(image_path)
        image_url = (
            image_path
            if image_path.startswith("http")
            else f"{self.base_url}{image_path}"
        )

        return CaptchaResult(
            image_bytes=image_bytes,
            image_url=image_url,
            image_path=image_path,
            captcha_token=token,
            timestamp=ts,
            session_id=self.session_id,
            user_agent=self.user_agent,
            user_agent_md5=self.user_agent_md5,
            cookies=self.cookies,
            raw_payload=dict(payload),
            challenge_encoded=encoded,
        )

    def get_as_dict(self, *, refresh_session: bool = False) -> dict[str, Any]:
        """Same as get(), but return a JSON-serializable dict (image as base64)."""
        result = self.get(refresh_session=refresh_session)
        return {
            "session_id": result.session_id,
            "user_agent": result.user_agent,
            "user_agent_md5": result.user_agent_md5,
            "image_url": result.image_url,
            "image_path": result.image_path,
            "captcha_token": result.captcha_token,
            "timestamp": result.timestamp,
            "cookies": result.cookies,
            "content_type": result.content_type,
            "image_base64": base64.b64encode(result.image_bytes).decode("ascii"),
            "image_size": len(result.image_bytes),
        }

    def export_cookies(self) -> MutableMapping[str, str]:
        return dict(self.cookies)


def get_captcha(
    save_path: Optional[str] = None,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    base_url: str = DEFAULT_BASE_URL,
) -> CaptchaResult:
    """Convenience one-shot helper."""
    client = ZefoyCaptcha(base_url=base_url, user_agent=user_agent)
    result = client.get()
    if save_path:
        result.save(save_path)
    return result


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Get captcha image from zefoy.com")
    parser.add_argument(
        "-o",
        "--output",
        default="captcha.png",
        help="Path to save captcha image (default: captcha.png)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print metadata as JSON (image as base64)",
    )
    args = parser.parse_args()

    try:
        captcha = get_captcha(save_path=args.output)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if args.json:
        print(
            json.dumps(
                {
                    "session_id": captcha.session_id,
                    "image_path": captcha.image_path,
                    "image_url": captcha.image_url,
                    "captcha_token": captcha.captcha_token,
                    "timestamp": captcha.timestamp,
                    "saved_to": args.output,
                    "image_size": len(captcha.image_bytes),
                    "cookies": captcha.cookies,
                },
                indent=2,
            )
        )
    else:
        print(f"saved: {args.output}")
        print(f"session: {captcha.session_id}")
        print(f"token: {captcha.captcha_token}")
        print(f"path: {captcha.image_path}")
        print(f"bytes: {len(captcha.image_bytes)}")
