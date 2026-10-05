#!/usr/bin/env python3
"""Daily price check for Dolphins at Bills (11/22/2026) — emails a report."""

import json
import os
import smtplib
import sys
from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
HISTORY_FILE = SCRIPT_DIR / "price_history.json"

NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "ngardone@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
SEATGEEK_CLIENT_ID = os.environ.get("SEATGEEK_CLIENT_ID", "")
TICKETMASTER_API_KEY = os.environ.get("TICKETMASTER_API_KEY", "")

GAME_DATE = date(2026, 11, 22)
EVENT_LABEL = "Miami Dolphins at Buffalo Bills"
VENUE = "Highmark Stadium, Orchard Park, NY"

# Link-only sources (no public pricing API — see README for why).
STATIC_LINKS = {
    "StubHub": "https://www.stubhub.com/buffalo-bills-orchard-park-tickets-11-22-2026/event/160447831/",
    "Vivid Seats": "https://www.vividseats.com/buffalo-bills-tickets-orchard-park-highmark-stadium-3-1-2026/production/6488199",
}


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_history() -> dict:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {
        "event": EVENT_LABEL,
        "venue": VENUE,
        "date": GAME_DATE.isoformat(),
        "tracking_started": date.today().isoformat(),
        "history": [],
    }


def save_history(data: dict) -> None:
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

def fetch_seatgeek() -> dict | None:
    """SeatGeek Platform API — https://platform.seatgeek.com/"""
    if not SEATGEEK_CLIENT_ID:
        return None
    try:
        resp = requests.get(
            "https://api.seatgeek.com/2/events",
            params={
                "q": "Miami Dolphins at Buffalo Bills",
                "client_id": SEATGEEK_CLIENT_ID,
                "per_page": 10,
            },
            timeout=20,
        )
        resp.raise_for_status()
        events = resp.json().get("events", [])
        for ev in events:
            ev_date = ev.get("datetime_local", "")[:10]
            if ev_date == GAME_DATE.isoformat():
                stats = ev.get("stats", {})
                return {
                    "lowest_price": stats.get("lowest_price"),
                    "average_price": stats.get("average_price"),
                    "highest_price": stats.get("highest_price"),
                    "listing_count": stats.get("listing_count"),
                    "url": ev.get("url"),
                }
        print("[SeatGeek] no event matched target date")
        return None
    except Exception as exc:
        print(f"[SeatGeek] error: {exc}")
        return None


