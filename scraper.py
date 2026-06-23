import os
import re
import time
import random
import urllib.parse
import pandas as pd
from bs4 import BeautifulSoup
import httpx
from playwright.sync_api import sync_playwright

# List of common User-Agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0"
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def clean_phone(phone_str):
    if not phone_str:
        return ""
    # Strip non-numeric/non-plus characters, keeping spaces/hyphens for readability
    cleaned = re.sub(r'[^\d+\-\s\(\)]', '', phone_str)
    return cleaned.strip()

def extract_owner_name_from_title(title, business_name):
    """
    Heuristics to extract owner/founder name from search result title.
    Example: "Jane Doe - Owner & Founder - Sweet Delights | LinkedIn"
    """
    # Remove platform suffixes
    title = re.sub(r'\|.*$', '', title) # Remove everything after |
    title = re.sub(r'\-.*LinkedIn.*$', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\-.*Facebook.*$', '', title, flags=re.IGNORECASE)
    
    # Split by delimiters
    parts = [p.strip() for p in re.split(r'[-–•:]', title) if p.strip()]
    
    job_titles = ["owner", "founder", "ceo", "partner", "director", "manager", "chef", "baker", "president", "proprietor"]
    
    for part in parts:
        lower_part = part.lower()
        if len(part) < 3 or len(part) > 30:
            continue
        # Skip parts containing business name or parts of it
        b_words = business_name.lower().split()
        if any(w in lower_part for w in b_words if len(w) > 2):
            continue
        # Skip job titles
        if any(jt in lower_part for jt in job_titles):
            continue
        # Skip common words
        if lower_part in ["linkedin", "facebook", "instagram", "home", "contact"]:
            continue
        return part
    
    # Fallback to first part if it doesn't contain business name or job titles
    if parts:
        first = parts[0]
        if not any(jt in first.lower() for jt in job_titles) and len(first) < 30:
            return first
    return ""

def crawl_website_for_contacts(url, log_callback):
    """
    Crawls website home and contacts pages to find email, phone, and social links.
    """
    log_callback(f"[INFO] Crawling website for direct contacts: {url}")
    emails = set()
    phones = set()
    social_links = {
        "linkedin": "",
        "facebook": "",
        "instagram": "",
        "twitter": "",
        "tiktok": "",
        "youtube": ""
    }
    
    headers = {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    # Normalise URL
    if not url.startswith("http"):
        url = "http://" + url
        
    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=10.0, verify=False) as client:
            # Fetch home page
            response = client.get(url)
            if response.status_code != 200:
                log_callback(f"[WARNING] Website {url} returned status {response.status_code}")
                return emails, phones, social_links
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Find candidate pages (Contact, About, Info, etc.)
            links_to_crawl = [url]
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                text = a_tag.text.strip().lower()
                
                # Check for contact-related keywords in text or href
                is_contact = any(k in text or k in href.lower() for k in ["contact", "about", "team", "legal", "terms", "privacy"])
                if is_contact:
                    # Construct absolute URL
                    abs_url = urllib.parse.urljoin(url, href)
                    # Filter same domain
                    if urllib.parse.urlparse(abs_url).netloc == urllib.parse.urlparse(url).netloc:
                        if abs_url not in links_to_crawl and len(links_to_crawl) < 4:
                            links_to_crawl.append(abs_url)
            
            # Crawl collected pages
            email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
            # Standard international/local phone regex
            phone_pattern = re.compile(r'\+?[0-9]{1,4}[-. ]?\(?[0-9]{1,3}?\)?[-. ]?[0-9]{1,4}[-. ]?[0-9]{1,4}[-. ]?[0-9]{1,9}')
            
            for page_url in links_to_crawl:
                if page_url != url:
                    time.sleep(random.uniform(0.5, 1.5))
                    try:
                        resp = client.get(page_url)
                        if resp.status_code == 200:
                            page_soup = BeautifulSoup(resp.text, "html.parser")
                        else:
                            continue
                    except Exception:
                        continue
                else:
                    page_soup = soup
                    
                text_content = page_soup.get_text()
                
                # Email search
                found_emails = email_pattern.findall(text_content)
                for email in found_emails:
                    # Filter out common false positives (e.g. image extensions, placeholder emails)
                    if not any(email.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]) and "example.com" not in email:
                        emails.add(email.lower())
                
                # Phone search
                found_phones = phone_pattern.findall(text_content)
                for ph in found_phones:
                    cleaned = clean_phone(ph)
                    if len(cleaned.replace(" ", "").replace("-", "")) >= 9:
                        phones.add(cleaned)
                        
                # Social Links search
                for a in page_soup.find_all("a", href=True):
                    href = a["href"]
                    for platform in social_links.keys():
                        if platform in href and not social_links[platform]:
                            social_links[platform] = href
                            
    except Exception as e:
        log_callback(f"[WARNING] Error crawling website {url}: {e}")
        
    return emails, phones, social_links

