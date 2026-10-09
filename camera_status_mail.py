import smtplib
import os
import time
import logging
import re
import psycopg2 as spg
from email.mime.text import MIMEText
from datetime import datetime
from dotenv import load_dotenv
import socket
import smtplib

# --- ADD THIS SNIPPET TO FIX THE ERROR ---
orig_getaddrinfo = socket.getaddrinfo

def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    # Force the family to AF_INET (IPv4)
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

socket.getaddrinfo = getaddrinfo_ipv4

# Load variables from .env file
load_dotenv()

# --- IMPROVED LOGGING CONFIG ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Fetch configurations
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_NAME = os.getenv("DB_NAME")

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SENDER_EMAIL = os.getenv("SMTP_USERNAME")

TEST_MODE = os.getenv("TEST_MODE", "False").lower() == "true"

def extract_ip(rtsp_link):
    if not rtsp_link:
        return "N/A"
    match = re.search(r'@([\d\.]+)|//([\d\.]+)', rtsp_link)
    if match:
        return match.group(1) or match.group(2)
    return "Unknown"

# (HTML_TEMPLATE remains the same as your previous version)
HTML_TEMPLATE = """
<html>
<head>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f4f4; margin: 0; padding: 0; }}
        .container {{ max-width: 850px; margin: 20px auto; background: #ffffff; border-radius: 8px; overflow: hidden; border: 1px solid #ddd; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }}
        .header {{ background-color: #d32f2f; color: white; padding: 25px; text-align: center; }}
        .header h2 {{ margin: 0; font-size: 26px; letter-spacing: 1px; }}
        .content {{ padding: 30px; color: #333; }}
        .status-card {{ background-color: {card_bg}; border-left: 5px solid {accent_color}; padding: 15px; margin-bottom: 25px; }}
        .status-text {{ font-size: 18px; font-weight: bold; color: {accent_color}; margin: 0 0 5px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px; background-color: white; }}
        th {{ background-color: #f8f8f8; color: #d32f2f; text-align: left; padding: 12px; border-bottom: 2px solid #d32f2f; text-transform: uppercase; }}
        td {{ padding: 12px; border-bottom: 1px solid #eee; color: #555; }}
        tr:nth-child(even) {{ background-color: #fafafa; }}
        .ip-badge {{ background-color: #eee; padding: 2px 6px; border-radius: 4px; font-family: monospace; color: #333; border: 1px solid #ccc; }}
        .footer {{ background-color: #f9f9f9; color: #777; padding: 20px; text-align: center; font-size: 12px; border-top: 1px solid #eee; }}
        .timestamp {{ font-style: italic; color: #999; margin-top: 10px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>PPE System: Daily Camera Health Report</h2>
        </div>
        <div class="content">
            <div class="status-card">
                <p class="status-text">{status_title}</p>
                <p style="margin:0;">{status_message}</p>
            </div>
            {table_content}
            <p style="margin-top:25px; font-size: 13px; color: #777; line-height: 1.5;">
                <strong>Troubleshooting Tip:</strong> If multiple cameras in the same Production House are offline, please check the local network switch or power distribution unit (PDU) for that area.
            </p>
        </div>
        <div class="footer">
            <p>Automated Monitoring Report | IIoT Solar Group System</p>
            <p class="timestamp">Data Snapshot: {timestamp}</p>
        </div>
    </div>
</body>
</html>
"""

def connect_to_db():
    return spg.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port='5432')

def fetch_inactive_cameras():
    logger.info("Connecting to database to fetch offline cameras...")
    con = None
    try:
        con = connect_to_db()
        with con.cursor() as cur:
            cur.execute("SELECT plant, production_house, area, rtsp_link FROM camera_health WHERE status = false;")
            rows = cur.fetchall()
            logger.info(f"Database query successful. Found {len(rows)} offline cameras.")
            return rows or []
    except Exception as e:
        logger.error(f"DATABASE ERROR: {e}")
        return []
    finally:
        if con: con.close()

def send_email(subject, html_body, to_recipients, cc_recipients, bcc_recipients):
    all_recipients = to_recipients + cc_recipients + bcc_recipients
    logger.info(f"Preparing email: '{subject}'")
    logger.info(f"Recipients: TO={len(to_recipients)}, CC={len(cc_recipients)}, BCC={len(bcc_recipients)} (Total: {len(all_recipients)})")
    
    message = MIMEText(html_body, "html")
    message["Subject"] = subject
    message["From"] = SENDER_EMAIL
    message["To"] = ", ".join(to_recipients)
    message["Cc"] = ", ".join(cc_recipients)
    message["Bcc"] = ", ".join(bcc_recipients)

    try:
        logger.info(f"Connecting to SMTP server {SMTP_SERVER}...")
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SENDER_EMAIL, all_recipients, message.as_string())
        logger.info("✅ EMAIL SENT SUCCESSFULLY.")
    except Exception as e:
        logger.error(f"❌ SMTP ERROR: {e}")

