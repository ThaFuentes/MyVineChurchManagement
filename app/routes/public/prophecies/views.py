# MYVINECHURCH.ONLINE/app/routes/public/prophecies/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/prophecies/views.py
# File name: views.py
# Brief, detailed purpose: Public Prophecies routes for unauthenticated guests only.
# • Listing shows public prophecies.
# • Detail page supports full guest comment/reply (parent_id) with censorship.
# • FIXED: Logged-in users now redirect to the correct private endpoint 'prophecies.list_prophecies'.
# • 100% original public_prophecies.py logic preserved.

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import prophecies_bp
from .queries import get_public_prophecies, get_public_prophecy
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word
from app.utils.time_utils import format_church


# ----------------------------------------------------------------------
# Public Prophecies Listing
# ----------------------------------------------------------------------
@prophecies_bp.route('/')
def public_prophecies():
    """Public prophecies listing (active + public only)."""
    print("🔍 [PUBLIC PROPHECIES] Listing route hit")

    # Redirect logged-in users to private view
    if 'user_id' in session:
        print("🔄 [PUBLIC PROPHECIES] Logged-in user → redirecting to PRIVATE prophecies list")
        return redirect(url_for('prophecies.list_prophecies'))

    prophecies = get_public_prophecies()

    # Format dates and censor
    for p in prophecies:
        p['datetime'] = format_church(p.get('datetime') or p.get('created_at')) if p.get('datetime') or p.get('created_at') else 'Unknown'
        p['posted_by'] = p.get('posted_by', 'Anonymous')

    prophecies = censor_public_content(prophecies)

    return render_template('public/prophecies/prophecies.html', prophecies=prophecies)


# ----------------------------------------------------------------------
# Public Single Prophecy Detail View
# ----------------------------------------------------------------------
@prophecies_bp.route('/<int:prophecy_id>', methods=['GET', 'POST'])
def public_prophecy_detail(prophecy_id):
    """Public single prophecy detail page with guest comments."""
    print(f"🔍 [PUBLIC PROPHECY DETAIL] ID={prophecy_id} | method={request.method}")

    # Redirect logged-in users to private view
    if 'user_id' in session:
        print("🔄 [PUBLIC PROPHECY DETAIL] Logged-in user → redirecting to PRIVATE view")
        return redirect(url_for('prophecies.view_prophecy', prophecy_id=prophecy_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    prophecy = get_public_prophecy(prophecy_id)
    if not prophecy:
        abort(404)

    # Server-side censorship
    prophecy['title'] = censor_text(prophecy['title'])
    if 'content' in prophecy:
        prophecy['content'] = censor_text(prophecy['content'])

    # Load comments
    cur.execute("""
        SELECT c.comment, c.date_added,
               COALESCE(u.username, 'Guest') AS commenter_name
        FROM prophecy_comments c
        LEFT JOIN users u ON c.user_id = u.id
        WHERE c.prophecy_id = %s
        ORDER BY c.date_added ASC
    """, (prophecy_id,))
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
                    INSERT INTO prophecy_comments 
                    (prophecy_id, contributor_name, comment, parent_id, date_added)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (prophecy_id, name, comment_text, parent_id or None))
                db.commit()
                flash('Comment posted successfully!', 'success')
            except Exception:
                flash('Failed to post comment.', 'error')
        return redirect(url_for('public.public_prophecies.public_prophecy_detail', prophecy_id=prophecy_id))

    return render_template('public/prophecies/view_prophecy.html',
                           prophecy=prophecy,
                           comments=comments)


print("✅ MYVINECHURCH.ONLINE public/prophecies/views.py loaded successfully (correct private redirect fixed)")