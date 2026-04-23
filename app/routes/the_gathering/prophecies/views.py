# MYVINECHURCH.ONLINE/app/routes/the_gathering/prophecies/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/prophecies/views.py
# File name: views.py
# Brief, detailed purpose: All prophecy routes for the Gathering Place Manager.
# • Dedicated sub-blueprint routes: listing, create/edit, view, delete, comment moderation.
# • Uses prophecies/forms.py, queries.py, and utils.py for clean separation.
# • Protected by the exact same session + DB role check pattern used everywhere else.
# • All url_for calls use the correct nested blueprint: 'the_gathering.prophecies.*'
# • 100% rebuilt entire file — only this script was touched.

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import prophecies_bp
from .queries import get_all_prophecies, get_prophecy, get_prophecy_comments
from .forms import validate_prophecy_form, validate_comment_moderation, validate_search_filter
from .utils import censor_for_manager

from app.models.db import get_db
from app.utils.helpers import censor_text


# ----------------------------------------------------------------------
# Access Control (exact same secure pattern as events, dreams, prayers, announcements)
# ----------------------------------------------------------------------
def gathering_place_required(f):
    """Decorator: only Staff/Admin/Owner or Gathering Place Managers can access."""
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access the Gathering Place Manager.', 'error')
            return redirect(url_for('auth.login'))

        try:
            db = get_db()
            cur = db.cursor(pymysql.cursors.DictCursor)
            cur.execute("SELECT role FROM users WHERE id = %s", (session['user_id'],))
            user = cur.fetchone()
            cur.close()
        except Exception:
            flash('Unable to verify permissions.', 'error')
            return redirect(url_for('the_gathering.dashboard'))

        if not user:
            flash('User not found.', 'error')
            return redirect(url_for('the_gathering.dashboard'))

        role = (user.get('role') or '').lower().strip()
        allowed = ('staff', 'admin', 'owner', 'gathering place manager', 'gathering manager')
        if role in allowed or 'manager' in role or 'admin' in role:
            return f(*args, **kwargs)

        flash('You do not have permission to access this section.', 'error')
        return redirect(url_for('the_gathering.dashboard'))
    return decorated_function


# ----------------------------------------------------------------------
# Prophecies Listing / Dashboard
# ----------------------------------------------------------------------
@prophecies_bp.route('/')
@gathering_place_required
def prophecies_dashboard():
    """Main prophecies management page with search + filters."""
    clean = validate_search_filter(request.args)
    filter_type = clean.get('filter', 'all')
    search = clean.get('search')

    prophecies = get_all_prophecies(filter_type=filter_type, search_query=search)
    prophecies = censor_for_manager(prophecies)

    return render_template('the_gathering/prophecies/prophecies_dashboard.html',
                           prophecies=prophecies,
                           filter_type=filter_type,
                           search=search or '',
                           page_title="Prophecies Manager")


# ----------------------------------------------------------------------
# Create / Edit Prophecy
# ----------------------------------------------------------------------
@prophecies_bp.route('/new', methods=['GET', 'POST'])
@prophecies_bp.route('/<int:prophecy_id>/edit', methods=['GET', 'POST'])
@gathering_place_required
def edit_prophecy(prophecy_id=None):
    """Create new or edit existing prophecy."""
    if request.method == 'POST':
        clean = validate_prophecy_form(request.form)
        if not clean:
            return redirect(url_for('the_gathering.prophecies.edit_prophecy', prophecy_id=prophecy_id))

        db = get_db()
        cur = db.cursor()

        try:
            if prophecy_id:  # UPDATE
                cur.execute("""
                    UPDATE prophecies 
                    SET title=%s, prophecy_text=%s, visibility=%s, 
                        updated_by=%s, updated_at=NOW()
                    WHERE id = %s
                """, (clean['title'], clean['prophecy_text'], clean['visibility'],
                      session['user_id'], prophecy_id))
                flash('Prophecy updated successfully.', 'success')
            else:  # INSERT
                cur.execute("""
                    INSERT INTO prophecies 
                    (title, prophecy_text, visibility, created_by, updated_by)
                    VALUES (%s, %s, %s, %s, %s)
                """, (clean['title'], clean['prophecy_text'], clean['visibility'],
                      session['user_id'], session['user_id']))
                flash('Prophecy created successfully.', 'success')
            db.commit()
        except Exception:
            db.rollback()
            flash('Failed to save prophecy.', 'error')

        return redirect(url_for('the_gathering.prophecies.prophecies_dashboard'))

    # GET - load existing or blank form
    prophecy = get_prophecy(prophecy_id) if prophecy_id else None
    return render_template('the_gathering/prophecies/edit.html',
                           prophecy=prophecy,
                           page_title="Edit Prophecy" if prophecy_id else "Create New Prophecy")


# ----------------------------------------------------------------------
# View Single Prophecy
# ----------------------------------------------------------------------
@prophecies_bp.route('/<int:prophecy_id>/view')
@gathering_place_required
def view_prophecy(prophecy_id):
    """Read-only view of a single prophecy."""
    prophecy = get_prophecy(prophecy_id)
    if not prophecy:
        abort(404)

    return render_template('the_gathering/prophecies/view.html',
                           prophecy=prophecy,
                           page_title="View Prophecy")


# ----------------------------------------------------------------------
# Delete Prophecy
# ----------------------------------------------------------------------
@prophecies_bp.route('/<int:prophecy_id>/delete', methods=['POST'])
@gathering_place_required
def delete_prophecy(prophecy_id):
    """Delete prophecy (with confirmation in template)."""
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM prophecies WHERE id = %s", (prophecy_id,))
        db.commit()
        flash('Prophecy deleted permanently.', 'success')
    except Exception:
        flash('Failed to delete prophecy.', 'error')
    return redirect(url_for('the_gathering.prophecies.prophecies_dashboard'))


# ----------------------------------------------------------------------
# Comment Moderation for a Prophecy
# ----------------------------------------------------------------------
@prophecies_bp.route('/<int:prophecy_id>/comments.html', methods=['GET', 'POST'])
@gathering_place_required
def prophecy_comments(prophecy_id):
    """Moderate comments.html on a specific prophecy."""
    prophecy = get_prophecy(prophecy_id)
    if not prophecy:
        abort(404)

    comments = get_prophecy_comments(prophecy_id)

    if request.method == 'POST':
        clean = validate_comment_moderation(request.form)
        if clean:
            db = get_db()
            cur = db.cursor()
            try:
                if clean['action'] == 'delete':
                    cur.execute("DELETE FROM prophecy_comments WHERE id = %s", (clean['comment_id'],))
                elif clean['action'] == 'approve':
                    cur.execute("UPDATE prophecy_comments SET moderated=1, moderated_by=%s, moderated_at=NOW() WHERE id = %s",
                                (session['user_id'], clean['comment_id']))
                db.commit()
                flash('Comment updated.', 'success')
            except Exception:
                flash('Failed to moderate comment.', 'error')
            return redirect(url_for('the_gathering.prophecies.prophecy_comments', prophecy_id=prophecy_id))

    return render_template('the_gathering/prophecies/comments.html.html',
                           prophecy=prophecy,
                           comments=comments,
                           page_title="Moderate Comments")


print("✅ MYVINECHURCH.ONLINE the_gathering/prophecies/views.py loaded successfully (full dedicated routes for prophecies ready)")