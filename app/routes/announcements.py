# myvinechurchonline/app/routes/announcements.py
# Full path: myvinechurchonline/app/routes/announcements.py
# File name: announcements.py
# Brief, detailed purpose: Fully rebuilt Announcements blueprint – 100% MariaDB-compatible (pymysql).
#   • Single route /announcements → different template based on login status:
#       - Guests (not logged in): public/announcements/announcements.html (simple public list, only public + active).
#       - Logged-in: announcements/announcements_dashboard.html (full private dashboard with comments, management, etc.).
#   • Guests see ONLY public + active announcements, full content, no comments/management.
#   • Logged-in members: all announcements + comment ability (if enabled).
#   • Create/edit/delete/email: Staff/Admin/Owner only.
#   • All actions audit-logged + censored word checks.
#   • Uses pymysql %s placeholders + DictCursor for dict-like rows.
#   • Permissions: can_manage / is_logged_in passed to templates.
#   • INSERTs explicitly list columns to match schema (ignores optional/extra columns safely).
#   • All log_change calls provide 5 arguments consistently (user_id, action, item_id, item_title, details).

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
import pymysql

from app.utils.decorators import login_required, role_required
from app.utils.helpers import contains_censored_word
from app.models.db import get_db
from app.models.log import log_change
from app.utils.emailer import send_email

announcements_bp = Blueprint('announcements', __name__, url_prefix='/announcements')

REQUIRED_ROLES = ['Staff', 'Admin', 'Owner']


# ----------------------------------------------------------------------
# Main Route – /announcements (single URL, conditional template)
# ----------------------------------------------------------------------
@announcements_bp.route('/')
def announcements():
    is_logged_in = 'user_id' in session
    can_manage = is_logged_in and session.get('user_role') in REQUIRED_ROLES

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Fetch announcements (different query based on login status)
    if is_logged_in:
        cur.execute("""
            SELECT a.id, a.title, a.content, a.created_at, a.visibility,
                   a.is_active, a.comments_enabled, a.created_by,
                   COALESCE(u.username, 'Unknown') AS creator_name
            FROM announcements a
            LEFT JOIN users u ON a.created_by = u.id
            ORDER BY a.created_at DESC
        """)
    else:
        cur.execute("""
            SELECT a.id, a.title, a.content, a.created_at,
                   a.visibility, a.is_active, a.comments_enabled,
                   COALESCE(u.username, 'Unknown') AS creator_name
            FROM announcements a
            LEFT JOIN users u ON a.created_by = u.id
            WHERE a.visibility = 'public' AND a.is_active = 1
            ORDER BY a.created_at DESC
        """)

    announcements_list = cur.fetchall()

    # PUBLIC VIEW (guests) – simple formatted list, no comments/management
    if not is_logged_in:
        public_announcements = []
        for ann in announcements_list:
            a = dict(ann)
            created = ann['created_at']
            a['datetime'] = f"{created.strftime('%B')} {created.day}, {created.year}"
            a['posted_by'] = ann['creator_name']
            public_announcements.append(a)

        return render_template(
            'public/announcements/announcements.html',
            announcements=public_announcements
        )

    # PRIVATE VIEW (logged-in) – full dashboard with comments, counts, management
    # Attach comment count + comments
    for ann in announcements_list:
        cur.execute("SELECT COUNT(*) AS cnt FROM announcement_comments WHERE announcement_id = %s", (ann['id'],))
        ann['comment_count'] = cur.fetchone()['cnt'] or 0

        cur.execute("""
            SELECT c.comment, c.date_added,
                   COALESCE(u.username, 'Anonymous') AS commenter_name
            FROM announcement_comments c
            LEFT JOIN users u ON c.user_id = u.id
            WHERE c.announcement_id = %s
            ORDER BY c.date_added ASC
        """, (ann['id'],))
        ann['comments'] = cur.fetchall()

    # Summary counts (only needed for private dashboard)
    cur.execute("SELECT COUNT(*) AS cnt FROM announcements")
    total_count = cur.fetchone()['cnt'] or 0

    cur.execute("SELECT COUNT(*) AS cnt FROM announcements WHERE is_active = 1")
    active_count = cur.fetchone()['cnt'] or 0

    cur.execute("SELECT COUNT(*) AS cnt FROM announcements WHERE visibility = 'public'")
    public_count = cur.fetchone()['cnt'] or 0

    # Members for email modal (only for authorized roles)
    members = []
    if can_manage:
        cur.execute("""
            SELECT id, username AS name, email
            FROM users
            WHERE email IS NOT NULL AND email != ''
            ORDER BY username
        """)
        members = cur.fetchall()

    return render_template(
        'announcements/announcements_dashboard.html',
        announcements_list=announcements_list,
        total_count=total_count,
        active_count=active_count,
        public_count=public_count,
        members=members,
        is_logged_in=is_logged_in,
        can_manage=can_manage
    )


