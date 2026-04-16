# MYVINECHURCH.ONLINE/app/routes/public/announcements/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/announcements/views.py
# File name: views.py
# Brief, detailed purpose: Public Announcements routes (listing + single detail view with guest comments).
# • Clean separation using the new feature-specific queries.py and utils.py
# • Guest comment form supported exactly like dreams/sermons.
# • FIXED: Added missing imports (session, request, flash, redirect, url_for) to prevent NameError.
# • 100% original logic preserved.

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import announcements_bp
from .queries import get_public_announcements, get_public_announcement
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word
from app.utils.time_utils import format_church


# ----------------------------------------------------------------------
# Public Announcements Listing
# ----------------------------------------------------------------------
@announcements_bp.route('/')
def public_announcements():
    """Public announcements listing (active + public only)."""
    announcements = get_public_announcements()

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    for a in announcements:
        a['datetime'] = format_church(a['created_at']) if a.get('created_at') else 'Unknown'
        a['posted_by'] = a.get('posted_by', 'Unknown')

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
@announcements_bp.route('/<int:ann_id>', methods=['GET', 'POST'])
def public_announcement_detail(ann_id):
    """Public single announcement detail page with guest comments."""
    # Redirect logged-in users to the private view
    if 'user_id' in session:
        return redirect(url_for('announcements.view_announcement', ann_id=ann_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Fetch announcement using the new dedicated query
    announcement = get_public_announcement(ann_id)
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

    if request.method == 'POST':
        action = request.form.get('action')
        name = request.form.get('contributor_name', '').strip()
        comment_text = request.form.get('comment', '').strip()
        parent_id = request.form.get('parent_id') if action == 'reply' else None

        if not name or not comment_text:
            flash('Name and comment are required.', 'error')
        elif contains_censored_word(name + ' ' + comment_text):
            flash('Your comment contains prohibited content.', 'error')
        else:
            try:
                cur.execute("""
                    INSERT INTO announcement_comments 
                    (announcement_id, contributor_name, comment, parent_id, date_added)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (ann_id, name, comment_text, parent_id or None))
                db.commit()
                flash('Comment posted successfully!', 'success')
            except Exception:
                flash('Failed to post comment.', 'error')
        return redirect(url_for('public.public_announcements.public_announcement_detail', ann_id=ann_id))

    return render_template('public/announcements/view_announcement.html',
                           announcement=announcement,
                           comments=comments)


print("✅ MYVINECHURCH.ONLINE public/announcements/views.py loaded successfully (NameError for 'session' fixed)")