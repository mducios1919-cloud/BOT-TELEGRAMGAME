"""Parse and display Zefoy service list with colored status table."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Any, Optional

from bs4 import BeautifulSoup


# ── ANSI colors (Windows 10+ VT enabled in modern terminals) ──────────────

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    # foreground
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    # bright
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"
    # background
    BG_GREEN = "\033[42m"
    BG_RED = "\033[41m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_DARK = "\033[100m"


def _enable_windows_ansi() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL
    except Exception:
        pass


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
    """
    Return (display_status, available).

    Examples:
      'soon will be update' → ('Offline / Updating', False)
      '7 days ago updated'  → ('Online · 7 days ago', True)
      'Updated: 3 days ago' → ('Online · 3 days ago', True)
    """
    text = re.sub(r"\s+", " ", (raw or "").strip())
    low = text.lower()

    if not text:
        return ("Unknown", False)

    if "soon" in low or "will be update" in low or "coming" in low:
        return ("Offline / Updating", False)

    # "7 days ago updated" / "Updated: 7 days ago"
    m = re.search(r"(\d+)\s*days?\s*ago", low)
    if m:
        days = m.group(1)
        return (f"Online · {days} days ago", True)

    m = re.search(r"(\d+)\s*hours?\s*ago", low)
    if m:
        return (f"Online · {m.group(1)} hours ago", True)

    if "update" in low or "online" in low or "active" in low:
        return (f"Online · {text}", True)

    if "disable" in low or "off" in low or "maintenance" in low:
        return (f"Disabled · {text}", False)

    return (text, True)


def parse_services(html: str) -> list[ServiceInfo]:
    """
    Merge status cards + action forms into one service list.

    Panel has two card groups:
      - status cards (card-body): title + 'soon will be update' / 'N days ago'
      - action cards (card-ortlax): title + form action / input name
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    by_title: dict[str, ServiceInfo] = {}

    # 1) status cards
    for card in soup.select("div.card"):
        title_el = card.select_one("h5, h6, .card-title, .toptitle")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue

        status_el = card.select_one("p.card-text, .card-text, p")
        raw_status = status_el.get_text(" ", strip=True) if status_el else ""
        # ignore pure "Search" placeholder from action cards
        if raw_status.lower() in ("search", "search."):
            raw_status = ""

        form = card.select_one("form")
        action = form.get("action") if form else None
        inp = None
        if form:
            inp = form.select_one(
                "input[type=text], input.form-control, input:not([type=hidden])"
            )
        input_name = inp.get("name") if inp else None

        # Status text is the source of truth for availability.
        # Form action alone does NOT mean online (offline services still have forms).
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
            # merge: status text wins for available flag; forms fill action fields
            if raw_status:
                existing.raw_status = raw_status
                existing.status, existing.available = _normalize_status(raw_status)
            if action:
                existing.action = action
            if input_name:
                existing.input_name = input_name

    # stable order known services first
    preferred = [
        "Followers",
        "Hearts",
        "Comments Hearts",
        "Views",
        "Shares",
        "Favorites",
        "Live Stream",
        "Repost",
    ]
    ordered: list[ServiceInfo] = []
    for name in preferred:
        if name in by_title:
            ordered.append(by_title.pop(name))
    ordered.extend(by_title.values())
    return ordered


def _status_style(svc: ServiceInfo) -> tuple[str, str]:
    """Return (colored_status_text, badge_label)."""
    if svc.available:
        badge = f"{C.BG_GREEN}{C.BLACK}{C.BOLD} ON  {C.RESET}"
        text = f"{C.BRIGHT_GREEN}{svc.status}{C.RESET}"
    elif "offline" in svc.status.lower() or "updat" in svc.status.lower():
        badge = f"{C.BG_YELLOW}{C.BLACK}{C.BOLD} WAIT{C.RESET}"
        text = f"{C.BRIGHT_YELLOW}{svc.status}{C.RESET}"
    else:
        badge = f"{C.BG_RED}{C.BRIGHT_WHITE}{C.BOLD} OFF {C.RESET}"
        text = f"{C.BRIGHT_RED}{svc.status}{C.RESET}"
    return text, badge