def fetch_ticketmaster() -> dict | None:
    """Ticketmaster Discovery API — https://developer.ticketmaster.com/"""
    if not TICKETMASTER_API_KEY:
        return None
    try:
        resp = requests.get(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            params={
                "apikey": TICKETMASTER_API_KEY,
                "keyword": "Buffalo Bills Miami Dolphins",
                "startDateTime": f"{GAME_DATE.isoformat()}T00:00:00Z",
                "endDateTime": f"{GAME_DATE.isoformat()}T23:59:59Z",
            },
            timeout=20,
        )
        resp.raise_for_status()
        events = resp.json().get("_embedded", {}).get("events", [])
        if not events:
            print("[Ticketmaster] no event matched target date")
            return None
        ev = events[0]
        price_ranges = ev.get("priceRanges", [])
        pr = price_ranges[0] if price_ranges else {}
        return {
            "min": pr.get("min"),
            "max": pr.get("max"),
            "url": ev.get("url"),
        }
    except Exception as exc:
        print(f"[Ticketmaster] error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def compute_rating(history: list[dict], today_low: float | None) -> str:
    past_lows = [h["seatgeek_lowest"] for h in history if h.get("seatgeek_lowest") is not None]
    if today_low is None:
        return "Unknown — no SeatGeek price available today"
    if len(past_lows) < 5:
        return (
            f"Establishing baseline ({len(past_lows)} day(s) of history so far) — "
            "not enough tracked history yet for a reliable High/Medium/Low rating. "
            "Check back after ~1-2 weeks of tracking."
        )
    lo, hi = min(past_lows), max(past_lows)
    if hi == lo:
        return "Medium (flat so far — no price movement observed yet)"
    pct = (today_low - lo) / (hi - lo)
    if pct <= 0.2:
        return "Low — near the lowest price seen since tracking began"
    if pct <= 0.4:
        return "Below Average"
    if pct <= 0.6:
        return "Medium"
    if pct <= 0.8:
        return "Above Average"
    return "High — near the highest price seen since tracking began"


def compute_trend(history: list[dict], today_low: float | None) -> str:
    days_remaining = (GAME_DATE - date.today()).days
    lines = []

    dated = [h for h in history if h.get("seatgeek_lowest") is not None]
    if today_low is not None and len(dated) >= 1:
        yesterday = dated[-1]["seatgeek_lowest"]
        delta = today_low - yesterday
        if abs(delta) > 0.01:
            direction = "up" if delta > 0 else "down"
            lines.append(f"Day-over-day: {direction} ${abs(delta):.2f} vs. yesterday's lowest (${yesterday:.2f}).")
        else:
            lines.append("Day-over-day: essentially flat vs. yesterday.")

    if today_low is not None and len(dated) >= 7:
        week_ago = dated[-7]["seatgeek_lowest"]
        delta = today_low - week_ago
        direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
        lines.append(f"Week-over-week: {direction} ${abs(delta):.2f} vs. 7 days ago (${week_ago:.2f}).")

    # Heuristic overlay based on general NFL secondary-market pricing patterns.
    if days_remaining > 45:
        lines.append(
            "Heuristic: with 45+ days out, inventory is typically still high and prices often "
            "soften over the coming weeks as the initial post-schedule-release demand fades."
        )
    elif days_remaining > 14:
        lines.append(
            "Heuristic: this is usually the most negotiable window — far enough from game day "
            "that panic-buying hasn't started, but late enough that initial markups have cooled."
        )
    elif days_remaining > 3:
        lines.append(
            "Heuristic: inside two weeks, expect more volatility — prices can dip as sellers "
            "unload late inventory, but can also spike if local demand or weather forecasts firm up."
        )
    else:
        lines.append(
            "Heuristic: final days before kickoff — prices usually swing hardest here, either "
            "a last-minute dip (day-of especially) or a spike if the game sells out."
        )

    return " ".join(lines) if lines else "Not enough data yet to call a trend."


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def build_report(history_data: dict, seatgeek: dict | None, ticketmaster: dict | None) -> str:
    today_low = seatgeek["lowest_price"] if seatgeek else None
    history = history_data["history"]
    days_remaining = (GAME_DATE - date.today()).days
    date_str = datetime.now().strftime("%B %-d, %Y")

    rating = compute_rating(history, today_low)
    trend = compute_trend(history, today_low)

    lines = [
        f"TICKET PRICE REPORT — {EVENT_LABEL}",
        f"{VENUE} — {GAME_DATE.strftime('%A, %B %-d, %Y')} ({days_remaining} days away)",
        f"As of {date_str}",
        "=" * 60,
        "",
        "1) PRICE RATING",
        f"   {rating}",
        "",
        "2) CURRENT LOWEST PRICES",
    ]

    if seatgeek and seatgeek.get("lowest_price") is not None:
        avg = seatgeek.get("average_price")
        avg_str = f"${avg:.2f}" if avg is not None else "n/a"
        lines.append(
            f"   SeatGeek:      ${seatgeek['lowest_price']:.2f} lowest "
            f"(avg {avg_str}, {seatgeek.get('listing_count', '?')} listings)"
        )
        if seatgeek.get("url"):
            lines.append(f"                  {seatgeek['url']}")
    elif seatgeek:
        lines.append("   SeatGeek:      event found, but no listings posted yet")
        if seatgeek.get("url"):
            lines.append(f"                  {seatgeek['url']}")
    else:
        lines.append("   SeatGeek:      unavailable today")

    if ticketmaster and ticketmaster.get("min") is not None:
        lines.append(f"   Ticketmaster:  ${ticketmaster['min']:.2f} - ${ticketmaster['max']:.2f} (official price range)")
        if ticketmaster.get("url"):
            lines.append(f"                  {ticketmaster['url']}")
    else:
        lines.append("   Ticketmaster:  unavailable today")

    for site, url in STATIC_LINKS.items():
        lines.append(f"   {site}: check directly -> {url}")

    lines += [
        "",
        "3) TREND — WHERE PRICES ARE HEADED",
        f"   {trend}",
        "",
        "4) PLANNING NOTES",
    ]

    dated = [h for h in history if h.get("seatgeek_lowest") is not None]
    if dated:
        all_lows = [h["seatgeek_lowest"] for h in dated] + ([today_low] if today_low else [])
        lines.append(f"   Lowest seen since tracking began ({history_data['tracking_started']}): ${min(all_lows):.2f}")
        lines.append(f"   Highest seen since tracking began: ${max(all_lows):.2f}")
    lines.append(f"   Days until kickoff: {days_remaining}")
    if days_remaining > 14:
        lines.append(
            "   If you want better seats for the same budget, this window is usually better for "
            "upgrading than waiting — prices rarely bottom out this early AND stay low."
        )
    else:
        lines.append(
            "   Getting close — if you see a price near or below the 'Low' range above, it's "
            "reasonable to stop waiting and buy."
        )
    lines.append(
        "   Note: 'life of sale' history only covers the period since this tracker started "
        f"({history_data['tracking_started']}) — true from-day-one data isn't available via public APIs."
    )

    return "\n".join(lines)


def send_email(body: str) -> None:
    if not GMAIL_APP_PASSWORD:
        print("[ERROR] GMAIL_APP_PASSWORD not set — skipping email")
        return
    date_str = datetime.now().strftime("%B %-d, %Y")
    subject = f"Bills vs Dolphins Ticket Report — {date_str}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = NOTIFY_EMAIL
    msg["To"] = NOTIFY_EMAIL
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(NOTIFY_EMAIL, GMAIL_APP_PASSWORD)
        server.sendmail(NOTIFY_EMAIL, NOTIFY_EMAIL, msg.as_string())
    print(f"Email sent to {NOTIFY_EMAIL}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    history_data = load_history()

    seatgeek = fetch_seatgeek()
    ticketmaster = fetch_ticketmaster()

    report = build_report(history_data, seatgeek, ticketmaster)
    print(report)
    send_email(report)

    history_data["history"].append({
        "date": date.today().isoformat(),
        "seatgeek_lowest": seatgeek["lowest_price"] if seatgeek else None,
        "seatgeek_average": seatgeek["average_price"] if seatgeek else None,
        "ticketmaster_min": ticketmaster["min"] if ticketmaster else None,
        "ticketmaster_max": ticketmaster["max"] if ticketmaster else None,
    })
    save_history(history_data)


if __name__ == "__main__":
    sys.exit(main() or 0)
