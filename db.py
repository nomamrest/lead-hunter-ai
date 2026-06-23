import os
import sys
import datetime
import streamlit as st

# Check if we should use PostgreSQL (Supabase) or SQLite (Local fallback)
use_postgres = False
try:
    if "postgres" in st.secrets and "connection_string" in st.secrets["postgres"]:
        if st.secrets["postgres"]["connection_string"].strip():
            use_postgres = True
except Exception:
    pass

if use_postgres:
    import psycopg2
    from psycopg2.extras import RealDictCursor
else:
    import sqlite3

def get_db_connection():
    """
    Establishes connection to either local SQLite or remote PostgreSQL.
    """
    if use_postgres:
        conn_str = st.secrets["postgres"]["connection_string"]
        conn = psycopg2.connect(conn_str)
    else:
        conn = sqlite3.connect("lead_hunter.db")
        conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    Initializes database tables. Handles PostgreSQL and SQLite syntax differences.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if use_postgres:
        # PostgreSQL schema
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS scrapes (
            id SERIAL PRIMARY KEY,
            timestamp TEXT,
            query TEXT,
            location TEXT,
            platform TEXT,
            leads_count INTEGER DEFAULT 0
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            source_url TEXT PRIMARY KEY,
            scrape_id INTEGER REFERENCES scrapes(id) ON DELETE CASCADE,
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
            call_status TEXT DEFAULT 'Pending',
            sales_notes TEXT
        )
        """)
        conn.commit()
        
        # Migrations for call_status and sales_notes if table already existed on Supabase
        try:
            cursor.execute("ALTER TABLE leads ADD COLUMN call_status TEXT DEFAULT 'Pending'")
            conn.commit()
        except Exception:
            conn.rollback()
            
        try:
            cursor.execute("ALTER TABLE leads ADD COLUMN sales_notes TEXT")
            conn.commit()
        except Exception:
            conn.rollback()
    else:
        # SQLite schema
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
            call_status TEXT DEFAULT 'Pending',
            sales_notes TEXT,
            FOREIGN KEY(scrape_id) REFERENCES scrapes(id) ON DELETE CASCADE
        )
        """)
        
        # Migrations for SQLite
        try:
            cursor.execute("ALTER TABLE leads ADD COLUMN call_status TEXT DEFAULT 'Pending'")
        except sqlite3.OperationalError:
            pass
            
        try:
            cursor.execute("ALTER TABLE leads ADD COLUMN sales_notes TEXT")
        except sqlite3.OperationalError:
            pass
            
        conn.commit()
        
    conn.close()

def start_scrape_record(query, location, platform):
    """
    Creates a new scrape run history log entry.
    Returns the scrape run record ID.
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor) if use_postgres else conn.cursor()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if use_postgres:
        cursor.execute(
            "INSERT INTO scrapes (timestamp, query, location, platform, leads_count) VALUES (%s, %s, %s, %s, 0) RETURNING id",
            (timestamp, query, location, platform)
        )
        scrape_id = cursor.fetchone()["id"]
    else:
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
    cursor = conn.cursor(cursor_factory=RealDictCursor) if use_postgres else conn.cursor()
    p = "%s" if use_postgres else "?"
    
    cursor.execute(f"SELECT * FROM leads WHERE source_url = {p}", (source_url,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return db_row_to_lead_dict(row)
    return None

def save_lead(lead, scrape_id):
    """
    Saves a scraped lead into the database, updating details but preserving salesperson call logs.
    Also updates the lead count in the corresponding scrape run entry.
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor) if use_postgres else conn.cursor()
    p = "%s" if use_postgres else "?"
    
    # Map lead keys to database columns using ON CONFLICT to preserve CRM statuses
    cursor.execute(f"""
    INSERT INTO leads (
        source_url, scrape_id, business_name, category, address, phone, email, website,
        facebook, instagram, linkedin, twitter, tiktok, youtube, owner_name, owner_profile,
        call_status, sales_notes
    ) VALUES ({', '.join([p]*16)}, 'Pending', '')
    ON CONFLICT(source_url) DO UPDATE SET
        scrape_id = excluded.scrape_id,
        business_name = excluded.business_name,
        category = excluded.category,
        address = excluded.address,
        phone = excluded.phone,
        email = excluded.email,
        website = excluded.website,
        facebook = excluded.facebook,
        instagram = excluded.instagram,
        linkedin = excluded.linkedin,
        twitter = excluded.twitter,
        tiktok = excluded.tiktok,
        youtube = excluded.youtube,
        owner_name = excluded.owner_name,
        owner_profile = excluded.owner_profile
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
    cursor.execute(f"SELECT COUNT(*) AS total FROM leads WHERE scrape_id = {p}", (scrape_id,))
    row = cursor.fetchone()
    count = row["total"] if use_postgres else row[0]
    
    cursor.execute(f"UPDATE scrapes SET leads_count = {p} WHERE id = {p}", (count, scrape_id))
    
    conn.commit()
    conn.close()

def update_lead_sales_info(source_url, call_status, sales_notes):
    """
    Updates the salesperson CRM details (Call Status, Notes) for a specific client.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    p = "%s" if use_postgres else "?"
    
    cursor.execute(f"""
    UPDATE leads
    SET call_status = {p}, sales_notes = {p}
    WHERE source_url = {p}
    """, (call_status, sales_notes, source_url))
    conn.commit()
    conn.close()

def get_scrape_history():
    """
    Retrieves all scrape run log entries.
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor) if use_postgres else conn.cursor()
    cursor.execute("SELECT * FROM scrapes ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_leads_by_scrape(scrape_id):
    """
    Retrieves all leads scraped in a specific run.
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor) if use_postgres else conn.cursor()
    p = "%s" if use_postgres else "?"
    
    cursor.execute(f"SELECT * FROM leads WHERE scrape_id = {p} ORDER BY business_name ASC", (scrape_id,))
    rows = cursor.fetchall()
    conn.close()
    return [db_row_to_lead_dict(r) for r in rows]

def get_all_leads():
    """
    Retrieves all unique leads ever saved in the database.
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor) if use_postgres else conn.cursor()
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
    p = "%s" if use_postgres else "?"
    cursor.execute(f"DELETE FROM leads WHERE scrape_id = {p}", (scrape_id,))
    cursor.execute(f"DELETE FROM scrapes WHERE id = {p}", (scrape_id,))
    conn.commit()
    conn.close()

def db_row_to_lead_dict(row):
    """
    Helper function to translate a Row (SQLite or PostgreSQL) back into standard lead layout.
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
        "Source URL": r.get("source_url", ""),
        "Call Status": r.get("call_status", "Pending"),
        "Sales Notes": r.get("sales_notes", "")
    }

# Run initialization upon import
init_db()
