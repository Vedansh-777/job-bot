# =========================
# INSTALL FIRST
# pip install python-jobspy pandas requests schedule beautifulsoup4
# =========================

import pandas as pd
from jobspy import scrape_jobs
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests
import os
import schedule
import time
import json
import logging
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =========================
# CONFIG (USE ENVIRONMENT VARIABLES FOR SECURITY)
# =========================
EMAIL = os.getenv("JOB_EMAIL", "official.vedansh12@gmail.com")
APP_PASSWORD = os.getenv("JOB_APP_PASSWORD", "xaxzpsxcqdklltgd")
TO_EMAIL = os.getenv("JOB_TO_EMAIL", "official.vedansh12@gmail.com")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8914935211:AAF36ybFy0zV1JgWyfRG3E_EvljhZXBgQis")
TELEGRAM_CHAT_IDS = os.getenv("TELEGRAM_CHAT_IDS", "1339085010").split(",")
#Romesh-1031032677
MAX_JOBS_TO_SEND = int(os.getenv("MAX_JOBS_TO_SEND", "50"))

SEARCH_QUERY = '"Software Engineer" AND ("C#" OR ".NET") -intern -fresher'
LOCATION = "India"
MAX_RESULTS = 100

SEEN_FILE = "seen_jobs.txt"

QUERIES = [
    "Developer",
    "Software Engineer",
    "Backend Developer"
    "SDE"
]

EXCLUDE_KEYWORDS = ["manager", "qa", "quality assurance", "senior", "lead", "principal","staff","test","testing","devops","Sr","II","III"]

def validate_config():
    required = ["EMAIL", "APP_PASSWORD", "TO_EMAIL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_IDS"]
    missing = [k for k in required if not os.getenv(k.replace("_", " ").lower())]
    if missing:
        logging.warning(f"⚠️ Missing env vars: {missing}. Using defaults.")

# =========================
# SEEN JOBS
# =========================
def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r") as f:
        return set(f.read().splitlines())

def save_seen(urls):
    with open(SEEN_FILE, "a") as f:
        for url in urls:
            f.write(url + "\n")

# =========================
# FILTER JOBS
# =========================
def filter_jobs(df):
    if df.empty:
        return df

    initial_count = len(df)

    df['title_lower'] = df['title'].str.lower()

    for keyword in EXCLUDE_KEYWORDS:
        df = df[~df['title_lower'].str.contains(keyword, na=False)]

    df = df.drop('title_lower', axis=1)

    filtered_count = initial_count - len(df)
    if filtered_count > 0:
        logging.info(f"🚫 Filtered out {filtered_count} jobs with excluded keywords")

    return df

# =========================
# FETCH FROM HIRING.CAFE
# =========================
def fetch_from_hiring_cafe():
    url = "https://hiring.cafe/api/search"

    payload = {
        "searchState": {
            "managementYoeRange": [0, 0],
            "roleYoeRange": [0, 3],
            "departments": ["Software Development"]
        }
    }

    try:
        logging.info("Fetching from hiring.cafe...")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()

        jobs_data = response.json()
        jobs_list = []

        if isinstance(jobs_data, dict) and 'jobs' in jobs_data:
            jobs_list = jobs_data['jobs']
        elif isinstance(jobs_data, list):
            jobs_list = jobs_data

        if not jobs_list:
            logging.warning("No jobs from hiring.cafe")
            return None

        records = []
        for job in jobs_list:
            try:
                records.append({
                    'title': job.get('title', 'N/A'),
                    'company': job.get('company', job.get('companyName', 'Unknown')),
                    'job_url': job.get('url', job.get('link', '')),
                    'location': job.get('location', 'India'),
                    'site_name': 'hiring.cafe',
                    'salary': job.get('salary', job.get('salaryRange', 'Not specified')),
                    'years_experience': job.get('yearsOfExperience', job.get('experience', '0-3')),
                })
            except Exception as e:
                logging.error(f"Error parsing job: {e}")

        if records:
            df = pd.DataFrame(records)
            logging.info(f"✅ Found {len(df)} jobs from hiring.cafe")
            return df

        return None

    except Exception as e:
        logging.error(f"Error fetching from hiring.cafe: {e}")
        return None

