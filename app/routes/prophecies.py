# app/routes/prophecies.py
# Full path: WebChurchMan/app/routes/prophecies.py
# File name: prophecies.py
# Brief, detailed purpose: Blueprint for all prophecy-related functionality (MariaDB/pymysql compatible).
# Single URL /prophecies – different template and data based on login status:
#   • Guests: ONLY public prophecies (read-only public view).
#   • Logged-in: ALL prophecies (public + private + personal own).
# Submit/edit/delete prophecy: logged-in + owner or Admin/Owner.
# Commenting/edit/delete comment: logged-in + owner or Admin/Owner.
# Visibility flag (default 'private') with full public/private/personal support.
# Server-side censored word check on create/edit/comment.
# Server-side display censorship on all user-generated text.
# All significant actions audit-logged.
# Visibility enforced at query level.
# FULL REBUILD: MariaDB/pymysql compatible (%s placeholders, DictCursor, ON DUPLICATE KEY UPDATE where needed).
#                 Uses created_at for sorting (matches DB schema).
#                 updated_at preserved in DB but not used in queries (available for future edits).

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app.utils.decorators import login_required, role_required
from app.utils.helpers import contains_censored_word, censor_text
from app.models.db import get_db
from app.models.log import log_change
import pymysql
from datetime import datetime
from collections import defaultdict

prophecies_bp = Blueprint('prophecies', __name__, url_prefix='/prophecies')

REQUIRED_ROLES = ['Admin', 'Owner']


# ----------------------------------------------------------------------
# Main Listing – /prophecies (single URL)
# ----------------------------------------------------------------------
@prophecies_bp.route('/')
def list_prophecies():
    is_logged_in = 'user_id' in session
    user_id = session.get('user_id')

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    sql = """
        SELECT p.id, p.title, p.description, p.created_at, p.visibility,
               p.user_id AS creator_id,
               u.username AS creator_username
        FROM prophecies p
        LEFT JOIN users u ON p.user_id = u.id
    """
    params = []
    if not is_logged_in:
        sql += " WHERE p.visibility = %s"
        params.append('public')
    else:
        sql += " WHERE p.visibility IN (%s, %s) OR (p.visibility = %s AND p.user_id = %s)"
        params.extend(['public', 'private', 'personal', user_id])

    sql += " ORDER BY p.created_at DESC"
    cur.execute(sql, params)
    rows = cur.fetchall()

    prophecies = []
    for row in rows:
        prophecy = dict(row)

        # Server-side display censorship
        prophecy['title'] = censor_text(prophecy['title'])
        prophecy['description'] = censor_text(prophecy['description'])
        prophecy['creator_username'] = censor_text(prophecy['creator_username'] or 'Anonymous')

        # Load comments for this prophecy
        cur.execute("""
            SELECT pc.id, pc.comment, pc.date_added, pc.user_id,
                   u.username AS commenter_username
            FROM prophecy_comments pc
            LEFT JOIN users u ON pc.user_id = u.id
            WHERE pc.prophecy_id = %s
            ORDER BY pc.date_added ASC
        """, (prophecy['id'],))
        comments = cur.fetchall()
        for c in comments:
            c['comment'] = censor_text(c['comment'])
            c['commenter_username'] = censor_text(c['commenter_username'] or 'Anonymous')
        prophecy['comments'] = comments

        prophecies.append(prophecy)

    return render_template('prophecies/prophecies.html',
                           prophecies=prophecies,
                           is_logged_in=is_logged_in)


