# MYVINECHURCH.ONLINE/app/routes/public/prayers/queries.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/prayers/queries.py
# File name: queries.py
# Brief, detailed purpose: Reusable database query functions specifically for the public Prayers section.
# Returns ONLY public records (with creator_name via LEFT JOIN on created_by/user_id).
# Clean, efficient, and 100% consistent with the public/events/queries.py gold standard.

from app.models.db import get_db
import pymysql.cursors


def get_public_prayers():
    """
    Retrieve publicly visible prayers for the main public prayers listing page.
    Ordered by most recent first. Includes creator_name exactly as Events does.
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            p.id,
            p.title,
            p.description,
            p.date_posted,
            COALESCE(u.username, p.contributor_name, 'Anonymous') AS creator_name
        FROM prayers p
        LEFT JOIN users u ON COALESCE(p.created_by, p.user_id) = u.id
        WHERE p.visibility = 'public'
        ORDER BY p.date_posted DESC
    """)
    prayers = cur.fetchall()
    cur.close()
    return prayers


def get_public_prayer(prayer_id):
    """
    Retrieve a single public prayer by ID for the detail page (view_prayer.html).
    Includes creator_name and all fields needed for responses.
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            p.*,
            COALESCE(u.username, p.contributor_name, 'Anonymous') AS creator_name
        FROM prayers p
        LEFT JOIN users u ON COALESCE(p.created_by, p.user_id) = u.id
        WHERE p.id = %s 
          AND p.visibility = 'public'
    """, (prayer_id,))

    prayer = cur.fetchone()
    cur.close()
    return prayer


print("✅ MYVINECHURCH.ONLINE public/prayers/queries.py loaded successfully (creator_name fixed to match Events gold standard)")