# =========================
# FETCH JOBS
# =========================
def fetch_jobs():
    all_jobs = []

    for query in QUERIES:
        try:
            logging.info(f"Fetching: {query}")

            jobs = scrape_jobs(
                site_name=["linkedin", "indeed", "google"],
                search_term=query,
                location=LOCATION,
                results_wanted=100,
                hours_old=24,
                country_indeed="India"
            )

            if jobs is not None and not jobs.empty:
                all_jobs.append(jobs)
                logging.info(f"✅ Found {len(jobs)} jobs for '{query}'")

        except Exception as e:
            logging.error(f"Error fetching '{query}': {e}")

    hiring_cafe_jobs = fetch_from_hiring_cafe()
    if hiring_cafe_jobs is not None and not hiring_cafe_jobs.empty:
        all_jobs.append(hiring_cafe_jobs)

    df = pd.concat(all_jobs, ignore_index=True) if all_jobs else pd.DataFrame()

    if df.empty:
        logging.warning("No jobs found")
        return None

    logging.info(f"Available columns: {df.columns.tolist()}")

    url_col = 'job_url' if 'job_url' in df.columns else ('url' if 'url' in df.columns else None)

    if url_col is None:
        logging.error(f"No URL column found. Available: {df.columns.tolist()}")
        return None

    if url_col != 'job_url':
        df.rename(columns={url_col: 'job_url'}, inplace=True)

    df.drop_duplicates(subset=['job_url'], inplace=True)
    df.dropna(subset=["title", "company", 'job_url'], inplace=True)

    logging.info(f"Total unique jobs: {len(df)}")

    df = filter_jobs(df)

    if df.empty:
        logging.warning("No jobs after filtering")
        return None

    logging.info(f"Jobs after filtering: {len(df)}")
    return df

# =========================
# FORMAT EMAIL
# =========================
def format_email(df):
    job_count = len(df)
    date_str = datetime.now().strftime('%d-%m-%Y %H:%M')

    html = f"""
    <html>
    <head><style>
    body {{ font-family: Arial, sans-serif; background-color: #f5f5f5; }}
    .header {{ background-color: #FF6B35; color: white; padding: 20px; text-align: center; }}
    .job {{ background-color: white; margin: 10px; padding: 15px; border-radius: 5px; border-left: 4px solid #FF6B35; }}
    .title {{ font-size: 18px; font-weight: bold; color: #333; }}
    .company {{ color: #666; margin: 5px 0; }}
    .details {{ font-size: 12px; color: #999; margin: 5px 0; }}
    .button {{ display: inline-block; background-color: #FF6B35; color: white; padding: 10px 20px; text-decoration: none; border-radius: 3px; margin-top: 10px; }}
    </style></head>
    <body>
    <div class="header"><h2>🔥 Daily Job Alerts - {job_count} New Jobs ({date_str})</h2></div>
    """

    for idx, (_, row) in enumerate(df.iterrows(), 1):
        location = row.get('location', 'Not specified')
        salary = row.get('salary_source', row.get('salary', 'Not specified'))
        site = row.get('site_name', row.get('site', 'Job Portal'))
        years_exp = row.get('years_experience', row.get('experience', 'Not specified'))

        html += f"""
        <div class="job">
        <span class="title">#{idx} {row['title']}</span><br>
        <span class="company">🏢 {row['company']}</span><br>
        <span class="details">📍 {location} | 💰 {salary} | 📅 {years_exp} yrs | 🌐 {site}</span><br>
        <a class="button" href="{row['job_url']}">👉 Apply Here →</a>
        </div>
        """

    html += "</body></html>"
    return html

# =========================
# SEND EMAIL
# =========================
def send_email(body):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🔥 Daily Job Alerts - {datetime.now().strftime('%d-%m-%Y')}"
        msg["From"] = EMAIL
        msg["To"] = TO_EMAIL

        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL, APP_PASSWORD)
            server.send_message(msg)

        logging.info("✅ Email sent successfully")
        return True

    except smtplib.SMTPAuthenticationError:
        logging.error("❌ Email auth failed - check credentials")
        return False
    except Exception as e:
        logging.error(f"❌ Email error: {e}")
        return False