# ----------------------------------------------------------------------
# Add Prophecy
# ----------------------------------------------------------------------
@prophecies_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_prophecy():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        visibility = request.form.get('visibility', 'private')

        if not title or not description:
            flash('Title and description are required.', 'error')
            return redirect(url_for('prophecies.add_prophecy'))

        if visibility not in ('public', 'private', 'personal'):
            flash('Invalid visibility setting.', 'error')
            return redirect(url_for('prophecies.add_prophecy'))

        if contains_censored_word(title) or contains_censored_word(description):
            flash('Content contains prohibited words.', 'error')
            return redirect(url_for('prophecies.add_prophecy'))

        db = get_db()
        cur = db.cursor()

        try:
            cur.execute("""
                INSERT INTO prophecies (title, description, visibility, user_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (title, description, visibility, session['user_id']))
            db.commit()

            prophecy_id = cur.lastrowid
            log_change(session['user_id'], 'create', prophecy_id, change_details='Added prophecy')
            flash('Prophecy submitted successfully.', 'success')
            return redirect(url_for('prophecies.list_prophecies'))
        except Exception as e:
            db.rollback()
            flash('Failed to submit prophecy.', 'error')
            print(f"Add prophecy error: {e}")

    return render_template('prophecies/add_prophecy.html')


# ----------------------------------------------------------------------
# Edit Prophecy
# ----------------------------------------------------------------------
@prophecies_bp.route('/edit/<int:prophecy_id>', methods=['GET', 'POST'])
@login_required
def edit_prophecy(prophecy_id):
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT * FROM prophecies WHERE id = %s", (prophecy_id,))
    prophecy = cur.fetchone()
    if not prophecy or (prophecy['user_id'] != session['user_id'] and session.get('user_role') not in REQUIRED_ROLES):
        flash('Not authorized to edit this prophecy.', 'error')
        return redirect(url_for('prophecies.list_prophecies'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        visibility = request.form.get('visibility', 'private')

        if not title or not description:
            flash('Title and description are required.', 'error')
            return redirect(url_for('prophecies.edit_prophecy', prophecy_id=prophecy_id))

        if visibility not in ('public', 'private', 'personal'):
            flash('Invalid visibility setting.', 'error')
            return redirect(url_for('prophecies.edit_prophecy', prophecy_id=prophecy_id))

        if contains_censored_word(title) or contains_censored_word(description):
            flash('Content contains prohibited words.', 'error')
            return redirect(url_for('prophecies.edit_prophecy', prophecy_id=prophecy_id))

        try:
            cur.execute("""
                UPDATE prophecies 
                SET title = %s, description = %s, visibility = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (title, description, visibility, prophecy_id))
            db.commit()

            log_change(session['user_id'], 'update', prophecy_id, change_details='Edited prophecy')
            flash('Prophecy updated successfully.', 'success')
            return redirect(url_for('prophecies.list_prophecies'))
        except Exception as e:
            db.rollback()
            flash('Failed to update prophecy.', 'error')
            print(f"Edit prophecy error: {e}")

    # Censored display for form repopulation
    prophecy['title'] = censor_text(prophecy['title'])
    prophecy['description'] = censor_text(prophecy['description'])

    return render_template('prophecies/edit_prophecy.html', prophecy=prophecy)


# ----------------------------------------------------------------------
# Delete Prophecy
# ----------------------------------------------------------------------
@prophecies_bp.route('/delete/<int:prophecy_id>', methods=['POST'])
@login_required
@role_required(REQUIRED_ROLES)
def delete_prophecy(prophecy_id):
    db = get_db()
    cur = db.cursor()

    try:
        cur.execute("DELETE FROM prophecies WHERE id = %s", (prophecy_id,))
        db.commit()
        if cur.rowcount:
            log_change(session['user_id'], 'delete', prophecy_id, change_details='Deleted prophecy')
            flash('Prophecy deleted.', 'success')
        else:
            flash('Prophecy not found.', 'error')
    except Exception as e:
        db.rollback()
        flash('Failed to delete prophecy.', 'error')
        print(f"Delete prophecy error: {e}")

    return redirect(url_for('prophecies.list_prophecies'))