def run_report_logic(to_recipients, cc_recipients):
    logger.info("--- STARTING REPORT GENERATION LOGIC ---")
    inactive_data = fetch_inactive_cameras()
    now = datetime.now()
    timestamp_str = now.strftime("%B %d, %Y at %I:%M %p")
    
    if not inactive_data:
        logger.info("All cameras are ONLINE. Generating 'Success' report.")
        subject = "DAILY REPORT: PPE Camera System [ALL ONLINE]"
        html_content = HTML_TEMPLATE.format(
            accent_color="#2e7d32", card_bg="#e8f5e9",
            status_title="SYSTEM OPERATIONAL",
            status_message="All PPE monitoring cameras are currently verified as ONLINE.",
            table_content="<div style='text-align:center; padding:30px; color:#2e7d32; font-weight:bold;'>✔ No network issues detected.</div>",
            timestamp=timestamp_str
        )
    else:
        logger.info(f"Building Offline Alert report for {len(inactive_data)} units...")
        subject = f"ALERT: {len(inactive_data)} PPE Cameras Offline"
        
        table_rows = ""
        for plant, ph, area, rtsp in inactive_data:
            ip = extract_ip(rtsp)
            logger.info(f" > Mapping: {plant} | {ph} | {area} | IP: {ip}")
            table_rows += f"""
            <tr>
                <td>{plant}</td>
                <td><strong>{ph}</strong></td>
                <td>{area}</td>
                <td><span class="ip-badge">{ip}</span></td>
            </tr>"""

        table_html = f"""
        <table>
            <thead>
                <tr>
                    <th>Plant</th>
                    <th>Production House</th>
                    <th>Area</th>
                    <th>Camera IP</th>
                </tr>
            </thead>
            <tbody>{table_rows}</tbody>
        </table>"""

        html_content = HTML_TEMPLATE.format(
            accent_color="#d32f2f", card_bg="#ffebee",
            status_title="ACTION REQUIRED: OFFLINE CAMERAS",
            status_message=f"The following {len(inactive_data)} units were unreachable during the scheduled health check.",
            table_content=table_html, 
            timestamp=timestamp_str
        )

    send_email(subject, html_content, to_recipients, cc_recipients, bcc_recipients)
    logger.info("--- REPORT LOGIC COMPLETED ---")

if __name__ == '__main__':
    to_recipients = ["py10919@solargroup.com", "alkesh.dodke@solargroup.com", "umesh.meshram@solargroup.com", "satish.bhajane@solargroup.com"]
    cc_recipients = [
        "hemant.tepale@solargroup.com", "sujay.kumar@solargroup.com", "paresh.tripathi@solargroup.com", "sachin.jamgade@solargroup.com", "nitin.gaikwad@solargroup.com"
    ]
    bcc_recipients = [
        "lalit.bopche@solargroup.com", "anurag.gokhale@solargroup.com", "saimadhu.muthyala@solargroup.com", 
        "ayush.shirbhate@solargroup.com", "rashi.channawar@solargroup.com",
        "avantika.malgewar@solargroup.com", "jay.jogi@solargroup.com"
    ]

    logger.info("Mailing Service Initialized.")
    logger.info(f"DB Host: {DB_HOST} | User: {DB_USER}")
    
    if TEST_MODE:
        logger.info("TEST_MODE IS ACTIVE: Bypassing timer to send report immediately...")
        run_report_logic(to_recipients, cc_recipients)

    last_sent_date = datetime.now().date() if TEST_MODE else None

    logger.info("Entering Main Loop. Target trigger time: 10:00 AM daily.")
    while True:
        now = datetime.now()
        
        # Log heartbeats every hour so you know the script hasn't crashed
        if now.minute == 0 and now.second < 10:
             logger.info(f"Heartbeat: Service is active. Current Time: {now.strftime('%H:%M')}")

        if now.hour == 10 and last_sent_date != now.date():
            logger.info("Target time 10:00 AM reached. Initiating daily health report...")
            run_report_logic(to_recipients, cc_recipients)
            last_sent_date = now.date()
        
        time.sleep(30) # Check more frequently to ensure we hit the 10:00 AM window