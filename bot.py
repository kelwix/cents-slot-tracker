import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


URL = "https://testcisia.it/calendario.php"
STATE_FILE = Path("seen_slots.json")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

CHAT_IDS = [
    os.environ["TELEGRAM_CHAT_ID"],
    os.environ["TELEGRAM_CHAT_ID_2"],
]

CALENDARS = [
    {"tolc": "cents", "l": "gb", "lingua": "inglese"},
    {"tolc": "cents", "l": "it", "lingua": "inglese"},
]


def send_telegram(message):
    for chat_id in CHAT_IDS:
        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )

        if not response.ok:
            try:
                print(
                    "Telegram error:",
                    chat_id,
                    response.json().get("description"),
                )
            except ValueError:
                print(
                    "Telegram HTTP error:",
                    response.status_code,
                )

        response.raise_for_status()


def normalize(text):
    return " ".join(text.upper().split())


def get_calendar(params):
    response = requests.get(
        URL,
        params=params,
        headers={
            "User-Agent": "Mozilla/5.0 CEnT-S Availability Monitor"
        },
        timeout=40,
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    sessions = {}
    recognized = 0

    for row in soup.select("tr"):
        cells = [
            cell.get_text(" ", strip=True)
            for cell in row.find_all("td", recursive=False)
        ]

        if len(cells) != 8:
            continue

        (
            exam_format,
            university,
            region,
            city,
            deadline,
            seats,
            status,
            exam_date,
        ) = cells

        exam_format = normalize(exam_format).replace(" ", "")
        status = normalize(status)

        # ONLY HOME / CASA
        if exam_format not in (
            "CENT@HOME",
            "CENT@CASA",
        ):
            continue

        recognized += 1

        if exam_format == "CENT@CASA":
            exam_format = "CENT@HOME"

        available = (
            "AVAILABLE SEATS" in status
            or "POSTI DISPONIBILI" in status
        )

        closed = (
            "NOT LONGER AVAILABLE" in status
            or "POSTI ESAURITI" in status
            or "CLOSED BOOKINGS" in status
            or "ISCRIZIONI CHIUSE" in status
            or "ISCRIZIONI CONCLUSE" in status
        )

        if not available and not closed:
            raise RuntimeError(
                f"Unknown CISIA status: {status}"
            )

        key = "|".join([
            normalize(university),
            normalize(city),
            exam_date.strip(),
            exam_format,
        ])

        count_match = re.search(r"\d+", seats)

        count = (
            int(count_match.group())
            if count_match
            else None
        )

        sessions[key] = {
            "university": university,
            "city": city,
            "date": exam_date,
            "format": exam_format,
            "seats": count,
            "available": available,
            "deadline": deadline,
        }

    if recognized == 0:
        raise RuntimeError(
            "No CEnT-S HOME sessions recognized. "
            "CISIA calendar structure may have changed."
        )

    return sessions


def collect_sessions():
    merged = {}

    for params in CALENDARS:
        sessions = get_calendar(params)

        print(
            "Calendar language:",
            params["l"],
            "| HOME sessions:",
            len(sessions),
        )

        for key, session in sessions.items():
            if key not in merged:
                merged[key] = session

            elif merged[key]["available"] != session["available"]:
                raise RuntimeError(
                    "English and Italian availability disagree: "
                    + key
                )

    return merged


def load_history():
    if not STATE_FILE.exists():
        return {}

    with STATE_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        saved = json.load(file)

    if isinstance(saved, dict):
        return saved

    if isinstance(saved, list):
        return {}

    raise RuntimeError(
        "Invalid notification history format"
    )


def make_message(session, reason):
    seats = session["seats"]

    seats_text = (
        str(seats)
        if seats is not None
        else "уточнить"
    )

    return (
        "🟢 CEnT-S — СВОБОДНЫЕ МЕСТА!\n\n"
        f"🔔 {reason}\n"
        f"🏛 Университет: {session['university']}\n"
        f"📍 Город: {session['city']}\n"
        "🏠 Формат: CEnT@CASA / CEnT@HOME\n"
        f"📅 Дата экзамена: {session['date']}\n"
        f"💺 Свободных мест: {seats_text}\n"
        f"⏳ Конец регистрации: {session['deadline']}\n\n"
        "🔗 https://testcisia.it/calendario.php"
        "?tolc=cents&l=it&lingua=inglese\n\n"
        "Места могут закончиться до бронирования."
    )


def main():
    sessions = collect_sessions()
    previous = load_history()

    current = {}
    notifications = 0

    for key, session in sessions.items():
        available = session["available"]
        seats = session["seats"]

        current[key] = {
            "available": available,
            "seats": seats,
        }

        if not available:
            continue

        old = previous.get(key)

        if old is None:
            reason = "Обнаружена доступная сессия"

        elif (
            isinstance(old, dict)
            and not old.get("available")
        ):
            reason = "Регистрация снова открылась"

        elif (
            isinstance(old, dict)
            and old.get("seats") != seats
        ):
            reason = "Изменилось количество мест"

        else:
            continue

        send_telegram(
            make_message(session, reason)
        )

        notifications += 1

    with STATE_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            current,
            file,
            ensure_ascii=False,
            indent=2,
        )

    available_count = sum(
        1
        for session in sessions.values()
        if session["available"]
    )

    print(
        "Checked:",
        datetime.now(timezone.utc).isoformat(),
    )

    print(
        "Total HOME sessions:",
        len(sessions),
    )

    print(
        "Available HOME sessions:",
        available_count,
    )

    print(
        "Notifications sent:",
        notifications,
    )


if __name__ == "__main__":
    main()
