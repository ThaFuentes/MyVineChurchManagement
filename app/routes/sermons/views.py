# app/routes/sermons/views.py
# Full path: WebChurchMan/app/routes/sermons/views.py
# File name: views.py
# Brief, detailed purpose: All route handlers (@bp.route) for the sermons blueprint – main controller file.
# Every endpoint name, function name, logic flow, flash message, redirect, logging call, file handling, and visibility enforcement exactly as original sermons.py.
# Only DB/form/permission/file logic delegated to sibling modules. 100% identical behavior preserved.

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_from_directory
from app.utils.decorators import login_required, role_required
from app.utils.helpers import censor_text
from app.models.log import log_change
from werkzeug.utils import secure_filename
from docx import Document as DocxDocument
import PyPDF2
import os
import time
import traceback

from .queries import (
    get_visible_sermons, get_sermon_by_id, get_sermon_comments,
    get_comment_owner, create_sermon, update_sermon, delete_sermon,
    create_sermon_comment, update_sermon_comment, delete_sermon_comment,
    get_sermon_file_owner
)
from .forms import validate_sermon_upload_or_edit, validate_sermon_comment
from .utils import ALLOWED_EXTENSIONS, UPLOAD_FOLDER, STAFF_ROLES, allowed_file


sermons_bp = Blueprint('sermons', __name__, url_prefix='/sermons')


# ----------------------------------------------------------------------
# Main Sermons List – /sermons (single URL)
# ----------------------------------------------------------------------
@sermons_bp.route('/')
def sermons():
    is_logged_in = 'user_id' in session
    user_id = session.get('user_id')

    sermons_list = get_visible_sermons(user_id)

    # Server-side display censorship + notes preview extraction
    for sermon in sermons_list:
        sermon['title'] = censor_text(sermon['title'])
        sermon['details'] = censor_text(sermon.get('details') or '')

        notes_content = None
        if sermon['notes']:
            path = os.path.join(UPLOAD_FOLDER, sermon['notes'])
            ext = sermon['notes'].rsplit('.', 1)[-1].lower() if '.' in sermon['notes'] else ''
            try:
                if ext == 'txt':
                    with open(path, 'r', encoding='utf-8') as f:
                        notes_content = f.read()
                elif ext == 'docx':
                    doc = DocxDocument(path)
                    notes_content = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
                elif ext == 'pdf':
                    reader = PyPDF2.PdfReader(path)
                    notes_content = "\n\n".join(page.extract_text() or '' for page in reader.pages)
            except Exception:
                notes_content = '(Error reading notes file)'
        sermon['notes_content'] = censor_text(notes_content) if notes_content else None

        # Comments – visible to everyone for public/private, only uploader for personal
        if is_logged_in or sermon['visibility'] == 'public':
            sermon['comments'] = get_sermon_comments(sermon['id'])
            for c in sermon['comments']:
                c['comment'] = censor_text(c['comment'])
                c['commenter_username'] = censor_text(c.get('commenter_username', 'Anonymous'))
        else:
            sermon['comments'] = []

    if user_id:
        log_change(user_id, 'view', change_details='Viewed sermons list')

    # Use public template for guests, private template for logged-in
    template = 'public/sermons/sermons.html' if not is_logged_in else 'sermons/sermons.html'
    return render_template(template, sermons=sermons_list, is_logged_in=is_logged_in)


