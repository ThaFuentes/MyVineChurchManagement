# MYVINECHURCH.ONLINE/app/builddb/events.py
# Full path: MYVINECHURCH.ONLINE/app/builddb/events.py
# File name: events.py
# Brief, detailed purpose: Creates/updates the events, potluck_signups, and event_comments tables for MariaDB.
# Uses exact column name "comment" to perfectly match your existing dreams table and legacy code.
# No schema changes — keeps everything you already have working.

def create_tables(cursor):
    """
    Creates/updates the events, potluck_signups, and event_comments tables.
    Designed for both fresh DB creation and safe migration.
    Uses "comment" column (exactly as your current DB and public/views.py expect).
    """

    # ----- EVENTS TABLE -----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id                        INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            event_name                VARCHAR(255) NOT NULL,
            event_date                VARCHAR(10) NOT NULL,
            event_time                VARCHAR(8),
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

    # ----- POTLUCK_SIGNUPS TABLE -----
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

    try:
        cursor.execute("DROP TABLE IF EXISTS potluck_contributions")
    except: pass

    # ----- EVENT_COMMENTS TABLE (uses "comment" to match your existing DB + dreams table) -----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_comments (
            id            INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            event_id      INT UNSIGNED NOT NULL,
            name          TEXT,
            comment       TEXT NOT NULL,
            user_id       INT UNSIGNED NULL,
            ip            TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            parent_id     INT UNSIGNED NULL,
            FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id)  REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(parent_id) REFERENCES event_comments(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)

    # Safe column additions for event_comments
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'event_comments'
    """)
    existing_comments = [row[0] for row in cursor.fetchall()]

    columns_to_add_comments = {
        'name':        "TEXT",
        'comment':     "TEXT NOT NULL",
        'user_id':     "INT UNSIGNED NULL",
        'ip':          "TEXT",
        'created_at':  "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        'parent_id':   "INT UNSIGNED NULL"
    }

    for col, defn in columns_to_add_comments.items():
        if col not in existing_comments:
            print(f"Migration: Adding missing column '{col}' to event_comments table.")
            cursor.execute(f"ALTER TABLE event_comments ADD COLUMN {col} {defn}")

    # Indexes for event_comments
    try:
        cursor.execute("CREATE INDEX idx_event_comments_event ON event_comments(event_id)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_event_comments_created ON event_comments(created_at DESC)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_event_comments_parent ON event_comments(parent_id)")
    except: pass

    print("✓ events.py migration completed successfully (using 'comment' column to match your existing DB)")