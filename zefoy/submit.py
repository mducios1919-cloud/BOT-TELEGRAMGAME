"""
Submit zefoy.com login captcha automatically (pure requests, no Playwright).

Flow (verified):
  1. GET /  → PHPSESSID + guard cookies zf/za
  2. GET /?getcapthca=<ts> → captcha image
  3. Build captcha_encoded = CryptoJS-AES(device fingerprint)
  4. NewOCR solves image word
  5. POST / XHR  {captchalogin, captcha_encoded}  → body "success"
  6. GET /  → service panel HTML
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import requests

from .captcha import (
    DEFAULT_BASE_URL,
    DEFAULT_USER_AGENT,
    CaptchaResult,
    ZefoyCaptcha,
)
from .fingerprint import apply_session_guard_cookies, build_captcha_encoded
from .ocr import SolverFn, make_newocr_api_solver, solve_image, solve_newocr
from .services import (
    ServiceInfo,
    parse_services,
    print_services_table,
)

Solver = SolverFn


class ZefoySubmitError(RuntimeError):
    """Raised when captcha submit fails or response is unexpected."""


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

    @property
    def is_captcha_page(self) -> bool:
        return is_captcha_page(self.html)

    def services_as_dicts(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.services]

    def print_services(self, *, use_color: bool = True) -> None:
        print_services_table(self.services, use_color=use_color)


def is_captcha_page(html: str) -> bool:
    if not html:
        return False
    if html.strip().lower() == "success":
        return False
    return (
        'name="captchalogin"' in html
        or "name='captchalogin'" in html
        or "captcha-login-input" in html
        or 'id="captcha-img"' in html
    )


def normalize_answer(answer: str) -> str:
    """Match site input filter: lowercase letters only."""
    return re.sub(r"[^a-z]", "", (answer or "").lower())


class ZefoyClient:
    """
    Pure-requests client: captcha get + NewOCR + fingerprint + XHR submit.

    Example:
        client = ZefoyClient()
        result = client.solve_and_submit()
        print(result.success, result.services)
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        session: Optional[requests.Session] = None,
        timeout: float = 30.0,
        solver: Optional[Solver] = None,
        newocr_api_key: Optional[str] = None,
    ) -> None:
        self.captcha_client = ZefoyCaptcha(
            base_url=base_url,
            user_agent=user_agent,
            session=session,
            timeout=timeout,
        )
        if solver is not None:
            self.solver = solver
        elif newocr_api_key:
            self.solver = make_newocr_api_solver(newocr_api_key)
        else:
            self.solver = solve_newocr
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
    def cookies(self) -> dict[str, str]:
        return self.captcha_client.cookies

    @property
    def session_id(self) -> Optional[str]:
        return self.captcha_client.session_id

    def get_captcha(self, *, refresh_session: bool = False) -> CaptchaResult:
        """Fetch captcha image + build synthetic captcha_encoded for this session."""
        captcha = self.captcha_client.get(refresh_session=refresh_session)
        apply_session_guard_cookies(self.session)
        self._last_encoded = build_captcha_encoded(self.user_agent)
        self._last_captcha = captcha
        return captcha

    def build_encoded(self) -> str:
        """Generate captcha_encoded (CryptoJS AES of device fingerprint)."""
        self._last_encoded = build_captcha_encoded(self.user_agent)
        return self._last_encoded

    def submit_answer(
        self,
        answer: str,
        *,
        captcha_encoded: Optional[str] = None,
        captcha: Optional[CaptchaResult] = None,
    ) -> SubmitResult:
        """
        XHR POST captcha (matches site jQuery handler).

        Success body is the plain string ``success``; then GET / for the panel.
        """
        answer = normalize_answer(answer)
        if not answer:
            raise ZefoySubmitError("Empty captcha answer after normalization")

        if not self.session_id:
            self.captcha_client.ensure_session()

        apply_session_guard_cookies(self.session)
        encoded = captcha_encoded or self._last_encoded or self.build_encoded()
        captcha = captcha or self._last_captcha

        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "Accept": "*/*",
        }
        data = {
            "captchalogin": answer,
            "captcha_encoded": encoded,
        }

        resp = self.session.post(
            f"{self.base_url}/",
            data=data,
            headers=headers,
            timeout=self.timeout,
            allow_redirects=False,
        )
        xhr_body = (resp.text or "").strip()
        xhr_ok = resp.status_code == 200 and xhr_body.lower() == "success"

        html = ""
        services: list[ServiceInfo] = []
        if xhr_ok:
            follow = self.session.get(
                f"{self.base_url}/",
                headers={
                    "Referer": f"{self.base_url}/",
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,*/*;q=0.8"
                    ),
                },
                timeout=self.timeout,
            )
            html = follow.text or ""
            success = not is_captcha_page(html)
            if success:
                services = parse_services(html)
            message = "ok" if success else "XHR success but panel still looks like captcha"
        else:
            html = resp.text or ""
            success = False
            message = (
                f"captcha rejected (xhr_body={xhr_body[:80]!r})"
                if xhr_body
                else "captcha rejected or empty response"
            )

        return SubmitResult(
            success=success,
            answer=answer,
            status_code=resp.status_code,
            html=html,
            session_id=self.session_id,
            cookies=self.cookies,
            services=services,
            message=message,
            captcha=captcha,
            attempts=1,
            xhr_body=xhr_body,
        )

    def solve_and_submit(
        self,
        *,
        max_attempts: int = 5,
        solver: Optional[Solver] = None,
        on_attempt: Optional[Callable[[int, CaptchaResult, str], None]] = None,
        use_ocr_fallbacks: bool = False,
    ) -> SubmitResult:
        """
        Loop: get captcha → NewOCR → gen fingerprint → XHR submit.
        """
        solver = solver if solver is not None else self.solver
        last: Optional[SubmitResult] = None

        for attempt in range(1, max_attempts + 1):
            # Always refresh captcha each attempt (answer is one-shot)
            captcha = self.get_captcha(refresh_session=(attempt == 1))
            try:
                answer = solve_image(captcha.image_bytes, solver=solver)
            except Exception as exc:  # noqa: BLE001
                last = SubmitResult(
                    success=False,
                    answer="",
                    status_code=0,
                    html="",
                    session_id=self.session_id,
                    cookies=self.cookies,
                    message=f"OCR failed: {exc}",
                    captcha=captcha,
                    attempts=attempt,
                )
                continue

            if on_attempt:
                on_attempt(attempt, captcha, answer)

            result = self.submit_answer(
                answer,
                captcha_encoded=self._last_encoded,
                captcha=captcha,
            )
            result.attempts = attempt
            last = result
            if result.success:
                return result

        if last is None:
            raise ZefoySubmitError("No captcha attempts were made")
        last.message = f"Failed after {max_attempts} attempts ({last.message})"
        return last


def submit_captcha(
    answer: str,
    *,
    session: Optional[requests.Session] = None,
    user_agent: str = DEFAULT_USER_AGENT,
    base_url: str = DEFAULT_BASE_URL,
) -> SubmitResult:
    """One-shot: get captcha + submit a known answer (same session)."""
    client = ZefoyClient(base_url=base_url, user_agent=user_agent, session=session)
    client.get_captcha()
    return client.submit_answer(answer)


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        description="Auto solve zefoy captcha (requests + NewOCR + gen fingerprint)"
    )
    parser.add_argument("-a", "--answer", help="Manual captcha answer (skip OCR)")
    parser.add_argument("-n", "--attempts", type=int, default=5, help="Max attempts")
    parser.add_argument("-o", "--save-html", help="Save panel HTML path")
    parser.add_argument(
        "--newocr-api-key",
        default=None,
        help="Official NewOCR API key (default: free web OCR)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON summary")
    args = parser.parse_args()

    client = ZefoyClient(newocr_api_key=args.newocr_api_key)

    def _log(i: int, captcha: CaptchaResult, ans: str) -> None:
        print(
            f"[attempt {i}] newocr={ans!r} token={captcha.captcha_token}",
            file=sys.stderr,
        )

    try:
        if args.answer:
            client.get_captcha()
            result = client.submit_answer(args.answer)
        else:
            result = client.solve_and_submit(
                max_attempts=args.attempts,
                on_attempt=_log,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if args.save_html and result.html:
        with open(args.save_html, "w", encoding="utf-8") as f:
            f.write(result.html)

    payload = {
        "success": result.success,
        "answer": result.answer,
        "attempts": result.attempts,
        "session_id": result.session_id,
        "status_code": result.status_code,
        "message": result.message,
        "xhr_body": result.xhr_body,
        "services": result.services_as_dicts(),
        "cookies": result.cookies,
        "html_len": len(result.html),
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("success:", result.success)
        print("answer:", result.answer)
        print("attempts:", result.attempts)
        print("session:", result.session_id)
        print("xhr_body:", result.xhr_body)
        print("message:", result.message)
        if result.success and result.services:
            print()
            result.print_services(use_color=True)
        elif result.services:
            print("services:")
            for s in result.services:
                print(" -", s.title, "|", s.status)