def format_services_table(
    services: list[ServiceInfo],
    *,
    use_color: bool = True,
    title: str = "ZEFOY SERVICES",
) -> str:
    """Render a colored ASCII table of services."""
    if use_color:
        _enable_windows_ansi()

    if not services:
        empty = "No services found."
        return f"{C.BRIGHT_RED}{empty}{C.RESET}" if use_color else empty

    # column widths (visible chars, not ANSI)
    headers = ["#", "Service", "Status", "State", "Action"]
    rows_plain: list[list[str]] = []
    rows_color: list[list[str]] = []

    for i, svc in enumerate(services, 1):
        status_colored, badge = _status_style(svc)
        action_short = (svc.action or "—")[:22]
        if svc.action and len(svc.action) > 22:
            action_short = svc.action[:19] + "..."

        rows_plain.append(
            [
                str(i),
                svc.title,
                svc.status,
                "ON" if svc.available else "WAIT" if "updat" in svc.status.lower() else "OFF",
                action_short,
            ]
        )
        if use_color:
            rows_color.append(
                [
                    f"{C.DIM}{i}{C.RESET}",
                    f"{C.BRIGHT_CYAN}{C.BOLD}{svc.title}{C.RESET}",
                    status_colored,
                    badge,
                    f"{C.DIM}{action_short}{C.RESET}",
                ]
            )

    # compute widths from plain rows
    widths = [len(h) for h in headers]
    for row in rows_plain:
        for j, cell in enumerate(row):
            widths[j] = max(widths[j], len(cell))

    def pad_plain(s: str, w: int) -> str:
        return s + " " * (w - len(s))

    def pad_ansi(plain: str, colored: str, w: int) -> str:
        return colored + " " * (w - len(plain))

    # box drawing
    top = "┌" + "┬".join("─" * (w + 2) for w in widths) + "┐"
    mid = "├" + "┼".join("─" * (w + 2) for w in widths) + "┤"
    bot = "└" + "┴".join("─" * (w + 2) for w in widths) + "┘"

    lines: list[str] = []
    # title bar
    table_w = sum(widths) + 3 * len(widths) + 1
    title_line = f"  {title}  "
    if use_color:
        lines.append(
            f"{C.BG_BLUE}{C.BRIGHT_WHITE}{C.BOLD}{title_line.center(table_w)}{C.RESET}"
        )
    else:
        lines.append(title_line.center(table_w))

    lines.append(top if not use_color else f"{C.BLUE}{top}{C.RESET}")

    # header
    header_cells = [pad_plain(h, widths[i]) for i, h in enumerate(headers)]
    header_row = "│ " + " │ ".join(header_cells) + " │"
    if use_color:
        colored_headers = [
            f"{C.BRIGHT_WHITE}{C.BOLD}{pad_plain(h, widths[i])}{C.RESET}"
            for i, h in enumerate(headers)
        ]
        header_row = (
            f"{C.BLUE}│{C.RESET} "
            + f" {C.BLUE}│{C.RESET} ".join(colored_headers)
            + f" {C.BLUE}│{C.RESET}"
        )
    lines.append(header_row)
    lines.append(mid if not use_color else f"{C.BLUE}{mid}{C.RESET}")

    display_rows = rows_color if use_color else rows_plain
    for plain, disp in zip(rows_plain, display_rows):
        if use_color:
            cells = [
                pad_ansi(plain[j], disp[j], widths[j]) for j in range(len(widths))
            ]
            row = (
                f"{C.BLUE}│{C.RESET} "
                + f" {C.BLUE}│{C.RESET} ".join(cells)
                + f" {C.BLUE}│{C.RESET}"
            )
        else:
            cells = [pad_plain(plain[j], widths[j]) for j in range(len(widths))]
            row = "│ " + " │ ".join(cells) + " │"
        lines.append(row)

    lines.append(bot if not use_color else f"{C.BLUE}{bot}{C.RESET}")

    # legend
    online = sum(1 for s in services if s.available)
    offline = len(services) - online
    if use_color:
        legend = (
            f"  {C.BG_GREEN}{C.BLACK}{C.BOLD} ON  {C.RESET} available  "
            f"{C.BG_YELLOW}{C.BLACK}{C.BOLD} WAIT{C.RESET} updating  "
            f"{C.BG_RED}{C.BRIGHT_WHITE}{C.BOLD} OFF {C.RESET} unavailable  "
            f"{C.DIM}|{C.RESET}  "
            f"{C.BRIGHT_GREEN}{online} online{C.RESET} · "
            f"{C.BRIGHT_YELLOW}{offline} wait/off{C.RESET}"
        )
    else:
        legend = f"  ON={online}  WAIT/OFF={offline}"
    lines.append(legend)

    return "\n".join(lines)


def print_services_table(
    services: list[ServiceInfo],
    *,
    use_color: bool = True,
    title: str = "ZEFOY SERVICES",
    file=None,
) -> None:
    """Print colored services table to stdout (or file)."""
    text = format_services_table(services, use_color=use_color, title=title)
    print(text, file=file or sys.stdout)
