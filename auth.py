from typing import Tuple, Optional
import os
import random
import smtplib
import re
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer # type: ignore
from passlib.context import CryptContext # type: ignore
from sqlalchemy import create_engine, text # type: ignore
from flask import request # type: ignore

# --- Configuration ---
load_dotenv()

# Security Rule Constants
MAX_FAILED_ATTEMPTS = 3
LOCKOUT_DURATION_MINS = 30
PASSWORD_EXPIRY_DAYS = 30
PASSWORD_HISTORY_LIMIT = 5

username = os.getenv('DB_USER')
password = os.getenv('DB_PASS_ENC')
host = os.getenv('DB_HOST')
port = os.getenv('DB_PORT')
dbname = os.getenv('DB_NAME')

db_url = f"postgresql://{username}:{password}@{host}:{port}/{dbname}"
engine = create_engine(db_url)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv('SECRET_KEY')
serializer = URLSafeTimedSerializer(SECRET_KEY)

# Email configuration
MAIL_SERVER = os.getenv('SMTP_SERVER')
MAIL_PORT = int(os.getenv('SMTP_PORT'))
MAIL_USERNAME = os.getenv('SMTP_USERNAME')
MAIL_PASSWORD = os.getenv('SMTP_PASSWORD')
MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True').lower() in ['true', '1', 't']
MAIL_SENDER_NAME = os.getenv('MAIL_SENDER_NAME', 'Dashboard Admin')

# --- Password and User Functions ---

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def hash_password(password):
    return pwd_context.hash(password)

def get_user_by_email(email):
    query = text("""
        SELECT id, email, _password_hash, role, is_active, 
               password_updated_at, failed_attempts, locked_until 
        FROM users WHERE email = :email
    """)
    with engine.connect() as connection:
        result = connection.execute(query, {'email': email}).fetchone()
        return result

# --- Security Logic Functions ---

def is_password_strong(password: str) -> Tuple[bool, str]:
    """Rule: 14 Chars Min + Complexity."""
    if len(password) < 14:
        return False, "Password must be at least 14 characters long."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number."
    if not re.search(r"[!@#$%^&*(),.?:{}|<>]", password):
        return False, "Password must contain at least one special character."
    return True, "Strong"

def check_lockout(user) -> Tuple[bool, str]:
    """Rule: Lockout for 30 mins after 3 fails."""
    if user.locked_until:
        locked_until = user.locked_until.replace(tzinfo=timezone.utc) if user.locked_until.tzinfo is None else user.locked_until
        if datetime.now(timezone.utc) < locked_until:
            remaining = int((locked_until - datetime.now(timezone.utc)).total_seconds() // 60)
            return True, f"Account locked. Try again in {remaining} minutes."
    return False, ""

def handle_failed_login(user_id, current_fails):
    new_attempts = (current_fails or 0) + 1
    locked_until = None
    if new_attempts >= MAX_FAILED_ATTEMPTS:
        locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINS)
    
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("UPDATE users SET failed_attempts = :att, locked_until = :lu WHERE id = :id"), 
                         {'att': new_attempts, 'lu': locked_until, 'id': user_id})

def reset_login_attempts(user_id):
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = :id"), {'id': user_id})

def is_password_expired(password_updated_at) -> bool:
    """Rule: 30-day expiry."""
    if not password_updated_at: return True
    updated_at = password_updated_at.replace(tzinfo=timezone.utc) if password_updated_at.tzinfo is None else password_updated_at
    return datetime.now(timezone.utc) > (updated_at + timedelta(days=PASSWORD_EXPIRY_DAYS))

def is_password_reused(user_id, new_password) -> bool:
    """Rule: Last 5 passwords history."""
    query = text("SELECT _password_hash FROM password_history WHERE user_id = :u_id ORDER BY created_at DESC LIMIT :limit")
    with engine.connect() as conn:
        history = conn.execute(query, {'u_id': user_id, 'limit': PASSWORD_HISTORY_LIMIT}).fetchall()
        for record in history:
            if verify_password(new_password, record[0]): return True
    return False

# --- OTP Functions ---

def generate_otp():
    return str(random.randint(100000, 999999))

