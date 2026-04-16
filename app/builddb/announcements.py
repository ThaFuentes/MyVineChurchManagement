# MYVINECHURCH.ONLINE/app/builddb/announcements.py
# Full path: MYVINECHURCH.ONLINE/app/builddb/announcements.py
# File name: announcements.py
# Brief, detailed purpose: Creates/updates the announcements and announcement_comments tables for MariaDB.
# This is the 100% complete rebuild — every single column, table, index, migration step, and behavior is preserved exactly as you had it.
# The only updates are: much clearer comments, better code organization, and explicit documentation around the created_by column (this powers "Created by: [Name]" on the public announcements page, just like events).
# No new columns, no new tables, no behavior changes.

def create_tables(cursor):
    """
    Creates/updates the announcements and announcement_comments tables.
    Designed for both fresh DB creation and safe migration of existing databases.
    The created_by column is required for displaying WHO created each announcement on the public page.
    """

    # ------------------------------------------------------------------
    # ----- ANNOUNCEMENTS TABLE -----
    # ------------------------------------------------------------------
    # This table stores every church announcement.
    # created_by and updated_by are used to show "Created by: [Username]"
    # on the public announcements listing (exactly like events).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id                 INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            title              VARCHAR(255) NOT NULL,
            content            TEXT NOT NULL,
            contributor_name   VARCHAR(255),
            ip_address         VARCHAR(45),
            created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            effective_date     DATETIME,
            expiration_date    DATETIME,
            is_active          TINYINT(1) DEFAULT 1,
            comments_enabled   TINYINT(1) DEFAULT 1,
            visibility         VARCHAR(20) NOT NULL DEFAULT 'private'
                               CHECK(visibility IN ('public', 'private')),
            user_id            INT UNSIGNED,
            created_by         INT UNSIGNED,           -- ← This column shows WHO created the announcement
            updated_by         INT UNSIGNED,
            FOREIGN KEY(user_id)    REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
        ) ENGINE=InnoDB;
    """)

    # ------------------------------------------------------------------
    # Safe column additions / migration for announcements table
    # ------------------------------------------------------------------
    # We check what columns already exist so we never break your current database.
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

    # Note about created_by / updated_by:
    # These two columns were already created in the CREATE TABLE above.
    # They allow the public announcements page to display "Created by: [Name]".
    # If you see "Unknown" on old announcements, it is only because created_by was NULL.
    # (You can fix old announcements with a one-time UPDATE if needed — the code is already ready.)

    # Indexes for announcements (safe — will not fail if they already exist)
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

    # ------------------------------------------------------------------
    # ----- ANNOUNCEMENT_COMMENTS TABLE (with parent_id for replies) -----
    # ------------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcement_comments (
            id               INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            announcement_id  INT UNSIGNED NOT NULL,
            user_id          INT UNSIGNED,
            contributor_name VARCHAR(255),
            ip_address       VARCHAR(45),
            comment          TEXT NOT NULL,
            date_added       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            parent_id        INT UNSIGNED NULL,   -- for simple one-level replies
            FOREIGN KEY(announcement_id) REFERENCES announcements(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id)         REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(parent_id)       REFERENCES announcement_comments(id) ON DELETE CASCADE
        ) ENGINE=InnoDB;
    """)

    # Safe column additions for announcement_comments table
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'announcement_comments'
    """)
    existing_comments_columns = [row[0] for row in cursor.fetchall()]

    # Safe addition of parent_id if missing
    if 'parent_id' not in existing_comments_columns:
        print("Migration: Adding missing 'parent_id' column to announcement_comments for one-level replies")
        cursor.execute("""
            ALTER TABLE announcement_comments 
            ADD COLUMN parent_id INT UNSIGNED NULL AFTER ip_address,
            ADD FOREIGN KEY (parent_id) REFERENCES announcement_comments(id) ON DELETE CASCADE
        """)

    columns_to_add_comments = {
        'contributor_name': "VARCHAR(255)",
        'ip_address':       "VARCHAR(45)"
    }

    for col_name, col_def in columns_to_add_comments.items():
        if col_name not in existing_comments_columns:
            print(f"Migration: Adding missing column '{col_name}' to announcement_comments table.")
            cursor.execute(f"ALTER TABLE announcement_comments ADD COLUMN {col_name} {col_def}")

    # Indexes for announcement_comments
    try:
        cursor.execute("CREATE INDEX idx_comments_announcement ON announcement_comments(announcement_id)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_comments_date ON announcement_comments(date_added DESC)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_comments_parent ON announcement_comments(parent_id)")
    except: pass

    print("✓ announcements.py migration completed successfully (including announcement_comments table with parent_id for simple one-level replies)")