# ----------------------------------------------------------------------
# Add Comment
# ----------------------------------------------------------------------
@prophecies_bp.route('/comment/add/<int:prophecy_id>', methods=['POST'])
@login_required
def add_comment(prophecy_id):
    comment_text = request.form.get('comment', '').strip()

    if not comment_text:
        flash('Comment cannot be empty.', 'error')
        return redirect(url_for('prophecies.list_prophecies') + f'#prophecy-{prophecy_id}')

    if contains_censored_word(comment_text):
        flash('Comment contains a prohibited word or phrase.', 'error')
        return redirect(url_for('prophecies.list_prophecies') + f'#prophecy-{prophecy_id}')

    db = get_db()
    cur = db.cursor()

    try:
        cur.execute("""
            INSERT INTO prophecy_comments (prophecy_id, user_id, comment, date_added)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        """, (prophecy_id, session['user_id'], comment_text))
        db.commit()

        log_change(session['user_id'], 'create', prophecy_id, change_details='Added prophecy comment')
        flash('Comment added.', 'success')
    except Exception as e:
        db.rollback()
        flash('Failed to add comment.', 'error')
        print(f"Add comment error: {e}")

    return redirect(url_for('prophecies.list_prophecies') + f'#prophecy-{prophecy_id}')


# ----------------------------------------------------------------------
# Edit Comment
# ----------------------------------------------------------------------
@prophecies_bp.route('/comment/edit/<int:comment_id>', methods=['POST'])
@login_required
def edit_comment(comment_id):
    comment_text = request.form.get('comment', '').strip()
    prophecy_id = request.form.get('prophecy_id')

    if not comment_text or not prophecy_id:
        flash('Invalid request.', 'error')
        return redirect(url_for('prophecies.list_prophecies'))

    if contains_censored_word(comment_text):
        flash('Comment contains a prohibited word or phrase.', 'error')
        return redirect(url_for('prophecies.list_prophecies'))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT user_id, prophecy_id FROM prophecy_comments WHERE id = %s", (comment_id,))
    comment = cur.fetchone()

    if not comment or (comment['user_id'] != session['user_id'] and session.get('user_role') not in REQUIRED_ROLES):
        flash('Not authorized to edit this comment.', 'error')
        return redirect(url_for('prophecies.list_prophecies'))

    try:
        cur.execute("UPDATE prophecy_comments SET comment = %s WHERE id = %s", (comment_text, comment_id))
        db.commit()

        log_change(session['user_id'], 'update', comment['prophecy_id'], change_details='Updated prophecy comment')
        flash('Comment updated.', 'success')
    except Exception as e:
        db.rollback()
        flash('Failed to update comment.', 'error')
        print(f"Edit comment error: {e}")

    return redirect(url_for('prophecies.list_prophecies') + f'#prophecy-{comment["prophecy_id"]}')


# ----------------------------------------------------------------------
# Delete Comment
# ----------------------------------------------------------------------
@prophecies_bp.route('/comment/delete/<int:comment_id>', methods=['POST'])
@login_required
def delete_comment(comment_id):
    prophecy_id = request.form.get('prophecy_id')

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT user_id, prophecy_id FROM prophecy_comments WHERE id = %s", (comment_id,))
    comment = cur.fetchone()

    if not comment or (comment['user_id'] != session['user_id'] and session.get('user_role') not in REQUIRED_ROLES):
        flash('Not authorized to delete this comment.', 'error')
        return redirect(url_for('prophecies.list_prophecies'))

    try:
        cur.execute("DELETE FROM prophecy_comments WHERE id = %s", (comment_id,))
        db.commit()

        log_change(session['user_id'], 'delete', comment['prophecy_id'], change_details='Deleted prophecy comment')
        flash('Comment deleted.', 'success')
    except Exception as e:
        db.rollback()
        flash('Failed to delete comment.', 'error')
        print(f"Delete comment error: {e}")

    return redirect(url_for('prophecies.list_prophecies') + f'#prophecy-{comment["prophecy_id"]}')