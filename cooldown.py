import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import psycopg2 as spg
import time
import logging
from email.mime.image import MIMEImage
import requests
import socket
import os
from dotenv import load_dotenv

from worker_common import LocalStorage

load_dotenv()

# --- ADD THIS SNIPPET TO FIX THE ERROR ---
orig_getaddrinfo = socket.getaddrinfo

def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    # Force the family to AF_INET (IPv4)
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

socket.getaddrinfo = getaddrinfo_ipv4

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_NAME = os.getenv("DB_NAME")
DB_PORT = os.getenv("DB_PORT", "5432")
# Recipients now live in the alert_recipients table (channel 'violation') and are
# managed per production house in the portal: Configuration -> Alert recipients.


class CooldownTracker:
    def __init__(self):
        self.cooldown_dict = {}

    def should_send_email(self, production_house, area_type):
        key = f"{production_house}_{area_type}"
        last_sent_time = self.cooldown_dict.get(key, datetime.min)
        current_time = datetime.now()
        cooldown_period = timedelta(minutes=360)  # 6 hours

        if current_time - last_sent_time >= cooldown_period:
            self.cooldown_dict[key] = current_time
            logger.info(f"Cooldown check passed for {key}.")
            return True
        else:
            logger.info(f"Cooldown active for {key}. Email will not be sent.")
            return False

def connect_to_db():
    try:
        con = spg.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT
        )
        # No need for autocommit with simple INSERTs if you manage the transaction
        cur = con.cursor()
        return con, cur
    except spg.Error as e:
        logger.error(f"Error connecting to the database: {e}")
        raise

# ### CHANGED ###: Accepts lists for recipients for cleaner data handling
def insert_email_record(class_label, production_house, area, to_recipients_list, cc_recipients_list):
    con, cur = connect_to_db()
    try:
        current_date = datetime.now().date()
        current_time = datetime.now().time().strftime('%H:%M:%S')
        
        # Convert lists to comma-separated strings for database storage
        to_str = ", ".join(to_recipients_list)
        cc_str = ", ".join(cc_recipients_list)

        cur.execute("""
            INSERT INTO ppes_emails_records (class_label, production_house, area, to_recipients, cc_recipients, insert_date, insert_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s);
        """, (class_label, production_house, area, to_str, cc_str, current_date, current_time))
        con.commit()
        logger.info("Email record inserted successfully.")
    except spg.Error as e:
        logger.error(f"Error inserting email record into the database: {e}")
        con.rollback() # Rollback on error
        raise
    finally:
        if con:
            con.close()

def fetch_recent_violations(limit=20):
    con, cur = connect_to_db()
    try:
        # ### NEW ###: Using a dictionary cursor to make code more readable later
        from psycopg2.extras import RealDictCursor
        cur = con.cursor(cursor_factory=RealDictCursor)

        # Events a reviewer marked as false positive (violation = false) are never emailed
        cur.execute("""
            SELECT id, camera_id, class1, production_house, camera_unit, date1, time1, image_url, area
            FROM ppes
            WHERE violation IS NOT FALSE
            ORDER BY id DESC
            LIMIT %s;
        """, (limit,))
        violations = cur.fetchall()
        return violations
    except spg.Error as e:
        logger.error(f"Error fetching violations from the database: {e}")
        raise
    finally:
        if con:
            con.close()

def fetch_recipients(camera_id, production_house):
    """TO / CC / BCC lists for a production house from alert_recipients (channel 'violation').
    The event's camera decides the production house; older rows without camera_id match by name."""
    con, cur = connect_to_db()
    try:
        cur.execute("""
            SELECT ar.email, ar.kind
            FROM alert_recipients ar
            WHERE ar.channel = 'violation'
              AND ar.production_house_id = COALESCE(
                    (SELECT c.production_house_id FROM cameras c WHERE c.id = %s),
                    (SELECT ph.id FROM production_houses ph WHERE ph.name = %s ORDER BY ph.id LIMIT 1))
            ORDER BY ar.id;
        """, (camera_id, production_house))
        recipients = {"to": [], "cc": [], "bcc": []}
        for email, kind in cur.fetchall():
            recipients.setdefault(kind, []).append(email)
        return recipients["to"], recipients["cc"], recipients["bcc"]
    finally:
        con.close()

def load_image_bytes(image_url):
    """Evidence image for the email: MinIO URL, or a local:// fallback written by inference.py."""
    if image_url.startswith("local://") or not image_url.startswith("http"):
        key = image_url.replace("local://", "", 1)
        local = LocalStorage()
        if local.exists(key):
            return local.get_bytes(key)
        # Pre-v2 fallback layout: saved_violations/<file> next to the scripts
        local_path = key
        if not os.path.exists(local_path):
            script_dir = os.path.dirname(os.path.realpath(__file__))
            local_path = os.path.join(script_dir, local_path)
        with open(local_path, "rb") as f:
            return f.read()
    response = requests.get(image_url, timeout=20, verify=False)
    response.raise_for_status()  # Will raise an HTTPError for bad responses (4xx or 5xx)
    return response.content