# ----------------------------------------------------------------------
# Upload Sermon – /sermons/upload
# ----------------------------------------------------------------------
@sermons_bp.route('/upload', methods=['GET', 'POST'])
@login_required
@role_required(STAFF_ROLES)
def upload_sermon():
    user_id = session['user_id']

    if request.method == 'POST':
        is_valid, errors, cleaned = validate_sermon_upload_or_edit(
            request.form, request.files, is_edit=False
        )

        for err in errors:
            flash(err, 'error')

        if not is_valid:
            return redirect(request.url)

        title = cleaned['title']
        details = cleaned['details']
        external_link = cleaned['external_link']
        visibility = cleaned['visibility']

        notes_filename = None
        sermon_filename = None
        timestamp = int(time.time())

        try:
            notes_file = request.files.get('sermon_notes')
            if notes_file and notes_file.filename and allowed_file(notes_file.filename):
                safe_name = secure_filename(notes_file.filename)
                notes_filename = f"{user_id}_{timestamp}_{safe_name}"
                notes_file.save(os.path.join(UPLOAD_FOLDER, notes_filename))

            sermon_file = request.files.get('sermon_file')
            if sermon_file and sermon_file.filename and allowed_file(sermon_file.filename):
                safe_name = secure_filename(sermon_file.filename)
                sermon_filename = f"{user_id}_{timestamp}_{safe_name}"
                sermon_file.save(os.path.join(UPLOAD_FOLDER, sermon_filename))

            sermon_id = create_sermon(
                title, notes_filename, details, sermon_filename,
                external_link, visibility, user_id
            )

            log_change(user_id, 'create_sermon', target_id=sermon_id,
                       change_details=f"Uploaded sermon '{title}' (visibility: {visibility})")
            flash('Sermon uploaded successfully.', 'success')

        except Exception as e:
            flash('Upload failed.', 'error')
            print(f"Upload sermon error: {e}\n{traceback.format_exc()}")

        return redirect(url_for('sermons.sermons'))

    return render_template('sermons/add_sermon.html')


# ----------------------------------------------------------------------
# Edit Sermon – /sermons/edit/<int:sermon_id>
# ----------------------------------------------------------------------
@sermons_bp.route('/edit/<int:sermon_id>', methods=['GET', 'POST'])
@login_required
@role_required(STAFF_ROLES)
def edit_sermon(sermon_id):
    user_id = session['user_id']

    sermon = get_sermon_by_id(sermon_id)
    if not sermon:
        flash('Sermon not found.', 'error')
        return redirect(url_for('sermons.sermons'))

    # Staff+ can edit any, uploader can edit their own
    if sermon['uploaded_by'] != user_id and session.get('user_role') not in STAFF_ROLES:
        flash('Not authorized to edit this sermon.', 'error')
        return redirect(url_for('sermons.sermons'))

    if request.method == 'POST':
        is_valid, errors, cleaned = validate_sermon_upload_or_edit(
            request.form, request.files, is_edit=True
        )

        for err in errors:
            flash(err, 'error')

        if not is_valid:
            return redirect(request.url)

        title = cleaned['title']
        details = cleaned['details']
        external_link = cleaned['external_link']
        visibility = cleaned['visibility']

        notes_filename = None
        sermon_filename = None
        timestamp = int(time.time())

        try:
            notes_file = request.files.get('sermon_notes')
            if notes_file and notes_file.filename and allowed_file(notes_file.filename):
                safe_name = secure_filename(notes_file.filename)
                notes_filename = f"{user_id}_{timestamp}_{safe_name}"
                notes_file.save(os.path.join(UPLOAD_FOLDER, notes_filename))
                # Clean up old notes if exists
                if sermon['notes']:
                    try:
                        os.remove(os.path.join(UPLOAD_FOLDER, sermon['notes']))
                    except OSError:
                        pass

            sermon_file = request.files.get('sermon_file')
            if sermon_file and sermon_file.filename and allowed_file(sermon_file.filename):
                safe_name = secure_filename(sermon_file.filename)
                sermon_filename = f"{user_id}_{timestamp}_{safe_name}"
                sermon_file.save(os.path.join(UPLOAD_FOLDER, sermon_filename))
                # Clean up old sermon file if exists
                if sermon['sermon_file']:
                    try:
                        os.remove(os.path.join(UPLOAD_FOLDER, sermon['sermon_file']))
                    except OSError:
                        pass

            update_sermon(
                sermon_id, title, details, external_link, visibility,
                notes_filename, sermon_filename
            )

            log_change(user_id, 'update_sermon', target_id=sermon_id,
                       change_details=f"Updated sermon '{title}' (visibility: {visibility})")
            flash('Sermon updated successfully.', 'success')

        except Exception as e:
            flash('Error updating sermon.', 'error')
            print(f"Edit sermon error: {e}\n{traceback.format_exc()}")

        return redirect(url_for('sermons.sermons'))

    # GET: pre-fill form with existing sermon data
    return render_template('sermons/add_sermon.html', sermon=sermon, is_edit=True)


