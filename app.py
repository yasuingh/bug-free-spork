from flask import Flask, request, jsonify, send_from_directory
from playwright.sync_api import sync_playwright
import re
import sqlite3
import os

app = Flask(__name__)

# --- HELPERS ---
def parse_price(price_str):
    cleaned = re.sub(r'[^\d]', '', price_str)
    return int(cleaned) if cleaned else None

def save_search(query, app_name, product, price):
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
    cursor.execute("""
        INSERT INTO searches (query, app, product, price)
        VALUES (?, ?, ?, ?)
    """, (query, app_name, product, price))
    conn.commit()
    conn.close()

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

# --- API ROUTE ---
@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "No query provided"}), 400

    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        # Blinkit
        try:
            page = browser.new_page()
            result = get_blinkit_price(page, query, query)
            page.close()
            if result:
                price_num = parse_price(result["price"])
                results["Blinkit"] = {
                    "name": result["name"],
                    "price": price_num,
                    "in_stock": result["in_stock"]
                }
                save_search(query, "blinkit", result["name"], price_num)
        except Exception as e:
            print(f"Blinkit error: {e}")

        # Zepto
        try:
            page = browser.new_page()
            result = get_zepto_price(page, query, query)
            page.close()
            if result:
                price_num = parse_price(result["price"])
                results["Zepto"] = {
                    "name": result["name"],
                    "price": price_num,
                    "in_stock": True
                }
                save_search(query, "zepto", result["name"], price_num)
        except Exception as e:
            print(f"Zepto error: {e}")

        browser.close()

    if not results:
        return jsonify({"error": "No results found"}), 404

    cheapest = min(results, key=lambda x: results[x]["price"])
    return jsonify({
        "query": query,
        "results": results,
        "cheapest": cheapest
    })

# --- SERVE FRONTEND ---
@app.route("/")
def index():
    return send_from_directory(".", "index.html")

if __name__ == "__main__":
    app.run(debug=True, port=5000)