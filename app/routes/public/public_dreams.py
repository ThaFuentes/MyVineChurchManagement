# MYVINECHURCH.ONLINE/app/routes/public/public_dreams.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/public_dreams.py
# File name: public_dreams.py
# Brief, detailed purpose: Public Dreams & Visions routes for unauthenticated guests only.
# Logged-in users are automatically redirected to the private dreams section.
# Supports full guest comment form + one-level replies (parent_id) and live censoring.
# Exact mirror of the working public_sermons.py pattern.

from flask import render_template, redirect, url_for, session, abort, request, flash
import pymysql

from . import public_bp
from .queries import get_public_list
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word


@public_bp.route('/dreams')
def public_dreams():
    """Public dreams listing page – guests only.
    Any logged-in user is redirected to the private dreams dashboard.
    """
    if 'user_id' in session:
        print("[PUBLIC DREAMS] Logged-in user → redirecting to PRIVATE dreams list")
        return redirect(url_for('dreams.dreams'))

    # Guest view only
    dreams = get_public_list('dreams', order_by='date_posted DESC')
    dreams = censor_public_content(dreams)
    return render_template('public/dreams/dreams.html', dreams=dreams)


@public_bp.route('/dreams/<int:dream_id>', methods=['GET', 'POST'])
def public_dream_detail(dream_id):
    """Public single dream detail page with guest comment + one-level reply support.
    Exact mirror of the public sermons detail view.
    """
    print(f"\n[DEBUG] PUBLIC DREAM DETAIL ROUTE – dream_id={dream_id} | method={request.method}")

    # Logged-in users go to private view
    if 'user_id' in session:
        print("[DEBUG] Logged-in user → redirecting to PRIVATE view_dream")
        return redirect(url_for('dreams.view_dream', dream_id=dream_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Fetch the public dream
    cur.execute("""
        SELECT * FROM dreams 
        WHERE id = %s AND visibility = 'public'
    """, (dream_id,))
    dream = cur.fetchone()

    if not dream:
        print("[DEBUG] Dream not found or not public → 404")
        abort(404)

    # Censor sensitive content for public view
    dream['title']       = censor_text(dream.get('title') or '')
    dream['description'] = censor_text(dream.get('description') or '')
    dream['notes']       = censor_text(dream.get('notes') or '')

    # Load comments (including one-level replies via parent_id)
    comments = []
    try:
        cur.execute("""
            SELECT c.id, c.comment, c.date_posted AS created_at, c.parent_id,
                   COALESCE(u.username, c.contributor_name, 'Guest') AS name
            FROM dream_comments c
            LEFT JOIN users u ON c.user_id = u.id
            WHERE c.dream_id = %s
            ORDER BY c.date_posted ASC
        """, (dream_id,))
        comments = cur.fetchall()

        for c in comments:
            c['date'] = c['created_at'].strftime('%B %d, %Y') if c.get('created_at') else 'Unknown'
            c['comment_text'] = c['comment']

        print(f"[DEBUG] Loaded {len(comments)} comments (including replies) for public dream {dream_id}")
    except Exception as e:
        print(f"[DEBUG] ERROR loading comments: {e}")

    dream['comments'] = comments

    # === HANDLE GUEST COMMENT OR REPLY ===
    if request.method == 'POST':
        action       = request.form.get('action')
        name         = request.form.get('contributor_name', '').strip()
        comment_text = request.form.get('comment', '').strip()
        parent_id    = request.form.get('parent_id') if action == 'reply' else None

        if action in ('comment', 'reply') and name and comment_text:
            if contains_censored_word(name + ' ' + comment_text):
                flash('Your comment contains prohibited content.', 'error')
            else:
                try:
                    cur.execute("""
                        INSERT INTO dream_comments 
                        (dream_id, contributor_name, comment, parent_id, date_posted)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, (dream_id, name, comment_text, parent_id))
                    db.commit()
                    flash('Comment posted successfully!', 'success')
                    print(f"[DEBUG] Guest comment/reply inserted for dream {dream_id}")
                except Exception as e:
                    flash('Failed to post comment.', 'error')
                    print(f"[DEBUG] Insert error: {e}")
        else:
            flash('Name and comment are required.', 'error')

        # Refresh the page to show the new comment
        return redirect(url_for('public.public_dream_detail', dream_id=dream_id))

    # Render public template
    print("[DEBUG] Rendering public/dreams/view_dream.html for guest")
    return render_template('public/dreams/view_dream.html', dream=dream)