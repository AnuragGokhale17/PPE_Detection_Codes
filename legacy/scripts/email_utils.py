import smtplib
import requests
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import time
import os
from dotenv import load_dotenv

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Centralized Recipient Configuration ---
DEFAULT_TO_RECIPIENTS = [""]
DEFAULT_CC_RECIPIENTS = [""]

production_house_recipients = {
    "Chakdoh Plant": {
        "to": [""],
        "cc": [""]
    }
}

def send_email(subject, violation_details, receivers, cc_receivers=None, max_retries=3, retry_delay=10):
    """
    A reusable function to send a formatted PPE violation email with an embedded image.
    Returns: (bool: success, str: message)
    """
    sender_email = os.getenv("SMTP_EMAIL")
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD") # Consider moving this to .env for better security

    all_receivers = receivers + (cc_receivers or [])
    if not all_receivers:
        logger.warning("No recipients specified. Aborting email send.")
        return False, "No recipients specified."

    message = MIMEMultipart("related")
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = ", ".join(receivers)
    if cc_receivers:
        message["Cc"] = ", ".join(cc_receivers)

    # Standardized HTML body
    html_body = f"""
    <html><head><style>
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
    </style></head><body>
    <div class="container">
        <div class="header"><h2>PPE Violation Alert</h2></div>
        <div class="content">
            <p>Dear Sir/Ma'am,</p>
            <p>This is a notification regarding a PPE violation. The details are provided below for your review and follow-up.</p>
            <table class="details-table">
                <tr><td>Production House</td><td>{violation_details.get('production_house', 'N/A')}</td></tr>
                <tr><td>Area</td><td>{violation_details.get('area', 'N/A')}</td></tr>
                <tr><td>Violation Type</td><td>{violation_details.get('class1', 'N/A')}</td></tr>
                <tr><td>Date</td><td>{violation_details.get('date1', 'N/A')}</td></tr>
                <tr><td>Time</td><td>{violation_details.get('time1', 'N/A')}</td></tr>
            </table>
            <h3>Violation Evidence:</h3>
            <div class="image-container"><img src="cid:violation_image" alt="Violation Image"></div>
        </div>
        <div class="footer">
            <p>This is an auto-generated email from the IIoT Monitoring System.</p>
        </div>
    </div></body></html>
    """
    message.attach(MIMEText(html_body, "html"))

    # Download and embed the image
    image_url = violation_details.get('image_url')
    if not image_url:
        logger.error("No image URL provided in violation details.")
        return False, "No image URL found."

    try:
        response = requests.get(image_url, timeout=20)
        response.raise_for_status()
        image_data = response.content
        image_part = MIMEImage(image_data)
        image_part.add_header('Content-ID', '<violation_image>')
        message.attach(image_part)
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download image from {image_url}: {e}")
        return False, "Failed to download image."

    # Send the email with retries
    for attempt in range(max_retries):
        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_username, smtp_password)
                server.sendmail(sender_email, all_receivers, message.as_string())
            logger.info(f"Email sent successfully to: {', '.join(all_receivers)}")
            return True, "Email sent successfully."
        except smtplib.SMTPException as e:
            logger.error(f"Error sending email (Attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    
    logger.error(f"Failed to send email after {max_retries} attempts.")
    return False, f"Failed to send email after {max_retries} attempts."