def search_owner_on_google(playwright_context, business_name, log_callback):
    """
    Search Google to find Owner/Founder LinkedIn or Facebook profiles.
    """
    log_callback(f"[INFO] Hunting socials/owner for: {business_name}")
    search_query = f'site:linkedin.com/in/ OR site:facebook.com "{business_name}" AND ("Owner" OR "Founder" OR "CEO" OR "Partner")'
    
    browser = playwright_context.chromium.launch(headless=True)
    context = browser.new_context(user_agent=get_random_user_agent())
    page = context.new_page()
    
    owner_name = ""
    profile_link = ""
    
    try:
        # Implement a search query URL
        google_url = f"https://www.google.com/search?q={urllib.parse.quote(search_query)}"
        page.goto(google_url, wait_until="domcontentloaded", timeout=15000)
        
        # Wait a short random delay
        time.sleep(random.uniform(2.0, 4.0))
        
        # Select search result anchors
        # Google search results are typically in a h3 inside a div.g or inside anchors
        results = page.locator('div.g').all()
        for res in results:
            anchor = res.locator('a').first
            title_el = res.locator('h3').first
            
            if anchor.count() > 0 and title_el.count() > 0:
                href = anchor.get_attribute("href")
                title = title_el.text_content()
                
                if href and ("linkedin.com/in/" in href or "facebook.com" in href):
                    profile_link = href
                    owner_name = extract_owner_name_from_title(title, business_name)
                    if owner_name:
                        log_callback(f"[INFO] Found owner: {owner_name} via {profile_link}")
                        break
        
        # Fallback if LinkedIn/Facebook specific not found, check any result link for CEO/Owner search
        if not owner_name:
            # Let's try parsing title headers generally from any result on the first page
            anchors = page.locator('a[href*="linkedin.com/in/"], a[href*="facebook.com/"]').all()
            for a in anchors:
                href = a.get_attribute("href")
                title = a.locator('h3').first.text_content() if a.locator('h3').first.count() > 0 else ""
                if href and title:
                    profile_link = href
                    owner_name = extract_owner_name_from_title(title, business_name)
                    if owner_name:
                        log_callback(f"[INFO] Found owner (fallback): {owner_name} via {profile_link}")
                        break
                        
    except Exception as e:
        log_callback(f"[WARNING] Error during owner search: {e}")
    finally:
        browser.close()
        
    return owner_name, profile_link