# ### CHANGED ###: Major overhaul of this function for better formatting and image embedding
def send_email(subject, violation_details, receivers, cc_receivers=None, bcc_receivers=None, max_retries=3, retry_delay=10):
    sender_email = os.getenv("SMTP_EMAIL")
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")

    # BCC recipients are only in the SMTP envelope, never in the headers
    all_receivers = receivers + (cc_receivers or []) + (bcc_receivers or [])
    if not all_receivers:
        logger.warning("No recipients specified. Aborting email send.")
        return

    message = MIMEMultipart("related")
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = ", ".join(receivers)
    if cc_receivers:
        message["Cc"] = ", ".join(cc_receivers)

    # --- Create the new, standardized HTML body ---
    # This template is more robust and centers content for better readability.
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 0; background-color: #f4f4f4; }}
            .container {{ max-width: 680px; margin: 20px auto; background-color: #ffffff; border: 1px solid #dddddd; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
            .header {{ background-color: #B22222; color: #ffffff; padding: 20px; text-align: center; border-top-left-radius: 8px; border-top-right-radius: 8px; }}
            .header h2 {{ margin: 0; font-size: 24px; }}
            .content {{ padding: 30px; }}
            .content p {{ font-size: 16px; line-height: 1.6; color: #333333; }}
            .details-table {{ width: 100%; border-collapse: collapse; margin-top: 20px; margin-bottom: 25px; }}
            .details-table td {{ padding: 12px 15px; border: 1px solid #eeeeee; }}
            .details-table td:first-child {{ font-weight: bold; background-color: #f9f9f9; width: 30%; }}
            .image-container {{ text-align: center; margin-top: 20px; }}
            .image-container img {{ max-width: 100%; height: auto; border: 1px solid #dddddd; border-radius: 4px; }}
            .footer {{ text-align: left; padding: 20px; font-size: 12px; color: #777777; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>PPE Violation Alert</h2>
            </div>
            <div class="content">
                <p>Dear Sir/Ma'am,</p>
                <p>This is an automated notification regarding a potential PPE violation detected by the safety monitoring system.</p>
                <p>The details of the incident are provided below. Your prompt review and follow-up are requested to ensure compliance with our safety protocols.</p>
                
                <table class="details-table">
                    <tr><td>Production House</td><td>{violation_details['production_house']}</td></tr>
                    <tr><td>Area</td><td>{violation_details['area']}</td></tr>
                    <tr><td>Violation Type</td><td>{violation_details['class1']}</td></tr>
                    <tr><td>Date</td><td>{violation_details['date1']}</td></tr>
                    <tr><td>Time</td><td>{violation_details['time1']}</td></tr>
                </table>

                <h3>Violation Evidence:</h3>
                <div class="image-container">
                    <img src="cid:violation_image" alt="Violation Image">
                </div>
            </div>
            <div class="footer">
                <p>This is an auto-generated email from the IIoT Monitoring System.</p>
                <p>Please do not reply to this message.</p>
            </div>
        </div>
    </body>
    </html>
    """
    message.attach(MIMEText(html_body, "html"))

    # --- Download and embed the image ---
    image_url = violation_details.get('image_url')
    if not image_url:
        logger.error("No image URL provided in violation details.")
        return # Or send email without image

    try:
        image_data = load_image_bytes(image_url)

        # ### NEW ###: Create MIMEImage and set Content-ID
        # This is the crucial step for embedding. The 'cid' in the <img> tag
        # must match the name in the <...> brackets here.
        image_part = MIMEImage(image_data)
        image_part.add_header('Content-ID', '<violation_image>')
        message.attach(image_part)

    except Exception as e:
        logger.error(f"Failed to load image from {image_url}: {e}")
        # Proceed with email without image rather than completely aborting
        return

    # --- Send the email with retries ---
    for attempt in range(max_retries):
        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_username, smtp_password)
                server.sendmail(sender_email, all_receivers, message.as_string())
            logger.info(f"Email sent successfully to: {', '.join(all_receivers)}")
            return
        except smtplib.SMTPException as e:
            logger.error(f"Error sending email (Attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)

    logger.error(f"Failed to send email after {max_retries} attempts. Aborting.")


if __name__ == '__main__':
    cooldown_tracker = CooldownTracker()
    processed_violations = set() # ### NEW ###: Track recently processed violations to avoid duplicates in a single run

    while True:
        try:
            # Fetch recent violations from the database
            # We use a dictionary cursor, so each 'violation' is a dictionary
            recent_violations = fetch_recent_violations(limit=20)

            for violation in recent_violations:
                # ### NEW ###: Create a unique key for the violation to prevent re-processing
                violation_key = (violation['production_house'], violation['area'], violation['date1'], violation['time1'])
                if violation_key in processed_violations:
                    continue # Skip if already processed in this session
                
                # Check cooldown period
                if cooldown_tracker.should_send_email(violation['production_house'], violation['area']):

                    # Recipients configured for this production house in the portal
                    ph_key = violation['production_house']
                    to_list, cc_list, bcc_list = fetch_recipients(violation.get('camera_id'), ph_key)
                    if not to_list:
                        logger.warning(
                            f"No alert recipients configured for production house '{ph_key}'. "
                            f"Add them in the portal (Configuration -> Alert recipients). Skipping email."
                        )
                        processed_violations.add(violation_key)
                        continue

                    # Insert record into the database using the lists
                    insert_email_record(violation['class1'], ph_key, violation['area'], to_list, cc_list)

                    # Send email with all violation details
                    subject = f"PPE Violation Detected: {violation['class1']} in {ph_key}, {violation['area']}"
                    send_email(subject, violation, to_list, cc_list, bcc_list)

                    # Mark as processed for this session
                    processed_violations.add(violation_key)

            # Sleep for a specified duration before the next iteration
            logger.info("Cycle complete. Sleeping for 15 seconds...")
            time.sleep(15)  # Adjust the sleep duration as needed

        except Exception as e:
            logger.critical(f"An unexpected error occurred in the main loop: {e}", exc_info=True)
            time.sleep(60) # Wait a minute before retrying after a major error