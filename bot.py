
import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

URL = "https://testcisia.it/calendario.php"
PARAMS = {
    "tolc": "cents",
    "l": "gb",
    "lingua": "inglese"
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
            "disable_web_page_preview": True
        },
        timeout=20
    )
    response.raise_for_status()


def get_slots():
    response = requests.get(
        URL,
        params=PARAMS,
        timeout=30,
        headers={"User-Agent": "CEnT-S-Availability-Monitor/1.0"}
    )
    if not response.ok:
    print("Telegram error:", response.status_code)
    print("Telegram response:", response.text)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    slots = []

    for row in soup.select("tr"):
        cells = [
            cell.get_text(" ", strip=True)
            for cell in row.find_all(["td"])
        ]

        if len(cells) != 8:
            continue

        fmt, university, region, city, deadline, seats, status, date = cells

        if fmt.upper() not in ("CENT@HOME", "CENT@CASA"):
            continue

        if "AVAILABLE SEATS" not in status.upper():
            continue

        key = "|".join([university, date, fmt])

        slots.append({
            "key": key,
            "university": university,
            "date": date,
            "seats": seats,
            "city": city
        })

    return slots


def main():
    slots = get_slots()

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            previous = set(json.load(f))
    else:
        previous = set()

    current = {slot["key"] for slot in slots}

    for slot in slots:
        if slot["key"] not in previous:
            message = (
                "🟢 CEnT-S @CASA: СВОБОДНЫЕ МЕСТА!\n\n"
                f"🏛 Университет: {slot['university']}\n"
                f"📅 Дата: {slot['date']}\n"
                f"📍 Город университета: {slot['city']}\n"
                f"💺 Места: {slot['seats']}\n\n"
                f"🔗 {URL}?tolc=cents&l=gb&lingua=inglese\n\n"
                "Проверь доступность перед бронированием."
            )
            notify(message)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(current), f, ensure_ascii=False, indent=2)

    print(
        f"{datetime.now(timezone.utc).isoformat()} "
        f"Available HOME sessions: {len(slots)}"
    )


if __name__ == "__main__":
    notify("✅ Тест успешен! Трекер CEnT-S подключён к Telegram.")
    main()
