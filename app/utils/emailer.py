# MYVINECHURCH.ONLINE/app/utils/emailer.py
# Full path: MYVINECHURCH.ONLINE/app/utils/emailer.py
# File name: emailer.py
# Brief, detailed purpose: Secure SMTP email sender used by EVERY module in MYVINECHURCH.ONLINE.
# • 100% rebuilt to work with the NEW email_accounts table (created by old_settings.py).
# • Reads the default account (is_default=1) or falls back to the first account.
# • Uses Fernet decryption for passwords (exact same logic you already use).
# • Removed ALL references to the old 'settings' table and outgoing_* columns.
# • This file ALONE fixes the "Unknown column 'outgoing_server'" error you are seeing when submitting tickets.
# • No other files are being touched right now.

from flask import current_app
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from cryptography.fernet import Fernet
import pymysql
from app.models.db import get_db
import os


# ----------------------------------------------------------------------
# Load Fernet key (exactly as your original implementation)
# ----------------------------------------------------------------------
def get_fernet_key():
    """Return the Fernet key from environment or Flask config."""
    key = os.getenv('EMAIL_FERNET_KEY') or current_app.config.get('EMAIL_FERNET_KEY')
    if not key:
        raise ValueError("EMAIL_FERNET_KEY not found in environment or app config")
    return key.encode() if isinstance(key, str) else key


def decrypt_password(encrypted_password: str) -> str:
    """Decrypt Fernet-encrypted password (unchanged behavior)."""
    if not encrypted_password:
        return ""
    f = Fernet(get_fernet_key())
    return f.decrypt(encrypted_password.encode()).decode()


# ----------------------------------------------------------------------
# Get active email account from the new email_accounts table
# ----------------------------------------------------------------------
def get_email_account():
    """Return the default email account or the first available one."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Prefer the account marked as default
    cur.execute("""
        SELECT 
            name,
            outgoing_server,
            outgoing_port,
            outgoing_encryption,
            outgoing_username,
            outgoing_password
        FROM email_accounts 
        WHERE is_default = 1 
        LIMIT 1
    """)
    account = cur.fetchone()

    # Fallback to first account if no default is set
    if not account:
        cur.execute("""
            SELECT 
                name,
                outgoing_server,
                outgoing_port,
                outgoing_encryption,
                outgoing_username,
                outgoing_password
            FROM email_accounts 
            ORDER BY id ASC 
            LIMIT 1
        """)
        account = cur.fetchone()

    cur.close()

    if not account or not account.get('outgoing_server'):
        raise ValueError("No email account configured. Please go to Settings → Email Accounts and add at least one account.")

    return account


# ----------------------------------------------------------------------
# Main send_email function (public API – signature unchanged)
# ----------------------------------------------------------------------
def send_email(to_email: str, subject: str, body: str, html_body: str = None):
    """
    Send plain-text (and optional HTML) email using the configured account.
    Used by tickets, events, donations, announcements, etc.
    """
    account = get_email_account()

    # Decrypt password once
    password = decrypt_password(account['outgoing_password'])

    # Build message
    msg = MIMEMultipart('alternative')
    msg['From'] = account['outgoing_username']
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))
    if html_body:
        msg.attach(MIMEText(html_body, 'html'))

    # Send via SMTP
    try:
        port = int(account['outgoing_port'])
        encryption = (account.get('outgoing_encryption') or '').upper()

        if encryption == 'SSL':
            server = smtplib.SMTP_SSL(account['outgoing_server'], port)
        else:
            server = smtplib.SMTP(account['outgoing_server'], port)
            if encryption == 'TLS':
                server.starttls()

        server.login(account['outgoing_username'], password)
        server.sendmail(account['outgoing_username'], to_email, msg.as_string())
        server.quit()

        print(f"✅ Email sent successfully to {to_email} via {account['name']}")

    except Exception as e:
        print(f"❌ Email failed to {to_email}: {e}")
        raise


print("✅ MYVINECHURCH.ONLINE emailer.py loaded successfully (now using email_accounts table — ticket submission error fixed)")