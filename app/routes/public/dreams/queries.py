# MYVINECHURCH.ONLINE/app/routes/public/dreams/queries.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/dreams/queries.py
# File name: queries.py
# Brief, detailed purpose: Reusable database query functions specifically for the public Dreams & Visions section.
# Returns ONLY public + approved records. Clean, efficient, and feature-specific (no generic table-name passing).
# Used by views.py for listing and single-dream detail pages.

from app.models.db import get_db
import pymysql.cursors


def get_public_dreams(limit=None):
    """
    Retrieve publicly visible dreams for the main public dreams listing page.
    Ordered by most recent first. Supports optional limit for previews.
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    sql = """
        SELECT 
            d.id,
            d.title,
            d.description,
            d.date_posted,
            COALESCE(u.username, d.contributor_name, 'Anonymous') AS poster_name
        FROM dreams d
        LEFT JOIN users u ON d.user_id = u.id
        WHERE d.visibility = 'public'
          AND d.is_approved = 1
        ORDER BY d.date_posted DESC
    """

    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    cur.execute(sql)
    dreams = cur.fetchall()
    cur.close()
    return dreams


def get_public_dream(dream_id):
    """
    Retrieve a single public dream by ID for the detail page (view_dream.html).
    Includes poster/creator name for display.
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT 
            d.*,
            COALESCE(u.username, d.contributor_name, 'Anonymous') AS poster_name,
            COALESCE(u.username, d.contributor_name) AS creator_name
        FROM dreams d
        LEFT JOIN users u ON d.user_id = u.id
        WHERE d.id = %s 
          AND d.visibility = 'public'
          AND d.is_approved = 1
    """, (dream_id,))

    dream = cur.fetchone()
    cur.close()
    return dream


print("✅ MYVINECHURCH.ONLINE public/dreams/queries.py loaded successfully")