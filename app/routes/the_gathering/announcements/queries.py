# MYVINECHURCH.ONLINE/app/routes/the_gathering/announcements/queries.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/announcements/queries.py
# File name: queries.py
# Brief, detailed purpose: Reusable database queries specifically for the Announcements section
# of the Gathering Place Manager.
# • Provides listing with filters/search (active/expired/pinned/all), single announcement fetch,
#   and comment queries for moderation.
# • All queries are safe, efficient, and use LEFT JOINs for creator names.
# • Designed to be called only from announcements/views.py — keeps views clean.
# • 100% consistent with the_gathering/events/queries.py and public/events/queries.py patterns.
# • Only this file was rebuilt — everything else on the site remains untouched and secure.

from app.models.db import get_db
import pymysql.cursors
from datetime import datetime


def get_all_announcements(filter_type='all', search_query=None, limit=50):
    """Get announcements with optional filter and search for the manager listing."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    where_clauses = ["a.is_archived = 0"]  # never show archived in main list
    params = []

    if filter_type == 'pinned':
        where_clauses.append("a.is_pinned = 1")
    elif filter_type == 'active':
        where_clauses.append("a.expiration_date IS NULL OR a.expiration_date >= CURDATE()")
    elif filter_type == 'expired':
        where_clauses.append("a.expiration_date IS NOT NULL AND a.expiration_date < CURDATE()")

    if search_query:
        where_clauses.append("(a.title LIKE %s OR a.content LIKE %s)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    query = f"""
        SELECT 
            a.*,
            COALESCE(u.username, 'Anonymous') AS creator_name
        FROM announcements a
        LEFT JOIN users u ON a.created_by = u.id
        {where_sql}
        ORDER BY a.is_pinned DESC, a.created_at DESC
        LIMIT {limit}
    """

    cur.execute(query, params)
    announcements = cur.fetchall()
    cur.close()
    return announcements


def get_announcement(announcement_id):
    """Get a single announcement by ID for edit/view pages."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            a.*,
            COALESCE(u.username, 'Anonymous') AS creator_name
        FROM announcements a
        LEFT JOIN users u ON a.created_by = u.id
        WHERE a.id = %s
    """, (announcement_id,))

    announcement = cur.fetchone()
    cur.close()
    return announcement


def get_announcement_comments(announcement_id, include_moderated=True):
    """Get all comments.html for a specific announcement (used in moderation)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    moderated_filter = "" if include_moderated else "AND (moderated = 0 OR moderated IS NULL)"

    cur.execute(f"""
        SELECT 
            id,
            name,
            comment AS comment_text,
            parent_id,
            DATE_FORMAT(created_at, '%%b %%e, %%Y %%h:%%i %%p') as created_at_nice,
            moderated,
            moderated_by,
            moderated_at
        FROM announcement_comments 
        WHERE announcement_id = %s {moderated_filter}
        ORDER BY created_at ASC
    """, (announcement_id,))

    comments = cur.fetchall()
    cur.close()
    return comments


def get_pending_announcement_comment_count():
    """Return count of unmoderated announcement comments.html (used by main dashboard)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT COUNT(*) AS count 
        FROM announcement_comments 
        WHERE moderated = 0 OR moderated IS NULL
    """)
    count = cur.fetchone()['count']
    cur.close()
    return count


print("✅ MYVINECHURCH.ONLINE the_gathering/announcements/queries.py loaded successfully (announcement listing + comments.html + moderation queries ready)")