# myvinechurchonline/app/builddb/groups.py
# Full path: myvinechurchonline/app/builddb/groups.py
# File name: groups.py
# Brief, detailed purpose: Creates/updates the groups table and seeds essential system groups for MariaDB.
# Supports group name (unique), description, visibility (public/private), permissions (JSON stored as TEXT),
# full audit trail (created_by/updated_by + timestamps).
# Safe schema evolution: adds missing columns via INFORMATION_SCHEMA.COLUMNS.
# Isolated module – called from builddb.py during DB initialization.
# FULL REBUILD: Added seeding for Ticket Managers, Pastoral Group, and Worship Team Group (idempotent with INSERT IGNORE).

def create_tables(cursor):
    """
    Creates/updates the groups table and seeds essential system groups.
    Designed for both fresh DB creation and safe migration of existing databases.
    """

    # ----- GROUPS TABLE -----
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(255) NOT NULL UNIQUE,
            description TEXT,
            visibility VARCHAR(20) NOT NULL DEFAULT 'private'
                        CHECK(visibility IN ('public', 'private')),
            permissions TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            created_by INT UNSIGNED,
            updated_by INT UNSIGNED,
            FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL,
            FOREIGN KEY (updated_by) REFERENCES users (id) ON DELETE SET NULL
        ) ENGINE=InnoDB;
    """)

    # Safe column additions for schema evolution
    cursor.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'groups'
    """)
    existing_cols = [row[0] for row in cursor.fetchall()]

    columns_to_add = {
        'description': "TEXT",
        'visibility': "VARCHAR(20) NOT NULL DEFAULT 'private' CHECK(visibility IN ('public', 'private'))",
        'permissions': "TEXT NOT NULL DEFAULT '[]'",
        'created_at': "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        'updated_at': "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        'created_by': "INT UNSIGNED",
        'updated_by': "INT UNSIGNED"
    }

    for col_name, col_def in columns_to_add.items():
        if col_name not in existing_cols:
            print(f"Migration: Adding missing column '{col_name}' to groups table.")
            cursor.execute(f"ALTER TABLE groups ADD COLUMN {col_name} {col_def}")

    # Indexes for common queries
    try:
        cursor.execute("CREATE INDEX idx_groups_visibility ON groups(visibility)")
    except:
        pass
    try:
        cursor.execute("CREATE INDEX idx_groups_created ON groups(created_at DESC)")
    except:
        pass

    # ----- SEED ESSENTIAL SYSTEM GROUPS -----
    # Using INSERT IGNORE – safe to run repeatedly (name is UNIQUE).
    essential_groups = [
        (
            "Ticket Managers",
            "Dedicated group for users who can fully manage the support ticket/helpdesk system.",
            "private",
            '["manage_tickets", "view_all_tickets"]'  # Specific permission for ticket management
        ),
        (
            "Pastoral Group",
            "Highly sensitive group for pastoral care, counseling notes, and leadership oversight.",
            "private",
            '["view_pastoral_notes", "manage_membership", "access_sensitive_data"]'
        ),
        (
            "Worship Team Group",
            "Planning for services, song lists, and team rehearsals.",
            "private",
            '["view_setlists", "upload_chord_charts", "manage_rehearsals"]'
        )
    ]

    for name, desc, visibility, perms in essential_groups:
        cursor.execute("""
            INSERT IGNORE INTO groups (name, description, visibility, permissions)
            VALUES (%s, %s, %s, %s)
        """, (name, desc, visibility, perms))

    print("Groups seeded (if not already present): Ticket Managers, Pastoral Group, Worship Team Group.")