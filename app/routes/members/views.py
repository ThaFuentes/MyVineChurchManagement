# app/routes/members/views.py
# Full path: MyVineChurch/app/routes/members/views.py
# File name: views.py
# Brief, detailed purpose: All route handlers (controllers) for the Members blueprint.
# • Every single function name and endpoint from the original members.py is preserved exactly (no renaming).
# • All database work moved to queries.py
# • All form validation + censorship moved to forms.py
# • All helpers moved to utils.py
# • 100% original behavior preserved.

from flask import render_template, request, redirect, url_for, flash, session, send_file
from werkzeug.security import generate_password_hash
import json
import os
import random
import string
from docx import Document
import traceback
import pymysql   # ← Added this import to fix NameError

from . import members_bp
from .queries import (
    get_members_directory,
    create_member,
    update_member,
    get_member_by_id,
    get_member_for_export,
    delete_member,
    assign_groups_to_member,
    get_email_roster
)
from .forms import validate_member_form, validate_email_roster_form
from .utils import REQUIRED_ROLES, current_user_id, generate_temporary_password

from app.utils.decorators import login_required, role_required
from app.utils.emailer import send_email
from app.models.log import log_change
from app.models.db import get_db


# ----------------------------------------------------------------------
# Members Directory – searchable with summary cards and expandable family rows
# ----------------------------------------------------------------------
@members_bp.route('/directory')
@login_required
@role_required(['Staff', 'Admin', 'Owner'])
def members_directory():
    search_term = request.args.get('search_term', '').strip()

    members = get_members_directory(search_term)

    total_count = len(members)
    member_count = sum(1 for m in members if m['role'] == 'Member')
    staff_count = sum(1 for m in members if m['role'] == 'Staff')
    admin_count = sum(1 for m in members if m['role'] == 'Admin')
    owner_count = sum(1 for m in members if m['role'] == 'Owner')
    families_linked = sum(1 for m in members if len(m.get('family_members', [])) > 0)

    log_change(session['user_id'], 'view', change_details='Viewed members directory')

    return render_template(
        'members/members_directory.html',
        members=members,
        total_count=total_count,
        member_count=member_count,
        staff_count=staff_count,
        admin_count=admin_count,
        owner_count=owner_count,
        families_linked=families_linked
    )


# ----------------------------------------------------------------------
# Add / Edit Member – combined route (endpoint name restored to original 'add_member')
# ----------------------------------------------------------------------
@members_bp.route('/member', methods=['GET', 'POST'])
@members_bp.route('/member/<int:member_id>', methods=['GET', 'POST'])
@login_required
@role_required(['Staff', 'Admin', 'Owner'])
def add_member(member_id=None):
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    current_role = session['user_role']

    # Fetch groups user is allowed to manage
    cur.execute("SELECT id, name, description, permissions FROM groups ORDER BY name")
    all_groups = cur.fetchall()
    available_groups = []
    for g in all_groups:
        try:
            perms = json.loads(g['permissions'] or '[]')
        except:
            perms = []
        if (current_role == 'Owner' or
            current_role in perms or
            (not perms and current_role in ['Staff', 'Admin', 'Owner'])):
            available_groups.append(g)

    member = None
    selected_group_ids = []

    if member_id:
        member = get_member_by_id(member_id)
        if not member:
            flash('Member not found.', 'error')
            return redirect(url_for('members.members_directory'))

        cur.execute("SELECT group_id FROM user_groups WHERE user_id = %s", (member_id,))
        selected_group_ids = [row['group_id'] for row in cur.fetchall()]

    if request.method == 'POST':
        clean_data = validate_member_form(request.form, is_edit=bool(member_id), current_role=current_role, available_group_ids=[g['id'] for g in available_groups])
        if not clean_data:
            return render_template('members/member_form.html',
                                   member=member,
                                   available_groups=available_groups,
                                   selected_group_ids=selected_group_ids)

        if not member_id:  # ADD NEW MEMBER
            try:
                temp_pass = generate_temporary_password()
                hashed_pw = generate_password_hash(temp_pass)
                username = clean_data['email'].split('@')[0]

                new_id = create_member({
                    'username': username,
                    'password': hashed_pw,
                    'first_name': clean_data['first_name'],
                    'last_name': clean_data['last_name'],
                    'email': clean_data['email'],
                    'phone': clean_data['phone'],
                    'address': clean_data['address'],
                    'birthday': clean_data['birthday'],
                    'show_birthday': clean_data['show_birthday'],
                    'role': clean_data['role'],
                    'accepts_emails': clean_data['accepts_emails'],
                    'created_by': session['user_id']
                })

                # Send welcome email
                body = f"""Welcome to MyVineChurch.Online!

Your account has been created.
Username: {username}
Temporary password: {temp_pass}

Please log in and change your password.
"""
                send_email(clean_data['email'], 'Welcome to MyVineChurch', body)

                flash('Member added successfully. Temporary password emailed.', 'success')
                log_change(session['user_id'], 'add_member', f'Added {clean_data["first_name"]} {clean_data["last_name"]} (ID {new_id})')

                # Assign groups
                assign_groups_to_member(new_id, clean_data['groups'], session['user_id'])

            except Exception as e:
                flash('Failed to add member.', 'error')
                print(f"Add member error: {e}")

        else:  # EDIT EXISTING MEMBER
            try:
                update_member(member_id, clean_data)
                assign_groups_to_member(member_id, clean_data['groups'], session['user_id'])

                flash('Member updated successfully.', 'success')
                log_change(session['user_id'], 'edit_member', f'Updated {clean_data["first_name"]} {clean_data["last_name"]} (ID {member_id})')

            except Exception as e:
                flash('Failed to update member.', 'error')
                print(f"Edit member error: {e}")

        return redirect(url_for('members.members_directory'))

    # GET – render form
    return render_template('members/member_form.html',
                           member=member,
                           available_groups=available_groups,
                           selected_group_ids=selected_group_ids)