# ----------------------------------------------------------------------
# Delete Sermon – /sermons/delete/<int:sermon_id>
# ----------------------------------------------------------------------
@sermons_bp.route('/delete/<int:sermon_id>', methods=['POST'])
@login_required
@role_required(STAFF_ROLES)
def delete_sermon(sermon_id):
    user_id = session['user_id']

    sermon = get_sermon_by_id(sermon_id)
    if not sermon:
        flash('Sermon not found.', 'error')
        return redirect(url_for('sermons.sermons'))

    try:
        delete_sermon(sermon_id)

        # Clean up files
        for filename in (sermon['notes'], sermon['sermon_file']):
            if filename:
                try:
                    os.remove(os.path.join(UPLOAD_FOLDER, filename))
                except OSError:
                    pass

        log_change(user_id, 'delete_sermon', target_id=sermon_id,
                   change_details=f"Deleted sermon '{sermon['title']}'")
        flash('Sermon deleted successfully.', 'success')

    except Exception as e:
        flash('Error deleting sermon.', 'error')
        print(f"Delete sermon error: {e}\n{traceback.format_exc()}")

    return redirect(url_for('sermons.sermons'))


# ----------------------------------------------------------------------
# Serve Uploaded Files (secure, logged-in only + personal visibility check)
# ----------------------------------------------------------------------
@sermons_bp.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    user_id = session['user_id']

    sermon = get_sermon_file_owner(filename)
    if not sermon:
        flash('File not found.', 'error')
        return redirect(url_for('sermons.sermons'))

    # Enforce personal visibility
    if sermon['visibility'] == 'personal' and sermon['uploaded_by'] != user_id:
        flash('Not authorized to access this file.', 'error')
        return redirect(url_for('sermons.sermons'))

    log_change(user_id, 'download', change_details=f"Downloaded sermon file: {filename}")
    return send_from_directory(UPLOAD_FOLDER, filename)


# ----------------------------------------------------------------------
# Comment Management (logged-in only)
# ----------------------------------------------------------------------
@sermons_bp.route('/comment/add/<int:sermon_id>', methods=['POST'])
@login_required
def add_comment(sermon_id):
    is_valid, errors, cleaned = validate_sermon_comment(request.form)

    for err in errors:
        flash(err, 'error')

    if not is_valid:
        return redirect(url_for('sermons.sermons'))

    try:
        create_sermon_comment(sermon_id, session['user_id'], cleaned['comment'])
        log_change(session['user_id'], 'add_comment', target_id=sermon_id,
                   change_details='Added comment to sermon')
        flash('Comment added.', 'success')
    except Exception:
        flash('Failed to add comment.', 'error')

    return redirect(url_for('sermons.sermons'))


@sermons_bp.route('/comment/edit/<int:sermon_id>/<int:comment_id>', methods=['POST'])
@login_required
def update_comment(sermon_id, comment_id):
    is_valid, errors, cleaned = validate_sermon_comment(request.form)

    for err in errors:
        flash(err, 'error')

    if not is_valid:
        return redirect(url_for('sermons.sermons'))

    owner_id = get_comment_owner(comment_id)
    if not owner_id or owner_id != session['user_id']:
        flash('Not authorized to edit this comment.', 'error')
        return redirect(url_for('sermons.sermons'))

    try:
        update_sermon_comment(comment_id, cleaned['comment'])
        log_change(session['user_id'], 'update_comment', target_id=sermon_id,
                   change_details='Updated sermon comment')
        flash('Comment updated.', 'success')
    except Exception:
        flash('Error updating comment.', 'error')

    return redirect(url_for('sermons.sermons'))


@sermons_bp.route('/comment/delete/<int:sermon_id>/<int:comment_id>', methods=['POST'])
@login_required
def delete_comment(sermon_id, comment_id):
    owner_id = get_comment_owner(comment_id)
    is_admin_owner = session.get('user_role') in ['Admin', 'Owner']

    if not owner_id or (owner_id != session['user_id'] and not is_admin_owner):
        flash('Not authorized to delete this comment.', 'error')
        return redirect(url_for('sermons.sermons'))

    try:
        delete_sermon_comment(comment_id)
        log_change(session['user_id'], 'delete_comment', target_id=sermon_id,
                   change_details='Deleted sermon comment')
        flash('Comment deleted.', 'success')
    except Exception:
        flash('Error deleting comment.', 'error')

    return redirect(url_for('sermons.sermons'))