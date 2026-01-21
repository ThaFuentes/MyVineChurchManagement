# myvinechurchonline/app/builddb/announcements.py
# Full path: myvinechurchonline/app/builddb/announcements.py
# File name: announcements.py
# Brief, detailed purpose: Creates the announcements and announcement_comments tables for MariaDB.
# Supports public/private visibility, guest contributions (contributor_name/ip_address for tracking and potential banning),
# full audit fields (created_by/updated_by + timestamps), effective/expiration dates, and comment enabling.
# Safe schema evolution: adds missing columns via INFORMATION_SCHEMA.COLUMNS without data loss.
# Isolated module – called from builddb.py during DB initialization.
# All user-related FKs use signed INT to match users.id type and fix errno 150 FK mismatch.

def create_tables(cursor):
    """
    Creates/updates the announcements-related tables.
    Designed for both fresh DB creation and safe migration of existing databases.
    """

    # ----- ANNOUNCEMENTS TABLE -----
    # Using VARCHAR for indexable fields and INT UNSIGNED for Foreign Key compatibility.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id                 INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            title              VARCHAR(255) NOT NULL,
            content            TEXT NOT NULL,
            contributor_name   VARCHAR(255),               -- For non-registered users
            ip_address         VARCHAR(45),                -- For IP tracking/banning (IPv6 safe)
            created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            effective_date     DATETIME,
            expiration_date    DATETIME,
            is_active          TINYINT(1) DEFAULT 1,
            comments_enabled   TINYINT(1) DEFAULT 1,
            visibility         VARCHAR(20) NOT NULL DEFAULT 'private'
                               CHECK(visibility IN ('public', 'private')),
            user_id            INT UNSIGNED,
            created_by         INT UNSIGNED,
            updated_by         INT UNSIGNED,
            FOREIGN KEY(user_id)    REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
        ) ENGINE=InnoDB;
    """)

    # Safe column additions for schema evolution
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'announcements'
    """)
    existing_columns = [row[0] for row in cursor.fetchall()]

    columns_to_add = {
        'visibility':       "VARCHAR(20) NOT NULL DEFAULT 'private' CHECK(visibility IN ('public', 'private'))",
        'is_active':        "TINYINT(1) DEFAULT 1",
        'comments_enabled': "TINYINT(1) DEFAULT 1",
        'created_by':       "INT UNSIGNED",
        'updated_by':       "INT UNSIGNED",
        'contributor_name': "VARCHAR(255)",
        'ip_address':       "VARCHAR(45)",
        'effective_date':   "DATETIME",
        'expiration_date':  "DATETIME",
        'updated_at':       "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
    }

    for col_name, col_def in columns_to_add.items():
        if col_name not in existing_columns:
            print(f"Migration: Adding missing column '{col_name}' to announcements table.")
            cursor.execute(f"ALTER TABLE announcements ADD COLUMN {col_name} {col_def}")

    # Indexes for common queries (Succeeds because visibility is now VARCHAR)
    try:
        cursor.execute("CREATE INDEX idx_announcements_visibility ON announcements(visibility)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_announcements_active ON announcements(is_active)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_announcements_dates ON announcements(effective_date, expiration_date)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_announcements_created ON announcements(created_at DESC)")
    except: pass

    # ----- ANNOUNCEMENT_COMMENTS TABLE -----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcement_comments (
            id               INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            announcement_id  INT UNSIGNED NOT NULL,
            user_id          INT UNSIGNED,
            contributor_name VARCHAR(255),               -- For non-registered users
            ip_address       VARCHAR(45),                -- For IP tracking
            comment          TEXT NOT NULL,
            date_added       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(announcement_id) REFERENCES announcements(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id)         REFERENCES users(id) ON DELETE SET NULL
        ) ENGINE=InnoDB;
    """)

    # Safe column additions for comments table
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'announcement_comments'
    """)
    existing_comments_columns = [row[0] for row in cursor.fetchall()]

    columns_to_add_comments = {
        'contributor_name': "VARCHAR(255)",
        'ip_address':       "VARCHAR(45)"
    }

    for col_name, col_def in columns_to_add_comments.items():
        if col_name not in existing_comments_columns:
            print(f"Migration: Adding missing column '{col_name}' to announcement_comments table.")
            cursor.execute(f"ALTER TABLE announcement_comments ADD COLUMN {col_name} {col_def}")

    # Indexes for fast lookup
    try:
        cursor.execute("CREATE INDEX idx_comments_announcement ON announcement_comments(announcement_id)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_comments_date ON announcement_comments(date_added DESC)")
    except: pass