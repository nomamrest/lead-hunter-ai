import os
import sqlite3
import datetime

DB_FILE = "lead_hunter.db"

def get_db_connection():
    """
    Establishes a connection to the SQLite database.
    Returns Row-factory connection for key-value dictionary access.
    """
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    Initializes database tables for scrape runs history and unique leads records.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Scrape Runs History table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scrapes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        query TEXT,
        location TEXT,
        platform TEXT,
        leads_count INTEGER DEFAULT 0
    )
    """)
    
    # 2. Leads database (source_url is the primary key for strict deduplication)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        source_url TEXT PRIMARY KEY,
        scrape_id INTEGER,
        business_name TEXT,
        category TEXT,
        address TEXT,
        phone TEXT,
        email TEXT,
        website TEXT,
        facebook TEXT,
        instagram TEXT,
        linkedin TEXT,
        twitter TEXT,
        tiktok TEXT,
        youtube TEXT,
        owner_name TEXT,
        owner_profile TEXT,
        FOREIGN KEY(scrape_id) REFERENCES scrapes(id) ON DELETE CASCADE
    )
    """)
    conn.commit()
    conn.close()

def start_scrape_record(query, location, platform):
    """
    Creates a new scrape run history log entry.
    Returns the scrape run record ID.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO scrapes (timestamp, query, location, platform, leads_count) VALUES (?, ?, ?, ?, 0)",
        (timestamp, query, location, platform)
    )
    scrape_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return scrape_id

def check_duplicate_lead(source_url):
    """
    Checks if a lead already exists in the database by its Source URL.
    Returns the lead dictionary if found, otherwise None.
    """
    if not source_url:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads WHERE source_url = ?", (source_url,))
    row = cursor.fetchone()
    conn.close()
    if row:
        # Convert sqlite3.Row to standard dictionary
        return dict(row)
    return None

def save_lead(lead, scrape_id):
    """
    Saves a scraped lead into the database (insert or replace).
    Also updates the lead count in the corresponding scrape run entry.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Map lead keys to database columns
    cursor.execute("""
    INSERT OR REPLACE INTO leads (
        source_url, scrape_id, business_name, category, address, phone, email, website,
        facebook, instagram, linkedin, twitter, tiktok, youtube, owner_name, owner_profile
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        lead.get("Source URL", ""),
        scrape_id,
        lead.get("Business Name", ""),
        lead.get("Category", ""),
        lead.get("Physical Address / Location", ""),
        lead.get("Business Phone Number", ""),
        lead.get("Public Email Address", ""),
        lead.get("Official Website", ""),
        lead.get("Facebook Link", ""),
        lead.get("Instagram Link", ""),
        lead.get("LinkedIn Link", ""),
        lead.get("Twitter Link", ""),
        lead.get("TikTok Link", ""),
        lead.get("YouTube Link", ""),
        lead.get("Estimated Owner Name (Enriched)", ""),
        lead.get("Owner Profile Link (LinkedIn/Facebook)", "")
    ))
    
    # Update leads count in the scrapes history table
    cursor.execute("SELECT COUNT(*) FROM leads WHERE scrape_id = ?", (scrape_id,))
    count = cursor.fetchone()[0]
    cursor.execute("UPDATE scrapes SET leads_count = ? WHERE id = ?", (count, scrape_id))
    
    conn.commit()
    conn.close()

def get_scrape_history():
    """
    Retrieves all scrape run log entries.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scrapes ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_leads_by_scrape(scrape_id):
    """
    Retrieves all leads scraped in a specific run.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads WHERE scrape_id = ? ORDER BY business_name ASC", (scrape_id,))
    rows = cursor.fetchall()
    conn.close()
    
    # Map database row columns back to lead dictionary format
    return [db_row_to_lead_dict(r) for r in rows]

def get_all_leads():
    """
    Retrieves all unique leads ever saved in the database.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads ORDER BY business_name ASC")
    rows = cursor.fetchall()
    conn.close()
    return [db_row_to_lead_dict(r) for r in rows]

def delete_scrape_run(scrape_id):
    """
    Deletes a scrape run history record and its associated leads.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM leads WHERE scrape_id = ?", (scrape_id,))
    cursor.execute("DELETE FROM scrapes WHERE id = ?", (scrape_id,))
    conn.commit()
    conn.close()

def db_row_to_lead_dict(row):
    """
    Helper function to translate an SQLite row dict back into the application's standard lead layout.
    """
    r = dict(row)
    return {
        "Business Name": r.get("business_name", ""),
        "Category": r.get("category", ""),
        "Physical Address / Location": r.get("address", ""),
        "Business Phone Number": r.get("phone", ""),
        "Public Email Address": r.get("email", ""),
        "Official Website": r.get("website", ""),
        "Facebook Link": r.get("facebook", ""),
        "Instagram Link": r.get("instagram", ""),
        "LinkedIn Link": r.get("linkedin", ""),
        "Twitter Link": r.get("twitter", ""),
        "TikTok Link": r.get("tiktok", ""),
        "YouTube Link": r.get("youtube", ""),
        "Estimated Owner Name (Enriched)": r.get("owner_name", ""),
        "Owner Profile Link (LinkedIn/Facebook)": r.get("owner_profile", ""),
        "Source URL": r.get("source_url", "")
    }

# Run initialization upon import
init_db()
