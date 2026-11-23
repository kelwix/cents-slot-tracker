
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://testcisia.it/calendario.php"
STATE_FILE = Path(__file__).with_name("seen_slots.json")

CALENDARS = [
    {"tolc": "cents", "l": "gb", "lingua": "inglese"},
    {"tolc": "cents", "l": "it", "lingua": "inglese"},
]

CLOSED_STATUSES = (
    "NOT LONGER AVAILABLE",
    "NO AVAILABLE SEATS",
    "NO SEATS AVAILABLE",
    "POSTI ESAURITI",
    "CLOSED BOOKINGS",
    "BOOKINGS CLOSED",
    "REGISTRATION CLOSED",
    "REGISTRATIONS CLOSED",
    "ISCRIZIONI CHIUSE",
    "ISCRIZIONI CONCLUSE",
    "PRENOTAZIONI CHIUSE",
)

AVAILABLE_STATUSES = (
    "AVAILABLE SEATS",
    "POSTI DISPONIBILI",
)


def normalize(value):
    return " ".join(value.upper().split())


def telegram_recipients():
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()

    ids = [
        os.environ["TELEGRAM_CHAT_ID"].strip(),
        os.environ["TELEGRAM_CHAT_ID_2"].strip(),
    ]

    if not token or not all(ids):
        raise RuntimeError(
            "Telegram token or one of the chat IDs is empty"
        )

    return token, list(dict.fromkeys(ids))


def send_telegram(message, token, chat_ids):
    for chat_id in chat_ids:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )

        if not response.ok:
            try:
                description = response.json().get(
                    "description",
                    response.text,
                )
            except ValueError:
                description = response.text

            raise RuntimeError(
                f"Telegram failed for chat ending in "
                f"{chat_id[-4:]}: "
                f"HTTP {response.status_code}: {description}"
            )


def parse_status(status):
    status = normalize(status)

    # Check closed statuses first.
    if any(
        phrase in status
        for phrase in CLOSED_STATUSES
    ):
        return False

    if any(
        phrase in status
        for phrase in AVAILABLE_STATUSES
    ):
        return True

    return None


def get_calendar(params):
    response = requests.get(
        URL,
        params=params,
        headers={
            "User-Agent": (
                "Mozilla/5.0 CEnT-S Availability Monitor"
            )
        },
        timeout=40,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    sessions = {}
    home_rows = 0
    unknown_rows = 0

    for row in soup.select("tr"):
        cells = [
            cell.get_text(" ", strip=True)
            for cell in row.find_all(
                "td",
                recursive=False,
            )
        ]

        if len(cells) != 8:
            continue

        (
            exam_format,
            university,
            _region,
            city,
            deadline,
            seats,
            status,
            exam_date,
        ) = cells

        exam_format = normalize(
            exam_format
        ).replace(" ", "")

        # ONLY HOME / CASA
        if exam_format not in (
            "CENT@HOME",
            "CENT@CASA",
        ):
            continue

        home_rows += 1

        available = parse_status(status)

        if available is None:
            unknown_rows += 1

            print(
                f"WARNING: Unknown HOME status "
                f"{status!r} for {university}, "
                f"{exam_date}"
            )

            continue

        # CASA and HOME are the same online format.
        exam_format = "CENT@HOME"

        key = "|".join([
            normalize(university),
            normalize(city),
            exam_date.strip(),
            exam_format,
        ])

        count_match = re.search(
            r"\d+",
            seats,
        )

        count = (
            int(count_match.group())
            if count_match
            else None
        )

        session = {
            "university": university,
            "city": city,
            "date": exam_date.strip(),
            "format": exam_format,
            "seats": count,
            "available": available,
            "deadline": deadline,
        }

        if (
            key in sessions
            and sessions[key] != session
        ):
            raise RuntimeError(
                f"Conflicting duplicate calendar rows: {key}"
            )

        sessions[key] = session

    if home_rows == 0:
        raise RuntimeError(
            "No HOME/CASA rows found. "
            "CISIA may have changed its calendar."
        )

    if not sessions:
        raise RuntimeError(
            "All HOME/CASA statuses were unrecognized. "
            "No safe check possible."
        )

    print(
        f"Calendar {params['l']}: "
        f"{len(sessions)} HOME sessions, "
        f"{unknown_rows} unrecognized status(es)"
    )

    return sessions


def collect_sessions():
    merged = {}

    for params in CALENDARS:
        sessions = get_calendar(params)

        for key, session in sessions.items():
            if key not in merged:
                merged[key] = session
                continue

            old = merged[key]

            if (
                old["available"]
                != session["available"]
            ):
                print(
                    "WARNING: Language versions "
                    "disagree about availability:",
                    key,
                )

                if session["available"]:
                    merged[key] = session

            elif old["seats"] != session["seats"]:
                print(
                    "WARNING: Language versions "
                    "disagree about seat count:",
                    key,
                )

                if (
                    old["seats"] is None
                    and session["seats"] is not None
                ):
                    merged[key] = session

    return merged


def load_history():
    if not STATE_FILE.exists():
        print(
            "No saved history; available sessions "
            "will be announced once."
        )
        return {}

    with STATE_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        saved = json.load(file)

    if isinstance(saved, dict):
        return saved

    if isinstance(saved, list):
        print(
            "Old list-format history found; "
            "starting a new history."
        )
        return {}

    raise RuntimeError(
        "Invalid seen_slots.json format"
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


def save_history(history):
    temp_file = STATE_FILE.with_suffix(
        ".json.tmp"
    )

    with temp_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            history,
            file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")

    temp_file.replace(STATE_FILE)


def main():
    token, chat_ids = telegram_recipients()

    sessions = collect_sessions()
    previous = load_history()

    # Keep history for temporarily missing rows.
    current = previous.copy()

    notifications = 0

    for key, session in sessions.items():
        available = session["available"]
        seats = session["seats"]
        old = previous.get(key)

        current[key] = {
            "available": available,
            "seats": seats,
        }

        if not available:
            continue

        if not isinstance(old, dict):
            reason = "Обнаружена доступная сессия"

        elif not old.get("available", False):
            reason = "Регистрация снова открылась"

        elif (
            isinstance(old.get("seats"), int)
            and isinstance(seats, int)
            and old["seats"] != seats
        ):
            reason = "Изменилось количество мест"

        else:
            continue

        send_telegram(
            make_message(session, reason),
            token,
            chat_ids,
        )

        notifications += 1

    save_history(current)

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
        sum(
            s["available"]
            for s in sessions.values()
        ),
    )

    print(
        "Notifications sent to each recipient:",
        notifications,
    )

    print(
        "Recipients:",
        len(chat_ids),
    )


if __name__ == "__main__":
    main()