def run_google_maps_scrape(playwright_context, query, location, max_results, session, log_callback, crawl_websites=True, hunt_owners=True):
    """
    Scrapes targets from Google Maps.
    """
    log_callback(f"[INFO] Starting Google Maps search for '{query}' in '{location}'")
    browser = playwright_context.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=get_random_user_agent(),
        viewport={"width": 1280, "height": 800}
    )
    page = context.new_page()
    
    search_url = f"https://www.google.com/maps/search/{urllib.parse.quote(f'{query} {location}')}"
    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    
    # Wait for page load
    time.sleep(3.0)
    
    # Check if redirected directly to a single result
    curr_url = page.url
    place_links = []
    
    if "/maps/place/" in curr_url:
        log_callback("[INFO] Single search result matched; parsing directly.")
        place_links = [curr_url]
    else:
        # We are on the search results feed
        feed_selector = 'div[role="feed"]'
        try:
            page.wait_for_selector(feed_selector, timeout=10000)
        except Exception:
            log_callback("[WARNING] Search results feed element not found. Attempting fallback card collection.")
        
        # Scroll loop to collect up to max_results links
        last_len = 0
        no_change_count = 0
        
        while len(place_links) < max_results and no_change_count < 10:
            # Check pause/stop
            if session.stop_event.is_set():
                break
            while session.pause_event.is_set():
                time.sleep(1.0)
                if session.stop_event.is_set():
                    break
            
            # Scroll feed
            try:
                feed_el = page.locator(feed_selector).first
                if feed_el.count() > 0:
                    feed_el.evaluate("el => el.scrollBy(0, 1000)")
                else:
                    # Fallback scroll page body
                    page.evaluate("window.scrollBy(0, 1000)")
            except Exception:
                pass
                
            time.sleep(2.0) # Wait for network
            
            # Collect anchors containing maps/place
            anchors = page.locator('a[href*="/maps/place/"]').all()
            current_urls = []
            for a in anchors:
                href = a.get_attribute("href")
                if href and href not in current_urls:
                    current_urls.append(href)
            
            # Filter unique and update place_links
            for u in current_urls:
                if u not in place_links:
                    place_links.append(u)
            
            if len(place_links) == last_len:
                no_change_count += 1
            else:
                no_change_count = 0
                last_len = len(place_links)
                
            log_callback(f"[INFO] Discovered {len(place_links)} lead URLs so far...")
            if len(place_links) >= max_results:
                break
                
        # Limit to max_results
        place_links = place_links[:max_results]
        
    log_callback(f"[INFO] Discovered {len(place_links)} final URLs to details scrape.")
    
    # Details extraction loop
    leads_scraped = 0
    for idx, link in enumerate(place_links):
        if session.stop_event.is_set():
            log_callback("[INFO] Scraping stopped by user.")
            break
            
        while session.pause_event.is_set():
            time.sleep(1.0)
            if session.stop_event.is_set():
                break
                
        log_callback(f"[INFO] Scraping lead details {idx+1}/{len(place_links)}...")
        
        try:
            page.goto(link, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2.0)
            
            # Extract Details
            # 1. Name
            name = ""
            h1s = page.locator('h1').all()
            for h in h1s:
                txt = h.text_content()
                if txt:
                    name = txt.strip()
                    break
            
            if not name:
                log_callback(f"[WARNING] Could not find business name at {link}. Skipping.")
                continue
                
            # 2. Category
            category = "Food Business"
            category_el = page.locator('button[class*="fontBodyMedium"]').first
            if category_el.count() > 0:
                category = category_el.text_content().strip()
            else:
                # Alternate category selector
                cat_el = page.locator('span[class*="fontBodyMedium"]').first
                if cat_el.count() > 0:
                    category = cat_el.text_content().strip()
            
            # 3. Address
            address = ""
            address_el = page.locator('button[data-item-id="address"]').first
            if address_el.count() > 0:
                address = address_el.text_content().strip()
            else:
                # Alternate address elements containing location markers
                addr_el = page.locator('div[class*="Io6YTe"]').first
                if addr_el.count() > 0:
                    address = addr_el.text_content().strip()
                    
            # 4. Phone
            phone = ""
            phone_el = page.locator('button[data-item-id*="phone:tel:"]').first
            if phone_el.count() > 0:
                phone_raw = phone_el.get_attribute("data-item-id")
                # Extract phone number from data-item-id e.g. "phone:tel:+923001234567"
                phone = phone_raw.replace("phone:tel:", "").strip()
            else:
                # Alternate phone lookup in standard text matches
                phones_els = page.locator('button[class*="CsEnBe"]').all()
                for el in phones_els:
                    label = el.get_attribute("aria-label")
                    if label and "Phone:" in label:
                        phone = label.replace("Phone:", "").strip()
                        break
            
            phone = clean_phone(phone)
            
            # 5. Website
            website = ""
            website_el = page.locator('a[data-item-id="authority"]').first
            if website_el.count() > 0:
                website = website_el.get_attribute("href")
            else:
                # Alternate website link
                web_els = page.locator('a[class*="CsEnBe"]').all()
                for el in web_els:
                    label = el.get_attribute("aria-label")
                    if label and "Website:" in label:
                        website = el.get_attribute("href")
                        break
                        
            # Create base lead dict
            lead = {
                "Business Name": name,
                "Category": category,
                "Physical Address / Location": address,
                "Business Phone Number": phone,
                "Public Email Address": "",
                "Official Website": website,
                "Facebook Link": "",
                "Instagram Link": "",
                "LinkedIn Link": "",
                "Twitter Link": "",
                "TikTok Link": "",
                "YouTube Link": "",
                "Estimated Owner Name (Enriched)": "",
                "Owner Profile Link (LinkedIn/Facebook)": "",
                "Source URL": link
            }
            
            # 6. Autonomous Enrichment
            # A. Website Crawling
            if website and crawl_websites:
                web_emails, web_phones, web_socials = crawl_website_for_contacts(website, log_callback)
                if web_emails:
                    lead["Public Email Address"] = ", ".join(list(web_emails))
                if web_phones and not lead["Business Phone Number"]:
                    lead["Business Phone Number"] = list(web_phones)[0]
                
                # Save crawled socials directly into their respective columns
                for platform in ["facebook", "instagram", "linkedin", "twitter", "tiktok", "youtube"]:
                    if web_socials[platform]:
                        lead[f"{platform.capitalize()} Link"] = web_socials[platform]
            
            # B. Social Hunting for Owner
            if hunt_owners:
                owner_name, owner_profile = search_owner_on_google(playwright_context, name, log_callback)
                if owner_name:
                    lead["Estimated Owner Name (Enriched)"] = owner_name
                if owner_profile and not lead["Owner Profile Link (LinkedIn/Facebook)"]:
                    lead["Owner Profile Link (LinkedIn/Facebook)"] = owner_profile
                
            # Contact Fallback
            if not lead["Estimated Owner Name (Enriched)"]:
                lead["Estimated Owner Name (Enriched)"] = "N/A - Public Contact Saved"
                
            session.leads.append(lead)
            leads_scraped += 1
            session.progress = float(leads_scraped) / len(place_links)
            
            log_callback(f"[SUCCESS] Scraped & Enriched: '{name}'")
            
            # Incremental save every 5 leads
            if len(session.leads) % 5 == 0:
                save_incremental(session.leads, log_callback)
                log_callback(f"[INFO] Saved {len(session.leads)} leads incrementally to 'food_leads.csv'")
                
            # Random delay
            time.sleep(random.uniform(2.0, 4.0))
            
        except Exception as ex:
            log_callback(f"[WARNING] Error scraping details for {link}: {ex}")
            continue
            
    browser.close()

