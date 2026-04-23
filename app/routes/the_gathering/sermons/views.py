# MYVINECHURCH.ONLINE/app/routes/the_gathering/sermons/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/sermons/views.py
# File name: views.py
# Brief, detailed purpose: All sermon routes for the Gathering Place Manager.
# • Dedicated sub-blueprint routes: listing, create/edit, view, delete, comment moderation.
# • Uses sermons/forms.py, queries.py, and utils.py for clean separation.
# • Protected by the exact same session + DB role check pattern used everywhere else.
# • All url_for calls use the correct nested blueprint: 'the_gathering.sermons.*'
# • 100% rebuilt entire file — only this script was touched.

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import sermons_bp
from .queries import get_all_sermons, get_sermon, get_sermon_comments
from .forms import validate_sermon_form, validate_comment_moderation, validate_search_filter
from .utils import censor_for_manager

from app.models.db import get_db
from app.utils.helpers import censor_text


# ----------------------------------------------------------------------
# Access Control (exact same secure pattern as events, prayers, dreams, prophecies, announcements)
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
# Sermons Listing / Dashboard
# ----------------------------------------------------------------------
@sermons_bp.route('/')
@gathering_place_required
def sermons_dashboard():
    """Main sermons management page with search + filters."""
    clean = validate_search_filter(request.args)
    filter_type = clean.get('filter', 'all')
    search = clean.get('search')

    sermons = get_all_sermons(filter_type=filter_type, search_query=search)
    sermons = censor_for_manager(sermons)

    return render_template('the_gathering/sermons/sermons_dashboard.html',
                           sermons=sermons,
                           filter_type=filter_type,
                           search=search or '',
                           page_title="Sermons Manager")


# ----------------------------------------------------------------------
# Create / Edit Sermon
# ----------------------------------------------------------------------
@sermons_bp.route('/new', methods=['GET', 'POST'])
@sermons_bp.route('/<int:sermon_id>/edit', methods=['GET', 'POST'])
@gathering_place_required
def edit_sermon(sermon_id=None):
    """Create new or edit existing sermon."""
    if request.method == 'POST':
        clean = validate_sermon_form(request.form)
        if not clean:
            return redirect(url_for('the_gathering.sermons.edit_sermon', sermon_id=sermon_id))

        db = get_db()
        cur = db.cursor()

        try:
            if sermon_id:  # UPDATE
                cur.execute("""
                    UPDATE sermons 
                    SET title=%s, scripture=%s, notes=%s, sermon_text=%s, visibility=%s, 
                        updated_by=%s, updated_at=NOW()
                    WHERE id = %s
                """, (clean['title'], clean['scripture'], clean['notes'],
                      clean['sermon_text'], clean['visibility'],
                      session['user_id'], sermon_id))
                flash('Sermon updated successfully.', 'success')
            else:  # INSERT
                cur.execute("""
                    INSERT INTO sermons 
                    (title, scripture, notes, sermon_text, visibility, created_by, updated_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (clean['title'], clean['scripture'], clean['notes'],
                      clean['sermon_text'], clean['visibility'],
                      session['user_id'], session['user_id']))
                flash('Sermon created successfully.', 'success')
            db.commit()
        except Exception:
            db.rollback()
            flash('Failed to save sermon.', 'error')

        return redirect(url_for('the_gathering.sermons.sermons_dashboard'))

    # GET - load existing or blank form
    sermon = get_sermon(sermon_id) if sermon_id else None
    return render_template('the_gathering/sermons/edit.html',
                           sermon=sermon,
                           page_title="Edit Sermon" if sermon_id else "Create New Sermon")


# ----------------------------------------------------------------------
# View Single Sermon
# ----------------------------------------------------------------------
@sermons_bp.route('/<int:sermon_id>/view')
@gathering_place_required
def view_sermon(sermon_id):
    """Read-only view of a single sermon."""
    sermon = get_sermon(sermon_id)
    if not sermon:
        abort(404)

    return render_template('the_gathering/sermons/view.html',
                           sermon=sermon,
                           page_title="View Sermon")


# ----------------------------------------------------------------------
# Delete Sermon
# ----------------------------------------------------------------------
@sermons_bp.route('/<int:sermon_id>/delete', methods=['POST'])
@gathering_place_required
def delete_sermon(sermon_id):
    """Delete sermon (with confirmation in template)."""
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM sermons WHERE id = %s", (sermon_id,))
        db.commit()
        flash('Sermon deleted permanently.', 'success')
    except Exception:
        flash('Failed to delete sermon.', 'error')
    return redirect(url_for('the_gathering.sermons.sermons_dashboard'))


# ----------------------------------------------------------------------
# Comment Moderation for a Sermon
# ----------------------------------------------------------------------
@sermons_bp.route('/<int:sermon_id>/comments.html', methods=['GET', 'POST'])
@gathering_place_required
def sermon_comments(sermon_id):
    """Moderate comments.html on a specific sermon."""
    sermon = get_sermon(sermon_id)
    if not sermon:
        abort(404)

    comments = get_sermon_comments(sermon_id)

    if request.method == 'POST':
        clean = validate_comment_moderation(request.form)
        if clean:
            db = get_db()
            cur = db.cursor()
            try:
                if clean['action'] == 'delete':
                    cur.execute("DELETE FROM sermon_comments WHERE id = %s", (clean['comment_id'],))
                elif clean['action'] == 'approve':
                    cur.execute("UPDATE sermon_comments SET moderated=1, moderated_by=%s, moderated_at=NOW() WHERE id = %s",
                                (session['user_id'], clean['comment_id']))
                db.commit()
                flash('Comment updated.', 'success')
            except Exception:
                flash('Failed to moderate comment.', 'error')
            return redirect(url_for('the_gathering.sermons.sermon_comments', sermon_id=sermon_id))

    return render_template('the_gathering/sermons/comments.html.html',
                           sermon=sermon,
                           comments=comments,
                           page_title="Moderate Comments")


print("✅ MYVINECHURCH.ONLINE the_gathering/sermons/views.py loaded successfully (full dedicated routes for sermons ready)")