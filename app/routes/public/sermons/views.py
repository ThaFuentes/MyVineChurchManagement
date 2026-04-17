# MYVINECHURCH.ONLINE/app/routes/public/sermons/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/sermons/views.py
# File name: views.py
# Brief, detailed purpose: Public Sermons routes for unauthenticated guests only.
# • Listing now safely formats uploaded_at (handles string or datetime) and correctly sets posted_by/creator_name.
# • Detail page supports guest comments/replies + admin delete.
# • 100% rebuilt to match the working public/events/views.py gold standard.

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import sermons_bp
from .queries import get_public_sermons, get_public_sermon
from .forms import validate_guest_comment_form
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word


# ----------------------------------------------------------------------
# Public Sermons Listing (Guests Only)
# ----------------------------------------------------------------------
@sermons_bp.route('/')
def public_sermons():
    """Public sermons listing – logged-in users are redirected to private dashboard."""
    if 'user_id' in session:
        return redirect(url_for('sermons.sermons'))

    # Guest view only
    sermons = get_public_sermons()
    sermons = censor_public_content(sermons)

    # Prepare data for template – SAFE date formatting + creator_name fallback
    for s in sermons:
        # Safe date formatting (handles both datetime objects and strings)
        uploaded_at = s.get('uploaded_at')
        if uploaded_at:
            if hasattr(uploaded_at, 'strftime'):
                s['datetime'] = uploaded_at.strftime('%B %d, %Y')
            else:
                # It's a string (common with pymysql)
                s['datetime'] = str(uploaded_at)[:10]  # take YYYY-MM-DD part
        else:
            s['datetime'] = 'Unknown'

        # Creator name – use creator_name first, then fallback
        s['posted_by'] = s.get('creator_name') or 'Anonymous'

    return render_template('public/sermons/sermons.html', sermons=sermons)


# ----------------------------------------------------------------------
# Public Single Sermon Detail (Guests Only + Comments/Replies + Admin Delete)
# ----------------------------------------------------------------------
@sermons_bp.route('/<int:sermon_id>', methods=['GET', 'POST'])
def public_sermon_detail(sermon_id):
    """Public single sermon detail with guest comments/replies and admin delete capability."""
    if 'user_id' in session:
        return redirect(url_for('sermons.view_sermon', sermon_id=sermon_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    sermon = get_public_sermon(sermon_id)
    if not sermon:
        abort(404)

    # Censor content for public view
    sermon['title']   = censor_text(sermon.get('title', ''))
    sermon['details'] = censor_text(sermon.get('details', ''))
    sermon['notes']   = censor_text(sermon.get('notes', ''))

    # Load comments
    comments = []
    try:
        cur.execute("""
            SELECT 
                c.id,
                c.comment,
                DATE_FORMAT(c.date_added, '%%b %%e, %%Y %%h:%%i %%p') as date,
                c.parent_id,
                COALESCE(u.username, c.contributor_name, 'Guest') AS name
            FROM sermon_comments c
            LEFT JOIN users u ON c.user_id = u.id
            WHERE c.sermon_id = %s
            ORDER BY c.date_added ASC
        """, (sermon_id,))
        comments = cur.fetchall()
    except Exception:
        pass

    sermon['comments'] = comments

    # Handle POST
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'delete' and session.get('role') in ['Owner', 'Admin']:
            comment_id = request.form.get('comment_id')
            try:
                cur.execute("DELETE FROM sermon_comments WHERE id = %s", (comment_id,))
                db.commit()
                flash('Comment deleted.', 'success')
            except Exception:
                flash('Failed to delete comment.', 'error')

        elif action in ('comment', 'reply'):
            clean = validate_guest_comment_form(request.form)
            if clean:
                try:
                    cur.execute("""
                        INSERT INTO sermon_comments 
                        (sermon_id, contributor_name, comment, parent_id, date_added)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, (sermon_id, clean['name'], clean['comment'], clean['parent_id']))
                    db.commit()
                    flash('Comment posted successfully!', 'success')
                except Exception:
                    flash('Failed to post comment.', 'error')

        return redirect(url_for('public.public_sermons.public_sermon_detail', sermon_id=sermon_id))

    return render_template('public/sermons/view_sermon.html', sermon=sermon)


print("✅ MYVINECHURCH.ONLINE public/sermons/views.py loaded successfully (date + creator_name fixes applied)")