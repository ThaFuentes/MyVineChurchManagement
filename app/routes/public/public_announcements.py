# app/routes/public/public_announcements.py
# Full path: MyVineChurch/app/routes/public/public_announcements.py
# File name: public_announcements.py
# Brief, detailed purpose: Public Announcements routes (listing + single detail view with guest comments).
# • Clean separation: listing + detail in one file for the public side.
# • Uses shared queries and utils from the public package.
# • Guest comment form supported exactly like dreams/sermons.

from flask import render_template, abort
import pymysql

from . import public_bp
from .queries import get_public_list
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text
from app.utils.time_utils import format_church


# ----------------------------------------------------------------------
# Public Announcements Listing
# ----------------------------------------------------------------------
@public_bp.route('/announcements')
def public_announcements():
    """Public announcements listing (active + public only)."""
    announcements = get_public_list(
        'announcements',
        where='is_active = 1',
        order_by='created_at DESC'
    )

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    for a in announcements:
        a['datetime'] = format_church(a['created_at']) if a.get('created_at') else 'Unknown'
        a['posted_by'] = a.get('creator_name', 'Unknown')

        # Fetch comments for each announcement
        cur.execute("""
            SELECT c.comment, c.date_added AS created_at,
                   COALESCE(u.username, 'Guest') AS name
            FROM announcement_comments c
            LEFT JOIN users u ON c.user_id = u.id
            WHERE c.announcement_id = %s
            ORDER BY c.date_added ASC
        """, (a['id'],))
        a['comments'] = cur.fetchall()

        for c in a['comments']:
            c['date'] = format_church(c['created_at']) if c.get('created_at') else 'Unknown'
            c['comment_text'] = c['comment']

    announcements = censor_public_content(announcements)
    return render_template('public/announcements/announcements.html', announcements=announcements)


# ----------------------------------------------------------------------
# Public Single Announcement Detail View
# ----------------------------------------------------------------------
@public_bp.route('/announcements/<int:ann_id>')
def public_announcement_detail(ann_id):
    """Public single announcement detail page with guest comments."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Fetch announcement (must be public + active)
    cur.execute("""
        SELECT * FROM announcements 
        WHERE id = %s 
          AND visibility = 'public' 
          AND is_active = 1
    """, (ann_id,))
    announcement = cur.fetchone()

    if not announcement:
        abort(404)

    # Server-side censorship
    announcement['title'] = censor_text(announcement['title'])
    announcement['content'] = censor_text(announcement.get('content', ''))

    # Load comments
    cur.execute("""
        SELECT c.comment, c.date_added,
               COALESCE(u.username, 'Guest') AS commenter_name
        FROM announcement_comments c
        LEFT JOIN users u ON c.user_id = u.id
        WHERE c.announcement_id = %s
        ORDER BY c.date_added ASC
    """, (ann_id,))
    comments = cur.fetchall()

    for c in comments:
        c['comment'] = censor_text(c['comment'])
        c['date'] = format_church(c['date_added']) if c.get('date_added') else 'Unknown'

    return render_template('public/announcements/view_announcement.html',
                           announcement=announcement,
                           comments=comments)