# ----------------------------------------------------------------------
# Create Announcement
# ----------------------------------------------------------------------
@announcements_bp.route('/create', methods=['GET', 'POST'])
@login_required
@role_required(REQUIRED_ROLES)
def create_announcement():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        visibility = request.form.get('visibility', 'private')
        is_active = 1 if 'is_active' in request.form else 0
        comments_enabled = 1 if 'comments_enabled' in request.form else 0

        if not title or not content:
            flash('Title and content are required.', 'error')
            return render_template('announcements/create_announcement.html', form_data=request.form)

        if contains_censored_word(title + ' ' + content):
            flash('Announcement contains a prohibited word or phrase.', 'error')
            return render_template('announcements/create_announcement.html', form_data=request.form)

        db = get_db()
        cur = db.cursor()
        try:
            cur.execute("""
                INSERT INTO announcements
                (title, content, visibility, is_active, comments_enabled, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (title, content, visibility, is_active, comments_enabled, session['user_id']))
            db.commit()
            ann_id = cur.lastrowid
            log_change(session['user_id'], 'create', ann_id, title, 'Created announcement')
            flash('Announcement created successfully.', 'success')
        except Exception as e:
            db.rollback()
            flash('Failed to create announcement – database error.', 'error')
            print(f"Create announcement DB error: {e}")

        return redirect(url_for('announcements.announcements'))

    return render_template('announcements/create_announcement.html', form_data=None)


# ----------------------------------------------------------------------
# Edit Announcement
# ----------------------------------------------------------------------
@announcements_bp.route('/edit/<int:ann_id>', methods=['GET', 'POST'])
@login_required
@role_required(REQUIRED_ROLES)
def edit_announcement(ann_id):
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT * FROM announcements WHERE id = %s", (ann_id,))
    announcement = cur.fetchone()
    if not announcement:
        flash('Announcement not found.', 'error')
        return redirect(url_for('announcements.announcements'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        visibility = request.form.get('visibility', 'private')
        is_active = 1 if 'is_active' in request.form else 0
        comments_enabled = 1 if 'comments_enabled' in request.form else 0

        if not title or not content:
            flash('Title and content are required.', 'error')
            return render_template('announcements/edit_announcement.html', announcement=announcement)

        if contains_censored_word(title + ' ' + content):
            flash('Announcement contains a prohibited word or phrase.', 'error')
            return render_template('announcements/edit_announcement.html', announcement=announcement)

        try:
            cur.execute("""
                UPDATE announcements
                SET title = %s, content = %s, visibility = %s, is_active = %s, comments_enabled = %s, updated_by = %s
                WHERE id = %s
            """, (title, content, visibility, is_active, comments_enabled, session['user_id'], ann_id))
            db.commit()
            log_change(session['user_id'], 'update', ann_id, title, 'Updated announcement')
            flash('Announcement updated successfully.', 'success')
        except Exception as e:
            db.rollback()
            flash('Failed to update announcement – database error.', 'error')
            print(f"Edit announcement DB error: {e}")

        return redirect(url_for('announcements.announcements'))

    return render_template('announcements/edit_announcement.html', announcement=announcement)


# ----------------------------------------------------------------------
# Delete Announcement
# ----------------------------------------------------------------------
@announcements_bp.route('/delete/<int:ann_id>', methods=['POST'])
@login_required
@role_required(REQUIRED_ROLES)
def delete_announcement(ann_id):
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT title FROM announcements WHERE id = %s", (ann_id,))
    row = cur.fetchone()
    title = row['title'] if row else 'Unknown'

    try:
        cur.execute("DELETE FROM announcement_comments WHERE announcement_id = %s", (ann_id,))
        cur.execute("DELETE FROM announcements WHERE id = %s", (ann_id,))
        db.commit()
        log_change(session['user_id'], 'delete', ann_id, title, 'Deleted announcement')
        flash('Announcement deleted.', 'success')
    except Exception as e:
        db.rollback()
        flash('Failed to delete announcement – database error.', 'error')
        print(f"Delete announcement DB error: {e}")

    return redirect(url_for('announcements.announcements'))


# ----------------------------------------------------------------------
# Add Comment
# ----------------------------------------------------------------------
@announcements_bp.route('/comment/add/<int:ann_id>', methods=['POST'])
@login_required
def add_comment(ann_id):
    comment_text = request.form.get('comment', '').strip()
    if not comment_text:
        flash('Comment cannot be empty.', 'error')
        return redirect(url_for('announcements.announcements') + f'#details-{ann_id}')

    if contains_censored_word(comment_text):
        flash('Comment contains a prohibited word or phrase.', 'error')
        return redirect(url_for('announcements.announcements') + f'#details-{ann_id}')

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT title FROM announcements WHERE id = %s", (ann_id,))
    row = cur.fetchone()
    ann_title = row['title'] if row else 'Unknown'

    try:
        cur.execute("""
            INSERT INTO announcement_comments (announcement_id, user_id, comment)
            VALUES (%s, %s, %s)
        """, (ann_id, session['user_id'], comment_text))
        db.commit()
        log_change(session['user_id'], 'create', ann_id, ann_title, 'Added comment')
        flash('Comment added.', 'success')
    except Exception as e:
        db.rollback()
        flash('Failed to add comment – database error.', 'error')
        print(f"Add comment DB error: {e}")

    return redirect(url_for('announcements.announcements') + f'#details-{ann_id}')


# ----------------------------------------------------------------------
# Email Announcement
# ----------------------------------------------------------------------
@announcements_bp.route('/email/<int:ann_id>', methods=['POST'])
@login_required
@role_required(REQUIRED_ROLES)
def email_announcement(ann_id):
    subject = request.form.get('subject', '').strip()
    message = request.form.get('message', '').strip()

    if not subject:
        flash('Subject is required.', 'error')
        return redirect(url_for('announcements.announcements'))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT title, content FROM announcements WHERE id = %s", (ann_id,))
    row = cur.fetchone()
    if not row:
        flash('Announcement not found.', 'error')
        return redirect(url_for('announcements.announcements'))

    body = f"{message}\n\n--- Announcement ---\nTitle: {row['title']}\n\n{row['content']}"

    if 'sendAll' in request.form:
        cur.execute("SELECT email FROM users WHERE email IS NOT NULL AND email != ''")
    else:
        member_ids = request.form.getlist('member_ids')
        if not member_ids:
            flash('No recipients selected.', 'error')
            return redirect(url_for('announcements.announcements'))
        placeholders = ','.join(['%s'] * len(member_ids))
        cur.execute(f"SELECT email FROM users WHERE id IN ({placeholders}) AND email IS NOT NULL AND email != ''",
                    [int(mid) for mid in member_ids])

    emails = [r['email'] for r in cur.fetchall()]

    if not emails:
        flash('No valid recipient emails found.', 'error')
        return redirect(url_for('announcements.announcements'))

    success_count = 0
    for email_addr in emails:
        try:
            send_email(email_addr, subject, body)
            success_count += 1
        except Exception as e:
            print(f"Email failed to {email_addr}: {e}")

    log_change(session['user_id'], 'email', ann_id, row['title'], f"Emailed to {success_count} recipients")
    flash(f'Announcement emailed to {success_count} members.', 'success')
    return redirect(url_for('announcements.announcements'))