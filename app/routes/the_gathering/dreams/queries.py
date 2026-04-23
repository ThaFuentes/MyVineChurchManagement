# MYVINECHURCH.ONLINE/app/routes/the_gathering/dreams/queries.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/dreams/queries.py
# File name: queries.py
# Brief, detailed purpose: Reusable database queries specifically for the Dreams section
# of the Gathering Place Manager.
# • Provides listing with filters/search (all/public/private), single dream fetch,
#   and comment queries for moderation.
# • All queries are safe, efficient, and use LEFT JOINs for creator names.
# • Designed to be called only from dreams/views.py — keeps views clean.
# • 100% consistent with the_gathering/announcements/queries.py and public/events/queries.py patterns.
# • Only this file was rebuilt — everything else on the site remains untouched and secure.

from app.models.db import get_db
import pymysql.cursors


def get_all_dreams(filter_type='all', search_query=None, limit=50):
    """Get dreams with optional filter and search for the manager listing."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    where_clauses = []
    params = []

    if filter_type == 'public':
        where_clauses.append("d.visibility = 'public'")
    elif filter_type == 'private':
        where_clauses.append("d.visibility = 'private'")

    if search_query:
        where_clauses.append("(d.title LIKE %s OR d.dream_text LIKE %s)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    query = f"""
        SELECT 
            d.*,
            COALESCE(u.username, 'Anonymous') AS creator_name
        FROM dreams d
        LEFT JOIN users u ON d.created_by = u.id
        {where_sql}
        ORDER BY d.created_at DESC
        LIMIT {limit}
    """

    cur.execute(query, params)
    dreams = cur.fetchall()
    cur.close()
    return dreams


def get_dream(dream_id):
    """Get a single dream by ID for edit/view pages."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            d.*,
            COALESCE(u.username, 'Anonymous') AS creator_name
        FROM dreams d
        LEFT JOIN users u ON d.created_by = u.id
        WHERE d.id = %s
    """, (dream_id,))

    dream = cur.fetchone()
    cur.close()
    return dream


def get_dream_comments(dream_id, include_moderated=True):
    """Get all comments.html for a specific dream (used in moderation)."""
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
        FROM dream_comments 
        WHERE dream_id = %s {moderated_filter}
        ORDER BY created_at ASC
    """, (dream_id,))

    comments = cur.fetchall()
    cur.close()
    return comments


def get_pending_dream_comment_count():
    """Return count of unmoderated dream comments.html (used by main dashboard)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT COUNT(*) AS count 
        FROM dream_comments 
        WHERE moderated = 0 OR moderated IS NULL
    """)
    count = cur.fetchone()['count']
    cur.close()
    return count


print("✅ MYVINECHURCH.ONLINE the_gathering/dreams/queries.py loaded successfully (dream listing + comments.html + moderation queries ready)")