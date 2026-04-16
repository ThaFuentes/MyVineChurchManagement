# MYVINECHURCH.ONLINE/app/routes/public/announcements/queries.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/announcements/queries.py
# File name: queries.py
# Brief, detailed purpose: Reusable database query functions for public Announcements.
# FIXED: Uses LEFT JOIN on created_by (the actual column in your table) instead of creator_name.

from app.models.db import get_db
import pymysql.cursors


def get_public_announcements():
    """Retrieve publicly visible and active announcements."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            a.id,
            a.title,
            a.content,
            a.created_at,
            a.is_active,
            COALESCE(u.username, 'Anonymous') AS posted_by
        FROM announcements a
        LEFT JOIN users u ON a.created_by = u.id
        WHERE a.visibility = 'public'
          AND a.is_active = 1
        ORDER BY a.created_at DESC
    """)
    announcements = cur.fetchall()
    cur.close()
    return announcements


def get_public_announcement(ann_id):
    """Retrieve a single public + active announcement by ID."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            a.*,
            COALESCE(u.username, 'Anonymous') AS posted_by
        FROM announcements a
        LEFT JOIN users u ON a.created_by = u.id
        WHERE a.id = %s 
          AND a.visibility = 'public'
          AND a.is_active = 1
    """, (ann_id,))

    announcement = cur.fetchone()
    cur.close()
    return announcement


print("✅ MYVINECHURCH.ONLINE public/announcements/queries.py loaded successfully (fixed creator_name → created_by join)")