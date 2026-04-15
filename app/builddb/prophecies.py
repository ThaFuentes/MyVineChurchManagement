# app/builddb/prophecies.py
# Full path: WebChurchMan/app/builddb/prophecies.py
# File name: prophecies.py
# Brief, detailed purpose: Creates/updates the prophecies and prophecy_comments tables for MariaDB.
# Standardized timestamps + visibility levels (public/private/personal) + parent_id for simple one-level replies.
# Safe migration for existing databases.

import textwrap

def create_tables(cursor):
    """
    Creates/updates the prophecies-related tables with full visibility support
    and parent_id for one-level replies.
    Designed for both fresh DB creation and safe migration.
    """

    # ----- PROPHECIES TABLE -----
    cursor.execute(textwrap.dedent("""
        CREATE TABLE IF NOT EXISTS prophecies (
            id               INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            title            VARCHAR(255) NOT NULL,
            description      TEXT,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            visibility       VARCHAR(20) NOT NULL DEFAULT 'private'
                             CHECK(visibility IN ('public', 'private', 'personal')),
            user_id          INT UNSIGNED,
            contributor_name VARCHAR(255),
            ip_address       VARCHAR(45),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        ) ENGINE=InnoDB;
    """).strip())

    # Safe migration: drop any old visibility CHECK constraint
    cursor.execute("""
        SELECT CONSTRAINT_NAME 
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS 
        WHERE TABLE_SCHEMA = DATABASE() 
          AND TABLE_NAME = 'prophecies' 
          AND CONSTRAINT_TYPE = 'CHECK'
          AND CONSTRAINT_NAME LIKE '%visibility%'
    """)
    old_constraint = cursor.fetchone()
    if old_constraint:
        constraint_name = old_constraint[0]
        try:
            cursor.execute(f"ALTER TABLE prophecies DROP CONSTRAINT {constraint_name}")
            print(f"Migration: Dropped old visibility CHECK constraint '{constraint_name}'")
        except Exception as e:
            print(f"Warning: Could not drop old constraint '{constraint_name}': {e}")

    # Ensure visibility column supports 'personal'
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prophecies'
    """)
    existing_columns = [row[0] for row in cursor.fetchall()]

    if 'visibility' not in existing_columns:
        print("Migration: Adding missing 'visibility' column with full options")
        cursor.execute(textwrap.dedent("""
            ALTER TABLE prophecies ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'private'
            CHECK(visibility IN ('public', 'private', 'personal'))
        """).strip())
    else:
        print("Migration: Updating visibility column to include 'personal'")
        cursor.execute(textwrap.dedent("""
            ALTER TABLE prophecies 
            MODIFY visibility VARCHAR(20) NOT NULL DEFAULT 'private'
            CHECK(visibility IN ('public', 'private', 'personal'))
        """).strip())

    # Safe column additions
    columns_to_add = {
        'created_at':       "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        'updated_at':       "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        'description':      "TEXT",
        'contributor_name': "VARCHAR(255)",
        'ip_address':       "VARCHAR(45)",
        'user_id':          "INT UNSIGNED"
    }

    for col_name, col_def in columns_to_add.items():
        if col_name not in existing_columns:
            print(f"Migration: Adding missing column '{col_name}' to prophecies table.")
            cursor.execute(f"ALTER TABLE prophecies ADD COLUMN {col_name} {col_def}")

    # Indexes
    try:
        cursor.execute("CREATE INDEX idx_prophecies_visibility ON prophecies(visibility)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_prophecies_user ON prophecies(user_id)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_prophecies_created ON prophecies(created_at DESC)")
    except: pass

    # ----- PROPHECY_COMMENTS TABLE (UPDATED WITH parent_id) -----
    cursor.execute(textwrap.dedent("""
        CREATE TABLE IF NOT EXISTS prophecy_comments (
            id               INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            prophecy_id      INT UNSIGNED NOT NULL,
            comment          TEXT NOT NULL,
            date_added       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id          INT UNSIGNED,
            contributor_name VARCHAR(255),
            ip_address       VARCHAR(45),
            parent_id        INT UNSIGNED NULL,   -- NEW: for one-level replies
            FOREIGN KEY(prophecy_id) REFERENCES prophecies(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id)     REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(parent_id)   REFERENCES prophecy_comments(id) ON DELETE CASCADE
        ) ENGINE=InnoDB;
    """).strip())

    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prophecy_comments'
    """)
    existing_comment_columns = [row[0] for row in cursor.fetchall()]

    # Safe addition of parent_id if missing
    if 'parent_id' not in existing_comment_columns:
        print("Migration: Adding missing 'parent_id' column to prophecy_comments for one-level replies")
        cursor.execute("""
            ALTER TABLE prophecy_comments 
            ADD COLUMN parent_id INT UNSIGNED NULL AFTER ip_address,
            ADD FOREIGN KEY (parent_id) REFERENCES prophecy_comments(id) ON DELETE CASCADE
        """)

    columns_to_add_comments = {
        'contributor_name': "VARCHAR(255)",
        'ip_address':       "VARCHAR(45)",
        'user_id':          "INT UNSIGNED"
    }

    for col_name, col_def in columns_to_add_comments.items():
        if col_name not in existing_comment_columns:
            print(f"Migration: Adding missing column '{col_name}' to prophecy_comments table.")
            cursor.execute(f"ALTER TABLE prophecy_comments ADD COLUMN {col_name} {col_def}")

    # Indexes for comments
    try:
        cursor.execute("CREATE INDEX idx_prophecy_comments_prophecy ON prophecy_comments(prophecy_id)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_prophecy_comments_date ON prophecy_comments(date_added DESC)")
    except: pass
    try:
        cursor.execute("CREATE INDEX idx_prophecy_comments_parent ON prophecy_comments(parent_id)")
    except: pass

    print("Prophecies tables synchronization complete (MariaDB). Ready for public/private/personal visibility with one-level replies.")