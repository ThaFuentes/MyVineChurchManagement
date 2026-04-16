# MYVINECHURCH.ONLINE/app/routes/public/prayers/queries.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/prayers/queries.py
# File name: queries.py
# Brief, detailed purpose: Reusable database query functions specifically for the public Prayers section.
# Returns ONLY public records (with posted_by via LEFT JOIN). Clean, efficient, and feature-specific – no generic table-name passing.
# Used by views.py for listing and single-prayer detail pages. 100% matches original public_prayers.py + shared queries.py logic for prayers.

from app.models.db import get_db
import pymysql.cursors


def get_public_prayers():
    """
    Retrieve publicly visible prayers for the main public prayers listing page.
    Ordered by most recent first. Includes posted_by exactly as the original code did.
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            p.id,
            p.title,
            p.description,
            p.date_posted,
            COALESCE(u.username, p.contributor_name, 'Unknown') AS posted_by
        FROM prayers p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.visibility = 'public'
        ORDER BY p.date_posted DESC
    """)
    prayers = cur.fetchall()
    cur.close()
    return prayers


def get_public_prayer(prayer_id):
    """
    Retrieve a single public prayer by ID for the detail page (view_prayer.html).
    Includes posted_by and all fields needed for comments.
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            p.*,
            COALESCE(u.username, p.contributor_name, 'Unknown') AS posted_by
        FROM prayers p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.id = %s 
          AND p.visibility = 'public'
    """, (prayer_id,))

    prayer = cur.fetchone()
    cur.close()
    return prayer


print("✅ MYVINECHURCH.ONLINE public/prayers/queries.py loaded successfully")