# =========================
# SEND TELEGRAM
# =========================
def send_telegram(jobs_data):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    if not jobs_data or (isinstance(jobs_data, str)):
        for chat_id in TELEGRAM_CHAT_IDS:
            try:
                requests.post(url, data={
                    "chat_id": chat_id.strip(),
                    "text": jobs_data if isinstance(jobs_data, str) else "No jobs found today 😢"
                }, timeout=5)
            except Exception as e:
                logging.error(f"Telegram error for chat {chat_id}: {e}")
        return

    for idx, job in enumerate(jobs_data[:MAX_JOBS_TO_SEND], 1):
        try:
            title = job.get("title", "N/A")
            job_url = job.get("job_url", "")
            site = job.get("site_name", job.get("site", "Unknown Site"))
            company = job.get("company", "Unknown Company")
            location = job.get("location", "India")
            salary = job.get("salary_source", job.get("salary", "Not specified"))
            years_exp = job.get("years_experience", job.get("experience", "Not specified"))

            message = (
                f"*Job #{idx}*\n"
                f"💼 *{title}*\n"
                f"🏢 {company}\n"
                f"📍 {location}\n"
                f"💰 {salary}\n"
                f"📅 Experience: {years_exp}\n"
                f"🌐 {site}"
            )

            keyboard = {
                "inline_keyboard": [
                    [{"text": "👉 Apply Now", "url": job_url}],
                    [{"text": "📋 View Job", "url": job_url}]
                ]
            }

            for chat_id in TELEGRAM_CHAT_IDS:
                try:
                    payload = {
                        "chat_id": chat_id.strip(),
                        "text": message,
                        "reply_markup": json.dumps(keyboard),
                        "parse_mode": "Markdown"
                    }

                    res = requests.post(url, data=payload, timeout=5)
                    if res.status_code == 200:
                        logging.info(f"✅ Job #{idx} sent to {chat_id}")
                    else:
                        logging.error(f"Telegram error for {chat_id}: {res.text}")

                except Exception as e:
                    logging.error(f"Telegram job error for {chat_id}: {e}")

            time.sleep(1)

        except Exception as e:
            logging.error(f"Telegram job error: {e}")
# =========================
# MAIN LOGIC
# =========================
def job_runner():
    logging.info("🔄 Running job fetch...")

    df = fetch_jobs()

    if df is None or df.empty:
        logging.warning("No jobs found today")
        send_telegram("No jobs found today 😢")
        return

    seen = load_seen()
    new_jobs = df[~df["job_url"].isin(seen)]

    if new_jobs.empty:
        logging.info("No new jobs today")
        send_telegram(f"No *new* jobs today (but {len(df)} total jobs found) 📊")
        return

    save_seen(new_jobs["job_url"])

    new_jobs = new_jobs.copy()
    new_jobs['location'] = new_jobs['location'].fillna('Other')

    def sort_priority(location):
        priority_order = {'Mumbai': 0, 'Bangalore': 1, 'Delhi': 2, 'Pune': 3, 'Hyderabad': 4}
        return priority_order.get(location, 999)

    new_jobs['location_priority'] = new_jobs['location'].apply(sort_priority)
    # new_jobs['salary_sort'] = new_jobs['salary'].fillna('Z').astype(str)

    new_jobs_sorted = new_jobs.sort_values(['location_priority', 'location'], ascending=[True, True])
    # new_jobs_sorted = new_jobs_sorted.drop(['location_priority', 'salary_sort'], axis=1)

    logging.info(f"📧 Sending ALL {len(new_jobs_sorted)} jobs via email (Mumbai on top)...")
    send_email(format_email(new_jobs_sorted))

    logging.info(f"📱 Sending top 50 jobs to {len(TELEGRAM_CHAT_IDS)} Telegram chat(s) (Mumbai on top)...")
    send_telegram(new_jobs_sorted.head(MAX_JOBS_TO_SEND).to_dict(orient="records"))

# =========================
# RUN ONCE IMMEDIATELY
# =========================
if __name__ == "__main__":
    validate_config()
    logging.info("🚀 Starting Job Bot...")
    job_runner()

    # =========================
    # SCHEDULER (RUN DAILY)
    # =========================
    schedule.every().day.at("10:00").do(job_runner)
    logging.info("🚀 Job bot started... (will run daily at 10:00)")
