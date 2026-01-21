# myvinechurchonline/app/builddb/prayers.py
# Full path: myvinechurchonline/app/builddb/prayers.py
# File name: prayers.py
# Brief, detailed purpose: Creates the prayers and prayers_added tables for MariaDB.
# Supports public/private visibility (defaults to 'public' per project guidelines), guest submissions (contributor_name/ip_address),
# and prayer responses ("added prayers") with similar guest tracking.
# Safe schema evolution: adds missing columns via INFORMATION_SCHEMA.COLUMNS.
# Isolated module – called from builddb.py during DB initialization.
# All ID/FK columns use UNSIGNED INT to match users.id type and fix errno 150.

def create_tables(cursor):
    """
    Creates/updates the prayers-related tables.
    Designed for both fresh DB creation and safe migration of existing databases.
    """

    # ----- PRAYERS TABLE -----
    # user_id must be INT UNSIGNED to match users.id.
    # visibility/ip/name changed to VARCHAR to support indexing and constraints.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prayers (
            id               INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            title            VARCHAR(255) NOT NULL,
            description      TEXT NOT NULL,
            date_posted      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            visibility       VARCHAR(20) NOT NULL DEFAULT 'public'
                             CHECK(visibility IN ('public', 'private')),
            user_id          INT UNSIGNED,
            contributor_name VARCHAR(255),               -- For non-registered users
            ip_address       VARCHAR(45),                -- For IP tracking/banning (IPv6 safe)
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        ) ENGINE=InnoDB;
    """)

    # Safe column additions for schema evolution
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prayers'
    """)
    existing_columns = [row[0] for row in cursor.fetchall()]

    columns_to_add = {
        'visibility':       "VARCHAR(20) NOT NULL DEFAULT 'public' CHECK(visibility IN ('public', 'private'))",
        'contributor_name': "VARCHAR(255)",
        'ip_address':       "VARCHAR(45)",
        'user_id':          "INT UNSIGNED"
    }

    for col_name, col_def in columns_to_add.items():
        if col_name not in existing_columns:
            print(f"Migration: Adding missing column '{col_name}' to prayers table.")
            cursor.execute(f"ALTER TABLE prayers ADD COLUMN {col_name} {col_def}")

    # Indexes for common queries (try/except for migration safety)
    try:
        cursor.execute("CREATE INDEX idx_prayers_visibility ON prayers(visibility)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_prayers_user ON prayers(user_id)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_prayers_date ON prayers(date_posted DESC)")
    except: pass

    # ----- PRAYERS_ADDED TABLE (responses/prayers added to a request) -----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prayers_added (
            id                 INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            prayer_request_id  INT UNSIGNED NOT NULL,
            prayer             TEXT NOT NULL,
            date_added         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id            INT UNSIGNED,
            contributor_name   VARCHAR(255),               -- For non-registered users
            ip_address         VARCHAR(45),                -- For IP tracking
            FOREIGN KEY(prayer_request_id) REFERENCES prayers(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id)           REFERENCES users(id) ON DELETE SET NULL
        ) ENGINE=InnoDB;
    """)

    # Safe column additions for responses table
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prayers_added'
    """)
    existing_added_columns = [row[0] for row in cursor.fetchall()]

    columns_to_add_responses = {
        'contributor_name': "VARCHAR(255)",
        'ip_address':       "VARCHAR(45)",
        'user_id':          "INT UNSIGNED"
    }

    for col_name, col_def in columns_to_add_responses.items():
        if col_name not in existing_added_columns:
            print(f"Migration: Adding missing column '{col_name}' to prayers_added table.")
            cursor.execute(f"ALTER TABLE prayers_added ADD COLUMN {col_name} {col_def}")

    # Indexes for fast lookup
    try:
        cursor.execute("CREATE INDEX idx_prayers_added_request ON prayers_added(prayer_request_id)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_prayers_added_date ON prayers_added(date_added DESC)")
    except: pass