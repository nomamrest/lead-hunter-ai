import sys
import os
import threading
import time

# Ensure stdout uses UTF-8 to prevent charmap/UnicodeEncodeError on Windows console
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from scraper import run_scraping_job

class DummySession:
    def __init__(self):
        self.leads = []
        self.progress = 0.0
        self.status = "idle"
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()

def log_cb(msg):
    print(f"[TEST LOG] {msg}")

def main():
    print("Starting Scraper Verification Test...")
    session = DummySession()
    # Scrape 1 bakery in Karachi
    run_scraping_job("bykers", "Karachi", 1, "Google Maps", session, log_cb)
    print("\n--- Test Completed ---")
    print(f"Status: {session.status}")
    print(f"Leads Found: {len(session.leads)}")
    if session.leads:
        print("First Lead Details:")
        for k, v in session.leads[0].items():
            print(f"  {k}: {v}")
    else:
        print("No leads found. Check Google Maps response or selectors.")

if __name__ == "__main__":
    main()
