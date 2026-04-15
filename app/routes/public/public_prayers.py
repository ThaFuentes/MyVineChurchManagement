# app/routes/public/public_prayers.py
# Full path: MyVineChurch/app/routes/public/public_prayers.py
# File name: public_prayers.py
# Brief, detailed purpose: Public Prayers routes with MAXIMUM DEBUGGING so we can see exactly why toggleReplyForm is not defined on this page.

from flask import render_template, redirect, url_for, session, abort, request, flash
import pymysql

from . import public_bp
from .queries import get_public_list
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word


@public_bp.route('/prayers')
def public_prayers():
    print("[DEBUG] public_prayers route hit")
    if 'user_id' in session:
        print("[DEBUG] Logged-in user → redirecting to PRIVATE")
        return redirect(url_for('prayers.prayers'))

    prayers = get_public_list('prayers', order_by='date_posted DESC')
    prayers = censor_public_content(prayers)
    print(f"[DEBUG] Rendering public prayers list with {len(prayers)} prayers")
    return render_template('public/prayers/prayers.html', prayers=prayers)


@public_bp.route('/prayers/<int:prayer_id>', methods=['GET', 'POST'])
def public_prayer_detail(prayer_id):
    print(f"\n[DEBUG] ==================== PUBLIC PRAYER DETAIL ROUTE HIT ====================")
    print(f"[DEBUG] prayer_id = {prayer_id}")
    print(f"[DEBUG] Request method = {request.method}")
    print(f"[DEBUG] Session user_id = {session.get('user_id')}")

    if 'user_id' in session:
        print("[DEBUG] Logged-in user → redirecting to PRIVATE view")
        return redirect(url_for('prayers.view_prayer', prayer_id=prayer_id))

    print("[DEBUG] Guest user → serving public version")

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Fetch prayer
    cur.execute("""
        SELECT p.*,
               COALESCE(u.username, p.contributor_name, 'Unknown') AS posted_by
        FROM prayers p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.id = %s AND p.visibility = 'public'
    """, (prayer_id,))
    prayer = cur.fetchone()
    if not prayer:
        print("[DEBUG] Prayer not found or not public → 404")
        abort(404)

    prayer['title'] = censor_text(prayer.get('title') or '')
    prayer['description'] = censor_text(prayer.get('description') or '')

    # Load comments with full debug
    comments = []
    try:
        cur.execute("""
            SELECT id, contributor_name AS name, prayer AS comment_text, parent_id,
                   DATE_FORMAT(date_added, '%%b %%e, %%Y %%h:%%i %%p') as created_at_nice
            FROM prayers_added
            WHERE prayer_request_id = %s
            ORDER BY date_added ASC
        """, (prayer_id,))
        comments = cur.fetchall()

        print(f"[DEBUG] Loaded {len(comments)} comments for prayer {prayer_id}")
        for i, c in enumerate(comments):
            parent = f" (reply to #{c.get('parent_id')})" if c.get('parent_id') else " (top-level)"
            print(f"[DEBUG] Comment {i+1} ID={c['id']} | Name='{c['name']}' | Text='{c['comment_text'][:60]}...' {parent}")
    except Exception as e:
        print(f"[DEBUG] ERROR loading comments: {e}")

    # === HANDLE POST ===
    if request.method == 'POST':
        print(f"[DEBUG] POST received. Form data keys: {list(request.form.keys())}")
        action = request.form.get('action')
        print(f"[DEBUG] action = '{action}'")
        print(f"[DEBUG] parent_id = {request.form.get('parent_id')}")

        name = request.form.get('name', '').strip()
        comment_text = request.form.get('comment', '').strip()

        if not name or not comment_text:
            flash('Name and comment are required.', 'error')
        elif contains_censored_word(name + ' ' + comment_text):
            flash('Your comment contains prohibited content.', 'error')
        else:
            try:
                cur.execute("""
                    INSERT INTO prayers_added (prayer_request_id, contributor_name, prayer, parent_id, date_added)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (prayer_id, name, comment_text, request.form.get('parent_id') or None))
                db.commit()
                flash('Comment posted successfully!', 'success')
                print(f"[DEBUG] SUCCESS: Comment inserted for prayer {prayer_id}")
            except Exception as e:
                flash('Failed to post comment.', 'error')
                print(f"[DEBUG] FAILED to insert comment: {e}")

        print("[DEBUG] Redirecting after POST")
        return redirect(url_for('public.public_prayer_detail', prayer_id=prayer_id))

    # Render template
    print("[DEBUG] Rendering template 'public/prayers/view_prayer.html' with comments")
    print(f"[DEBUG] Number of comments passed to template: {len(comments)}")
    return render_template('public/prayers/view_prayer.html',
                           prayer=prayer,
                           comments=comments)