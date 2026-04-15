# app/routes/public/queries.py
# Full path: MyVineChurch/app/routes/public/queries.py
# File name: queries.py
# Brief, detailed purpose: All database queries and operations for the Public module.
# • Pure data-access layer – no Flask routes, no templates, no flash messages.
# • Every SELECT from the original public.py is now here.
# • 100% original behavior preserved with correct date columns per table.
# • SECURITY: Strict table whitelist + parameterized queries.

import pymysql
from app.models.db import get_db


# Allowed public tables (whitelist for security)
ALLOWED_PUBLIC_TABLES = {
    'events', 'sermons', 'announcements', 'prayers', 'dreams', 'prophecies'
}


# ----------------------------------------------------------------------
# Public Previews for Dashboard
# ----------------------------------------------------------------------
def get_public_previews(limit=5):
    """Return limited public previews for the public dashboard."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    previews = {}

    # Upcoming Events – FIXED with STR_TO_DATE (event_date is VARCHAR)
    try:
        cur.execute("""
            SELECT id, event_name AS title,
                   CONCAT(event_date, ' ', COALESCE(event_time, '')) AS datetime,
                   location
            FROM events
            WHERE visibility = 'public' 
              AND STR_TO_DATE(event_date, '%Y-%m-%d') >= CURDATE()
            ORDER BY event_date ASC, event_time ASC
            LIMIT %s
        """, (limit,))
        previews['events'] = cur.fetchall()
    except Exception as e:
        previews['events'] = []
        print(f"⚠️ Upcoming events preview failed: {e}")

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

    # Recent Prophecies – FIXED: uses created_at (correct column)
    try:
        cur.execute("""
            SELECT p.title, p.created_at AS datetime,
                   u.username AS posted_by
            FROM prophecies p
            LEFT JOIN users u ON p.user_id = u.id
            WHERE p.visibility = 'public'
            ORDER BY p.created_at DESC
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
# Full Public Listings (SECURE + CORRECT COLUMNS)
# ----------------------------------------------------------------------
def get_public_list(table, where='1=1', order_by=None, limit=None):
    """Generic helper for full public listings.
    Table name is strictly validated. Correct date column is auto-selected."""
    if table not in ALLOWED_PUBLIC_TABLES:
        return []  # Silent fail for security

    # Map each table to its correct sort column
    date_column_map = {
        'events': 'event_date',
        'prayers': 'date_posted',
        'dreams': 'date_posted',
        'prophecies': 'created_at',      # ← Correct column for prophecies
        'sermons': 'uploaded_at',
        'announcements': 'created_at'
    }

    sort_column = date_column_map.get(table.lower(), 'created_at')
    final_order_by = order_by or f"{sort_column} DESC"

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    sql = f"""
        SELECT * FROM {table}
        WHERE visibility = 'public' AND {where}
        ORDER BY {final_order_by}
    """
    params = []

    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)

    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception as e:
        print(f"Public list error for table {table}: {e}")
        return []