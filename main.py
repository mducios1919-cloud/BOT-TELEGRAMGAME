import os
import sys
import json
import time
import base64
import threading
import re
import random
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from string import ascii_letters, digits

# ==================== TẠO CẤU TRÚC THƯ MỤC ====================
def create_project_structure():
    """Tạo tất cả file và thư mục cần thiết"""
    
    # Tạo thư mục zefoy
    zefoy_dir = Path('zefoy')
    zefoy_dir.mkdir(exist_ok=True)
    
    # Tạo thư mục templates
    templates_dir = Path('templates')
    templates_dir.mkdir(exist_ok=True)
    
    # ====== zefoy/__init__.py ======
    init_file = zefoy_dir / '__init__.py'
    if not init_file.exists():
        with open(init_file, 'w') as f:
            f.write('''"""Zefoy client helpers."""

from .captcha import CaptchaResult, ZefoyCaptcha, ZefoyCaptchaError, get_captcha
from .newocr import NewOcrApi, NewOcrError, NewOcrResult, NewOcrWeb, ocr_newocr
from .ocr import make_newocr_api_solver, solve_newocr
from .services import (
    ServiceInfo,
    format_services_table,
    parse_services,
    print_services_table,
)
from .submit import SubmitResult, ZefoyClient, ZefoySubmitError, submit_captcha

__all__ = [
    "CaptchaResult",
    "ZefoyCaptcha",
    "ZefoyCaptchaError",
    "get_captcha",
    "SubmitResult",
    "ZefoyClient",
    "ZefoySubmitError",
    "submit_captcha",
    "NewOcrWeb",
    "NewOcrApi",
    "NewOcrResult",
    "NewOcrError",
    "ocr_newocr",
    "solve_newocr",
    "make_newocr_api_solver",
    "ServiceInfo",
    "parse_services",
    "format_services_table",
    "print_services_table",
]
__version__ = "0.4.0"
''')
    
    # ====== zefoy/captcha.py ======
    captcha_file = zefoy_dir / 'captcha.py'
    if not captcha_file.exists():
        with open(captcha_file, 'w') as f:
            f.write('''"""
Fetch the login captcha image from https://zefoy.com/
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
    pass


@dataclass(slots=True)
class CaptchaResult:
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
    challenge_encoded: Optional[str] = None

    def save(self, path: str) -> str:
        with open(path, "wb") as f:
            f.write(self.image_bytes)
        return path

    @property
    def content_type(self) -> str:
        if self.image_bytes.startswith(b"\\x89PNG"):
            return "image/png"
        if self.image_bytes[:3] == b"\\xff\\xd8\\xff":
            return "image/jpeg"
        return "application/octet-stream"


class ZefoyCaptcha:
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
        resp = self.session.get(f"{self.base_url}/", timeout=self.timeout)
        resp.raise_for_status()
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
            raise ZefoyCaptchaError(f"Captcha endpoint did not return JSON") from exc
        if not isinstance(data, dict) or not data:
            raise ZefoyCaptchaError(f"Unexpected captcha payload: {data!r}")
        return data

    @staticmethod
    def decode_image_path(encoded: str) -> str:
        try:
            once = base64.b64decode(encoded, validate=False)
            twice = base64.b64decode(once, validate=False)
            path = twice.decode("utf-8").strip()
        except Exception as exc:
            raise ZefoyCaptchaError("Failed to decode captcha image path") from exc
        if not path.startswith("/"):
            path = "/" + path
        return path

    def resolve_encoded_value(self, payload: Mapping[str, Any]) -> str:
        key = self.user_agent_md5
        if key in payload:
            value = payload[key]
        elif len(payload) == 1:
            value = next(iter(payload.values()))
        else:
            raise ZefoyCaptchaError(f"Payload key {key} missing")
        if not isinstance(value, str) or not value:
            raise ZefoyCaptchaError("Captcha payload value is empty")
        return value

    def download_image(self, image_path: str) -> bytes:
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
        parsed = urlparse(image_path)
        qs = parse_qs(parsed.query)
        token = (qs.get("_CAPTCHA") or qs.get("captcha") or [None])[0]
        ts = (qs.get("t") or [None])[0]
        return token, ts

    def get(self, *, refresh_session: bool = False) -> CaptchaResult:
        if refresh_session or not self.session_id:
            self.ensure_session()
        payload = self.fetch_challenge_payload()
        encoded = self.resolve_encoded_value(payload)
        image_path = self.decode_image_path(encoded)
        image_bytes = self.download_image(image_path)
        token, ts = self.parse_path_meta(image_path)
        image_url = image_path if image_path.startswith("http") else f"{self.base_url}{image_path}"
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
''')
    
    # ====== zefoy/crypto_util.py ======
    crypto_file = zefoy_dir / 'crypto_util.py'
    if not crypto_file.exists():
        with open(crypto_file, 'w') as f:
            f.write('''from __future__ import annotations
import base64
import hashlib
import json
import os
from typing import Any, Mapping, Union
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

AES_PASSPHRASE = "43fdda1192dde7f8ffff7161e13580d7"

def evp_bytes_to_key(password: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16) -> tuple[bytes, bytes]:
    derived = b""
    block = b""
    while len(derived) < key_len + iv_len:
        block = hashlib.md5(block + password + salt).digest()
        derived += block
    return derived[:key_len], derived[key_len:key_len + iv_len]

def encrypt_cryptojs_json(plaintext: Union[str, Mapping[str, Any]], passphrase: str = AES_PASSPHRASE) -> str:
    if not isinstance(plaintext, str):
        plaintext = json.dumps(plaintext, separators=(",", ":"), ensure_ascii=False)
    salt = os.urandom(8)
    key, iv = evp_bytes_to_key(passphrase.encode("utf-8"), salt)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    payload = {
        "ct": base64.b64encode(ciphertext).decode("ascii"),
        "iv": iv.hex(),
        "s": salt.hex(),
    }
    return json.dumps(payload, separators=(",", ":"))

def decrypt_cryptojs_json(blob: Union[str, Mapping[str, Any]], passphrase: str = AES_PASSPHRASE) -> str:
    data = json.loads(blob) if isinstance(blob, str) else dict(blob)
    ct = base64.b64decode(data["ct"])
    salt = bytes.fromhex(data["s"])
    key, iv_kdf = evp_bytes_to_key(passphrase.encode("utf-8"), salt)
    candidates = [iv_kdf]
    if data.get("iv"):
        candidates.append(bytes.fromhex(data["iv"]))
    for iv in candidates:
        try:
            cipher = AES.new(key, AES.MODE_CBC, iv)
            return unpad(cipher.decrypt(ct), AES.block_size).decode("utf-8")
        except Exception:
            pass
    raise ValueError("Failed to decrypt captcha_encoded")
''')
    
    # ====== zefoy/fingerprint.py ======
    fingerprint_file = zefoy_dir / 'fingerprint.py'
    if not fingerprint_file.exists():
        with open(fingerprint_file, 'w') as f:
            f.write('''from __future__ import annotations
import hashlib
import time
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo
from .crypto_util import encrypt_cryptojs_json

def browser_guard_cookies() -> dict[str, str]:
    zf = hashlib.md5(str(int(time.time() * 1000)).encode("utf-8")).hexdigest()
    return {"zf": zf, "za": "200"}

def build_device_fingerprint(
    user_agent: str,
    *,
    timezone: str = "Asia/Saigon",
    locale: str = "en-US",
    screen_width: int = 1920,
    screen_height: int = 1080,
    cpu_cores: int = 8,
    device_memory_gb: int = 8,
    language: Optional[str] = None,
) -> dict[str, Any]:
    language = language or locale.split("-")[0]
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        offset_min = -int(now.utcoffset().total_seconds() // 60)
        locale_dt = now.strftime("%H:%M:%S %d/%m/%Y")
    except Exception:
        now = datetime.utcnow()
        offset_min = 0
        locale_dt = now.strftime("%H:%M:%S %d/%m/%Y")
    unix = int(time.time())
    app_version = user_agent.replace("Mozilla/", "") if user_agent.startswith("Mozilla/") else user_agent
    return {
        "deviceInfo": {
            "cpuCores": cpu_cores,
            "cpuLoad": "Skipped",
            "deviceMemoryGB": device_memory_gb,
            "platform": "Win32",
            "maxTouchPoints": 0,
            "msMaxTouchPoints": "Not Supported",
            "gpu": {
                "vendor": "Google Inc. (NVIDIA)",
                "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0, D3D11)",
            },
            "battery": "Not Supported",
            "stylusDetection": "No",
            "touchSupport": "No",
        },
        "browserInfo": {
            "userAgent": user_agent,
            "timezone": timezone,
            "timezoneOffset": offset_min,
            "localeDateTime": locale_dt,
            "localUnixTime": unix,
            "calendar": "gregory",
            "day": "numeric",
            "locale": language,
            "month": "numeric",
            "numberingSystem": "latn",
            "year": "numeric",
            "appName": "Netscape",
            "appVersion": app_version,
            "vendor": "Google Inc.",
            "language": language,
            "languages": [language],
            "cookieEnabled": True,
            "onlineStatus": "Online",
            "javaEnabled": False,
            "doNotTrack": "Not Supported",
            "referrerHeader": "None",
            "httpsConnection": "Yes",
            "historyLength": 2,
            "mimeTypes": 2,
            "plugins": 5,
            "webdriver": False,
            "pageVisibility": "visible",
            "isBot": "No",
            "featuresSupported": {
                "geolocation": "Yes",
                "serviceWorker": "Yes",
                "localStorage": "Yes",
                "sessionStorage": "Yes",
                "indexedDB": "Yes",
                "notifications": "Yes",
                "notificationsFirebase": "default",
                "clipboard": "Yes",
                "pushAPI": "Yes",
                "webRTC": "Yes",
                "gamepadAPI": "Yes",
                "speechSynthesis": "Yes",
                "webGL": "Yes",
                "vibrationAPI": "Yes",
                "deviceMotion": "Yes",
                "deviceOrientation": "Yes",
                "wakeLock": "Yes",
                "serial": "Yes",
                "usb": "Yes",
                "networkInformation": "Yes",
                "screenCapture": "Yes",
                "fullscreenAPI": "Yes",
                "pictureInPicture": "Yes",
            },
        },
        "screenInfo": {
            "width": screen_width,
            "height": screen_height,
            "colorDepth": 24,
            "pixelDepth": 24,
            "devicePixelRatio": 1,
            "orientation": "landscape-primary",
            "screenOrientationAngle": 0,
            "availableWidth": screen_width,
            "availableHeight": screen_height - 40,
            "screenLeft": 0,
            "screenTop": 0,
            "outerWidth": screen_width,
            "outerHeight": screen_height,
            "innerWidth": screen_width,
            "innerHeight": screen_height - 120,
        },
        "otherData": {
            "mouseAvailable": "Yes",
            "keyboardAvailable": "Yes",
            "bluetoothSupport": "Yes",
            "usbSupport": "Yes",
            "gamepadSupport": "Yes",
            "incognitoMode": "No",
        },
        "storageInfo": {
            "localStorage": "Yes",
            "sessionStorage": "Yes",
            "indexedDB": "Yes",
            "cacheStorage": "Yes",
            "storageEstimate": "Not Supported",
        },
    }

def build_captcha_encoded(user_agent: str, **fingerprint_kwargs: Any) -> str:
    fp = build_device_fingerprint(user_agent, **fingerprint_kwargs)
    return encrypt_cryptojs_json(fp)

def apply_session_guard_cookies(session: Any, *, domain: str = "zefoy.com") -> dict[str, str]:
    cookies = browser_guard_cookies()
    for name, value in cookies.items():
        session.cookies.set(name, value, path="/")
        try:
            session.cookies.set(name, value, domain=domain, path="/")
        except Exception:
            pass
    return cookies
''')
    
    # ====== zefoy/newocr.py ======
    newocr_file = zefoy_dir / 'newocr.py'
    if not newocr_file.exists():
        with open(newocr_file, 'w') as f:
            f.write('''from __future__ import annotations
import os
import re
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional, Union
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WEB_BASE = "https://www.newocr.com"
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

class _InsecureHTTPAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

def _make_session(session: Optional[requests.Session] = None) -> requests.Session:
    s = session or requests.Session()
    s.verify = False
    adapter = _InsecureHTTPAdapter()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

PathOrBytes = Union[str, Path, bytes]

class NewOcrError(RuntimeError):
    pass

@dataclass(slots=True)
class NewOcrResult:
    text: str
    file_id: Optional[str] = None
    raw_html: str = ""
    source: str = "web"

class NewOcrWeb:
    def __init__(self, base_url: str = WEB_BASE, user_agent: str = DEFAULT_UA, session: Optional[requests.Session] = None, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = _make_session(session)
        self.session.headers.update({"User-Agent": user_agent, "Referer": f"{self.base_url}/", "Origin": self.base_url})

    def ocr(self, image: PathOrBytes, *, lang: str = "eng", psm: str = "6") -> NewOcrResult:
        if isinstance(image, bytes):
            data = image
            filename = "image.png"
        else:
            path = Path(image)
            data = path.read_bytes()
            filename = path.name
        self.session.get(self.base_url, timeout=self.timeout)
        resp = self.session.post(
            self.base_url,
            data={"preview": "1"},
            files={"userfile": (filename, data, "application/octet-stream")},
            timeout=self.timeout
        )
        resp.raise_for_status()
        html = resp.text
        m = re.search(r'name\\s*=\\s*["\\']?u["\\']?\\s+value\\s*=\\s*["\\']([a-f0-9]{32})["\\']', html, re.I)
        if m:
            file_id = m.group(1)
        else:
            m = re.search(r'name\\s*=\\s*["\\']u["\\'][^>]*value\\s*=\\s*["\\']([^"\\']+)', html, re.I)
            file_id = m.group(1) if m else None
        if not file_id:
            raise NewOcrError("File id not found")
        data = {"l3": "", "l2[]": lang, "r": "0", "psm": psm, "u": file_id, "x1": "0", "y1": "0", "x2": "100", "y2": "100", "ocr": "1"}
        resp = self.session.post(self.base_url, data=data, timeout=self.timeout)
        resp.raise_for_status()
        m = re.search(r'<textarea[^>]*id=["\\']ocr-result["\\'][^>]*>([\\s\\S]*?)</textarea>', resp.text, re.I)
        text = m.group(1).strip() if m else ""
        return NewOcrResult(text=text, file_id=file_id, raw_html=resp.text, source="web")
''')
    
    # ====== zefoy/ocr.py ======
    ocr_file = zefoy_dir / 'ocr.py'
    if not ocr_file.exists():
        with open(ocr_file, 'w') as f:
            f.write('''from __future__ import annotations
import re
from typing import Callable, Optional
from .newocr import NewOcrWeb

SolverFn = Callable[[bytes], str]

class OcrError(RuntimeError):
    pass

def _letters_only(text: str) -> str:
    return re.sub(r"[^a-zA-Z]", "", text or "").lower()

def solve_newocr(image_bytes: bytes) -> str:
    try:
        result = NewOcrWeb().ocr(image_bytes, lang="eng", psm="6")
    except Exception as exc:
        raise OcrError(f"NewOCR failed: {exc}")
    text = _letters_only(result.text)
    if not text:
        raise OcrError("NewOCR returned empty text")
    return text

def solve_image(image_bytes: bytes) -> str:
    try:
        return solve_newocr(image_bytes)
    except Exception:
        raise OcrError("OCR failed")
''')
    
    # ====== zefoy/services.py ======
    services_file = zefoy_dir / 'services.py'
    if not services_file.exists():
        with open(services_file, 'w') as f:
            f.write('''from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Optional
from bs4 import BeautifulSoup

@dataclass(slots=True)
class ServiceInfo:
    title: str
    status: str
    available: bool
    action: Optional[str] = None
    input_name: Optional[str] = None
    raw_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "status": self.status,
            "available": self.available,
            "action": self.action,
            "input_name": self.input_name,
            "raw_status": self.raw_status,
        }

def _normalize_status(raw: str) -> tuple[str, bool]:
    text = re.sub(r"\\s+", " ", (raw or "").strip())
    low = text.lower()
    if not text:
        return ("Unknown", False)
    if "soon" in low or "will be update" in low or "coming" in low:
        return ("Offline / Updating", False)
    if "update" in low or "online" in low or "active" in low or "days ago" in low or "hours ago" in low:
        return (f"Online · {text}", True)
    if "disable" in low or "off" in low or "maintenance" in low:
        return (f"Disabled · {text}", False)
    return (text, True)

def parse_services(html: str) -> list[ServiceInfo]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    by_title: dict[str, ServiceInfo] = {}
    for card in soup.select("div.card"):
        title_el = card.select_one("h5, h6, .card-title, .toptitle")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue
        status_el = card.select_one("p.card-text, .card-text, p")
        raw_status = status_el.get_text(" ", strip=True) if status_el else ""
        if raw_status.lower() in ("search", "search."):
            raw_status = ""
        form = card.select_one("form")
        action = form.get("action") if form else None
        inp = None
        if form:
            inp = form.select_one("input[type=text], input.form-control, input:not([type=hidden])")
        input_name = inp.get("name") if inp else None
        if raw_status:
            display, available = _normalize_status(raw_status)
        elif action:
            display, available = ("Online", True)
        else:
            display, available = ("Unknown", False)
        existing = by_title.get(title)
        if existing is None:
            by_title[title] = ServiceInfo(
                title=title,
                status=display,
                available=available,
                action=action,
                input_name=input_name,
                raw_status=raw_status,
            )
        else:
            if raw_status:
                existing.raw_status = raw_status
                existing.status, existing.available = _normalize_status(raw_status)
            if action:
                existing.action = action
            if input_name:
                existing.input_name = input_name
    return list(by_title.values())
''')
    
    # ====== zefoy/submit.py ======
    submit_file = zefoy_dir / 'submit.py'
    if not submit_file.exists():
        with open(submit_file, 'w') as f:
            f.write('''from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
import requests
from .captcha import DEFAULT_BASE_URL, DEFAULT_USER_AGENT, CaptchaResult, ZefoyCaptcha
from .fingerprint import apply_session_guard_cookies, build_captcha_encoded
from .ocr import SolverFn, solve_image
from .services import ServiceInfo, parse_services

Solver = SolverFn

class ZefoySubmitError(RuntimeError):
    pass

@dataclass(slots=True)
class SubmitResult:
    success: bool
    answer: str
    status_code: int
    html: str
    session_id: Optional[str]
    cookies: dict[str, str] = field(default_factory=dict)
    services: list[ServiceInfo] = field(default_factory=list)
    message: str = ""
    captcha: Optional[CaptchaResult] = None
    attempts: int = 1
    xhr_body: str = ""

    def services_as_dicts(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.services]

def is_captcha_page(html: str) -> bool:
    if not html or html.strip().lower() == "success":
        return False
    return 'name="captchalogin"' in html or "name='captchalogin'" in html or "captcha-login-input" in html or 'id="captcha-img"' in html

def normalize_answer(answer: str) -> str:
    return re.sub(r"[^a-z]", "", (answer or "").lower())

class ZefoyClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, user_agent: str = DEFAULT_USER_AGENT, session: Optional[requests.Session] = None, timeout: float = 30.0, solver: Optional[Solver] = None):
        self.captcha_client = ZefoyCaptcha(base_url=base_url, user_agent=user_agent, session=session, timeout=timeout)
        self.solver = solver or solve_image
        self.timeout = timeout
        self._last_captcha: Optional[CaptchaResult] = None
        self._last_encoded: Optional[str] = None

    @property
    def session(self) -> requests.Session:
        return self.captcha_client.session

    @property
    def user_agent(self) -> str:
        return self.captcha_client.user_agent

    @property
    def base_url(self) -> str:
        return self.captcha_client.base_url

    @property
    def session_id(self) -> Optional[str]:
        return self.captcha_client.session_id

    def get_captcha(self) -> CaptchaResult:
        captcha = self.captcha_client.get(refresh_session=not self.session_id)
        apply_session_guard_cookies(self.session)
        self._last_encoded = build_captcha_encoded(self.user_agent)
        self._last_captcha = captcha
        return captcha

    def submit_answer(self, answer: str, captcha_encoded: Optional[str] = None, captcha: Optional[CaptchaResult] = None) -> SubmitResult:
        answer = normalize_answer(answer)
        if not answer:
            raise ZefoySubmitError("Empty captcha answer")
        if not self.session_id:
            self.captcha_client.ensure_session()
        apply_session_guard_cookies(self.session)
        encoded = captcha_encoded or self._last_encoded or build_captcha_encoded(self.user_agent)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "Accept": "*/*",
        }
        data = {"captchalogin": answer, "captcha_encoded": encoded}
        resp = self.session.post(f"{self.base_url}/", data=data, headers=headers, timeout=self.timeout, allow_redirects=False)
        xhr_body = (resp.text or "").strip()
        xhr_ok = resp.status_code == 200 and xhr_body.lower() == "success"
        html = ""
        services: list[ServiceInfo] = []
        if xhr_ok:
            follow = self.session.get(f"{self.base_url}/", timeout=self.timeout)
            html = follow.text or ""
            success = not is_captcha_page(html)
            if success:
                services = parse_services(html)
            message = "ok" if success else "XHR success but panel still looks like captcha"
        else:
            html = resp.text or ""
            success = False
            message = f"captcha rejected (xhr_body={xhr_body[:80]!r})"
        return SubmitResult(
            success=success,
            answer=answer,
            status_code=resp.status_code,
            html=html,
            session_id=self.session_id,
            cookies=self.captcha_client.cookies,
            services=services,
            message=message,
            captcha=captcha or self._last_captcha,
            attempts=1,
            xhr_body=xhr_body,
        )

    def solve_and_submit(self, max_attempts: int = 5) -> SubmitResult:
        last: Optional[SubmitResult] = None
        for attempt in range(1, max_attempts + 1):
            captcha = self.get_captcha()
            try:
                answer = self.solver(captcha.image_bytes)
            except Exception as exc:
                last = SubmitResult(
                    success=False,
                    answer="",
                    status_code=0,
                    html="",
                    session_id=self.session_id,
                    cookies=self.captcha_client.cookies,
                    message=f"OCR failed: {exc}",
                    captcha=captcha,
                    attempts=attempt,
                )
                continue
            result = self.submit_answer(answer, captcha_encoded=self._last_encoded, captcha=captcha)
            result.attempts = attempt
            last = result
            if result.success:
                return result
        if last is None:
            raise ZefoySubmitError("No captcha attempts were made")
        last.message = f"Failed after {max_attempts} attempts ({last.message})"
        return last
''')
    
    # ====== templates/index.html ======
    index_file = templates_dir / 'index.html'
    if not index_file.exists():
        with open(index_file, 'w') as f:
            f.write('''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zefoy API - Tool Tăng Tương Tác TikTok</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; min-height: 100vh; }
        .navbar { background: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .form-control, .form-select { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; }
        .form-control:focus, .form-select:focus { background: #0d1117; border-color: #58a6ff; color: #c9d1d9; box-shadow: 0 0 0 3px rgba(88,166,255,0.2); }
        .btn-primary { background: #238636; border: none; }
        .btn-primary:hover { background: #2ea043; }
        .btn-secondary { background: #21262d; border: 1px solid #30363d; }
        .btn-secondary:hover { background: #30363d; }
        .text-muted { color: #8b949e !important; }
        .bg-dark-card { background: #0d1117; }
        .captcha-img { border-radius: 8px; border: 1px solid #30363d; max-width: 100%; }
        .log-area { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 12px; max-height: 200px; overflow-y: auto; font-family: monospace; font-size: 13px; color: #8b949e; }
        .log-area .log-success { color: #3fb950; }
        .log-area .log-error { color: #f85149; }
        .log-area .log-info { color: #58a6ff; }
        .service-badge { background: #21262d; padding: 4px 12px; border-radius: 20px; font-size: 12px; cursor: pointer; border: 1px solid #30363d; display: inline-block; margin: 2px; }
        .service-badge:hover { border-color: #58a6ff; }
        .service-badge.active { background: #238636; border-color: #238636; color: #fff; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg sticky-top">
        <div class="container">
            <a class="navbar-brand text-white fw-bold" href="/">
                <i class="bi bi-rocket-takeoff"></i> Zefoy API
            </a>
            <div class="ms-auto">
                <span class="text-muted small">v1.0</span>
                <a href="/admin" class="btn btn-secondary btn-sm ms-2">
                    <i class="bi bi-shield-lock"></i> Admin
                </a>
            </div>
        </div>
    </nav>

    <div class="container py-4">
        <div class="row">
            <div class="col-lg-8 mx-auto">
                <div class="text-center mb-4">
                    <h1 class="display-5 fw-bold">🚀 Tool Tăng Tương Tác TikTok</h1>
                    <p class="text-muted">Hỗ trợ: Comments Hearts, Views, Followers, Shares và nhiều hơn</p>
                </div>

                <div class="card mb-3">
                    <div class="card-body">
                        <div class="row g-3">
                            <div class="col-md-8">
                                <label class="form-label small text-muted">Link video TikTok</label>
                                <div class="input-group">
                                    <span class="input-group-text bg-dark-card border-secondary"><i class="bi bi-link-45deg"></i></span>
                                    <input type="text" class="form-control" id="videoLink" placeholder="https://www.tiktok.com/@user/video/123456789">
                                </div>
                            </div>
                            <div class="col-md-4">
                                <label class="form-label small text-muted">Chọn dịch vụ</label>
                                <select class="form-select" id="serviceSelect">
                                    <option value="Comments Hearts">💬 Comments Hearts</option>
                                    <option value="Views">👁️ Views</option>
                                    <option value="Hearts">❤️ Hearts</option>
                                    <option value="Followers">👥 Followers</option>
                                    <option value="Shares">🔄 Shares</option>
                                    <option value="Favorites">⭐ Favorites</option>
                                    <option value="Live Stream">🔴 Live Stream</option>
                                    <option value="Repost">🔄 Repost</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card mb-3">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <span><i class="bi bi-shield-check"></i> Xác thực Captcha</span>
                        <button class="btn btn-secondary btn-sm" id="refreshCaptcha">
                            <i class="bi bi-arrow-clockwise"></i> Làm mới
                        </button>
                    </div>
                    <div class="card-body">
                        <div class="row align-items-center">
                            <div class="col-md-4 text-center">
                                <img id="captchaImg" class="captcha-img" src="" alt="Captcha" style="max-height: 120px;">
                                <div id="captchaStatus" class="mt-2 small text-muted">Chưa tải captcha</div>
                            </div>
                            <div class="col-md-8">
                                <div class="input-group">
                                    <input type="text" class="form-control" id="captchaAnswer" placeholder="Nhập captcha">
                                    <button class="btn btn-primary" id="solveCaptcha">
                                        <i class="bi bi-check2-circle"></i> Giải
                                    </button>
                                </div>
                                <div class="mt-2">
                                    <button class="btn btn-secondary btn-sm" id="autoSolve">
                                        <i class="bi bi-magic"></i> Auto Solve
                                    </button>
                                    <span class="text-muted ms-2 small">(sử dụng OCR)</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card mb-3">
                    <div class="card-header">
                        <i class="bi bi-terminal"></i> Log
                    </div>
                    <div class="card-body">
                        <div id="logArea" class="log-area">
                            <div class="log-info">🔹 Chờ thực hiện...</div>
                        </div>
                    </div>
                </div>

                <button class="btn btn-primary w-100 btn-lg" id="submitBtn">
                    <i class="bi bi-play-circle"></i> Bắt đầu
                </button>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let currentSessionId = null;
        let isProcessing = false;

        function log(message, type = 'info') {
            const area = document.getElementById('logArea');
            const div = document.createElement('div');
            div.className = `log-${type}`;
            const time = new Date().toLocaleTimeString();
            div.textContent = `[${time}] ${message}`;
            area.appendChild(div);
            area.scrollTop = area.scrollHeight;
        }

        async function refreshCaptcha() {
            try {
                log('Đang tải captcha...', 'info');
                const resp = await fetch('/api/captcha');
                const data = await resp.json();
                if (data.success) {
                    currentSessionId = data.session_id;
                    document.getElementById('captchaImg').src = `data:image/png;base64,${data.image}`;
                    document.getElementById('captchaStatus').textContent = '✅ Captcha đã tải';
                    document.getElementById('captchaAnswer').value = '';
                    log('Captcha đã tải thành công', 'success');
                } else {
                    log('Lỗi tải captcha: ' + data.error, 'error');
                }
            } catch(e) {
                log('Lỗi tải captcha: ' + e.message, 'error');
            }
        }

        async function autoSolve() {
            if (!currentSessionId) {
                await refreshCaptcha();
            }
            try {
                log('Đang auto solve captcha...', 'info');
                const resp = await fetch('/api/solve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        link: document.getElementById('videoLink').value || 'https://www.tiktok.com/@test/video/123456789',
                        service: document.getElementById('serviceSelect').value,
                        session_id: currentSessionId
                    })
                });
                const data = await resp.json();
                if (data.success) {
                    document.getElementById('captchaAnswer').value = data.answer || '';
                    log(`✅ Auto solve thành công: ${data.answer}`, 'success');
                } else {
                    log('❌ Auto solve thất bại: ' + data.error, 'error');
                }
            } catch(e) {
                log('Lỗi auto solve: ' + e.message, 'error');
            }
        }

        async function submit() {
            if (isProcessing) return;
            isProcessing = true;
            const btn = document.getElementById('submitBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Đang xử lý...';

            try {
                const link = document.getElementById('videoLink').value.trim();
                const service = document.getElementById('serviceSelect').value;
                const answer = document.getElementById('captchaAnswer').value.trim();

                if (!link) {
                    log('⚠️ Vui lòng nhập link video', 'error');
                    return;
                }

                if (!currentSessionId) {
                    await refreshCaptcha();
                }

                if (!answer) {
                    log('Đang giải captcha tự động...', 'info');
                    const solveResp = await fetch('/api/solve', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            link: link,
                            service: service,
                            session_id: currentSessionId
                        })
                    });
                    const solveData = await solveResp.json();
                    if (!solveData.success) {
                        log('❌ Giải captcha thất bại: ' + solveData.error, 'error');
                        return;
                    }
                    document.getElementById('captchaAnswer').value = solveData.answer || '';
                    log(`✅ Captcha: ${solveData.answer}`, 'success');
                }

                log(`🚀 Đang gửi ${service} cho video...`, 'info');
                const resp = await fetch('/api/submit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        link: link,
                        service: service,
                        session_id: currentSessionId
                    })
                });
                const data = await resp.json();
                if (data.success) {
                    log(`✅ ${data.message || 'Đã gửi thành công!'}`, 'success');
                } else {
                    log('❌ Lỗi: ' + (data.message || data.error || 'Không xác định'), 'error');
                }

            } catch(e) {
                log('❌ Lỗi: ' + e.message, 'error');
            } finally {
                isProcessing = false;
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-play-circle"></i> Bắt đầu';
            }
        }

        document.getElementById('refreshCaptcha').addEventListener('click', refreshCaptcha);
        document.getElementById('autoSolve').addEventListener('click', autoSolve);
        document.getElementById('submitBtn').addEventListener('click', submit);

        document.getElementById('captchaAnswer').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') submit();
        });
        document.getElementById('videoLink').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') submit();
        });

        window.onload = function() {
            refreshCaptcha();
            log('🚀 Zefoy API đã sẵn sàng', 'success');
        };
    </script>
</body>
</html>''')
    
    # ====== templates/admin_login.html ======
    admin_login_file = templates_dir / 'admin_login.html'
    if not admin_login_file.exists():
        with open(admin_login_file, 'w') as f:
            f.write('''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Đăng nhập Admin - Zefoy API</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; min-height: 100vh; display: flex; align-items: center; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .form-control { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; }
        .form-control:focus { background: #0d1117; border-color: #58a6ff; color: #c9d1d9; box-shadow: 0 0 0 3px rgba(88,166,255,0.2); }
        .btn-primary { background: #238636; border: none; }
        .btn-primary:hover { background: #2ea043; }
        .alert-danger { background: #0d1117; border-color: #f85149; color: #f85149; }
    </style>
</head>
<body>
    <div class="container">
        <div class="row justify-content-center">
            <div class="col-md-4">
                <div class="card">
                    <div class="card-header text-center">
                        <h4><i class="bi bi-shield-lock"></i> Admin Login</h4>
                    </div>
                    <div class="card-body">
                        {% if error %}
                        <div class="alert alert-danger">{{ error }}</div>
                        {% endif %}
                        <form method="POST">
                            <div class="mb-3">
                                <label class="form-label small text-muted">Username</label>
                                <input type="text" name="username" class="form-control" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label small text-muted">Password</label>
                                <input type="password" name="password" class="form-control" required>
                            </div>
                            <button type="submit" class="btn btn-primary w-100">Đăng nhập</button>
                        </form>
                        <div class="text-center mt-3">
                            <a href="/" class="text-muted small">← Quay lại</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
</body>
</html>''')
    
    # ====== templates/admin_dashboard.html ======
    admin_dashboard_file = templates_dir / 'admin_dashboard.html'
    if not admin_dashboard_file.exists():
        with open(admin_dashboard_file, 'w') as f:
            f.write('''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - Zefoy API</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; }
        .navbar { background: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .stat-card { text-align: center; padding: 20px; }
        .stat-card .number { font-size: 2rem; font-weight: bold; color: #58a6ff; }
        .stat-card .label { color: #8b949e; font-size: 0.9rem; }
        .sidebar { min-height: 100vh; border-right: 1px solid #30363d; }
        .nav-link { color: #8b949e; padding: 12px 20px; border-radius: 8px; }
        .nav-link:hover, .nav-link.active { color: #c9d1d9; background: #21262d; }
        .nav-link i { margin-right: 10px; width: 20px; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg sticky-top">
        <div class="container-fluid">
            <a class="navbar-brand text-white fw-bold" href="/admin">
                <i class="bi bi-shield-lock"></i> Zefoy Admin
            </a>
            <div class="ms-auto">
                <a href="/admin/logout" class="btn btn-secondary btn-sm">
                    <i class="bi bi-box-arrow-right"></i> Đăng xuất
                </a>
            </div>
        </div>
    </nav>
    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 sidebar pt-3">
                <nav class="nav flex-column">
                    <a class="nav-link active" href="/admin"><i class="bi bi-speedometer2"></i> Dashboard</a>
                    <a class="nav-link" href="/admin/services"><i class="bi bi-list-ul"></i> Dịch vụ</a>
                    <a class="nav-link" href="/admin/api-keys"><i class="bi bi-key"></i> API Keys</a>
                    <a class="nav-link" href="/admin/settings"><i class="bi bi-gear"></i> Cài đặt</a>
                    <hr class="border-secondary">
                    <a class="nav-link" href="/"><i class="bi bi-house"></i> Trang chủ</a>
                </nav>
            </div>
            <div class="col-md-10 pt-4">
                <h4><i class="bi bi-speedometer2"></i> Tổng quan</h4>
                <p class="text-muted">Quản lý API Zefoy và các dịch vụ</p>
                <div class="row g-3 mb-4">
                    <div class="col-md-3"><div class="card stat-card"><div class="number">1.0</div><div class="label">API Version</div></div></div>
                    <div class="col-md-3"><div class="card stat-card"><div class="number" style="color:#3fb950;">4</div><div class="label">Dịch vụ Online</div></div></div>
                    <div class="col-md-3"><div class="card stat-card"><div class="number" style="color:#d29922;">8</div><div class="label">Tổng dịch vụ</div></div></div>
                    <div class="col-md-3"><div class="card stat-card"><div class="number" style="color:#3fb950;">OK</div><div class="label">Zefoy Status</div></div></div>
                </div>
                <div class="row">
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header">📋 Dịch vụ khả dụng</div>
                            <div class="card-body" id="servicesList"><div class="text-muted">Đang tải...</div></div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header">🔑 API Endpoints</div>
                            <div class="card-body">
                                <div class="mb-2"><code class="text-info">GET /api/captcha</code><span class="text-muted small d-block">Lấy captcha mới</span></div>
                                <div class="mb-2"><code class="text-info">POST /api/solve</code><span class="text-muted small d-block">Giải captcha + đăng nhập</span></div>
                                <div class="mb-2"><code class="text-info">POST /api/submit</code><span class="text-muted small d-block">Gửi service</span></div>
                                <div class="mb-2"><code class="text-info">GET /api/status</code><span class="text-muted small d-block">Kiểm tra trạng thái</span></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <script>
        async function loadServices() {
            try {
                const resp = await fetch('/api/services');
                const data = await resp.json();
                if (data.success) {
                    document.getElementById('servicesList').innerHTML = data.services.map(s => 
                        `<div class="d-flex justify-content-between py-1 border-bottom border-secondary">
                            <span>${s.title}</span>
                            <span class="${s.available ? 'text-success' : 'text-danger'}">${s.available ? '🟢 Online' : '🔴 Offline'}</span>
                        </div>`
                    ).join('');
                }
            } catch(e) {
                document.getElementById('servicesList').innerHTML = '<div class="text-danger">Lỗi tải dịch vụ</div>';
            }
        }
        loadServices();
    </script>
</body>
</html>''')
    
    # ====== templates/admin_services.html ======
    admin_services_file = templates_dir / 'admin_services.html'
    if not admin_services_file.exists():
        with open(admin_services_file, 'w') as f:
            f.write('''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dịch vụ - Zefoy API</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; }
        .navbar { background: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .sidebar { min-height: 100vh; border-right: 1px solid #30363d; }
        .nav-link { color: #8b949e; padding: 12px 20px; border-radius: 8px; }
        .nav-link:hover, .nav-link.active { color: #c9d1d9; background: #21262d; }
        .nav-link i { margin-right: 10px; width: 20px; }
        .table { color: #c9d1d9; }
        .table thead th { border-bottom: 1px solid #30363d; color: #8b949e; }
        .table td { border-bottom: 1px solid #21262d; }
        .status-online { color: #3fb950; }
        .status-offline { color: #f85149; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg sticky-top">
        <div class="container-fluid">
            <a class="navbar-brand text-white fw-bold" href="/admin"><i class="bi bi-shield-lock"></i> Zefoy Admin</a>
            <a href="/admin/logout" class="btn btn-secondary btn-sm ms-auto"><i class="bi bi-box-arrow-right"></i> Đăng xuất</a>
        </div>
    </nav>
    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 sidebar pt-3">
                <nav class="nav flex-column">
                    <a class="nav-link" href="/admin"><i class="bi bi-speedometer2"></i> Dashboard</a>
                    <a class="nav-link active" href="/admin/services"><i class="bi bi-list-ul"></i> Dịch vụ</a>
                    <a class="nav-link" href="/admin/api-keys"><i class="bi bi-key"></i> API Keys</a>
                    <a class="nav-link" href="/admin/settings"><i class="bi bi-gear"></i> Cài đặt</a>
                    <hr class="border-secondary">
                    <a class="nav-link" href="/"><i class="bi bi-house"></i> Trang chủ</a>
                </nav>
            </div>
            <div class="col-md-10 pt-4">
                <h4><i class="bi bi-list-ul"></i> Danh sách dịch vụ</h4>
                <div class="card">
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table" id="servicesTable">
                                <thead><tr><th>#</th><th>Tên dịch vụ</th><th>Trạng thái</th><th>Action</th></tr></thead>
                                <tbody id="servicesBody"><tr><td colspan="4" class="text-muted">Đang tải...</td></tr></tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <script>
        async function loadServices() {
            const tbody = document.getElementById('servicesBody');
            tbody.innerHTML = '<tr><td colspan="4" class="text-muted">Đang tải...</td></tr>';
            try {
                const resp = await fetch('/api/services');
                const data = await resp.json();
                if (data.success) {
                    tbody.innerHTML = data.services.map((s, i) => `
                        <tr>
                            <td>${i + 1}</td>
                            <td>${s.title}</td>
                            <td class="${s.available ? 'status-online' : 'status-offline'}">${s.available ? '🟢 Online' : '🔴 Offline'}</td>
                            <td><span class="text-muted small">${s.action || 'N/A'}</span></td>
                        </tr>
                    `).join('');
                }
            } catch(e) {
                tbody.innerHTML = `<tr><td colspan="4" class="text-danger">Lỗi: ${e.message}</td></tr>`;
            }
        }
        loadServices();
    </script>
</body>
</html>''')
    
    # ====== templates/admin_api_keys.html ======
    admin_api_keys_file = templates_dir / 'admin_api_keys.html'
    if not admin_api_keys_file.exists():
        with open(admin_api_keys_file, 'w') as f:
            f.write('''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Keys - Zefoy API</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; }
        .navbar { background: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .sidebar { min-height: 100vh; border-right: 1px solid #30363d; }
        .nav-link { color: #8b949e; padding: 12px 20px; border-radius: 8px; }
        .nav-link:hover, .nav-link.active { color: #c9d1d9; background: #21262d; }
        .nav-link i { margin-right: 10px; width: 20px; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg sticky-top">
        <div class="container-fluid">
            <a class="navbar-brand text-white fw-bold" href="/admin"><i class="bi bi-shield-lock"></i> Zefoy Admin</a>
            <a href="/admin/logout" class="btn btn-secondary btn-sm ms-auto"><i class="bi bi-box-arrow-right"></i> Đăng xuất</a>
        </div>
    </nav>
    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 sidebar pt-3">
                <nav class="nav flex-column">
                    <a class="nav-link" href="/admin"><i class="bi bi-speedometer2"></i> Dashboard</a>
                    <a class="nav-link" href="/admin/services"><i class="bi bi-list-ul"></i> Dịch vụ</a>
                    <a class="nav-link active" href="/admin/api-keys"><i class="bi bi-key"></i> API Keys</a>
                    <a class="nav-link" href="/admin/settings"><i class="bi bi-gear"></i> Cài đặt</a>
                    <hr class="border-secondary">
                    <a class="nav-link" href="/"><i class="bi bi-house"></i> Trang chủ</a>
                </nav>
            </div>
            <div class="col-md-10 pt-4">
                <h4><i class="bi bi-key"></i> Quản lý API Keys</h4>
                <div class="card">
                    <div class="card-body">
                        <div class="alert alert-info bg-dark-card border-secondary text-muted">
                            <i class="bi bi-info-circle"></i> Sử dụng username/password admin để xác thực.
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>''')
    
    # ====== templates/admin_settings.html ======
    admin_settings_file = templates_dir / 'admin_settings.html'
    if not admin_settings_file.exists():
        with open(admin_settings_file, 'w') as f:
            f.write('''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cài đặt - Zefoy API</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body { background: #0d1117; color: #c9d1d9; }
        .navbar { background: #161b22 !important; border-bottom: 1px solid #30363d; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; }
        .card-header { background: transparent; border-bottom: 1px solid #30363d; }
        .sidebar { min-height: 100vh; border-right: 1px solid #30363d; }
        .nav-link { color: #8b949e; padding: 12px 20px; border-radius: 8px; }
        .nav-link:hover, .nav-link.active { color: #c9d1d9; background: #21262d; }
        .nav-link i { margin-right: 10px; width: 20px; }
        .form-control { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; }
        .form-control:focus { background: #0d1117; border-color: #58a6ff; color: #c9d1d9; }
        .btn-primary { background: #238636; border: none; }
        .btn-primary:hover { background: #2ea043; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg sticky-top">
        <div class="container-fluid">
            <a class="navbar-brand text-white fw-bold" href="/admin"><i class="bi bi-shield-lock"></i> Zefoy Admin</a>
            <a href="/admin/logout" class="btn btn-secondary btn-sm ms-auto"><i class="bi bi-box-arrow-right"></i> Đăng xuất</a>
        </div>
    </nav>
    <div class="container-fluid">
        <div class="row">
            <div class="col-md-2 sidebar pt-3">
                <nav class="nav flex-column">
                    <a class="nav-link" href="/admin"><i class="bi bi-speedometer2"></i> Dashboard</a>
                    <a class="nav-link" href="/admin/services"><i class="bi bi-list-ul"></i> Dịch vụ</a>
                    <a class="nav-link" href="/admin/api-keys"><i class="bi bi-key"></i> API Keys</a>
                    <a class="nav-link active" href="/admin/settings"><i class="bi bi-gear"></i> Cài đặt</a>
                    <hr class="border-secondary">
                    <a class="nav-link" href="/"><i class="bi bi-house"></i> Trang chủ</a>
                </nav>
            </div>
            <div class="col-md-10 pt-4">
                <h4><i class="bi bi-gear"></i> Cài đặt</h4>
                <div class="card">
                    <div class="card-header">🔐 Bảo mật</div>
                    <div class="card-body">
                        <div class="alert alert-info bg-dark-card border-secondary text-muted">
                            <i class="bi bi-info-circle"></i> Admin: admin / zefoy2026
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>''')

