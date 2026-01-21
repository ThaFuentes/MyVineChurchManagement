# myvinechurchonline/app/builddb/old_settings.py
# Full path: myvinechurchonline/app/builddb/old_settings.py
# File name: old_settings.py
# Brief, detailed purpose: Creates/updates the global settings table AND the new email_accounts table.
# • settings table remains single-row (id=1) for church-wide globals (paths, church info, censored_words, etc.).
# • NEW email_accounts table supports MULTIPLE email configurations (outgoing + optional incoming).
#   - Allows professional addresses like groups@myvinechurch.online, events@, pastors@, etc.
#   - Each account has a name, full SMTP/IMAP details, and is_default flag (only one default recommended).
#   - Passwords stored encrypted in routes (Fernet) – schema stores as TEXT.
#   - Safe migration: adds table/columns if missing, migrates legacy single email from settings to new table as "Main Account".
# • Isolated module – called from builddb.py during DB initialization.

def create_tables(cursor):
    """
    Creates/updates the settings and email_accounts tables.
    Designed for both fresh DB creation and safe migration of existing databases.
    """

    # ----- SETTINGS TABLE (single-row globals – email fields REMOVED, migrated below) -----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id                          INT PRIMARY KEY AUTO_INCREMENT,
            export_location             TEXT,
            sermon_folder_location      TEXT,
            church_name                 TEXT,
            tax_status                  TEXT,
            address                     TEXT,
            phone_number                TEXT,
            pastor                      TEXT,
            icon_path                   TEXT,
            online_donations_enabled    INTEGER DEFAULT 0,
            donations_page_title        TEXT DEFAULT 'Support Our Ministry',
            donations_welcome_text      TEXT DEFAULT 'Thank you for considering a gift to support our ministry.',
            donations_thank_you_text    TEXT DEFAULT 'Thank you for your generous support!',
            donations_extra_text        TEXT,
            censored_words              TEXT  -- One per line (UI handles JSON-like storage)
        ) ENGINE=InnoDB
    """)

    # Safe column additions for settings table
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'settings'
    """)
    existing_settings_columns = [row[0] for row in cursor.fetchall()]

    settings_columns_to_add = {
        'export_location':             "TEXT",
        'sermon_folder_location':      "TEXT",
        'church_name':                 "TEXT",
        'tax_status':                  "TEXT",
        'address':                     "TEXT",
        'phone_number':                "TEXT",
        'pastor':                      "TEXT",
        'icon_path':                   "TEXT",
        'online_donations_enabled':    "INTEGER DEFAULT 0",
        'donations_page_title':        "TEXT DEFAULT 'Support Our Ministry'",
        'donations_welcome_text':      "TEXT DEFAULT 'Thank you for considering a gift to support our ministry.'",
        'donations_thank_you_text':    "TEXT DEFAULT 'Thank you for your generous support!'",
        'donations_extra_text':        "TEXT",
        'censored_words':              "TEXT"
    }

    for col_name, col_def in settings_columns_to_add.items():
        if col_name not in existing_settings_columns:
            print(f"Migration: Adding missing column '{col_name}' to settings table.")
            cursor.execute(f"ALTER TABLE settings ADD COLUMN {col_name} {col_def}")

    # Ensure single row exists (id=1)
    cursor.execute("SELECT 1 FROM settings WHERE id = 1")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO settings (id) VALUES (1)")
        print("Created initial settings row (id=1).")

    # ----- NEW EMAIL_ACCOUNTS TABLE (multiple email configs) -----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_accounts (
            id                     INT PRIMARY KEY AUTO_INCREMENT,
            name                   TEXT NOT NULL,                     -- e.g., "Main", "Events", "Groups", "Pastors"
            outgoing_server        TEXT,
            outgoing_port          INT,
            outgoing_encryption    TEXT,                              -- e.g., 'SSL', 'TLS', 'None'
            outgoing_username      TEXT,
            outgoing_password      TEXT,                              -- Encrypted in routes
            incoming_protocol      TEXT,                              -- Optional: 'IMAP', 'POP3'
            incoming_server        TEXT,
            incoming_port          INT,
            incoming_encryption    TEXT,
            incoming_username      TEXT,
            incoming_password      TEXT,                              -- Encrypted in routes
            is_default             INTEGER DEFAULT 0,                 -- Only one should be 1 (default sender)
            created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    """)

    # Safe column additions for email_accounts
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'email_accounts'
    """)
    existing_email_columns = [row[0] for row in cursor.fetchall()]

    email_columns_to_add = {
        'name':                   "TEXT NOT NULL",
        'outgoing_server':        "TEXT",
        'outgoing_port':          "INT",
        'outgoing_encryption':    "TEXT",
        'outgoing_username':      "TEXT",
        'outgoing_password':      "TEXT",
        'incoming_protocol':      "TEXT",
        'incoming_server':        "TEXT",
        'incoming_port':          "INT",
        'incoming_encryption':    "TEXT",
        'incoming_username':      "TEXT",
        'incoming_password':      "TEXT",
        'is_default':             "INTEGER DEFAULT 0",
        'created_at':             "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    }

    for col_name, col_def in email_columns_to_add.items():
        if col_name not in existing_email_columns:
            print(f"Migration: Adding missing column '{col_name}' to email_accounts table.")
            cursor.execute(f"ALTER TABLE email_accounts ADD COLUMN {col_name} {col_def}")

    # ----- LEGACY MIGRATION: Move old single email config to new table as "Main Account" -----
    # Check if legacy email fields exist in settings (old schema)
    legacy_fields = ['outgoing_server', 'outgoing_port', 'outgoing_encryption', 'outgoing_username', 'outgoing_password']
    if all(field in existing_settings_columns for field in legacy_fields):
        cursor.execute("SELECT outgoing_server, outgoing_port, outgoing_encryption, outgoing_username, outgoing_password FROM settings WHERE id = 1")
        legacy_row = cursor.fetchone()
        if legacy_row and legacy_row['outgoing_server']:  # If any legacy data exists
            # Check if already migrated (avoid duplicates)
            cursor.execute("SELECT COUNT(*) AS cnt FROM email_accounts WHERE name = 'Main Account'")
            if cursor.fetchone()['cnt'] == 0:
                cursor.execute("""
                    INSERT INTO email_accounts 
                    (name, outgoing_server, outgoing_port, outgoing_encryption, outgoing_username, outgoing_password, is_default)
                    VALUES ('Main Account', %s, %s, %s, %s, %s, 1)
                """, legacy_row)
                print("Migration: Legacy single email config moved to email_accounts as 'Main Account' (default).")

    print("Settings and email_accounts table synchronization complete.")