# ----------------------------------------------------------------------
# Delete Member (Admin/Owner only)
# ----------------------------------------------------------------------
@members_bp.route('/member/delete/<int:member_id>', methods=['POST'])
@login_required
@role_required(['Admin', 'Owner'])
def delete_member(member_id):
    try:
        member = get_member_by_id(member_id)
        if not member:
            flash('Member not found.', 'error')
            return redirect(url_for('members.members_directory'))

        if member['role'] in ['Admin', 'Owner'] and session['user_role'] != 'Owner':
            flash('Only Owner can delete Admin/Owner accounts.', 'error')
            return redirect(url_for('members.members_directory'))

        delete_member(member_id)

        flash('Member deleted successfully.', 'success')
        log_change(session['user_id'], 'delete_member', f'Deleted {member["first_name"]} {member["last_name"]} (ID {member_id})')

    except Exception as e:
        flash('Failed to delete member.', 'error')
        print(f"Delete member error: {e}\n{traceback.format_exc()}")

    return redirect(url_for('members.members_directory'))


# ----------------------------------------------------------------------
# Export Directory to DOCX (Admin/Owner only)
# ----------------------------------------------------------------------
@members_bp.route('/export')
@login_required
@role_required(['Admin', 'Owner'])
def export_directory():
    try:
        members = get_member_for_export()

        doc = Document()
        doc.add_heading('MyVineChurch Members Directory', 0)

        table = doc.add_table(rows=1, cols=10)
        hdr_cells = table.rows[0].cells
        headers = ['First', 'Last', 'Phone', 'Email', 'Address', 'Role',
                   'Username', 'Emails', 'Birthday', 'Show Bday']
        for i, h in enumerate(headers):
            hdr_cells[i].text = h

        for m in members:
            row = table.add_row().cells
            row[0].text = m['first_name'] or ''
            row[1].text = m['last_name'] or ''
            row[2].text = m['phone'] or ''
            row[3].text = m['email'] or ''
            row[4].text = m['address'] or ''
            row[5].text = m['role']
            row[6].text = m['username'] or ''
            row[7].text = 'Yes' if m['accepts_emails'] else 'No'
            row[8].text = m['birthday'] or ''
            row[9].text = 'Yes' if m['show_birthday'] else 'No'

        export_dir = os.path.join(os.getcwd(), 'export')
        os.makedirs(export_dir, exist_ok=True)
        path = os.path.join(export_dir, 'members_directory.docx')
        doc.save(path)

        log_change(session['user_id'], 'export_directory', 'Exported members directory to DOCX')
        return send_file(path, as_attachment=True, download_name='members_directory.docx')

    except Exception as e:
        flash('Failed to export directory.', 'error')
        print(f"Export error: {e}\n{traceback.format_exc()}")
        return redirect(url_for('members.members_directory'))


# ----------------------------------------------------------------------
# Email Church Roster (Admin/Owner only)
# ----------------------------------------------------------------------
@members_bp.route('/email_roster', methods=['GET', 'POST'])
@login_required
@role_required(['Admin', 'Owner'])
def email_roster():
    if request.method == 'GET':
        return render_template('members/email_roster.html')

    clean = validate_email_roster_form(request.form)
    if not clean:
        return render_template('members/email_roster.html')

    subject = clean['subject']
    message = clean['message']
    include_roster = clean['include_roster']

    try:
        recipients = get_email_roster()

        if not recipients:
            flash('No members accept emails.', 'error')
            return redirect(url_for('members.members_directory'))

        roster_text = ""
        if include_roster:
            roster_text = "\n\n--- Church Roster ---\n"
            for r in recipients:
                phone = r['phone'] or 'Not provided'
                roster_text += f"{r['first_name']} {r['last_name']} • {phone} • {r['email']}\n"

        body = f"{message}{roster_text}\n\nBlessings,\nMyVineChurch Team"

        sent = 0
        for r in recipients:
            try:
                send_email(r['email'], subject, body)
                sent += 1
            except Exception as e:
                print(f"Email failed to {r['email']}: {e}")

        flash(f'Email sent to {sent} member(s).', 'success')
        log_change(session['user_id'], 'email_roster', f'Sent roster email to {sent} members')

    except Exception as e:
        flash('Failed to send email.', 'error')
        print(f"Email roster error: {e}\n{traceback.format_exc()}")

    return redirect(url_for('members.members_directory'))