
import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

URL = "https://testcisia.it/calendario.php"

PARAMS = {
    "tolc": "cents",
    "l": "gb",
    "lingua": "inglese",
}

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE_FILE = "seen_slots.json"


def notify(message):
    response = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )

    if not response.ok:
        print("Telegram error:", response.status_code)
        try:
            error = response.json()
            print(
                "Telegram description:",
                error.get("description", "Unknown error"),
            )
        except ValueError:
            print("Telegram returned a non-JSON error")

    response.raise_for_status()


def get_slots():
    response = requests.get(
        URL,
        params=PARAMS,
        timeout=30,
        headers={
            "User-Agent": "CEnT-S-Availability-Monitor/1.0"
        },
    )
    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    slots = []
    rows = soup.select("tr")
    parsed_rows = 0

    for row in rows:
        cells = [
            cell.get_text(" ", strip=True)
            for cell in row.find_all("td")
        ]

        if len(cells) != 8:
            continue

        parsed_rows += 1

        (
            fmt,
            university,
            region,
            city,
            deadline,
            seats,
            status,
            date,
        ) = cells

        normalized_format = fmt.upper().replace(" ", "")
        normalized_status = status.upper().strip()

        if normalized_format not in (
            "CENT@HOME",
            "CENT@CASA",
        ):
            continue

        if normalized_status.startswith(
            "NOT LONGER AVAILABLE"
        ):
            continue

        if "AVAILABLE SEATS" not in normalized_status:
            continue

        key = "|".join([
            university,
            date,
            normalized_format,
        ])

        slots.append({
            "key": key,
            "university": university,
            "date": date,
            "seats": seats,
            "city": city,
        })

    if parsed_rows == 0:
        raise RuntimeError(
            "No calendar rows were recognized. "
            "The CISIA page structure may have changed."
        )

    return slots


def main():
    slots = get_slots()

    if os.path.exists(STATE_FILE):
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            previous = set(json.load(file))
    else:
        previous = set()

    current = {
        slot["key"]
        for slot in slots
    }

    new_slots = [
        slot
        for slot in slots
        if slot["key"] not in previous
    ]

    for slot in new_slots:
        message = (
            "🟢 CEnT-S @CASA: СВОБОДНЫЕ МЕСТА!\n\n"
            f"🏛 Университет: {slot['university']}\n"
            f"📅 Дата: {slot['date']}\n"
            f"📍 Город: {slot['city']}\n"
            f"💺 Места: {slot['seats']}\n\n"
            "🔗 Календарь CISIA:\n"
            "https://testcisia.it/calendario.php"
            "?tolc=cents&l=gb&lingua=inglese\n\n"
            "Проверь наличие мест перед бронированием."
        )

        notify(message)

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            sorted(current),
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(
        datetime.now(timezone.utc).isoformat(),
        "Available HOME sessions:",
        len(slots),
    )


if __name__ == "__main__":
    if os.environ.get("TEST_TELEGRAM") == "1":
        notify(
            "✅ Тест Telegram: "
            "сообщение от трекера CEnT-S."
        )

    main()