def store_otp(user_id, otp_code):
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text("DELETE FROM otps WHERE user_id = :user_id"), {'user_id': user_id})
            connection.execute(text("""
                INSERT INTO otps (user_id, otp_code, created_at, expires_at)
                VALUES (:user_id, :otp_code, :now, :exp)
            """), {'user_id': user_id, 'otp_code': otp_code, 'now': datetime.now(timezone.utc), 'exp': expires_at})

def verify_otp(user_id: int, otp_code: str) -> Tuple[bool, str]:
    if not (otp_code and len(otp_code) == 6): return False, "Invalid OTP format."
    query = text("SELECT otp_code FROM otps WHERE user_id = :user_id AND expires_at > :now")
    with engine.connect() as connection:
        record = connection.execute(query, {'user_id': user_id, 'now': datetime.now(timezone.utc)}).fetchone()
    if not record: return False, "Your OTP is invalid or has expired."
    if record.otp_code == otp_code:
        with engine.connect() as conn:
            with conn.begin(): conn.execute(text("DELETE FROM otps WHERE user_id = :user_id"), {'user_id': user_id})
        return True, "Success"
    return False, "Incorrect OTP code."

# --- RESTORED: STYLED EMAIL FUNCTIONS ---

def send_otp_email(recipient_email, otp_code):
    """Sends beautifully formatted HTML OTP email."""
    if not all([MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD]): return False
    message = MIMEMultipart("alternative")
    message["Subject"] = "Your PPEs Dashboard Login Code"
    message["From"] = f"{MAIL_SENDER_NAME} <{MAIL_USERNAME}>"
    message["To"] = recipient_email

    text_part = f"Your One-Time Password is: {otp_code}\nValid for 5 minutes."
    html_part = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; padding: 0;">
        <table border="0" cellpadding="0" cellspacing="0" width="100%">
            <tr><td style="padding: 20px 0;" align="center">
                <table align="center" border="0" cellpadding="0" cellspacing="0" width="600" style="border: 1px solid #cccccc; background-color: #ffffff;">
                    <tr><td align="center" style="padding: 40px 0; background-color: #0a192f; color: #ffffff; font-size: 28px; font-weight: bold;">PPE Monitoring Dashboard</td></tr>
                    <tr><td style="padding: 40px 30px;">
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr><td style="color: #153643; font-size: 24px; font-weight: bold;">Your Login Code</td></tr>
                            <tr><td style="padding: 20px 0; color: #153643; font-size: 16px;">Use the code below to login. Valid for 5 minutes.</td></tr>
                            <tr><td align="center" style="padding: 20px; background-color: #eeeeee; border-radius: 5px;">
                                <p style="font-size: 48px; font-weight: bold; letter-spacing: 10px; margin: 0; color: #c32026;">{otp_code}</p>
                            </td></tr>
                        </table>
                    </td></tr>
                    <tr><td style="padding: 30px; background-color: #eeeeee; color: #707070; font-size: 12px;" align="center">If you did not request this, please ignore.</td></tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>"""
    message.attach(MIMEText(text_part, "plain"))
    message.attach(MIMEText(html_part, "html"))
    try:
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            if MAIL_USE_TLS: server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_USERNAME, recipient_email, message.as_string())
        return True
    except: return False

def send_password_reset_email(recipient_email, reset_token):
    """Sends beautifully formatted HTML Password Reset email."""
    if not all([MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD]): return False
    
    # FIX: No port 8000
    base_url = os.getenv('APP_BASE_URL', 'https://ppes-siil.solargroup.com').rstrip('/')
    reset_url = f"{base_url}/reset-password/{reset_token}"

    message = MIMEMultipart("alternative")
    message["Subject"] = "PPEs Dashboard - Password Reset Request"
    message["From"] = f"{MAIL_SENDER_NAME} <{MAIL_USERNAME}>"
    message["To"] = recipient_email

    text_part = f"Reset your password here: {reset_url}\nValid for 30 minutes."
    html_part = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; padding: 0;">
        <table border="0" cellpadding="0" cellspacing="0" width="100%">
            <tr><td style="padding: 20px 0;" align="center">
                <table align="center" border="0" cellpadding="0" cellspacing="0" width="600" style="border: 1px solid #cccccc; background-color: #ffffff;">
                    <tr><td align="center" style="padding: 40px 0; background-color: #0a192f; color: #ffffff; font-size: 28px; font-weight: bold;">PPE Monitoring Dashboard</td></tr>
                    <tr><td style="padding: 40px 30px;">
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr><td style="color: #153643; font-size: 24px; font-weight: bold;">Password Reset Request</td></tr>
                            <tr><td style="padding: 20px 0; color: #153643; font-size: 16px;">Click the button below to set a new password. Valid for 30 minutes.</td></tr>
                            <tr><td align="center">
                                <a href="{reset_url}" style="background-color: #c32026; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">Reset Your Password</a>
                            </td></tr>
                        </table>
                    </td></tr>
                    <tr><td style="padding: 30px; background-color: #eeeeee; color: #707070; font-size: 12px;" align="center">If you did not request this, please ignore.</td></tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>"""
    message.attach(MIMEText(text_part, "plain"))
    message.attach(MIMEText(html_part, "html"))
    try:
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            if MAIL_USE_TLS: server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_USERNAME, recipient_email, message.as_string())
        return True
    except: return False

