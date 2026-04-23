# MYVINECHURCH.ONLINE/app/routes/the_gathering/prayers/queries.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/prayers/queries.py
# File name: queries.py
# Brief, detailed purpose: Reusable database queries specifically for the Prayers section
# of the Gathering Place Manager.
# • Provides listing with filters/search (all/public/private), single prayer fetch,
#   and comment queries for moderation.
# • All queries are safe, efficient, and use LEFT JOINs for creator names.
# • Designed to be called only from prayers/views.py — keeps views clean.
# • 100% consistent with the_gathering/events/queries.py, dreams/queries.py and announcements/queries.py patterns.
# • Only this file was rebuilt — everything else on the site remains untouched and secure.

from app.models.db import get_db
import pymysql.cursors


def get_all_prayers(filter_type='all', search_query=None, limit=50):
    """Get prayers with optional filter and search for the manager listing."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    where_clauses = []
    params = []

    if filter_type == 'public':
        where_clauses.append("p.visibility = 'public'")
    elif filter_type == 'private':
        where_clauses.append("p.visibility = 'private'")

    if search_query:
        where_clauses.append("(p.title LIKE %s OR p.prayer_text LIKE %s)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    query = f"""
        SELECT 
            p.*,
            COALESCE(u.username, 'Anonymous') AS creator_name
        FROM prayers p
        LEFT JOIN users u ON p.created_by = u.id
        {where_sql}
        ORDER BY p.created_at DESC
        LIMIT {limit}
    """

    cur.execute(query, params)
    prayers = cur.fetchall()
    cur.close()
    return prayers


def get_prayer(prayer_id):
    """Get a single prayer by ID for edit/view pages."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            p.*,
            COALESCE(u.username, 'Anonymous') AS creator_name
        FROM prayers p
        LEFT JOIN users u ON p.created_by = u.id
        WHERE p.id = %s
    """, (prayer_id,))

    prayer = cur.fetchone()
    cur.close()
    return prayer


def get_prayer_comments(prayer_id, include_moderated=True):
    """Get all comments.html for a specific prayer (used in moderation)."""
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
        FROM prayer_comments 
        WHERE prayer_id = %s {moderated_filter}
        ORDER BY created_at ASC
    """, (prayer_id,))

    comments = cur.fetchall()
    cur.close()
    return comments


def get_pending_prayer_comment_count():
    """Return count of unmoderated prayer comments.html (used by main dashboard)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT COUNT(*) AS count 
        FROM prayer_comments 
        WHERE moderated = 0 OR moderated IS NULL
    """)
    count = cur.fetchone()['count']
    cur.close()
    return count


print("✅ MYVINECHURCH.ONLINE the_gathering/prayers/queries.py loaded successfully (prayer listing + comments.html + moderation queries ready)")