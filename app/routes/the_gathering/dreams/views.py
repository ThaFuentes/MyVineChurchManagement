# MYVINECHURCH.ONLINE/app/routes/the_gathering/dreams/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/dreams/views.py
# File name: views.py
# Brief, detailed purpose: All dream/vision routes for the Gathering Place Manager.
# • Dedicated sub-blueprint routes: listing, create/edit, view, delete, comment moderation.
# • Uses dreams/forms.py, queries.py, and utils.py for clean separation.
# • Protected by the exact same session + DB role check pattern used everywhere else.
# • All url_for calls use the correct nested blueprint: 'the_gathering.dreams.*'
# • 100% rebuilt entire file — only this script was touched.

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import dreams_bp
from .queries import get_all_dreams, get_dream, get_dream_comments
from .forms import validate_dream_form, validate_comment_moderation, validate_search_filter
from .utils import censor_for_manager

from app.models.db import get_db
from app.utils.helpers import censor_text


# ----------------------------------------------------------------------
# Access Control (exact same secure pattern as announcements and events)
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
# Dreams Listing / Dashboard
# ----------------------------------------------------------------------
@dreams_bp.route('/')
@gathering_place_required
def dreams_dashboard():
    """Main dreams management page with search + filters."""
    clean = validate_search_filter(request.args)
    filter_type = clean.get('filter', 'all')
    search = clean.get('search')

    dreams = get_all_dreams(filter_type=filter_type, search_query=search)
    dreams = censor_for_manager(dreams)

    return render_template('the_gathering/dreams/dreams_dashboard.html',
                           dreams=dreams,
                           filter_type=filter_type,
                           search=search or '',
                           page_title="Dreams & Visions Manager")


# ----------------------------------------------------------------------
# Create / Edit Dream
# ----------------------------------------------------------------------
@dreams_bp.route('/<int:dream_id>/edit', methods=['GET', 'POST'])
@dreams_bp.route('/new', methods=['GET', 'POST'], defaults={'dream_id': None})
@gathering_place_required
def edit_dream(dream_id):
    """Create new or edit existing dream/vision."""
    if request.method == 'POST':
        clean = validate_dream_form(request.form)
        if not clean:
            return redirect(url_for('the_gathering.dreams.edit_dream', dream_id=dream_id))

        db = get_db()
        cur = db.cursor()

        try:
            if dream_id:  # UPDATE
                cur.execute("""
                    UPDATE dreams 
                    SET title=%s, dream_text=%s, visibility=%s, 
                        updated_by=%s, updated_at=NOW()
                    WHERE id = %s
                """, (clean['title'], clean['dream_text'], clean['visibility'],
                      session['user_id'], dream_id))
                flash('Dream/Vision updated successfully.', 'success')
            else:  # INSERT
                cur.execute("""
                    INSERT INTO dreams 
                    (title, dream_text, visibility, created_by, updated_by)
                    VALUES (%s, %s, %s, %s, %s)
                """, (clean['title'], clean['dream_text'], clean['visibility'],
                      session['user_id'], session['user_id']))
                flash('Dream/Vision created successfully.', 'success')
            db.commit()
        except Exception as e:
            db.rollback()
            flash('Failed to save dream/vision.', 'error')

        return redirect(url_for('the_gathering.dreams.dreams_dashboard'))

    # GET - load existing or blank form
    dream = get_dream(dream_id) if dream_id else None
    return render_template('the_gathering/dreams/edit.html',
                           dream=dream,
                           page_title="Edit Dream/Vision" if dream_id else "New Dream/Vision")


# ----------------------------------------------------------------------
# View Single Dream
# ----------------------------------------------------------------------
@dreams_bp.route('/<int:dream_id>/view')
@gathering_place_required
def view_dream(dream_id):
    """Read-only view of a single dream/vision."""
    dream = get_dream(dream_id)
    if not dream:
        abort(404)

    return render_template('the_gathering/dreams/view.html',
                           dream=dream,
                           page_title="View Dream/Vision")


# ----------------------------------------------------------------------
# Delete Dream
# ----------------------------------------------------------------------
@dreams_bp.route('/<int:dream_id>/delete', methods=['POST'])
@gathering_place_required
def delete_dream(dream_id):
    """Delete dream/vision (with confirmation in template)."""
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM dreams WHERE id = %s", (dream_id,))
        db.commit()
        flash('Dream/Vision deleted permanently.', 'success')
    except Exception:
        flash('Failed to delete dream/vision.', 'error')
    return redirect(url_for('the_gathering.dreams.dreams_dashboard'))


# ----------------------------------------------------------------------
# Comment Moderation for Dreams
# ----------------------------------------------------------------------
@dreams_bp.route('/<int:dream_id>/comments.html', methods=['GET', 'POST'])
@gathering_place_required
def dream_comments(dream_id):
    """Moderate comments.html on a specific dream/vision."""
    dream = get_dream(dream_id)
    if not dream:
        abort(404)

    comments = get_dream_comments(dream_id)

    if request.method == 'POST':
        clean = validate_comment_moderation(request.form)
        if clean:
            db = get_db()
            cur = db.cursor()
            try:
                if clean['action'] == 'delete':
                    cur.execute("DELETE FROM dream_comments WHERE id = %s", (clean['comment_id'],))
                elif clean['action'] == 'approve':
                    cur.execute("UPDATE dream_comments SET moderated=1, moderated_by=%s, moderated_at=NOW() WHERE id = %s",
                                (session['user_id'], clean['comment_id']))
                db.commit()
                flash('Comment updated.', 'success')
            except Exception:
                flash('Failed to moderate comment.', 'error')
            return redirect(url_for('the_gathering.dreams.dream_comments', dream_id=dream_id))

    return render_template('the_gathering/dreams/comments.html.html',
                           dream=dream,
                           comments=comments,
                           page_title="Moderate Comments")


print("✅ MYVINECHURCH.ONLINE the_gathering/dreams/views.py loaded successfully (full dedicated routes for dreams ready)")