# ==================== FLASK APP ====================
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# Tạo cấu trúc project trước khi chạy
create_project_structure()

# Import zefoy sau khi đã tạo
try:
    from zefoy import ZefoyClient, ZefoyCaptcha, SubmitResult
    from zefoy.services import ServiceInfo, parse_services
    from zefoy.ocr import solve_image
    from zefoy.submit import is_captcha_page
    ZEFOY_AVAILABLE = True
except ImportError as e:
    print(f"Lỗi import zefoy: {e}")
    ZEFOY_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'zefoy-secret-key-change-this')
CORS(app)

ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'zefoy2026')
ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)

SESSIONS = {}
CAPTCHA_CACHE = {}

def require_admin(f):
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

def get_zefoy_client():
    if not ZEFOY_AVAILABLE:
        raise Exception("Zefoy module không khả dụng")
    return ZefoyClient(timeout=45)

# ==================== API ENDPOINTS ====================

@app.route('/api/captcha', methods=['GET'])
def api_get_captcha():
    try:
        client = get_zefoy_client()
        captcha = client.get_captcha()
        session_id = captcha.session_id or str(int(time.time()))
        CAPTCHA_CACHE[session_id] = {
            'captcha': captcha,
            'client': client,
            'created': time.time()
        }
        return jsonify({
            'success': True,
            'session_id': session_id,
            'image': base64.b64encode(captcha.image_bytes).decode('ascii'),
            'image_url': captcha.image_url,
            'captcha_token': captcha.captcha_token,
            'message': 'Captcha đã được tạo'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/solve', methods=['POST'])
def api_solve_captcha():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Missing JSON data'}), 400
        
        link = data.get('link', '').strip()
        service = data.get('service', 'Comments Hearts')
        session_id = data.get('session_id', '')
        
        if not link:
            return jsonify({'success': False, 'error': 'Vui lòng nhập link video'}), 400
        
        client = get_zefoy_client()
        if session_id and session_id in CAPTCHA_CACHE:
            cache = CAPTCHA_CACHE[session_id]
            captcha = cache['captcha']
            client = cache['client']
        else:
            captcha = client.get_captcha()
        
        result = client.solve_and_submit(max_attempts=3)
        
        if result.success:
            services = [s.title for s in result.services]
            return jsonify({
                'success': True,
                'message': 'Đã đăng nhập thành công',
                'session_id': result.session_id,
                'services': services,
                'answer': result.answer
            })
        else:
            return jsonify({
                'success': False,
                'error': result.message or 'Không thể giải captcha',
                'attempts': result.attempts
            }), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/services', methods=['GET'])
def api_get_services():
    try:
        client = get_zefoy_client()
        client.get_captcha()
        html = client.session.get(client.base_url, timeout=30).text
        services = parse_services(html)
        return jsonify({
            'success': True,
            'services': [s.to_dict() for s in services]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/submit', methods=['POST'])
def api_submit_service():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Missing JSON data'}), 400
        
        link = data.get('link', '').strip()
        service = data.get('service', 'Comments Hearts')
        session_id = data.get('session_id', '')
        
        if not link:
            return jsonify({'success': False, 'error': 'Vui lòng nhập link video'}), 400
        
        if session_id and session_id in SESSIONS:
            client = SESSIONS[session_id]
        else:
            client = get_zefoy_client()
            SESSIONS[session_id] = client
        
        html = client.session.get(client.base_url, timeout=30).text
        services = parse_services(html)
        
        service_action = None
        service_input = None
        for s in services:
            if s.title.lower() == service.lower():
                service_action = s.action
                service_input = s.input_name
                break
        
        if not service_action:
            for m in re.finditer(r'<form action="([^"]+)"[^>]*>[\s\S]*?name="([^"]+)"[^>]*placeholder="Enter Video', html, re.I):
                prev = html[max(0, m.start() - 400):m.start()]
                titles = re.findall(r'<h5[^>]*>([^<]+)</h5>', prev)
                title = titles[-1].strip() if titles else service
                if title.lower() == service.lower():
                    service_action = m.group(1)
                    service_input = m.group(2)
                    break
        
        if not service_action:
            return jsonify({'success': False, 'error': f'Không tìm thấy service: {service}'}), 400
        
        url = service_action if service_action.startswith('http') else f'{client.base_url}{service_action}'
        token = "".join(random.choices(ascii_letters + digits, k=16))
        boundary = f'----WebKitFormBoundary{token}'
        
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="{service_input or "video_url"}"\r\n\r\n{link}\r\n'
        ]
        parts.append(f'--{boundary}--\r\n')
        body = ''.join(parts)
        
        resp = client.session.post(
            url,
            headers={
                'content-type': f'multipart/form-data; boundary={boundary}',
                'user-agent': client.user_agent,
                'origin': client.base_url,
                'referer': client.base_url,
                'accept': '*/*'
            },
            data=body.encode('utf-8'),
            timeout=45
        )
        
        text = resp.text.strip()
        if text.lower() == 'success':
            return jsonify({'success': True, 'message': 'Đã gửi thành công'})
        
        try:
            decoded = base64.b64decode(text).decode('utf-8', errors='replace')
            if 'success' in decoded.lower():
                return jsonify({'success': True, 'message': decoded})
        except:
            pass
        
        return jsonify({'success': False, 'message': text or 'Không có phản hồi'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/status', methods=['GET'])
def api_status():
    return jsonify({
        'status': 'running',
        'zefoy_available': ZEFOY_AVAILABLE,
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })

# ==================== ADMIN ROUTES ====================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', error='Sai tên đăng nhập hoặc mật khẩu')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin')
@require_admin
def admin_dashboard():
    return render_template('admin_dashboard.html')

@app.route('/admin/services')
@require_admin
def admin_services():
    return render_template('admin_services.html')

@app.route('/admin/api-keys')
@require_admin
def admin_api_keys():
    return render_template('admin_api_keys.html')

@app.route('/admin/settings')
@require_admin
def admin_settings():
    return render_template('admin_settings.html')

# ==================== MAIN ROUTES ====================

@app.route('/')
def index():
    return render_template('index.html')

# ==================== MAIN ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    print("=" * 50)
    print("🚀 ZEFOY API SERVER")
    print("=" * 50)
    print(f"📍 Port: {port}")
    print(f"👤 Admin: {ADMIN_USERNAME}")
    print(f"🔑 Admin Password: {ADMIN_PASSWORD}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=debug, threaded=True)
