# myvinechurchonline/app/routes/prayers.py
# Full path: myvinechurchonline/app/routes/prayers.py
# File name: prayers.py
# Brief, detailed purpose: Blueprint for prayer requests and responses – PUBLIC FOCUS.
# • /prayers → listing:
#   - Guests: ONLY public prayers → renders public/prayers/prayers.html (simple grid, read-only).
#   - Logged-in: ALL visible prayers (public + private + own personal) → renders prayers/prayers_dashboard.html (richer private view with management).
# • /prayers/add → add new prayer request (guests submit public only, logged-in can choose visibility)
# • /prayers/<int:prayer_id> → GET: view detail + responses (public prayers only for detail view); POST: add response (guests allowed on public prayers)
# • /prayers/<int:prayer_id>/edit → edit (creator or Staff+)
# • /prayers/<int:prayer_id>/delete → delete (Admin/Owner only)
# Visibility strictly enforced in queries.
# All text censored server-side on display and before save.
# All significant actions audit-logged.
# FULL REBUILD: Separate listing templates – public grid for guests, full dashboard for logged-in.
# Standardized to pymysql/DictCursor (MariaDB compatible).

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app.utils.decorators import login_required, role_required
from app.utils.helpers import contains_censored_word, censor_text
from app.models.db import get_db
from app.models.log import log_change
import pymysql

prayers_bp = Blueprint('prayers', __name__, url_prefix='/prayers')

REQUIRED_ROLES = ['Staff', 'Admin', 'Owner']
ADMIN_ROLES = ['Admin', 'Owner']


# ----------------------------------------------------------------------
# Listing – /prayers
# ----------------------------------------------------------------------
@prayers_bp.route('/')
def prayers():
    is_logged_in = 'user_id' in session
    user_id = session.get('user_id')

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    if is_logged_in:
        # Logged-in: show public + private + own personal
        cur.execute("""
            SELECT p.id, p.title, p.description, p.date_posted, p.visibility,
                   COALESCE(CONCAT(u.first_name, ' ', u.last_name), p.contributor_name, 'Anonymous') AS creator_name
            FROM prayers p
            LEFT JOIN users u ON p.user_id = u.id
            WHERE p.visibility IN ('public', 'private')
               OR (p.visibility = 'personal' AND p.user_id = %s)
            ORDER BY p.date_posted DESC
        """, (user_id,))
        template = 'prayers/prayers_dashboard.html'
    else:
        # Guests: only public
        cur.execute("""
            SELECT p.id, p.title, p.description, p.date_posted,
                   COALESCE(p.contributor_name, 'Anonymous') AS creator_name
            FROM prayers p
            WHERE p.visibility = 'public'
            ORDER BY p.date_posted DESC
        """)
        template = 'public/prayers/prayers.html'

    prayers_list = cur.fetchall()

    # Server-side display censorship
    for p in prayers_list:
        p['title'] = censor_text(p['title'])
        p['description'] = censor_text(p['description'] or '')
        p['creator_name'] = censor_text(p['creator_name'])

    if user_id:
        log_change(user_id, 'view', change_details='Viewed prayers listing')

    return render_template(template, prayers=prayers_list, is_logged_in=is_logged_in)


