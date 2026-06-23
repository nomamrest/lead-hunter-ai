import sys
import os
import time
import threading
import pandas as pd
import streamlit as st

# Auto-install Playwright browser binaries if running in a Linux cloud environment (e.g. Streamlit Cloud)
playwright_flag = "/tmp/playwright_installed"
if sys.platform.startswith("linux") and not os.path.exists(playwright_flag):
    try:
        import subprocess
        print("[INFO] Cloud environment detected. Installing Playwright Chromium browser...")
        # Run playwright installation using the current Python environment
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        # Create flag file to prevent repeating on every script rerun
        with open(playwright_flag, "w") as f:
            f.write("done")
        print("[INFO] Playwright Chromium browser installed successfully.")
    except Exception as e:
        print(f"[ERROR] Playwright auto-installation failed: {e}")

# Ensure stdout uses UTF-8 to prevent charmap/UnicodeEncodeError on Windows console
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from scraper import run_scraping_job, save_incremental
import db
import io

# Set page config for a premium wide layout
st.set_page_config(
    page_title="Lead Hunter AI - Food Business & Owner Scraper",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Premium Styles with Glassmorphism and Custom Typography
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');

html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    font-family: 'Outfit', sans-serif;
    background: radial-gradient(circle at 50% 50%, #171d31, #0a0b10);
    color: #f0f2f6;
}

[data-testid="stSidebar"] {
    background-color: rgba(15, 20, 35, 0.95) !important;
    border-right: 1px solid rgba(255, 255, 255, 0.05);
}

/* Glassmorphism card container */
.glass-card {
    background: rgba(255, 255, 255, 0.02);
    backdrop-filter: blur(12px);
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.06);
    padding: 20px;
    margin-bottom: 20px;
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
}

