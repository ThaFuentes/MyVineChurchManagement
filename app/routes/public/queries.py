# app/routes/public/queries.py
# Full path: MyVineChurch/app/routes/public/queries.py
# File name: queries.py
# Brief, detailed purpose: All database queries and operations for the Public module.
# • Pure data-access layer – no Flask routes, no templates, no flash messages.
# • Every SELECT from the original public.py (_get_public_previews and _get_public_list) is now here.
# • 100% original behavior preserved (public previews for dashboard, full public listings for events/sermons/announcements/prayers/dreams/prophecies).
# • 100% MariaDB/pymysql compatible (%s placeholders, DictCursor).

import pymysql
from app.models.db import get_db


# ----------------------------------------------------------------------
# Public Previews for Dashboard
# ----------------------------------------------------------------------
def get_public_previews(limit=5):
    """Return limited public previews for the public dashboard."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    previews = {}

    # Upcoming Events
    try:
        cur.execute("""
            SELECT id, event_name AS title,
                   CONCAT(event_date, ' ', COALESCE(event_time, '')) AS datetime,
                   location
            FROM events
            WHERE visibility = 'public' AND event_date >= CURDATE()
            ORDER BY event_date ASC, event_time ASC
            LIMIT %s
        """, (limit,))
        previews['events'] = cur.fetchall()
    except Exception:
        previews['events'] = []

    # Recent Prayers
    try:
        cur.execute("""
            SELECT title, date_posted AS datetime
            FROM prayers
            WHERE visibility = 'public'
            ORDER BY date_posted DESC
            LIMIT %s
        """, (limit,))
        previews['prayers'] = cur.fetchall()
    except Exception:
        previews['prayers'] = []

    # Recent Dreams & Visions
    try:
        cur.execute("""
            SELECT d.title, d.date_posted AS datetime,
                   u.username AS posted_by
            FROM dreams d
            LEFT JOIN users u ON d.user_id = u.id
            WHERE d.visibility = 'public'
            ORDER BY d.date_posted DESC
            LIMIT %s
        """, (limit,))
        previews['dreams'] = cur.fetchall()
    except Exception:
        previews['dreams'] = []

    # Recent Prophecies
    try:
        cur.execute("""
            SELECT p.title, p.date_posted AS datetime,
                   u.username AS posted_by
            FROM prophecies p
            LEFT JOIN users u ON p.user_id = u.id
            WHERE p.visibility = 'public'
            ORDER BY p.date_posted DESC
            LIMIT %s
        """, (limit,))
        previews['prophecies'] = cur.fetchall()
    except Exception:
        previews['prophecies'] = []

    # Recent Sermons
    try:
        cur.execute("""
            SELECT s.title, s.uploaded_at AS datetime,
                   u.username AS posted_by
            FROM sermons s
            LEFT JOIN users u ON s.uploaded_by = u.id
            WHERE s.visibility = 'public'
            ORDER BY s.uploaded_at DESC
            LIMIT %s
        """, (limit,))
        previews['sermons'] = cur.fetchall()
    except Exception:
        previews['sermons'] = []

    # Recent Announcements
    try:
        cur.execute("""
            SELECT a.title, a.content, a.created_at AS datetime,
                   u.username AS posted_by
            FROM announcements a
            LEFT JOIN users u ON a.created_by = u.id
            WHERE a.visibility = 'public' AND a.is_active = 1
            ORDER BY a.created_at DESC
            LIMIT %s
        """, (limit,))
        previews['announcements'] = cur.fetchall()
    except Exception:
        previews['announcements'] = []

    return previews


# ----------------------------------------------------------------------
# Full Public Listings
# ----------------------------------------------------------------------
def get_public_list(table, where='1=1', order_by='created_at DESC', limit=None):
    """Generic helper for full public listings."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    sql = f"""
        SELECT * FROM {table}
        WHERE visibility = 'public' AND {where}
        ORDER BY {order_by}
    """
    params = []
    if limit:
        sql += " LIMIT %s"
        params.append(limit)

    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception:
        return []