# ----------------------------------------------------------------------
# Add New Prayer Request – /prayers/add
# ----------------------------------------------------------------------
@prayers_bp.route('/add', methods=['GET', 'POST'])
def add_prayer():
    is_logged_in = 'user_id' in session
    user_id = session.get('user_id')

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        visibility = request.form.get('visibility', 'public') if is_logged_in else 'public'
        contributor_name = request.form.get('contributor_name', '').strip() if not is_logged_in else None

        if not is_logged_in:
            contributor_name = contributor_name or 'Anonymous'

        check_text = title + ' ' + description
        if contributor_name:
            check_text += ' ' + contributor_name

        if contains_censored_word(check_text):
            flash('Prayer request contains a prohibited word or phrase.', 'error')
        elif not title or not description:
            flash('Title and description are required.', 'error')
        else:
            db = get_db()
            cur = db.cursor()
            ip = request.remote_addr if not is_logged_in else None
            cur.execute("""
                INSERT INTO prayers
                (title, description, visibility, user_id, contributor_name, ip_address, date_posted)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, (title, description, visibility, user_id, contributor_name, ip))
            prayer_id = cur.lastrowid
            db.commit()

            log_change(user_id or 0, 'create_prayer', target_id=prayer_id,
                       change_details=f"Created prayer '{title}' ({visibility})")
            flash('Prayer request submitted successfully!', 'success')
            return redirect(url_for('prayers.prayers'))

        # On error – repopulate (use same template for public/guest add form)
        return render_template('public/prayers/add_prayer.html',
                               title=title, description=description,
                               visibility=visibility, contributor_name=contributor_name or '')

    return render_template('public/prayers/add_prayer.html', is_logged_in=is_logged_in)


# ----------------------------------------------------------------------
# View Prayer + Add Response – /prayers/<int:prayer_id> (public prayers only)
# ----------------------------------------------------------------------
@prayers_bp.route('/<int:prayer_id>', methods=['GET', 'POST'])
def view_prayer(prayer_id):
    is_logged_in = 'user_id' in session
    user_id = session.get('user_id')

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT p.*, 
               COALESCE(CONCAT(u.first_name, ' ', u.last_name), p.contributor_name, 'Anonymous') AS creator_name
        FROM prayers p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.id = %s AND p.visibility = 'public'
    """, (prayer_id,))
    prayer = cur.fetchone()

    if not prayer:
        flash('Prayer request not found or not public.', 'error')
        return redirect(url_for('prayers.prayers'))

    # Display censorship
    prayer['title'] = censor_text(prayer['title'])
    prayer['description'] = censor_text(prayer['description'] or '')
    prayer['creator_name'] = censor_text(prayer['creator_name'])

    # Fetch responses
    cur.execute("""
        SELECT pa.*, 
               COALESCE(CONCAT(u.first_name, ' ', u.last_name), pa.contributor_name, 'Anonymous') AS responder_name
        FROM prayers_added pa
        LEFT JOIN users u ON pa.user_id = u.id
        WHERE pa.prayer_request_id = %s
        ORDER BY pa.date_added ASC
    """, (prayer_id,))
    responses = cur.fetchall()

    for r in responses:
        r['prayer'] = censor_text(r['prayer'] or '')
        r['responder_name'] = censor_text(r['responder_name'])

    # Handle POST – add response
    if request.method == 'POST':
        prayer_text = request.form.get('prayer', '').strip()
        contributor_name = request.form.get('contributor_name', '').strip() if not is_logged_in else None
        contributor_name = contributor_name or 'Anonymous'

        check_text = prayer_text + ' ' + contributor_name if contributor_name != 'Anonymous' else prayer_text

        if not prayer_text:
            flash('Response text is required.', 'error')
        elif contains_censored_word(check_text):
            flash('Response contains a prohibited word or phrase.', 'error')
        else:
            cur = db.cursor()
            ip = request.remote_addr if not is_logged_in else None
            cur.execute("""
                INSERT INTO prayers_added 
                (prayer_request_id, prayer, user_id, contributor_name, ip_address, date_added)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, (prayer_id, prayer_text, user_id, contributor_name, ip))
            db.commit()

            log_change(user_id or 0, 'add_response', target_id=prayer_id,
                       change_details='Added response to public prayer request')
            flash('Your prayer response has been added.', 'success')

        return redirect(url_for('prayers.view_prayer', prayer_id=prayer_id))

    if user_id:
        log_change(user_id, 'view', change_details=f"Viewed public prayer request {prayer_id}")

    return render_template('public/prayers/view_prayer.html',
                           prayer=prayer,
                           responses=responses,
                           is_logged_in=is_logged_in)


# ----------------------------------------------------------------------
# Edit Prayer Request – /prayers/<int:prayer_id>/edit
# ----------------------------------------------------------------------
@prayers_bp.route('/<int:prayer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_prayer(prayer_id):
    user_id = session['user_id']
    role = session.get('user_role')
    is_staff_plus = role in REQUIRED_ROLES

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT * FROM prayers WHERE id = %s", (prayer_id,))
    prayer = cur.fetchone()
    if not prayer:
        flash('Prayer request not found.', 'error')
        return redirect(url_for('prayers.prayers'))

    if prayer['user_id'] != user_id and not is_staff_plus:
        flash('You are not authorized to edit this prayer request.', 'error')
        return redirect(url_for('prayers.prayers'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        visibility = request.form.get('visibility', prayer['visibility'])

        if contains_censored_word(title + ' ' + description):
            flash('Prayer request contains a prohibited word or phrase.', 'error')
        elif not title or not description:
            flash('Title and description are required.', 'error')
        else:
            cur = db.cursor()
            cur.execute("""
                UPDATE prayers
                SET title = %s, description = %s, visibility = %s
                WHERE id = %s
            """, (title, description, visibility, prayer_id))
            db.commit()

            log_change(user_id, 'update_prayer', target_id=prayer_id,
                       change_details=f"Updated prayer '{title}'")
            flash('Prayer request updated successfully.', 'success')
            return redirect(url_for('prayers.prayers'))

    return render_template('prayers/edit_prayer.html', prayer=prayer)


# ----------------------------------------------------------------------
# Delete Prayer Request – /prayers/<int:prayer_id>/delete
# ----------------------------------------------------------------------
@prayers_bp.route('/<int:prayer_id>/delete', methods=['POST'])
@login_required
@role_required(ADMIN_ROLES)
def delete_prayer(prayer_id):
    user_id = session['user_id']

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT title FROM prayers WHERE id = %s", (prayer_id,))
    row = cur.fetchone()
    if not row:
        flash('Prayer request not found.', 'error')
        return redirect(url_for('prayers.prayers'))

    title = row['title']

    try:
        cur = db.cursor()
        cur.execute("DELETE FROM prayers_added WHERE prayer_request_id = %s", (prayer_id,))
        cur.execute("DELETE FROM prayers WHERE id = %s", (prayer_id,))
        db.commit()

        log_change(user_id, 'delete_prayer', target_id=prayer_id,
                   change_details=f"Deleted prayer '{title}'")
        flash('Prayer request deleted successfully.', 'success')
    except Exception as e:
        db.rollback()
        flash('Failed to delete prayer request.', 'error')

    return redirect(url_for('prayers.prayers'))