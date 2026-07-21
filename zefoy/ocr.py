"""OCR backends for zefoy word captchas.

Default solver: NewOCR free web (https://www.newocr.com/).
Fallbacks: RapidOCR, ddddocr.
"""

from __future__ import annotations

import io
import re
from typing import Callable, Optional

SolverFn = Callable[[bytes], str]


class OcrError(RuntimeError):
    pass


def _letters_only(text: str) -> str:
    return re.sub(r"[^a-zA-Z]", "", text or "").lower()


def solve_newocr(image_bytes: bytes) -> str:
    """
    Solve captcha via newocr.com free website OCR (no API key).

    Uses Tesseract on their server (lang=eng, psm=6).
    """
    try:
        from .newocr import NewOcrError, NewOcrWeb
    except ImportError as exc:  # pragma: no cover
        raise OcrError("newocr module unavailable") from exc

    try:
        result = NewOcrWeb().ocr(image_bytes, lang="eng", psm="6")
    except NewOcrError as exc:
        raise OcrError(f"NewOCR failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise OcrError(f"NewOCR request error: {exc}") from exc

    text = _letters_only(result.text)
    if not text:
        raise OcrError("NewOCR returned empty text")
    return text


def solve_newocr_api(image_bytes: bytes, api_key: str) -> str:
    """Solve via official NewOCR REST API (requires free/paid API key)."""
    try:
        from .newocr import NewOcrApi, NewOcrError
    except ImportError as exc:  # pragma: no cover
        raise OcrError("newocr module unavailable") from exc

    try:
        result = NewOcrApi(api_key).ocr(image_bytes, lang="eng", psm=6)
    except NewOcrError as exc:
        raise OcrError(f"NewOCR API failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise OcrError(f"NewOCR API request error: {exc}") from exc

    text = _letters_only(result.text)
    if not text:
        raise OcrError("NewOCR API returned empty text")
    return text


def make_newocr_api_solver(api_key: str) -> SolverFn:
    """Build a solver closure that uses the official NewOCR API key."""

    def _solve(image_bytes: bytes) -> str:
        return solve_newocr_api(image_bytes, api_key)

    return _solve


def solve_rapidocr(image_bytes: bytes) -> str:
    """Solve captcha with rapidocr-onnxruntime (recommended for English words)."""
    try:
        import numpy as np
        from PIL import Image
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise OcrError(
            "rapidocr-onnxruntime (and Pillow/numpy) required for OCR. "
            "pip install rapidocr-onnxruntime pillow numpy"
        ) from exc

    engine = RapidOCR()
    im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    best, best_score = "", -1.0

    variants = [im]
    for scale in (2, 3, 4, 5):
        variants.append(
            im.resize((im.width * scale, im.height * scale), Image.Resampling.LANCZOS)
        )
    # high-contrast grayscale variants help first/last letters
    try:
        from PIL import ImageOps

        g = ImageOps.autocontrast(ImageOps.grayscale(im)).convert("RGB")
        variants.append(g.resize((g.width * 3, g.height * 3), Image.Resampling.LANCZOS))
        thr = ImageOps.grayscale(im).point(lambda x: 0 if x < 150 else 255).convert("RGB")
        variants.append(thr.resize((thr.width * 3, thr.height * 3), Image.Resampling.LANCZOS))
    except Exception:
        pass

    for cand in variants:
        result, _ = engine(np.array(cand))
        if not result:
            continue
        text = _letters_only("".join(item[1] for item in result))
        conf = float(result[0][2]) if result and len(result[0]) > 2 else 0.0
        score = conf + min(len(text), 12) * 0.03
        if len(text) >= 3 and score > best_score:
            best, best_score = text, score

    if not best:
        raise OcrError("OCR produced empty result")
    return best


def solve_ddddocr(image_bytes: bytes) -> str:
    try:
        import ddddocr
    except ImportError as exc:
        raise OcrError("ddddocr not installed") from exc

    ocr = ddddocr.DdddOcr(show_ad=False)
    text = _letters_only(ocr.classification(image_bytes) or "")
    if not text:
        raise OcrError("ddddocr empty result")
    return text


def solve_with_fallbacks(image_bytes: bytes) -> str:
    """
    Try NewOCR web first, then local engines (ddddocr, RapidOCR).

    Network/SSL issues on newocr.com are common on Windows; local OCR is the
    reliable fallback when installed.
    """
    errors: list[str] = []
    for name, fn in (
        ("newocr", solve_newocr),
        ("ddddocr", solve_ddddocr),
        ("rapidocr", solve_rapidocr),
    ):
        try:
            text = _letters_only(fn(image_bytes))
            if text:
                return text
            errors.append(f"{name}: empty")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
    raise OcrError("All OCR backends failed: " + " | ".join(errors))


def get_default_solver() -> SolverFn:
    """Default OCR: NewOCR free web, then local ddddocr / RapidOCR."""
    return solve_with_fallbacks


def solve_image(
    image_bytes: bytes,
    solver: Optional[SolverFn] = None,
    *,
    use_fallbacks: bool = True,
) -> str:
    """
    Run OCR on captcha image bytes.

    Default: NewOCR → ddddocr → RapidOCR.
    Pass a custom ``solver`` to override.
    """
    if solver is not None:
        return _letters_only(solver(image_bytes))
    if use_fallbacks:
        return solve_with_fallbacks(image_bytes)
    return _letters_only(solve_newocr(image_bytes))