def run_foodpanda_scrape(playwright_context, query, location, max_results, session, log_callback, crawl_websites=True, hunt_owners=True):
    """
    Simulates Foodpanda scraping by searching Google to bypass direct UI blocking,
    extracting listings, and parsing info.
    """
    log_callback(f"[INFO] Starting Foodpanda simulation for '{query}' in '{location}'")
    browser = playwright_context.chromium.launch(headless=True)
    context = browser.new_context(user_agent=get_random_user_agent())
    page = context.new_page()
    
    # Build search query for Google
    search_query = f'site:foodpanda.pk/restaurant/ "{location}" "{query}"'
    google_url = f"https://www.google.com/search?q={urllib.parse.quote(search_query)}"
    
    log_callback(f"[INFO] Querying Google: {search_query}")
    try:
        page.goto(google_url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(3.0)
        
        # Extract foodpanda restaurant page links from Google results
        anchors = page.locator('a[href*="foodpanda."]').all()
        urls = []
        for a in anchors:
            href = a.get_attribute("href")
            if href and "/restaurant/" in href and href not in urls:
                urls.append(href)
                
        # Limit to max results
        urls = urls[:max_results]
        log_callback(f"[INFO] Discovered {len(urls)} Foodpanda restaurant links.")
        
        leads_scraped = 0
        for idx, url in enumerate(urls):
            if session.stop_event.is_set():
                log_callback("[INFO] Scraping stopped by user.")
                break
            while session.pause_event.is_set():
                time.sleep(1.0)
                if session.stop_event.is_set():
                    break
                    
            log_callback(f"[INFO] Scraping Foodpanda restaurant {idx+1}/{len(urls)}: {url}")
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                time.sleep(3.0)
                
                # Extract details
                # 1. Restaurant Name
                name_el = page.locator('h1[class*="vendor-name"], h1').first
                name = name_el.text_content().strip() if name_el.count() > 0 else ""
                if not name:
                    log_callback(f"[WARNING] Could not find restaurant name. Skipping.")
                    continue
                
                # 2. Category
                category = "Restaurant / Delivery"
                cat_el = page.locator('div[class*="vendor-characteristics"], span[class*="characteristics"]').first
                if cat_el.count() > 0:
                    category = cat_el.text_content().strip()
                
                # 3. Address (Often requires clicking info button or is in footer / info section)
                # Try clicking Info button
                address = f"Foodpanda listing - {location}"
                info_button = page.locator('button:has-text("About"), button:has-text("Info"), button[data-testid="vendor-info-button"]').first
                if info_button.count() > 0:
                    try:
                        info_button.click()
                        time.sleep(2.0)
                        # Address inside info modal
                        addr_el = page.locator('div[class*="vendor-info-modal"] p, div[data-testid="vendor-info-address"]').first
                        if addr_el.count() > 0:
                            address = addr_el.text_content().strip()
                    except Exception:
                        pass
                
                # If clicking fails, parse address from general text or metadata
                if address == f"Foodpanda listing - {location}":
                    # Fallback address lookup
                    addr_body = page.locator('p:has-text("Address:"), span:has-text("Address:")').first
                    if addr_body.count() > 0:
                        address = addr_body.text_content().replace("Address:", "").strip()
                
                lead = {
                    "Business Name": name,
                    "Category": category,
                    "Physical Address / Location": address,
                    "Business Phone Number": "", # Foodpanda doesn't usually show direct restaurant phone
                    "Public Email Address": "",
                    "Official Website": "",
                    "Facebook Link": "",
                    "Instagram Link": "",
                    "LinkedIn Link": "",
                    "Twitter Link": "",
                    "TikTok Link": "",
                    "YouTube Link": "",
                    "Estimated Owner Name (Enriched)": "",
                    "Owner Profile Link (LinkedIn/Facebook)": "",
                    "Source URL": url
                }
                
                # Enrichments
                # Google Search for restaurant name to find official website/socials
                web_link = ""
                if crawl_websites:
                    enrich_web_query = f'"{name}" "{location}" official website'
                    enrich_url = f"https://www.google.com/search?q={urllib.parse.quote(enrich_web_query)}"
                    
                    try:
                        # Search Google for official website
                        sub_context = browser.new_context(user_agent=get_random_user_agent())
                        sub_page = sub_context.new_page()
                        sub_page.goto(enrich_url, wait_until="domcontentloaded", timeout=15000)
                        time.sleep(2.0)
                        
                        # Extract first non-foodpanda/non-google link as website
                        anchors_web = sub_page.locator('div.g a').all()
                        for a_web in anchors_web:
                            href_web = a_web.get_attribute("href")
                            if href_web and not any(x in href_web for x in ["google.com", "foodpanda.", "facebook.com", "instagram.com", "linkedin.com"]):
                                web_link = href_web
                                break
                        sub_context.close()
                    except Exception:
                        pass
                
                if web_link and crawl_websites:
                    lead["Official Website"] = web_link
                    log_callback(f"[INFO] Found potential official website: {web_link}")
                    web_emails, web_phones, web_socials = crawl_website_for_contacts(web_link, log_callback)
                    if web_emails:
                        lead["Public Email Address"] = ", ".join(list(web_emails))
                    if web_phones:
                        lead["Business Phone Number"] = list(web_phones)[0]
                    
                    # Save crawled socials directly into their respective columns
                    for platform in ["facebook", "instagram", "linkedin", "twitter", "tiktok", "youtube"]:
                        if web_socials[platform]:
                            lead[f"{platform.capitalize()} Link"] = web_socials[platform]
                
                # Social Hunting for Owner
                if hunt_owners:
                    owner_name, owner_profile = search_owner_on_google(playwright_context, name, log_callback)
                    if owner_name:
                        lead["Estimated Owner Name (Enriched)"] = owner_name
                    if owner_profile and not lead["Owner Profile Link (LinkedIn/Facebook)"]:
                        lead["Owner Profile Link (LinkedIn/Facebook)"] = owner_profile
                    
                # Contact Fallback
                if not lead["Estimated Owner Name (Enriched)"]:
                    lead["Estimated Owner Name (Enriched)"] = "N/A - Public Contact Saved"
                    
                session.leads.append(lead)
                leads_scraped += 1
                session.progress = float(leads_scraped) / len(urls)
                
                log_callback(f"[SUCCESS] Scraped & Enriched Foodpanda: '{name}'")
                
                # Incremental save every 5 leads
                if len(session.leads) % 5 == 0:
                    save_incremental(session.leads, log_callback)
                    log_callback(f"[INFO] Saved {len(session.leads)} leads incrementally to 'food_leads.csv'")
                    
                # Random delay
                time.sleep(random.uniform(2.0, 4.0))
                
            except Exception as ex:
                log_callback(f"[WARNING] Error scraping Foodpanda restaurant {url}: {ex}")
                continue
                
    except Exception as e:
        log_callback(f"[ERROR] Foodpanda Google search failed: {e}")
    finally:
        browser.close()

def save_incremental(leads, log_callback=None):
    """
    Saves leads dataset to a local CSV file. Fallback if the file is locked.
    """
    df = pd.DataFrame(leads)
    filename = "food_leads.csv"
    try:
        df.to_csv(filename, index=False)
    except PermissionError:
        timestamp = int(time.time())
        alt_filename = f"food_leads_{timestamp}.csv"
        try:
            df.to_csv(alt_filename, index=False)
            msg = f"[WARNING] '{filename}' is locked by another program (e.g. Excel). Saved output to '{alt_filename}' instead."
            if log_callback:
                log_callback(msg)
            else:
                print(msg)
        except Exception:
            pass

def run_scraping_job(query, location, max_results, platform, session, log_callback, crawl_websites=True, hunt_owners=True):
    """
    Wrapper function to run the scraping job in a background thread.
    """
    session.status = "running"
    session.progress = 0.0
    session.leads = []
    
    log_callback("[INFO] Scraping process started...")
    
    with sync_playwright() as playwright_context:
        try:
            if platform in ["Google Maps", "Both"]:
                run_google_maps_scrape(playwright_context, query, location, max_results, session, log_callback, crawl_websites, hunt_owners)
                
            if platform == "Both":
                log_callback("[INFO] Switching to Foodpanda Discovery...")
                
            if platform in ["Foodpanda (Simulated)", "Both"]:
                if not session.stop_event.is_set():
                    run_foodpanda_scrape(playwright_context, query, location, max_results, session, log_callback, crawl_websites, hunt_owners)
            
            # Save final results
            if session.leads:
                save_incremental(session.leads, log_callback)
                log_callback(f"[SUCCESS] Scraping Job completed successfully! Total leads saved: {len(session.leads)}")
                session.status = "completed"
            else:
                log_callback("[WARNING] Scraping completed, but no leads were found.")
                session.status = "completed"
                
        except Exception as e:
            log_callback(f"[ERROR] Scraping thread failed: {e}")
            session.status = "stopped"
        finally:
            session.progress = 1.0