# --- Management & Admin Functions ---

def update_user_password(email, new_password) -> Tuple[bool, str]:
    user = get_user_by_email(email)
    if not user: return False, "User not found."
    is_strong, msg = is_password_strong(new_password)
    if not is_strong: return False, msg
    if is_password_reused(user.id, new_password): return False, "You cannot reuse any of your last 5 passwords."
    
    new_hash = hash_password(new_password)
    now = datetime.now(timezone.utc)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text("UPDATE users SET _password_hash = :h, password_updated_at = :now, failed_attempts = 0, locked_until = NULL WHERE email = :e"), 
                             {'h': new_hash, 'now': now, 'e': email})
                conn.execute(text("INSERT INTO password_history (user_id, _password_hash, created_at) VALUES (:u, :h, :now)"), 
                             {'u': user.id, 'h': new_hash, 'now': now})
        return True, "Success"
    except Exception as e: return False, str(e)

def add_new_user(email, password, role):
    if not email.endswith('@solargroup.com'): return False, "Must be @solargroup.com"
    is_strong, msg = is_password_strong(password)
    if not is_strong: return False, msg
    if get_user_by_email(email): return False, "User exists."
    
    h = hash_password(password)
    now = datetime.now(timezone.utc)
    try:
        with engine.connect() as conn:
            with conn.begin():
                uid = conn.execute(text("INSERT INTO users (email, _password_hash, role, password_updated_at) VALUES (:e, :h, :r, :n) RETURNING id"),
                                   {'e': email, 'h': h, 'r': role, 'n': now}).fetchone()[0]
                conn.execute(text("INSERT INTO password_history (user_id, _password_hash, created_at) VALUES (:u, :h, :n)"), {'u': uid, 'h': h, 'n': now})
        return True, "User added."
    except Exception as e: return False, str(e)

def get_all_users():
    query = text("SELECT id, email, role, is_active FROM users ORDER BY id")
    with engine.connect() as connection:
        result = connection.execute(query).fetchall()
        return [dict(row._mapping) for row in result]

def toggle_user_status(user_id):
    with engine.connect() as connection:
        with connection.begin(): connection.execute(text("UPDATE users SET is_active = NOT is_active WHERE id = :u"), {'u': user_id})
    return True

def delete_user(user_id):
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text("DELETE FROM password_history WHERE user_id = :u"), {'u': user_id})
            connection.execute(text("DELETE FROM otps WHERE user_id = :u"), {'u': user_id})
            connection.execute(text("DELETE FROM users WHERE id = :u"), {'u': user_id})
    return True

# --- Logging ---

def log_activity(action, user_id=None, user_email=None, details=None, ip_address=None):
    ip_address = ip_address or request.remote_addr
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text("INSERT INTO activity_logs (user_id, user_email, action, details, ip_address) VALUES (:u, :e, :a, :d, :ip)"),
                                   {'u': user_id, 'e': user_email, 'a': action, 'd': details, 'ip': ip_address})
        return True
    except: return False

def get_activity_logs(limit=100):
    query = text("SELECT user_email, action, details, ip_address, to_char(timestamp, 'DD Mon YYYY HH:MI:SS AM') as formatted_time FROM activity_logs ORDER BY timestamp DESC LIMIT :l")
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query, {'l': limit}).fetchall()]

def generate_reset_token(email): return serializer.dumps(email, salt='password-reset-salt')
def verify_reset_token(token, max_age=1800):
    try: return serializer.loads(token, salt='password-reset-salt', max_age=max_age)
    except: return None