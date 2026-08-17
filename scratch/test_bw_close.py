from playwright.sync_api import sync_playwright
import time

print("Starting playwright...")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://example.com")
    time.sleep(1)
    print("Closing page...")
    page.close()
    print("Closing context...")
    context.close()
    print("Closing browser...")
    browser.close()
    print("Browser closed successfully!")
