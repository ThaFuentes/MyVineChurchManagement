# Message library tables. Playback uses Google Drive.
# An authorized copy can be stored outside the web folder.
# Site columns (title, speaker, date, who can listen) are edited here only.

SEED_FOLDER_ID = '1Q4lfrixsNDrWpvnT3SmXiDb2IjZedAU1'
SEED_LABEL = 'Church messages'

CREATE_SOURCES = """
    CREATE TABLE IF NOT EXISTS sermon_drive_sources (
        id         INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
        folder_id  VARCHAR(128) NOT NULL,
        label      VARCHAR(120) NOT NULL DEFAULT 'Church messages',
        enabled       TINYINT(1) NOT NULL DEFAULT 1,
        refresh_hours INT NOT NULL DEFAULT 168,
        default_visibility VARCHAR(20) NOT NULL DEFAULT 'public',
        synced_at     DATETIME NULL,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_sermon_drive_folder (folder_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

CREATE_ITEMS = """
    CREATE TABLE IF NOT EXISTS sermon_drive_items (
        id               INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
        source_id        INT UNSIGNED NOT NULL,
        drive_file_id    VARCHAR(128) NOT NULL,
        parent_folder_id VARCHAR(128) NULL,
        drive_name       VARCHAR(500) NOT NULL,
        mime_type        VARCHAR(120) NULL,
        kind             VARCHAR(20) NOT NULL DEFAULT 'audio',
        drive_modified   VARCHAR(40) NULL,
        title            VARCHAR(255) NOT NULL,
        speaker          VARCHAR(160) NULL,
        scripture        VARCHAR(255) NULL,
        summary          TEXT NULL,
        series           VARCHAR(160) NULL,
        preached_on      DATE NULL,
        visibility       VARCHAR(20) NOT NULL DEFAULT 'public',
        hidden           TINYINT(1) NOT NULL DEFAULT 0,
        site_edited      TINYINT(1) NOT NULL DEFAULT 0,
        missing_on_drive TINYINT(1) NOT NULL DEFAULT 0,
        local_name       VARCHAR(40) NULL,
        local_bytes      BIGINT UNSIGNED NULL,
        local_saved_at   DATETIME NULL,
        local_saved_by   INT UNSIGNED NULL,
        speaker_id       INT UNSIGNED NULL,
        synced_at        DATETIME NULL,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        updated_by       INT UNSIGNED NULL,
        UNIQUE KEY uq_sermon_drive_file (drive_file_id),
        KEY idx_sermon_drive_source (source_id),
        KEY idx_sermon_drive_preached (preached_on),
        KEY idx_sermon_drive_speaker (speaker_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

CREATE_SPEAKERS = """
    CREATE TABLE IF NOT EXISTS sermon_speakers (
        id           INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
        display_name VARCHAR(160) NOT NULL,
        user_id      INT UNSIGNED NULL,
        listen_rule  VARCHAR(20) NULL,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_sermon_speaker_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

CREATE_SPEAKER_NAMES = """
    CREATE TABLE IF NOT EXISTS sermon_speaker_names (
        id         INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
        speaker_id INT UNSIGNED NOT NULL,
        name       VARCHAR(160) NOT NULL,
        name_key   VARCHAR(160) NOT NULL,
        UNIQUE KEY uq_sermon_speaker_name (name_key),
        KEY idx_sermon_speaker_names_speaker (speaker_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

SEED_SOURCE = """
    INSERT INTO sermon_drive_sources (folder_id, label, enabled)
    VALUES (%s, %s, 1)
"""

CREATE_COMMENTS = """
    CREATE TABLE IF NOT EXISTS sermon_drive_comments (
        id               INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
        item_id          INT UNSIGNED NOT NULL,
        comment          TEXT NOT NULL,
        date_added       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        user_id          INT UNSIGNED NULL,
        contributor_name VARCHAR(80) NOT NULL,
        ip_address       VARCHAR(45) NULL,
        parent_id        INT UNSIGNED NULL,
        shadowed         TINYINT(1) NOT NULL DEFAULT 0,
        shadow_ip        VARCHAR(45) NULL,
        shadow_user_id   INT UNSIGNED NULL,
        moderated        TINYINT(1) NOT NULL DEFAULT 1,
        moderated_by     INT UNSIGNED NULL,
        moderated_at     TIMESTAMP NULL,
        edited_by_moderator TINYINT(1) NOT NULL DEFAULT 0,
        moderator_edited_at TIMESTAMP NULL,
        removed          TINYINT(1) NOT NULL DEFAULT 0,
        KEY idx_sermon_drive_comments_item (item_id),
        KEY idx_sermon_drive_comments_parent (parent_id),
        KEY idx_sermon_drive_comments_date (date_added)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

CREATE_LISTENS = """
    CREATE TABLE IF NOT EXISTS sermon_drive_listens (
        id           INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
        item_id      INT UNSIGNED NOT NULL,
        listener_key VARCHAR(40) NOT NULL,
        started_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_sermon_listen (item_id, listener_key),
        KEY idx_sermon_listen_item (item_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def _has_column(cursor, table, column):
    cursor.execute(
        """
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (table, column),
    )
    return cursor.fetchone() is not None


def create_tables(cursor):
    """Create the library tables and seed the church folder once."""
    cursor.execute(CREATE_SOURCES)
    cursor.execute(CREATE_ITEMS)
    cursor.execute(CREATE_COMMENTS)
    cursor.execute(CREATE_LISTENS)
    cursor.execute(CREATE_SPEAKERS)
    cursor.execute(CREATE_SPEAKER_NAMES)
    if not _has_column(cursor, 'sermon_drive_sources', 'refresh_hours'):
        cursor.execute(
            "ALTER TABLE sermon_drive_sources "
            "ADD COLUMN refresh_hours INT NOT NULL DEFAULT 168"
        )
    if not _has_column(cursor, 'sermon_drive_sources', 'default_visibility'):
        cursor.execute(
            "ALTER TABLE sermon_drive_sources "
            "ADD COLUMN default_visibility VARCHAR(20) NOT NULL DEFAULT 'public'"
        )
    for name, ddl in (
        ('local_name', 'VARCHAR(40) NULL'),
        ('local_bytes', 'BIGINT UNSIGNED NULL'),
        ('local_saved_at', 'DATETIME NULL'),
        ('local_saved_by', 'INT UNSIGNED NULL'),
    ):
        if not _has_column(cursor, 'sermon_drive_items', name):
            cursor.execute(f'ALTER TABLE sermon_drive_items ADD COLUMN {name} {ddl}')
    if not _has_column(cursor, 'sermon_drive_items', 'speaker_id'):
        cursor.execute(
            "ALTER TABLE sermon_drive_items ADD COLUMN speaker_id INT UNSIGNED NULL"
        )
    if not _has_column(cursor, 'sermon_speakers', 'listen_rule'):
        cursor.execute(
            "ALTER TABLE sermon_speakers ADD COLUMN listen_rule VARCHAR(20) NULL"
        )
    cursor.execute("SELECT id FROM sermon_drive_sources LIMIT 1")
    if cursor.fetchone() is None:
        cursor.execute(SEED_SOURCE, (SEED_FOLDER_ID, SEED_LABEL))
