# MYVINECHURCH.ONLINE/app/routes/public/sermons/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/sermons/views.py
# File name: views.py
# Brief, detailed purpose: Public Sermons routes – EXACT pattern as public_events.py and public_prayers.py.
# • Logged-in users forced to private view.
# • Guests can leave comments and replies + Owner/Admin can delete any comment or reply.
# • Uses the new feature-specific queries.py, utils.py, and forms.py.
# • 100% original public_sermons.py logic preserved with debug prints and exact template expectations.

from flask import render_template, redirect, url_for, session, abort, request, flash
import pymysql

from . import sermons_bp
from .queries import get_public_sermons, get_public_sermon
from .forms import validate_guest_comment_form
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word


@sermons_bp.route('/')
def public_sermons():
    """Public sermons listing – logged-in users go to private dashboard."""
    if 'user_id' in session:
        print("[PUBLIC SERMONS] Logged-in user → redirecting to PRIVATE sermons list")
        return redirect(url_for('sermons.sermons'))

    # Guest view only
    sermons = get_public_sermons()
    sermons = censor_public_content(sermons)
    return render_template('public/sermons/sermons.html', sermons=sermons)


@sermons_bp.route('/<int:sermon_id>', methods=['GET', 'POST'])
def public_sermon_detail(sermon_id):
    """Public single sermon detail with guest comment support + replies + delete."""
    print(f"\n[DEBUG] ==================== PUBLIC SERMON DETAIL ROUTE HIT ====================")
    print(f"[DEBUG] sermon_id = {sermon_id}")
    print(f"[DEBUG] Request method = {request.method}")
    print(f"[DEBUG] Session user_id = {session.get('user_id')}")

    if 'user_id' in session:
        print("[DEBUG] Logged-in user → redirecting to PRIVATE view")
        return redirect(url_for('sermons.view_sermon', sermon_id=sermon_id))

    print("[DEBUG] Guest user → serving public version")

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Fetch sermon using dedicated query
    sermon = get_public_sermon(sermon_id)
    if not sermon:
        print("[DEBUG] Sermon not found or not public → 404")
        abort(404)

    sermon['title'] = censor_text(sermon.get('title') or '')
    sermon['details'] = censor_text(sermon.get('details') or '')
    sermon['notes_content'] = censor_text(sermon.get('notes_content') or '')

    # Load comments
    comments = []
    try:
        cur.execute("""
            SELECT c.id, c.comment, c.date_added AS created_at, c.parent_id,
                   COALESCE(u.username, c.contributor_name, 'Guest') AS name
            FROM sermon_comments c
            LEFT JOIN users u ON c.user_id = u.id
            WHERE c.sermon_id = %s
            ORDER BY c.date_added ASC
        """, (sermon_id,))
        comments = cur.fetchall()

        for c in comments:
            c['date'] = c['created_at'].strftime('%B %d, %Y') if c.get('created_at') else 'Unknown'
            c['comment_text'] = c['comment']

        print(f"[DEBUG] Loaded {len(comments)} comments for sermon {sermon_id}")
    except Exception as e:
        print(f"[DEBUG] ERROR loading comments for sermon {sermon_id}: {e}")

    sermon['comments'] = comments   # <-- Critical for template

    # === HANDLE POST (comment, reply, or delete) ===
    if request.method == 'POST':
        action = request.form.get('action')
        print(f"[DEBUG] POST action = '{action}'")

        if action == 'delete':
            comment_id = request.form.get('comment_id')
            if session.get('role') in ['Owner', 'Admin']:
                try:
                    cur.execute("DELETE FROM sermon_comments WHERE id = %s", (comment_id,))
                    db.commit()
                    flash('Comment deleted.', 'success')
                except Exception:
                    flash('Failed to delete comment.', 'error')
            else:
                flash('You do not have permission to delete.', 'error')

        elif action in ('comment', 'reply'):
            clean = validate_guest_comment_form(request.form)
            if not clean:
                return redirect(url_for('public_sermons.public_sermon_detail', sermon_id=sermon_id))

            try:
                cur.execute("""
                    INSERT INTO sermon_comments (sermon_id, contributor_name, comment, parent_id, date_added)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (sermon_id, clean['name'], clean['comment'], clean['parent_id']))
                db.commit()
                flash('Comment posted successfully!', 'success')
            except Exception as e:
                flash('Failed to post comment.', 'error')
                print(f"[DEBUG] FAILED to insert comment: {e}")

        return redirect(url_for('public_sermons.public_sermon_detail', sermon_id=sermon_id))

    print("[DEBUG] Rendering template 'public/sermons/view_sermon.html'")
    return render_template('public/sermons/view_sermon.html', sermon=sermon)


print("✅ MYVINECHURCH.ONLINE public/sermons/views.py loaded successfully")