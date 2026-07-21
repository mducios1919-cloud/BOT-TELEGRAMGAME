"""Build browser/device fingerprint JSON encrypted into captcha_encoded."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .crypto_util import encrypt_cryptojs_json


def browser_guard_cookies() -> dict[str, str]:
    """
    Cookies set by site JS on window load.

    - zf = md5(Date.now())
    - za = adsbygoogle probe status (200 when script reachable)
    """
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
    """
    Construct fingerprint matching live page schema:

      deviceInfo / browserInfo / screenInfo / otherData / storageInfo
    """
    language = language or locale.split("-")[0]
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        offset_min = -int(now.utcoffset().total_seconds() // 60)  # type: ignore[union-attr]
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
                "renderer": (
                    "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 "
                    "vs_5_0 ps_5_0, D3D11)"
                ),
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


def build_captcha_encoded(
    user_agent: str,
    *,
    fingerprint: Optional[dict[str, Any]] = None,
    **fingerprint_kwargs: Any,
) -> str:
    """Build encrypted captcha_encoded form field value."""
    fp = fingerprint or build_device_fingerprint(user_agent, **fingerprint_kwargs)
    return encrypt_cryptojs_json(fp)


def apply_session_guard_cookies(session: Any, *, domain: str = "zefoy.com") -> dict[str, str]:
    """Write za/zf cookies into a requests session jar."""
    cookies = browser_guard_cookies()
    for name, value in cookies.items():
        # Avoid duplicate domain/path entries — set without forcing domain first.
        session.cookies.set(name, value, path="/")
        try:
            session.cookies.set(name, value, domain=domain, path="/")
        except Exception:
            pass
    return cookies
