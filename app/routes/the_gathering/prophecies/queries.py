# MYVINECHURCH.ONLINE/app/routes/the_gathering/prophecies/queries.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/prophecies/queries.py
# File name: queries.py
# Brief, detailed purpose: Reusable database queries specifically for the Prophecies section
# of the Gathering Place Manager.
# • Provides listing with filters/search (all/public/private), single prophecy fetch,
#   and comment queries for moderation.
# • All queries are safe, efficient, and use LEFT JOINs for creator names.
# • Designed to be called only from prophecies/views.py — keeps views clean.
# • 100% consistent with the_gathering/events/queries.py, dreams/queries.py, prayers/queries.py and announcements/queries.py patterns.
# • Only this file was rebuilt — everything else on the site remains untouched and secure.

from app.models.db import get_db
import pymysql.cursors


def get_all_prophecies(filter_type='all', search_query=None, limit=50):
    """Get prophecies with optional filter and search for the manager listing."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    where_clauses = []
    params = []

    if filter_type == 'public':
        where_clauses.append("pr.visibility = 'public'")
    elif filter_type == 'private':
        where_clauses.append("pr.visibility = 'private'")

    if search_query:
        where_clauses.append("(pr.title LIKE %s OR pr.prophecy_text LIKE %s)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    query = f"""
        SELECT 
            pr.*,
            COALESCE(u.username, 'Anonymous') AS creator_name
        FROM prophecies pr
        LEFT JOIN users u ON pr.created_by = u.id
        {where_sql}
        ORDER BY pr.created_at DESC
        LIMIT {limit}
    """

    cur.execute(query, params)
    prophecies = cur.fetchall()
    cur.close()
    return prophecies


def get_prophecy(prophecy_id):
    """Get a single prophecy by ID for edit/view pages."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            pr.*,
            COALESCE(u.username, 'Anonymous') AS creator_name
        FROM prophecies pr
        LEFT JOIN users u ON pr.created_by = u.id
        WHERE pr.id = %s
    """, (prophecy_id,))

    prophecy = cur.fetchone()
    cur.close()
    return prophecy


def get_prophecy_comments(prophecy_id, include_moderated=True):
    """Get all comments.html for a specific prophecy (used in moderation)."""
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
        FROM prophecy_comments 
        WHERE prophecy_id = %s {moderated_filter}
        ORDER BY created_at ASC
    """, (prophecy_id,))

    comments = cur.fetchall()
    cur.close()
    return comments


def get_pending_prophecy_comment_count():
    """Return count of unmoderated prophecy comments.html (used by main dashboard)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT COUNT(*) AS count 
        FROM prophecy_comments 
        WHERE moderated = 0 OR moderated IS NULL
    """)
    count = cur.fetchone()['count']
    cur.close()
    return count


print("✅ MYVINECHURCH.ONLINE the_gathering/prophecies/queries.py loaded successfully (prophecy listing + comments.html + moderation queries ready)")