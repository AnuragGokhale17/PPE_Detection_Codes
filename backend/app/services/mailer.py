import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from app.core.config import get_settings

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, text: str, html: str) -> bool:
    settings = get_settings()
    if not settings.smtp_configured:
        if settings.dev_print_emails:
            log.warning("SMTP not configured; email to %s\nSubject: %s\n%s", to, subject, text)
            return True
        log.error("SMTP not configured; cannot send '%s' to %s", subject, to)
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"{settings.mail_sender_name} <{settings.smtp_username}>"
    message["To"] = to
    message.attach(MIMEText(text, "plain"))
    message.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP(settings.smtp_server, settings.smtp_port, timeout=20) as server:
            if settings.mail_use_tls:
                server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(settings.smtp_username, [to], message.as_string())
        return True
    except (smtplib.SMTPException, OSError):
        log.exception("Failed to send '%s' to %s", subject, to)
        return False


def _layout(title: str, body_html: str) -> str:
    # Table layout + inline styles: the only thing Outlook renders reliably
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f3f4f5;font-family:Montserrat,Arial,sans-serif;color:#212529;">
<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td align="center" style="padding:24px 0;">
  <table width="560" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;border:1px solid #e6e8ea;border-radius:12px;">
    <tr><td style="height:2px;background:#ed1c24;border-radius:12px 12px 0 0;font-size:0;line-height:0;">&nbsp;</td></tr>
    <tr><td style="padding:28px 32px 8px;font-size:13px;color:#707070;">Solar Smart Factory · PPE safety</td></tr>
    <tr><td style="padding:0 32px 8px;font-size:22px;font-weight:700;">{escape(title)}</td></tr>
    <tr><td style="padding:8px 32px 28px;font-size:14px;line-height:1.6;color:#464c53;">{body_html}</td></tr>
    <tr><td style="padding:16px 32px;border-top:1px solid #e6e8ea;font-size:12px;color:#707070;">
      If you did not request this, you can ignore this email.</td></tr>
  </table>
</td></tr></table></body></html>"""


def send_otp_email(to: str, code: str, ttl_minutes: int) -> bool:
    text = f"Your PPE portal sign-in code is {code}. It expires in {ttl_minutes} minutes."
    html = _layout(
        "Your sign-in code",
        f"""Use this code to finish signing in. It expires in {ttl_minutes} minutes.
        <div style="margin:20px 0;padding:18px;background:#f1f2f4;border-radius:8px;text-align:center;
                    font-size:34px;font-weight:700;letter-spacing:10px;color:#212529;">{escape(code)}</div>""",
    )
    return send_email(to, "PPE portal sign-in code", text, html)


def send_password_reset_email(to: str, link: str, ttl_minutes: int) -> bool:
    text = f"Reset your PPE portal password: {link}\nThe link expires in {ttl_minutes} minutes."
    html = _layout(
        "Reset your password",
        f"""Use the button below to choose a new password. The link expires in {ttl_minutes} minutes.
        <div style="margin:22px 0;"><a href="{escape(link)}" style="background:#d31017;color:#ffffff;
          padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:700;display:inline-block;">
          Reset password</a></div>""",
    )
    return send_email(to, "PPE portal password reset", text, html)
