from playwright.sync_api import sync_playwright
import requests
import time
import re
import sqlite3

# --- CONFIG ---
TELEGRAM_TOKEN = "8650725604:AAEtgWJZoWNFl5Wjlz_r-Q5n1vEVJg83UuI"
CHAT_ID = "1996005215"

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect("prices.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT,
            app TEXT,
            product TEXT,
            price INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_search(query, app, product, price):
    conn = sqlite3.connect("prices.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO searches (query, app, product, price)
        VALUES (?, ?, ?, ?)
    """, (query, app, product, price))
    conn.commit()
    conn.close()

# --- TELEGRAM ---
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_telegram_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 30, "offset": offset}
    try:
        r = requests.get(url, params=params, timeout=35)
        return r.json().get("result", [])
    except:
        return []

# --- HELPERS ---
def normalize(text):
    text = text.lower().strip()
    text = re.sub(r'\s+', '', text)
    text = re.sub(r'litre|liter|ltr', 'l', text)
    text = re.sub(r'ml', '', text)
    return text

def parse_price(price_str):
    cleaned = re.sub(r'[^\d]', '', price_str)
    return int(cleaned) if cleaned else None

# --- BLINKIT SCRAPER ---
def get_blinkit_price(page, search_query, target_product):
    results = []

    def handle_response(response):
        if "v1/layout/search" in response.url:
            try:
                results.append(response.json())
            except:
                pass

    page.on("response", handle_response)

    page.context.add_cookies([
        {"name": "gr_1_deviceId",    "value": "164654b6-a383-4451-9aea-79e1ffa9e797", "domain": "blinkit.com", "path": "/"},
        {"name": "gr_1_locality",    "value": "1849",                                  "domain": "blinkit.com", "path": "/"},
        {"name": "gr_1_lat",         "value": "28.4132534",                            "domain": "blinkit.com", "path": "/"},
        {"name": "gr_1_lon",         "value": "77.07271589999999",                     "domain": "blinkit.com", "path": "/"},
        {"name": "gr_1_accessToken", "value": "v2%3A%3A0bfe4f8e-a18b-4be6-b967-a89a999d9b2c", "domain": "blinkit.com", "path": "/"},
        {"name": "__cf_bm",          "value": "zrcyX.DRGmh8fxt413XCBekn3RG760PRprZ_lcyq5V8-1775218896-1.0.1.1-jc1XiJI02bcGUlg9Z_KoeWdyxI_258wbkIbqo_sRsD7Xn3pbligFIwWQTREutKu0rr.C6LNo1y3e.061OjAPh63xIYzhcV0Iv_AhaP1WQjM", "domain": "blinkit.com", "path": "/"},
    ])

    page.goto(f"https://blinkit.com/s/?q={search_query}")
    page.wait_for_timeout(8000)
    page.remove_listener("response", handle_response)

    if not results:
        return None

    target_words = target_product.lower().split()
    snippets = results[0].get("response", {}).get("snippets", [])
    for snippet in snippets:
        try:
            d = snippet["data"]
            name = d["name"]["text"]
            variant = d["variant"]["text"]
            full_name = f"{name} {variant}"
            if any(word in full_name.lower() for word in target_words if len(word) > 3):
                return {
                    "name": full_name,
                    "price": d["normal_price"]["text"],
                    "in_stock": not d["is_sold_out"],
                }
        except:
            pass
    return None

# --- ZEPTO SCRAPER ---
def get_zepto_price(page, search_query, target_product):
    try:
        page.goto(
            f"https://www.zepto.com/search?query={search_query}",
            timeout=60000,
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(8000)
        text = page.evaluate("() => document.body.innerText")
    except Exception as e:
        print(f"Zepto error: {e}")
        return None

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    target_words = target_product.lower().split()

    products = []
    i = 0
    while i < len(lines):
        if re.match(r'^₹\d+$', lines[i]):
            price = lines[i]
            for j in range(i + 1, min(i + 5, len(lines))):
                if (len(lines[j]) > 15
                        and '₹' not in lines[j]
                        and 'OFF' not in lines[j]
                        and 'ADD' not in lines[j]):
                    products.append({"name": lines[j], "price": price})
                    break
        i += 1

    for product in products:
        if any(word in product["name"].lower() for word in target_words if len(word) > 3):
            return product
    return None

# --- SEARCH HANDLER ---
def handle_search(query):
    print(f"\n🔍 Searching: {query}")
    send_telegram(f"🔍 Searching for '{query}'...")

    app_prices = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        # Blinkit
        try:
            page = browser.new_page()
            result = get_blinkit_price(page, query, query)
            page.close()
            if result:
                app_prices["Blinkit"] = {
                    "price": parse_price(result["price"]),
                    "name": result["name"],
                    "in_stock": result["in_stock"]
                }
                save_search(query, "blinkit", result["name"], parse_price(result["price"]))
        except Exception as e:
            print(f"  Blinkit error: {e}")

        time.sleep(2)

        # Zepto
        try:
            page = browser.new_page()
            result = get_zepto_price(page, query, query)
            page.close()
            if result:
                app_prices["Zepto"] = {
                    "price": parse_price(result["price"]),
                    "name": result["name"],
                    "in_stock": True
                }
                save_search(query, "zepto", result["name"], parse_price(result["price"]))
        except Exception as e:
            print(f"  Zepto error: {e}")

        browser.close()

    # build message
    if app_prices:
        cheapest_app = min(app_prices, key=lambda x: app_prices[x]["price"])

        lines = []
        for app, data in sorted(app_prices.items(), key=lambda x: x[1]["price"]):
            trophy = "🏆" if app == cheapest_app else "  "
            stock = "✅" if data["in_stock"] else "❌ OOS"
            lines.append(f"{trophy} {app}: ₹{data['price']} {stock}\n      {data['name']}")

        message = f"🛒 Results for '{query}'\n"
        message += "─────────────────\n"
        message += "\n\n".join(lines)
        message += f"\n\n💰 Best price: {cheapest_app} at ₹{app_prices[cheapest_app]['price']}"
    else:
        message = f"❌ Could not find '{query}' on any app"

    print(message)
    send_telegram(message)

# --- MAIN ---
init_db()

print("🚀 Price bot started!")
send_telegram("🛒 Price bot is ready!\nSend me any product name!")

offset = None

while True:
    try:
        updates = get_telegram_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            try:
                text = update["message"]["text"].strip()
                if text:
                    handle_search(text)
            except Exception as e:
                print(f"Error: {e}")
                send_telegram("❌ Something went wrong, try again!")
    except Exception as e:
        print(f"Loop error: {e}")
        time.sleep(5) 