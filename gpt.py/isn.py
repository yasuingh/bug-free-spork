from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    page.goto("https://www.swiggy.com/instamart/search?query=diet coke", 
              timeout=90000, 
              wait_until="domcontentloaded")
    page.wait_for_timeout(10000)
    
    text = page.evaluate("() => document.body.innerText")
    
    with open("instamart_text.txt", "w") as f:
        f.write(text)
    
    print("Saved!")
    print(text[:500])
    
    browser.close()