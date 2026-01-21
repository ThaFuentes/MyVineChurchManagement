# myvinechurchonline/app/builddb/events.py
# Full path: myvinechurchonline/app/builddb/events.py
# File name: events.py
# Brief, detailed purpose: Creates/updates the events and potluck_signups tables.
# Supports public/private visibility, potluck flag, optional event_time, full audit trail (created_by/updated_by + timestamps),
# and ALL extensive optional fields for rich event details (as listed in project spec).
# Guest potluck signups: potluck_signups table (name, item, quantity, note, ip – no user_id required).
# All truly optional fields allow NULL; required fields remain NOT NULL.
# Safe schema evolution: adds missing columns via INFORMATION_SCHEMA.COLUMNS (MariaDB-safe).
# Isolated module – called from builddb.py during DB initialization.
# FULL REBUILD: Includes every field from your provided code + guest potluck_signups table.

def create_tables(cursor):
    """
    Creates/updates the events and potluck_signups tables.
    Designed for both fresh DB creation and safe migration of existing databases.
    events table created first to satisfy FK in potluck_signups.
    """

    # ----- EVENTS TABLE -----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id                        INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            event_name                VARCHAR(255) NOT NULL,
            event_date                VARCHAR(10) NOT NULL,              -- YYYY-MM-DD
            event_time                VARCHAR(8),                        -- HH:MM or HH:MM AM/PM (optional)
            visibility                VARCHAR(20) NOT NULL DEFAULT 'private'
                                      CHECK(visibility IN ('public', 'private')),
            potluck_enabled           TINYINT(1) NOT NULL DEFAULT 0,
            location                  TEXT,
            description               TEXT,
            speaker_host              TEXT,
            special_guests            TEXT,
            theme                     TEXT,
            agenda                    TEXT,
            registration_info         TEXT,
            cost_fees                 DECIMAL(10, 2),
            contact_info              TEXT,
            childcare_availability    TEXT,
            accessibility             TEXT,
            promotional_materials     TEXT,
            volunteer_opportunities   TEXT,
            parking_info              TEXT,
            dress_code                TEXT,
            food_beverages            TEXT,
            event_sponsor             TEXT,
            social_media_hashtag      VARCHAR(100),
            donation_info             TEXT,
            safety_protocols          TEXT,
            follow_up                 TEXT,
            event_coordinator         TEXT,
            announcements_reminders   TEXT,
            feedback_form             TEXT,
            live_streaming_details    TEXT,
            event_objectives          TEXT,
            created_by                INT UNSIGNED,
            updated_by                INT UNSIGNED,
            created_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
        ) ENGINE=InnoDB
    """)

    # Safe column additions for events
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'events'
    """)
    existing_events = [row[0] for row in cursor.fetchall()]

    columns_to_add_events = {
        'potluck_enabled':           "TINYINT(1) NOT NULL DEFAULT 0",
        'event_time':                "VARCHAR(8)",
        'location':                  "TEXT",
        'description':               "TEXT",
        'speaker_host':              "TEXT",
        'special_guests':            "TEXT",
        'theme':                     "TEXT",
        'agenda':                    "TEXT",
        'registration_info':         "TEXT",
        'cost_fees':                 "DECIMAL(10, 2)",
        'contact_info':              "TEXT",
        'childcare_availability':    "TEXT",
        'accessibility':             "TEXT",
        'promotional_materials':     "TEXT",
        'volunteer_opportunities':   "TEXT",
        'parking_info':              "TEXT",
        'dress_code':                "TEXT",
        'food_beverages':            "TEXT",
        'event_sponsor':             "TEXT",
        'social_media_hashtag':      "VARCHAR(100)",
        'donation_info':             "TEXT",
        'safety_protocols':          "TEXT",
        'follow_up':                 "TEXT",
        'event_coordinator':         "TEXT",
        'announcements_reminders':   "TEXT",
        'feedback_form':             "TEXT",
        'live_streaming_details':    "TEXT",
        'event_objectives':          "TEXT",
        'created_at':                "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        'updated_at':                "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
    }

    for col, defn in columns_to_add_events.items():
        if col not in existing_events:
            print(f"Migration: Adding missing column '{col}' to events table.")
            cursor.execute(f"ALTER TABLE events ADD COLUMN {col} {defn}")

    # Indexes for events
    try:
        cursor.execute("CREATE INDEX idx_events_date ON events(event_date)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_events_visibility ON events(visibility)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_events_potluck ON events(potluck_enabled)")
    except: pass

    # ----- POTLUCK_SIGNUPS TABLE (guest contributions – replaces potluck_contributions for public) -----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS potluck_signups (
            id         INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            event_id   INT UNSIGNED NOT NULL,
            name       TEXT NOT NULL,
            item       TEXT NOT NULL,
            quantity   TEXT,
            note       TEXT,
            ip         TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)

    # Safe column additions for potluck_signups
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'potluck_signups'
    """)
    existing_signups = [row[0] for row in cursor.fetchall()]

    columns_to_add_signups = {
        'name':       "TEXT NOT NULL",
        'item':       "TEXT NOT NULL",
        'quantity':   "TEXT",
        'note':       "TEXT",
        'ip':         "TEXT",
        'created_at': "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    }

    for col, defn in columns_to_add_signups.items():
        if col not in existing_signups:
            print(f"Migration: Adding missing column '{col}' to potluck_signups table.")
            cursor.execute(f"ALTER TABLE potluck_signups ADD COLUMN {col} {defn}")

    # Indexes for potluck_signups
    try:
        cursor.execute("CREATE INDEX idx_potluck_event ON potluck_signups(event_id)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_potluck_created ON potluck_signups(created_at DESC)")
    except: pass

    # Optional: Drop old potluck_contributions if exists (clean up)
    try:
        cursor.execute("DROP TABLE IF EXISTS potluck_contributions")
    except: pass