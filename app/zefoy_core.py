"""Ported core logic from buff.py - Zefoy interactions using pre-authenticated cookies."""
from __future__ import annotations
import base64
import html
import json
import re
import time
import urllib.parse
from typing import Any

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://zefoy.com"

DEFAULT_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}


def parse_cookie_string(cookie_str: str) -> dict:
    cookies = {}
    for item in (cookie_str or "").split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def build_session(cookie_string: str, user_agent: str) -> requests.Session:
    s = requests.Session()
    s.cookies.update(parse_cookie_string(cookie_string))
    headers = dict(DEFAULT_HEADERS)
    headers["user-agent"] = user_agent or DEFAULT_HEADERS.get(
        "user-agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    )
    s.headers.update(headers)
    return s


def decode_zefoy_response(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text

    def try_decode(val: str) -> str:
        try:
            rev = val[::-1]
            url_dec = urllib.parse.unquote(rev)
            decoded = base64.b64decode(url_dec + "=" * (-len(url_dec) % 4)).decode("utf-8", errors="replace")
            if "<" in decoded or "{" in decoded or "div" in decoded:
                return decoded
        except Exception:
            pass
        try:
            decoded = base64.b64decode(val + "=" * (-len(val) % 4)).decode("utf-8", errors="replace")
            if "<" in decoded or "{" in decoded:
                return decoded
        except Exception:
            pass
        return val

    decoded = try_decode(text)
    if decoded != text:
        try:
            data = json.loads(decoded)
            if isinstance(data, dict) and "html" in data:
                return try_decode(data["html"])
        except Exception:
            pass
        return decoded
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "html" in data:
            return try_decode(data["html"])
    except Exception:
        pass
    return text


def clean_html_text(html_content: str) -> str:
    return BeautifulSoup(html_content or "", "html.parser").get_text(separator=" ").strip()


def extract_cooldown_seconds(decoded_response: str) -> tuple[int, str]:
    soup = BeautifulSoup(decoded_response or "", "html.parser")
    tag = soup.find(id="login-countdown") or soup.find(class_=re.compile(r"countdown"))
    countdown_text = tag.text.strip() if tag else ""
    text_clean = clean_html_text(decoded_response)
    if not countdown_text:
        countdown_text = text_clean

    min_m = re.search(r"(\d+)\s*minute", countdown_text, re.I)
    sec_m = re.search(r"(\d+)\s*second", countdown_text, re.I)
    if min_m or sec_m:
        mins = int(min_m.group(1)) if min_m else 0
        secs = int(sec_m.group(1)) if sec_m else 0
        total = mins * 60 + secs
        if total > 0:
            return total, f"Please wait {mins}m {secs}s"

    for pat in [
        r"var\s+ltm\s*=\s*(\d+)", r"ltm\s*=\s*(\d+)", r"ltimer\s*\(\s*(\d+)",
        r"timer\s*\(\s*(\d+)", r"startTimer\s*\(\s*(\d+)", r"var\s+k\s*=\s*(\d+)",
        r"var\s+time\s*=\s*(\d+)", r"var\s+timeleft\s*=\s*(\d+)", r"var\s+c\s*=\s*(\d+)",
        r"seconds\s*=\s*(\d+)",
    ]:
        m = re.search(pat, decoded_response or "", re.I)
        if m:
            secs = int(m.group(1))
            if secs > 0:
                return secs, f"Please wait {secs // 60}m {secs % 60}s"

    low = text_clean.lower()
    if "checking timer" in low or "please wait" in low:
        return 120, "Checking timer (default 120s)"
    return 0, ""


def get_services(session: requests.Session) -> tuple[list[dict], str]:
    r = session.get(BASE_URL + "/", timeout=30)
    html_content = r.text or ""
    soup = BeautifulSoup(html_content, "html.parser")
    cards = soup.find_all("div", class_="colsmenu")
    services = []
    for card in cards:
        title_tag = card.find("h5", class_="card-title")
        if not title_tag:
            continue
        title = title_tag.text.strip()
        btn = card.find("button")
        if not btn:
            continue
        is_active = "disabled" not in btn.attrs
        btn_class = ""
        for cls in btn.get("class", []):
            if cls.startswith("t-") and cls.endswith("-button"):
                btn_class = cls
                break
        status_tag = card.find(class_="badge") or card.find("small")
        status_text = status_tag.text.strip() if status_tag else ("ON" if is_active else "OFF")
        services.append({
            "name": title,
            "active": is_active,
            "status": status_text,
            "btn_class": btn_class,
            "menu_class": btn_class.replace("-button", "-menu") if btn_class else "",
        })
    return services, html_content


def get_service_form(html_content: str, menu_class: str) -> dict | None:
    soup = BeautifulSoup(html_content, "html.parser")
    menu_div = soup.find("div", class_=menu_class)
    if not menu_div and menu_class:
        menu_div = soup.find(class_=re.compile(menu_class))
    if not menu_div:
        return None
    form = menu_div.find("form")
    if not form:
        return None
    action = form.get("action")
    inp = form.find("input", type="search") or form.find("input", class_="form-control")
    input_name = inp.get("name") if inp else None
    if not input_name:
        for i in form.find_all("input"):
            if i.get("type", "text").lower() in ["search", "text"] and i.get("name"):
                input_name = i.get("name")
                break
    return {"action": action, "input_name": input_name}


AJAX_HEADERS_EXTRA = {
    "accept": "*/*",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "origin": BASE_URL,
    "referer": BASE_URL + "/",
    "x-requested-with": "XMLHttpRequest",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}


def run_boost(session: requests.Session, service: dict, home_html: str, video_url: str) -> dict:
    """Run one boost cycle. Returns {ok, message, cooldown, amount}."""
    form_info = get_service_form(home_html, service["menu_class"])
    if not form_info or not form_info.get("action") or not form_info.get("input_name"):
        return {"ok": False, "message": "Không tìm thấy form cho dịch vụ này", "cooldown": 0}

    action_url = f"{BASE_URL}/{form_info['action']}"
    input_name = form_info["input_name"]

    ajax = dict(session.headers)
    ajax.update(AJAX_HEADERS_EXTRA)

    search_data = {input_name: video_url}
    decoded_response = ""
    total_wait = 0
    countdown_text = ""
    submit_btn = None
    form = None

    for attempt in range(3):
        r = session.post(action_url, headers=ajax, data=search_data, timeout=45)
        decoded_response = decode_zefoy_response(r.text or "")
        soup = BeautifulSoup(decoded_response, "html.parser")
        total_wait, countdown_text = extract_cooldown_seconds(decoded_response)
        form = soup.find("form")
        submit_btn = soup.find("button", class_=re.compile(r"wbutton|btn"))
        if (total_wait > 0 and "default 120s" not in countdown_text.lower()) or form or submit_btn:
            break
        time.sleep(1.5)

    if total_wait > 0:
        return {"ok": False, "message": countdown_text or "Đang chờ cooldown", "cooldown": total_wait}

    if not (form or submit_btn):
        return {"ok": False, "message": clean_html_text(decoded_response) or "Phản hồi không hợp lệ", "cooldown": 0}

    target_form = form if form else submit_btn.find_parent("form")
    submit_action = target_form.get("action") if target_form else None
    if not submit_action or submit_action.strip() in ("", "/") or not submit_action.startswith("c2Vu"):
        submit_action = form_info["action"]
    submit_url = f"{BASE_URL}/{submit_action}"

    submit_data = {}
    inputs = target_form.find_all("input") if target_form else []
    for inp in inputs:
        name = inp.get("name")
        val = inp.get("value", "")
        if name:
            submit_data[name] = val

    selects = target_form.find_all("select") if target_form else []
    for sel in selects:
        name = sel.get("name")
        if not name:
            continue
        max_val = None
        max_int = -1
        for opt in sel.find_all("option"):
            val = opt.get("value", "").strip()
            if not val:
                continue
            try:
                v = int(val)
                if v > max_int:
                    max_int, max_val = v, val
            except ValueError:
                if max_val is None:
                    max_val = val
        if max_val is not None:
            submit_data[name] = max_val

    actual_btn = target_form.find("button", type="submit") if target_form else submit_btn
    if actual_btn and actual_btn.get("name"):
        submit_data[actual_btn.get("name")] = actual_btn.get("value", "")

    boost_r = session.post(submit_url, headers=ajax, data=submit_data, timeout=45)
    decoded_boost = decode_zefoy_response(boost_r.text or "")
    result_text = clean_html_text(decoded_boost) or "Không có phản hồi rõ ràng"

    # try parse amount
    amount = None
    m = re.search(r"(\d+)\s*(views?|hearts?|followers?|shares?|comments?|favorites?)", result_text, re.I)
    if m:
        try:
            amount = int(m.group(1))
        except Exception:
            pass

    ok = bool(re.search(r"sent|success|completed|added", result_text, re.I) or amount)
    return {"ok": ok, "message": result_text[:300], "cooldown": 0, "amount": amount}
