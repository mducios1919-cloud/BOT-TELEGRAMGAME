"""Zefoy client helpers: captcha fetch + auto submit + NewOCR."""

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
