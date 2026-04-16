# MYVINECHURCH.ONLINE/app/routes/public/prophecies/queries.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/prophecies/queries.py
# File name: queries.py
# Brief, detailed purpose: Reusable database query functions specifically for the public Prophecies section.
# Returns ONLY public records (with posted_by via LEFT JOIN). Clean, efficient, and feature-specific – no generic table-name passing.
# Used by views.py for listing and single-prophecy detail pages. 100% matches original public_prophecies.py + shared queries.py logic for prophecies.

from app.models.db import get_db
import pymysql.cursors


def get_public_prophecies():
    """
    Retrieve publicly visible prophecies for the main public prophecies listing page.
    Ordered by most recent first (created_at). Includes posted_by exactly as the original code did.
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            p.id,
            p.title,
            p.description,
            p.created_at,
            COALESCE(u.username, p.contributor_name, 'Anonymous') AS posted_by
        FROM prophecies p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.visibility = 'public'
        ORDER BY p.created_at DESC
    """)
    prophecies = cur.fetchall()
    cur.close()
    return prophecies


def get_public_prophecy(prophecy_id):
    """
    Retrieve a single public prophecy by ID for the detail page (view_prophecy.html).
    Includes posted_by and all fields needed for comments.
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            p.*,
            COALESCE(u.username, p.contributor_name, 'Anonymous') AS posted_by
        FROM prophecies p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.id = %s 
          AND p.visibility = 'public'
    """, (prophecy_id,))

    prophecy = cur.fetchone()
    cur.close()
    return prophecy


print("✅ MYVINECHURCH.ONLINE public/prophecies/queries.py loaded successfully")