/* Gradient Headings */
.gradient-title {
    background: linear-gradient(135deg, #ff8a00 0%, #e52e71 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 700;
    font-size: 2.8rem;
    margin-bottom: 5px;
}

.gradient-subtitle {
    font-size: 1.1rem;
    color: #a0aec0;
    margin-bottom: 25px;
    font-weight: 300;
}

/* Status Indicators */
.status-indicator {
    padding: 6px 12px;
    border-radius: 20px;
    font-weight: 600;
    display: inline-block;
}
.status-running {
    background-color: rgba(74, 144, 226, 0.2);
    color: #4a90e2;
    border: 1px solid #4a90e2;
}
.status-paused {
    background-color: rgba(245, 166, 35, 0.2);
    color: #f5a623;
    border: 1px solid #f5a623;
}
.status-completed {
    background-color: rgba(126, 211, 33, 0.2);
    color: #7ed321;
    border: 1px solid #7ed321;
}
.status-stopped {
    background-color: rgba(208, 2, 27, 0.2);
    color: #d0021b;
    border: 1px solid #d0021b;
}
.status-idle {
    background-color: rgba(150, 150, 150, 0.2);
    color: #9b9b9b;
    border: 1px solid #9b9b9b;
}

/* Console logs style */
.console-box {
    background-color: #0c0f16 !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 8px !important;
    font-family: 'Courier New', Courier, monospace;
    font-size: 0.85rem;
    padding: 15px;
    height: 250px;
    overflow-y: scroll;
}

/* Custom button styles */
div.stButton > button {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: #f0f2f6;
    transition: all 0.3s ease;
    border-radius: 8px;
    font-weight: 600;
}
div.stButton > button:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: #ff8a00;
    color: #ff8a00;
    transform: translateY(-1px);
}
</style>
""", unsafe_allow_html=True)

# Thread-safe class to store the scraper's run-time variables
class ScraperSession:
    def __init__(self):
        self.leads = []
        self.logs = []
        self.progress = 0.0
        self.status = "idle"  # idle, running, paused, stopped, completed
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.thread = None

# Persistent session state initialization
if "session" not in st.session_state:
    st.session_state.session = ScraperSession()

session = st.session_state.session

# Sync status if thread has terminated in the background before rendering UI
if session.status in ["running", "paused"] and session.thread and not session.thread.is_alive():
    if session.status == "running":
        session.status = "completed"
    session.progress = 1.0

initial_status = session.status

# Sidebar - Configuration Panel
st.sidebar.markdown("<div style='text-align: center; margin-bottom: 20px;'><h1 style='font-size: 2.2rem; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;'>Lead Hunter AI</h1><span style='font-size: 0.85rem; color:#764ba2; font-weight:600;'>AUTOMATED LEAD GENERATOR</span></div>", unsafe_allow_html=True)
st.sidebar.markdown("---")

st.sidebar.subheader("Configuration Settings")
query_val = st.sidebar.text_input("Search Queries (e.g., bakeries, cafes)", "bakeries")
location_val = st.sidebar.text_input("Target Location (e.g., Karachi, London)", "Karachi")
max_results_val = st.sidebar.slider("Max Results to Fetch", min_value=1, max_value=100, value=10)
platform_val = st.sidebar.selectbox("Target Discovery Platform", ["Google Maps", "Foodpanda (Simulated)", "Both"])

st.sidebar.markdown("---")
st.sidebar.subheader("Enrichment Options")
crawl_web_val = st.sidebar.checkbox("Crawl Business Websites", value=True, help="Visit the business's official website to extract emails, phone numbers, and social links.")
hunt_owner_val = st.sidebar.checkbox("Hunt for Owners (LinkedIn/Facebook)", value=True, help="Search Google, LinkedIn, and Facebook to discover the owner's name and profile link.")
skip_duplicates_val = st.sidebar.checkbox("Skip Previously Scraped Leads", value=True, help="Avoid scraping leads that were already scraped in previous runs to save time and API queries.")

st.sidebar.markdown("---")
st.sidebar.subheader("Select Export Columns")
all_columns = [
    "Business Name",
    "Category",
    "Physical Address / Location",
    "Business Phone Number",
    "Public Email Address",
    "Official Website",
    "Facebook Link",
    "Instagram Link",
    "LinkedIn Link",
    "Twitter Link",
    "TikTok Link",
    "YouTube Link",
    "Estimated Owner Name (Enriched)",
    "Owner Profile Link (LinkedIn/Facebook)",
    "Source URL"
]
selected_fields = st.sidebar.multiselect(
    "Target Fields/Columns",
    options=all_columns,
    default=all_columns,
    help="Select the exact data columns you want to display in the dashboard and export to your final file."
)
if not selected_fields:
    selected_fields = ["Business Name"]

st.sidebar.markdown("---")

# Help instruction box
st.sidebar.markdown("""
<div class='glass-card' style='padding: 12px; font-size:0.85rem; border-color: rgba(255,255,255,0.03);'>
<strong>💡 Usage Tip:</strong><br/>
Google Maps searches local listings directly. Foodpanda simulation queries Google search to extract local delivery listings, reducing Cloudflare block risks.
</div>
""", unsafe_allow_html=True)

# Main Dashboard UI
st.markdown("<h1 class='gradient-title'>🍳 Food Business & Owner Lead Hunter</h1>", unsafe_allow_html=True)
st.markdown("<p class='gradient-subtitle'>Extract and enrich local food business leads to autonomously find owners, phone numbers, emails, and LinkedIn profiles.</p>", unsafe_allow_html=True)

# Set up tabs
tab1, tab2, tab3 = st.tabs(["🍳 Active Scraper", "📜 Scrape History", "🗄️ Master Database"])

with tab1:
    # Status indicators row
    status_class = f"status-{session.status}"
    status_display = session.status.upper()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class='glass-card'>
            <span style='color: #a0aec0; font-size: 0.85rem;'>ACTIVE RUN STATUS</span><br/>
            <span class='status-indicator {status_class}' style='margin-top: 8px;'>{status_display}</span>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class='glass-card'>
            <span style='color: #a0aec0; font-size: 0.85rem;'>LEADS EXTRACTED</span><br/>
            <span style='font-size: 1.8rem; font-weight: 700; color: #ff8a00;'>{len(session.leads)}</span>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        progress_pct = int(session.progress * 100)
        st.markdown(f"""
        <div class='glass-card'>
            <span style='color: #a0aec0; font-size: 0.85rem;'>PROGRESS BAR</span><br/>
            <span style='font-size: 1.8rem; font-weight: 700; color: #4a90e2;'>{progress_pct}%</span>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        has_owner_count = sum(1 for lead in session.leads if lead["Estimated Owner Name (Enriched)"] and lead["Estimated Owner Name (Enriched)"] != "N/A - Public Contact Saved")
        st.markdown(f"""
        <div class='glass-card'>
            <span style='color: #a0aec0; font-size: 0.85rem;'>OWNERS ENRICHED</span><br/>
            <span style='font-size: 1.8rem; font-weight: 700; color: #7ed321;'>{has_owner_count}</span>
        </div>
        """, unsafe_allow_html=True)
    
    # Dynamic Progress Bar
    st.progress(session.progress)
    
    # Control Buttons
    st.markdown("<div style='margin-top: 15px; margin-bottom: 25px;'>", unsafe_allow_html=True)
    btn_col1, btn_col2, btn_col3, btn_col4 = st.columns([1, 1, 1, 3])
    
    with btn_col1:
        start_disabled = session.status in ["running", "paused"]
        if st.button("🚀 Start Scraping", disabled=start_disabled, use_container_width=True):
            session.status = "running"
            session.progress = 0.0
            session.leads = []
            session.logs = []
            session.stop_event.clear()
            session.pause_event.clear()
            
            def log_callback(msg):
                timestamp = time.strftime("[%H:%M:%S]")
                session.logs.append(f"{timestamp} {msg}")
                
            session.thread = threading.Thread(
                target=run_scraping_job,
                args=(query_val, location_val, max_results_val, platform_val, session, log_callback, crawl_web_val, hunt_owner_val, skip_duplicates_val),
                daemon=True
            )
            session.thread.start()
            st.rerun()
            
    with btn_col2:
        pause_disabled = session.status not in ["running", "paused"]
        pause_text = "▶️ Resume" if session.status == "paused" else "⏸️ Pause"
        if st.button(pause_text, disabled=pause_disabled, use_container_width=True):
            if session.status == "running":
                session.pause_event.set()
                session.status = "paused"
                session.logs.append(f"{time.strftime('[%H:%M:%S]')} [INFO] Scraping paused by user.")
            else:
                session.pause_event.clear()
                session.status = "running"
                session.logs.append(f"{time.strftime('[%H:%M:%S]')} [INFO] Scraping resumed by user.")
            st.rerun()
            
    with btn_col3:
        stop_disabled = session.status not in ["running", "paused"]
        if st.button("⏹️ Stop", disabled=stop_disabled, use_container_width=True):
            session.stop_event.set()
            session.pause_event.clear() # Clear pause to allow stop check
            session.status = "stopped"
            session.logs.append(f"{time.strftime('[%H:%M:%S]')} [INFO] Scraping stopped by user.")
            st.rerun()
            
    with btn_col4:
        pass
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Main layout content split: Logs Console (left) and Data Table (right)
    layout_col1, layout_col2 = st.columns([1, 2])
    
    with layout_col1:
        st.markdown("### 💻 Live Scrolling Console Log")
        log_content = "\n".join(session.logs) if session.logs else "Console idle. Press 'Start Scraping' to begin."
        st.text_area("Console logs", value=log_content, height=350, disabled=True, label_visibility="collapsed")
        
    with layout_col2:
        st.markdown("### 📊 Scraped Leads Viewer (Real-Time)")
        if session.leads:
            df = pd.DataFrame(session.leads)
            st.dataframe(df[selected_fields], height=350, use_container_width=True)
        else:
            st.info("No leads scraped yet. Start a scraping job to populate data.")
            
    # Export panel
    if session.leads:
        st.markdown("### 📥 Export Finalized Leads")
        exp_col1, exp_col2, exp_col3 = st.columns([1, 1, 2])
        
        df_export = pd.DataFrame(session.leads)[selected_fields]
        
        csv_data = df_export.to_csv(index=False).encode('utf-8')
        with exp_col1:
            st.download_button(
                label="Download as CSV",
                data=csv_data,
                file_name="food_leads_export.csv",
                mime="text/csv",
                use_container_width=True
            )
            
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Leads')
        excel_data = excel_buffer.getvalue()
        with exp_col2:
            st.download_button(
                label="Download as Excel",
                data=excel_data,
                file_name="food_leads_export.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

with tab2:
    st.markdown("### 📜 Scrape Runs History")
    history = db.get_scrape_history()
    
    if history:
        df_history = pd.DataFrame(history)
        # Rename columns for user-friendly display
        df_history.columns = ["ID", "Scrape Date/Time", "Search Query", "Location", "Discovery Platform", "Leads Count"]
        st.dataframe(df_history, use_container_width=True)
        
        st.markdown("#### 🔍 Load or Manage a Past Scrape Run")
        # Let user select a run by its ID and Query/Location details
        run_options = {r["id"]: f"Run #{r['id']} - '{r['query']}' in {r['location']} ({r['timestamp']}, {r['leads_count']} leads)" for r in history}
        selected_run_id = st.selectbox("Select Scrape Run", options=list(run_options.keys()), format_func=lambda x: run_options[x])
        
        if selected_run_id:
            # Fetch leads for selected run
            run_leads = db.get_leads_by_scrape(selected_run_id)
            if run_leads:
                df_run_leads = pd.DataFrame(run_leads)
                st.markdown(f"**Leads for {run_options[selected_run_id]}**")
                st.dataframe(df_run_leads[selected_fields], use_container_width=True)
                
                # Export options for this past run
                hist_col1, hist_col2, hist_col3 = st.columns([1, 1, 2])
                
                df_run_export = df_run_leads[selected_fields]
                csv_run_data = df_run_export.to_csv(index=False).encode('utf-8')
                with hist_col1:
                    st.download_button(
                        label="Download Run as CSV",
                        data=csv_run_data,
                        file_name=f"food_leads_run_{selected_run_id}.csv",
                        mime="text/csv",
                        key=f"dl_csv_run_{selected_run_id}",
                        use_container_width=True
                    )
                
                excel_run_buffer = io.BytesIO()
                with pd.ExcelWriter(excel_run_buffer, engine='openpyxl') as writer:
                    df_run_export.to_excel(writer, index=False, sheet_name='Leads')
                excel_run_data = excel_run_buffer.getvalue()
                with hist_col2:
                    st.download_button(
                        label="Download Run as Excel",
                        data=excel_run_data,
                        file_name=f"food_leads_run_{selected_run_id}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_xlsx_run_{selected_run_id}",
                        use_container_width=True
                    )
            else:
                st.info("No leads saved for this run.")
                
            # Delete button
            st.markdown("---")
            if st.button("🗑️ Delete Selected Scrape Run from Database", type="secondary", use_container_width=True):
                db.delete_scrape_run(selected_run_id)
                st.success(f"Successfully deleted Run #{selected_run_id}!")
                time.sleep(1)
                st.rerun()
    else:
        st.info("No scrape runs recorded in history yet.")

with tab3:
    st.markdown("### 🗄️ Master Leads Database")
    all_leads = db.get_all_leads()
    
    if all_leads:
        st.markdown(f"Total unique leads collected: **{len(all_leads)}**")
        
        # Search filter
        search_query = st.text_input("🔍 Search Leads Database (Name, Category, Address, Phone, Email, Owner name)", "")
        
        df_master = pd.DataFrame(all_leads)
        
        if search_query:
            # Filter rows containing query in any string column
            q = search_query.lower()
            mask = df_master.apply(lambda row: row.astype(str).str.lower().str.contains(q).any(), axis=1)
            df_filtered = df_master[mask]
        else:
            df_filtered = df_master
            
        st.markdown(f"Showing **{len(df_filtered)}** leads after filtering:")
        st.dataframe(df_filtered[selected_fields], use_container_width=True)
        
        # Export Master List
        master_col1, master_col2, master_col3 = st.columns([1, 1, 2])
        
        df_master_export = df_filtered[selected_fields]
        csv_master_data = df_master_export.to_csv(index=False).encode('utf-8')
        with master_col1:
            st.download_button(
                label="Download Database as CSV",
                data=csv_master_data,
                file_name="master_leads_export.csv",
                mime="text/csv",
                key="dl_master_csv",
                use_container_width=True
            )
            
        excel_master_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_master_buffer, engine='openpyxl') as writer:
            df_master_export.to_excel(writer, index=False, sheet_name='Master Leads')
        excel_master_data = excel_master_buffer.getvalue()
        with master_col2:
            st.download_button(
                label="Download Database as Excel",
                data=excel_master_data,
                file_name="master_leads_export.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_master_xlsx",
                use_container_width=True
            )
    else:
        st.info("The master database is currently empty. Run a scrape job first.")

# Transition check: if the UI rendered a running/paused state but the job finished during execution, trigger an immediate rerun
if initial_status in ["running", "paused"] and (session.status not in ["running", "paused"] or (session.thread and not session.thread.is_alive())):
    if session.status == "running":
        session.status = "completed"
        session.progress = 1.0
    st.rerun()

# Auto-refresh loop when job is running
if session.status in ["running", "paused"]:
    time.sleep(1.0)
    st.rerun()
