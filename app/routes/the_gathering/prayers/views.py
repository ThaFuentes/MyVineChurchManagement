# MYVINECHURCH.ONLINE/app/routes/the_gathering/prayers/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/prayers/views.py
# File name: views.py
# Brief, detailed purpose: All prayer routes for the Gathering Place Manager.
# • Dedicated sub-blueprint routes: listing, create/edit, view, delete, comment moderation.
# • Uses prayers/forms.py, queries.py, and utils.py for clean separation.
# • Protected by the exact same session + DB role check pattern used everywhere else.
# • All url_for calls use the correct nested blueprint: 'the_gathering.prayers.*'
# • 100% rebuilt entire file — only this script was touched.

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import prayers_bp
from .queries import get_all_prayers, get_prayer, get_prayer_comments
from .forms import validate_prayer_form, validate_comment_moderation, validate_search_filter
from .utils import censor_for_manager

from app.models.db import get_db
from app.utils.helpers import censor_text


# ----------------------------------------------------------------------
# Access Control (exact same secure pattern as events, dreams, announcements)
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
# Prayers Listing / Dashboard
# ----------------------------------------------------------------------
@prayers_bp.route('/')
@gathering_place_required
def prayers_dashboard():
    """Main prayers management page with search + filters."""
    clean = validate_search_filter(request.args)
    filter_type = clean.get('filter', 'all')
    search = clean.get('search')

    prayers = get_all_prayers(filter_type=filter_type, search_query=search)
    prayers = censor_for_manager(prayers)

    return render_template('the_gathering/prayers/prayers_dashboard.html',
                           prayers=prayers,
                           filter_type=filter_type,
                           search=search or '',
                           page_title="Prayers Manager")


# ----------------------------------------------------------------------
# Create / Edit Prayer
# ----------------------------------------------------------------------
@prayers_bp.route('/new', methods=['GET', 'POST'])
@prayers_bp.route('/<int:prayer_id>/edit', methods=['GET', 'POST'])
@gathering_place_required
def edit_prayer(prayer_id=None):
    """Create new or edit existing prayer."""
    if request.method == 'POST':
        clean = validate_prayer_form(request.form)
        if not clean:
            return redirect(url_for('the_gathering.prayers.edit_prayer', prayer_id=prayer_id))

        db = get_db()
        cur = db.cursor()

        try:
            if prayer_id:  # UPDATE
                cur.execute("""
                    UPDATE prayers 
                    SET title=%s, prayer_text=%s, visibility=%s, 
                        updated_by=%s, updated_at=NOW()
                    WHERE id = %s
                """, (clean['title'], clean['prayer_text'], clean['visibility'],
                      session['user_id'], prayer_id))
                flash('Prayer updated successfully.', 'success')
            else:  # INSERT
                cur.execute("""
                    INSERT INTO prayers 
                    (title, prayer_text, visibility, created_by, updated_by)
                    VALUES (%s, %s, %s, %s, %s)
                """, (clean['title'], clean['prayer_text'], clean['visibility'],
                      session['user_id'], session['user_id']))
                flash('Prayer created successfully.', 'success')
            db.commit()
        except Exception:
            db.rollback()
            flash('Failed to save prayer.', 'error')

        return redirect(url_for('the_gathering.prayers.prayers_dashboard'))

    # GET - load existing or blank form
    prayer = get_prayer(prayer_id) if prayer_id else None
    return render_template('the_gathering/prayers/edit.html',
                           prayer=prayer,
                           page_title="Edit Prayer" if prayer_id else "Create New Prayer")


# ----------------------------------------------------------------------
# View Single Prayer
# ----------------------------------------------------------------------
@prayers_bp.route('/<int:prayer_id>/view')
@gathering_place_required
def view_prayer(prayer_id):
    """Read-only view of a single prayer."""
    prayer = get_prayer(prayer_id)
    if not prayer:
        abort(404)

    return render_template('the_gathering/prayers/view.html',
                           prayer=prayer,
                           page_title="View Prayer")


# ----------------------------------------------------------------------
# Delete Prayer
# ----------------------------------------------------------------------
@prayers_bp.route('/<int:prayer_id>/delete', methods=['POST'])
@gathering_place_required
def delete_prayer(prayer_id):
    """Delete prayer (with confirmation in template)."""
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM prayers WHERE id = %s", (prayer_id,))
        db.commit()
        flash('Prayer deleted permanently.', 'success')
    except Exception:
        flash('Failed to delete prayer.', 'error')
    return redirect(url_for('the_gathering.prayers.prayers_dashboard'))


# ----------------------------------------------------------------------
# Comment Moderation for a Prayer
# ----------------------------------------------------------------------
@prayers_bp.route('/<int:prayer_id>/comments.html', methods=['GET', 'POST'])
@gathering_place_required
def prayer_comments(prayer_id):
    """Moderate comments.html on a specific prayer."""
    prayer = get_prayer(prayer_id)
    if not prayer:
        abort(404)

    comments = get_prayer_comments(prayer_id)

    if request.method == 'POST':
        clean = validate_comment_moderation(request.form)
        if clean:
            db = get_db()
            cur = db.cursor()
            try:
                if clean['action'] == 'delete':
                    cur.execute("DELETE FROM prayer_comments WHERE id = %s", (clean['comment_id'],))
                elif clean['action'] == 'approve':
                    cur.execute("UPDATE prayer_comments SET moderated=1, moderated_by=%s, moderated_at=NOW() WHERE id = %s",
                                (session['user_id'], clean['comment_id']))
                db.commit()
                flash('Comment updated.', 'success')
            except Exception:
                flash('Failed to moderate comment.', 'error')
            return redirect(url_for('the_gathering.prayers.prayer_comments', prayer_id=prayer_id))

    return render_template('the_gathering/prayers/comments.html.html',
                           prayer=prayer,
                           comments=comments,
                           page_title="Moderate Comments")


print("✅ MYVINECHURCH.ONLINE the_gathering/prayers/views.py loaded successfully (full dedicated routes for prayers ready)")