# WebChurchMan/app/builddb/sermons.py
# Full path: WebChurchMan/app/builddb/sermons.py
# File name: sermons.py
# Brief, detailed purpose: Creates/updates the sermons and sermon_comments tables for MariaDB.
# Now supports three visibility levels:
# - 'public'   : visible to everyone (including guests)
# - 'private'  : visible to all logged-in members
# - 'personal' : visible ONLY to the uploader (new option)
# Default remains 'private' for backward compatibility.
# Safe schema evolution: modifies existing CHECK constraint to include 'personal'.
# Isolated module – called from builddb.py during DB initialization.

def create_tables(cursor):
    """
    Creates/updates the sermons-related tables with new 'personal' visibility.
    Designed for both fresh DB creation and safe migration of existing databases.
    """

    # ----- SERMONS TABLE -----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sermons (
            id            INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            title         VARCHAR(255) NOT NULL,
            notes         TEXT,
            details       TEXT,
            sermon_file   TEXT,
            external_link TEXT,
            uploaded_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            visibility    VARCHAR(20) NOT NULL DEFAULT 'private'
                          CHECK(visibility IN ('public', 'private', 'personal')),
            uploaded_by   INT UNSIGNED NOT NULL,
            FOREIGN KEY(uploaded_by) REFERENCES users(id) ON DELETE RESTRICT
        ) ENGINE=InnoDB;
    """)

    # Safe migration: add/modify visibility column and CHECK constraint
    cursor.execute("""
        SELECT COLUMN_NAME, CONSTRAINT_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS c
        LEFT JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc 
          ON tc.TABLE_SCHEMA = DATABASE() 
          AND tc.TABLE_NAME = 'sermons' 
          AND tc.CONSTRAINT_TYPE = 'CHECK'
        WHERE c.TABLE_SCHEMA = DATABASE() AND c.TABLE_NAME = 'sermons' AND c.COLUMN_NAME = 'visibility'
    """)
    visibility_info = cursor.fetchone()

    # If visibility column exists but old CHECK, drop old constraint and add new one
    if visibility_info:
        old_constraint = visibility_info[1]
        if old_constraint:
            try:
                cursor.execute(f"ALTER TABLE sermons DROP CONSTRAINT {old_constraint}")
                print(f"Migration: Dropped old visibility CHECK constraint '{old_constraint}'")
            except:
                pass  # Constraint may not exist or name varies

    # Ensure column definition is correct (add if missing, modify if needed)
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'sermons'
    """)
    existing_columns = [row[0] for row in cursor.fetchall()]

    if 'visibility' not in existing_columns:
        print("Migration: Adding missing 'visibility' column with new values")
        cursor.execute("""
            ALTER TABLE sermons ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'private'
            CHECK(visibility IN ('public', 'private', 'personal'))
        """)
    else:
        print("Migration: Updating visibility CHECK to include 'personal'")
        cursor.execute("""
            ALTER TABLE sermons 
            MODIFY visibility VARCHAR(20) NOT NULL DEFAULT 'private'
            CHECK(visibility IN ('public', 'private', 'personal'))
        """)

    # Other safe column additions (unchanged)
    columns_to_add = {
        'notes':         "TEXT",
        'details':       "TEXT",
        'sermon_file':   "TEXT",
        'external_link': "TEXT",
        'uploaded_at':   "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        'uploaded_by':   "INT UNSIGNED NOT NULL"
    }

    for col_name, col_def in columns_to_add.items():
        if col_name not in existing_columns:
            print(f"Migration: Adding missing column '{col_name}' to sermons table.")
            cursor.execute(f"ALTER TABLE sermons ADD COLUMN {col_name} {col_def}")

    # Indexes (unchanged)
    try:
        cursor.execute("CREATE INDEX idx_sermons_visibility ON sermons(visibility)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_sermons_uploaded_by ON sermons(uploaded_by)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_sermons_uploaded_at ON sermons(uploaded_at DESC)")
    except: pass

    # ----- SERMON_COMMENTS TABLE (unchanged) -----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sermon_comments (
            id               INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            sermon_id        INT UNSIGNED NOT NULL,
            comment          TEXT NOT NULL,
            date_added       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id          INT UNSIGNED,
            contributor_name VARCHAR(255),
            ip_address       VARCHAR(45),
            FOREIGN KEY(sermon_id) REFERENCES sermons(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id)   REFERENCES users(id) ON DELETE SET NULL
        ) ENGINE=InnoDB;
    """)

    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'sermon_comments'
    """)
    existing_comment_columns = [row[0] for row in cursor.fetchall()]

    columns_to_add_comments = {
        'contributor_name': "VARCHAR(255)",
        'ip_address':       "VARCHAR(45)",
        'user_id':          "INT UNSIGNED"
    }

    for col_name, col_def in columns_to_add_comments.items():
        if col_name not in existing_comment_columns:
            print(f"Migration: Adding missing column '{col_name}' to sermon_comments table.")
            cursor.execute(f"ALTER TABLE sermon_comments ADD COLUMN {col_name} {col_def}")

    try:
        cursor.execute("CREATE INDEX idx_sermon_comments_sermon ON sermon_comments(sermon_id)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_sermon_comments_date ON sermon_comments(date_added DESC)")
    except: pass