# MYVINECHURCH.ONLINE/app/routes/public/prophecies/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/prophecies/views.py
# File name: views.py
# Brief, detailed purpose: Public Prophecies routes (guests only) – sub-blueprint version.
# • Uses the LOCAL queries.py and utils.py that already exist in this prophecies folder
# • Logged-in users instantly redirect to private prophecies
# • Guests get clean listing + single-detail view with full guest comment/reply support
# • 100% rebuilt – exact match to your current prophecies/queries.py (get_public_prophecies + get_public_prophecy)

from flask import render_template, redirect, url_for, session, abort, request, flash
import pymysql

from . import prophecies_bp
from .queries import get_public_prophecies, get_public_prophecy
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word
from app.utils.time_utils import format_church


# ----------------------------------------------------------------------
# Public Prophecies Listing (Guests Only)
# ----------------------------------------------------------------------
@prophecies_bp.route('/prophecies')
def public_prophecies():
    """Public prophecies listing page – guests only."""
    if 'user_id' in session:
        return redirect(url_for('prophecies.list_prophecies'))

    # Guest view only
    prophecies = get_public_prophecies()
    prophecies = censor_public_content(prophecies)

    # Format dates for template
    for p in prophecies:
        p['datetime'] = format_church(p.get('created_at')) if p.get('created_at') else 'Unknown'
        p['posted_by'] = p.get('posted_by', 'Anonymous')

    return render_template('public/prophecies/prophecies.html', prophecies=prophecies)


# ----------------------------------------------------------------------
# Public Single Prophecy Detail (Guests Only + Guest Comments/Replies)
# ----------------------------------------------------------------------
@prophecies_bp.route('/prophecies/<int:prophecy_id>', methods=['GET', 'POST'])
def public_prophecy_detail(prophecy_id):
    """Public single prophecy detail page with guest comment + one-level reply support."""
    # Logged-in users go to private view
    if 'user_id' in session:
        return redirect(url_for('prophecies.view_prophecy', prophecy_id=prophecy_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Fetch single prophecy using your local query function
    prophecy = get_public_prophecy(prophecy_id)
    if not prophecy:
        abort(404)

    # Server-side censorship
    prophecy['title']       = censor_text(prophecy.get('title') or 'Untitled Prophecy')
    prophecy['description'] = censor_text(prophecy.get('description') or '')

    # Load comments (including one-level replies via parent_id)
    comments = []
    try:
        cur.execute("""
            SELECT 
                pc.id,
                pc.comment,
                pc.date_added AS created_at,
                pc.parent_id,
                COALESCE(u.username, pc.contributor_name, 'Guest') AS name
            FROM prophecy_comments pc
            LEFT JOIN users u ON pc.user_id = u.id
            WHERE pc.prophecy_id = %s
            ORDER BY pc.date_added ASC
        """, (prophecy_id,))
        comments = cur.fetchall()

        for c in comments:
            c['date'] = format_church(c['created_at']) if c.get('created_at') else 'Unknown'
            c['comment_text'] = c['comment']
    except Exception:
        pass

    prophecy['comments'] = comments

    # === HANDLE GUEST COMMENT OR REPLY (POST) ===
    if request.method == 'POST':
        action       = request.form.get('action')
        name         = request.form.get('contributor_name', '').strip()
        comment_text = request.form.get('comment', '').strip()
        parent_id    = request.form.get('parent_id') if action == 'reply' else None

        if action in ('comment', 'reply'):
            if not name or not comment_text:
                flash('Name and comment are required.', 'error')
            elif contains_censored_word(name + ' ' + comment_text):
                flash('Your comment contains prohibited content.', 'error')
            else:
                try:
                    cur.execute("""
                        INSERT INTO prophecy_comments 
                        (prophecy_id, contributor_name, comment, parent_id, date_added)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, (prophecy_id, name, comment_text, parent_id))
                    db.commit()
                    flash('Comment posted successfully!', 'success')
                except Exception:
                    flash('Failed to post comment.', 'error')
        else:
            flash('Invalid action.', 'error')

        # Refresh the page to show the new comment
        return redirect(url_for('public.prophecies.public_prophecy_detail', prophecy_id=prophecy_id))

    # Render public template for guests
    return render_template('public/prophecies/view_prophecy.html', prophecy=prophecy)