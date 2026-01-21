# app/utils/emailer.py
# Full path: WebChurchMan/app/utils/emailer.py
# File name: emailer.py
# Brief, detailed purpose: Centralized email sending utility for MyVineChurch.Online.
#          Loads encrypted SMTP credentials from the settings table using the same Fernet key as old_settings.py.
#          Safe decryption (handles None/empty/invalid tokens gracefully).
#          Supports SSL (implicit, port 465) and TLS (STARTTLS, port 587).
#          Clear, user-friendly error messages for common issues (no password set, auth failure, connection issues).
#          Used by settings test email, event invites, donation reminders, etc.
#          Audit logs successful sends via log_change (optional caller provides user_id).

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from cryptography.fernet import Fernet
from app.models.db import get_db_connection
from app.models.log import log_change  # Optional for logging sends

# --- Identical key loading as old_settings.py ---
key_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config_key.bin')
env_key = os.environ.get('ENCRYPTION_KEY')

if env_key:
    key = env_key.encode()
elif os.path.exists(key_path):
    with open(key_path, 'rb') as f:
        key = f.read()
else:
    # Should never happen – old_settings.py generates it on first run
    raise FileNotFoundError("Encryption key not found. Delete config_key.bin and restart to regenerate.")

cipher = Fernet(key)

def _decrypt(token: str or None) -> str:
    """Safe decrypt – returns empty string for None, empty, or invalid tokens."""
    if not token:
        return ''
    try:
        return cipher.decrypt(token.encode()).decode()
    except Exception:
        return ''  # Invalid/old token – treat as empty

def send_email(to_email: str, subject: str, body: str, from_email: str or None = None, user_id: int or None = None):
    """
    Send an email using the encrypted SMTP settings from the database.
    Raises clear exceptions for common failures (helps test email feedback).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT outgoing_server, outgoing_port, outgoing_encryption, outgoing_username, outgoing_password FROM settings WHERE id = 1")
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise ValueError("Email settings not configured in Settings dashboard.")

    server = row['outgoing_server']
    port = row['outgoing_port']
    encryption = row['outgoing_encryption'] or 'None'
    username = _decrypt(row['outgoing_username'])
    password = _decrypt(row['outgoing_password'])

    if not server or not port:
        raise ValueError("SMTP server or port not configured in Settings.")

    if not username or not password:
        raise ValueError("SMTP username or password not set. Go to Settings > Email Settings & Test and enter/re-enter them, then save.")

    # Default from email if not provided
    if not from_email:
        from_email = username  # Use the SMTP username as sender

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        if encryption == 'SSL':
            server_obj = smtplib.SMTP_SSL(server, port)
        else:
            server_obj = smtplib.SMTP(server, port)
            if encryption == 'TLS':
                server_obj.starttls()

        server_obj.login(username, password)
        server_obj.send_message(msg)
        server_obj.quit()

        if user_id:
            log_change(user_id, 'email', change_details=f'Sent email to {to_email} subject "{subject}"')

    except smtplib.SMTPAuthenticationError:
        raise ValueError("SMTP authentication failed – check username/password in Settings (re-enter password and save to fix decryption issues).")
    except smtplib.SMTPConnectError:
        raise ValueError(f"Could not connect to SMTP server {server}:{port} – check server, port, and encryption settings.")
    except Exception as e:
        raise ValueError(f"Email sending failed: {str(e)}")