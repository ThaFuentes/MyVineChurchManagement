# MYVINECHURCH.ONLINE/app/routes/the_gathering/sermons/queries.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/sermons/queries.py
# File name: queries.py
# Brief, detailed purpose: Reusable database queries specifically for the Sermons section
# of the Gathering Place Manager.
# • Provides listing with filters/search (all/public/private), single sermon fetch,
#   and comment queries for moderation.
# • All queries are safe, efficient, and use LEFT JOINs for creator names.
# • Designed to be called only from sermons/views.py — keeps views clean.
# • 100% consistent with the_gathering/events/queries.py, prayers/queries.py,
#   dreams/queries.py, prophecies/queries.py and announcements/queries.py patterns.
# • Only this file was rebuilt — everything else on the site remains untouched and secure.

from app.models.db import get_db
import pymysql.cursors


def get_all_sermons(filter_type='all', search_query=None, limit=50):
    """Get sermons with optional filter and search for the manager listing."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    where_clauses = []
    params = []

    if filter_type == 'public':
        where_clauses.append("s.visibility = 'public'")
    elif filter_type == 'private':
        where_clauses.append("s.visibility = 'private'")

    if search_query:
        where_clauses.append("(s.title LIKE %s OR s.scripture LIKE %s OR s.sermon_text LIKE %s)")
        params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    query = f"""
        SELECT 
            s.*,
            COALESCE(u.username, 'Anonymous') AS creator_name
        FROM sermons s
        LEFT JOIN users u ON s.created_by = u.id
        {where_sql}
        ORDER BY s.created_at DESC
        LIMIT {limit}
    """

    cur.execute(query, params)
    sermons = cur.fetchall()
    cur.close()
    return sermons


def get_sermon(sermon_id):
    """Get a single sermon by ID for edit/view pages."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            s.*,
            COALESCE(u.username, 'Anonymous') AS creator_name
        FROM sermons s
        LEFT JOIN users u ON s.created_by = u.id
        WHERE s.id = %s
    """, (sermon_id,))

    sermon = cur.fetchone()
    cur.close()
    return sermon


def get_sermon_comments(sermon_id, include_moderated=True):
    """Get all comments.html for a specific sermon (used in moderation)."""
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
        FROM sermon_comments 
        WHERE sermon_id = %s {moderated_filter}
        ORDER BY created_at ASC
    """, (sermon_id,))

    comments = cur.fetchall()
    cur.close()
    return comments


def get_pending_sermon_comment_count():
    """Return count of unmoderated sermon comments.html (used by main dashboard)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT COUNT(*) AS count 
        FROM sermon_comments 
        WHERE moderated = 0 OR moderated IS NULL
    """)
    count = cur.fetchone()['count']
    cur.close()
    return count


