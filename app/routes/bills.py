# app/routes/bills.py
# Full path: myvinechurchonline/app/routes/bills.py
# File name: bills.py
# Brief, detailed purpose: Blueprint for recurring bills management (internal administrative tool).
#          /bills → dashboard listing: managers see all bills, assigned members see only theirs.
#          Full CRUD for Staff/Admin/Owner.
#          Assigned users (or managers) can view details (including decrypted credentials), record payments.
#          Managers can assign users, update reminder preferences, send manual reminders.
#          All editable text fields + link labels checked for censored words on create/edit.
#          Encrypted username/password decrypted only on view/edit form (FERNET_KEY from config).
#          Additional links stored as JSON in DB but user enters via repeatable normal inputs (label + URL).
#          All significant actions audit-logged.
#          Strictly private – login_required on all routes.
#          FULL REBUILD: Integrated timezone-aware UTC storage for timestamps (last_reminder_sent, updated_at).
#                    Displayed timestamps formatted in church local time via time_utils.
#                    All existing functionality preserved exactly – only time handling updated for consistency.

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from app.utils.decorators import login_required, role_required
from app.utils.helpers import contains_censored_word
from app.models.db import get_db
from app.models.log import log_change
from app.utils.emailer import send_email
from app.utils.time_utils import utc_now, format_church, format_church_full
from cryptography.fernet import Fernet, InvalidToken
import sqlite3
import json
from datetime import datetime
from itertools import zip_longest

bills_bp = Blueprint('bills', __name__, url_prefix='/bills')

REQUIRED_ROLES = ['Staff', 'Admin', 'Owner']


def user_is_manager():
    return session.get('user_role') in REQUIRED_ROLES


def has_bill_access(bill_id: int, user_id: int):
    if user_is_manager():
        return True
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT 1 FROM recurring_bill_assignments WHERE bill_id = ? AND user_id = ?", (bill_id, user_id))
    return cur.fetchone() is not None


# ----------------------------------------------------------------------
# Dashboard / Listing – /bills
# ----------------------------------------------------------------------
@bills_bp.route('/')
@login_required
def bills():
    user_id = session['user_id']
    is_manager = user_is_manager()

    db = get_db()
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    if is_manager:
        cur.execute("""
            SELECT b.*, 
                   (SELECT COUNT(*) FROM recurring_bill_assignments a WHERE a.bill_id = b.id) AS assigned_count
            FROM recurring_bills b
            ORDER BY b.next_due_date ASC, b.bill_name ASC
        """)
    else:
        cur.execute("""
            SELECT b.*
            FROM recurring_bills b
            JOIN recurring_bill_assignments a ON b.id = a.bill_id
            WHERE a.user_id = ?
            ORDER BY b.next_due_date ASC, b.bill_name ASC
        """, (user_id,))

    bills_list = [dict(row) for row in cur.fetchall()]

    # Add nice formatted next_due_date (local date – no time component)
    for b in bills_list:
        if b['next_due_date']:
            due_date = datetime.strptime(b['next_due_date'], '%Y-%m-%d')
            b['nice_next_due'] = due_date.strftime('%A, %B %d, %Y')
        else:
            b['nice_next_due'] = 'Not set'

    log_change(user_id, 'view', change_details='Viewed recurring bills dashboard')

    return render_template('bills/bills_dashboard.html',
                           bills=bills_list,
                           is_manager=is_manager)


# ----------------------------------------------------------------------
# Add New Bill – /bills/add
# ----------------------------------------------------------------------
@bills_bp.route('/add', methods=['GET', 'POST'])
@login_required
@role_required(REQUIRED_ROLES)
def add_bill():
    if request.method == 'GET':
        return render_template('bills/edit_bill.html', bill=None, additional_links=[])

    # POST
    bill_name = request.form.get('bill_name', '').strip()

    if not bill_name:
        flash('Bill name is required.', 'error')
        # Collect links for repopulation
        link_labels = request.form.getlist('link_label')
        link_urls = request.form.getlist('link_url')
        links = [{"label": l.strip(), "url": u.strip()} for l, u in zip_longest(link_labels, link_urls) if l.strip() or u.strip()]
        return render_template('bills/edit_bill.html', bill=None, additional_links=links)

    # Collect repeatable links
    link_labels = request.form.getlist('link_label')
    link_urls = request.form.getlist('link_url')
    links = [{"label": l.strip(), "url": u.strip()} for l, u in zip_longest(link_labels, link_urls) if l.strip() or u.strip()]

    # Censored word check (all user-editable text + link labels)
    combined_text = (
        f"{bill_name} {request.form.get('vendor_name', '')} {request.form.get('description', '')} "
        f"{request.form.get('notes', '')} {' '.join(link['label'] for link in links)}"
    )
    if contains_censored_word(combined_text):
        flash('Entry contains a prohibited word or phrase.', 'error')
        return render_template('bills/edit_bill.html', bill=None, additional_links=links)

    # Encryption
    fernet = Fernet(current_app.config['FERNET_KEY'])
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    encrypted_username = fernet.encrypt(username.encode()) if username else None
    encrypted_password = fernet.encrypt(password.encode()) if password else None

    links_json = json.dumps(links) if links else None

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO recurring_bills (
            bill_name, vendor_name, description, typical_amount, account_number, customer_number,
            phone1, phone2, address, payment_url, login_url, additional_links,
            encrypted_username, encrypted_password, frequency, due_day, due_month,
            reminder_days_before, next_due_date, current_status, notes, created_by
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
    """, (
        bill_name, request.form.get('vendor_name'), request.form.get('description'),
        request.form.get('typical_amount') or None,
        request.form.get('account_number'), request.form.get('customer_number'),
        request.form.get('phone1'), request.form.get('phone2'),
        request.form.get('address'), request.form.get('payment_url'),
        request.form.get('login_url'), links_json,
        encrypted_username, encrypted_password,
        request.form.get('frequency', 'monthly'),
        request.form.get('due_day') or None,
        request.form.get('due_month') or None,
        request.form.get('reminder_days_before', 7),
        request.form.get('next_due_date'),
        request.form.get('current_status', 'pending'),
        request.form.get('notes'), session['user_id']
    ))
    db.commit()
    bill_id = cur.lastrowid

    log_change(session['user_id'], 'create', bill_id, bill_name, 'Created recurring bill')
    flash('Recurring bill added successfully.', 'success')
    return redirect(url_for('bills.bills'))


# ----------------------------------------------------------------------
# Edit Bill – /bills/edit/<int:bill_id>
# ----------------------------------------------------------------------
@bills_bp.route('/edit/<int:bill_id>', methods=['GET', 'POST'])
@login_required
@role_required(REQUIRED_ROLES)
def edit_bill(bill_id):
    db = get_db()
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    cur.execute("SELECT * FROM recurring_bills WHERE id = ?", (bill_id,))
    bill_row = cur.fetchone()
    if not bill_row:
        flash('Bill not found.', 'error')
        return redirect(url_for('bills.bills'))
    bill = dict(bill_row)

    if request.method == 'POST':
        bill_name = request.form.get('bill_name', '').strip()

        if not bill_name:
            flash('Bill name is required.', 'error')

        # Collect links
        link_labels = request.form.getlist('link_label')
        link_urls = request.form.getlist('link_url')
        links = [{"label": l.strip(), "url": u.strip()} for l, u in zip_longest(link_labels, link_urls) if l.strip() or u.strip()]

        # Censored check
        combined_text = (
            f"{bill_name} {request.form.get('vendor_name', '')} {request.form.get('description', '')} "
            f"{request.form.get('notes', '')} {' '.join(link['label'] for link in links)}"
        )
        if contains_censored_word(combined_text):
            flash('Entry contains a prohibited word or phrase.', 'error')

        if flash.get_flashed_messages():  # any error so far
            # Repopulate with entered values
            repop_bill = dict(bill)
            normal_fields = ['bill_name', 'vendor_name', 'description', 'typical_amount', 'account_number',
                             'customer_number', 'phone1', 'phone2', 'address', 'payment_url', 'login_url',
                             'frequency', 'due_day', 'due_month', 'reminder_days_before', 'next_due_date',
                             'current_status', 'notes']
            for f in normal_fields:
                repop_bill[f] = request.form.get(f, repop_bill.get(f, ''))
            repop_bill['username'] = request.form.get('username', repop_bill.get('username', ''))
            repop_bill['password'] = request.form.get('password', repop_bill.get('password', ''))
            return render_template('bills/edit_bill.html', bill=repop_bill, additional_links=links)

        # Encryption – only update if non-blank
        fernet = Fernet(current_app.config['FERNET_KEY'])
        username_input = request.form.get('username', '').strip()
        password_input = request.form.get('password', '').strip()

        encrypted_username = fernet.encrypt(username_input.encode()) if username_input else bill['encrypted_username']
        encrypted_password = fernet.encrypt(password_input.encode()) if password_input else bill['encrypted_password']

        links_json = json.dumps(links) if links else None

        update_time_utc = utc_now()  # UTC for updated_at

        cur.execute("""
            UPDATE recurring_bills SET
                bill_name = ?, vendor_name = ?, description = ?, typical_amount = ?,
                account_number = ?, customer_number = ?, phone1 = ?, phone2 = ?,
                address = ?, payment_url = ?, login_url = ?, additional_links = ?,
                encrypted_username = ?, encrypted_password = ?, frequency = ?,
                due_day = ?, due_month = ?, reminder_days_before = ?,
                next_due_date = ?, current_status = ?, notes = ?,
                updated_by = ?, updated_at = ?
            WHERE id = ?
        """, (
            bill_name, request.form.get('vendor_name'), request.form.get('description'),
            request.form.get('typical_amount') or None,
            request.form.get('account_number'), request.form.get('customer_number'),
            request.form.get('phone1'), request.form.get('phone2'),
            request.form.get('address'), request.form.get('payment_url'),
            request.form.get('login_url'), links_json,
            encrypted_username, encrypted_password,
            request.form.get('frequency', 'monthly'),
            request.form.get('due_day') or None,
            request.form.get('due_month') or None,
            request.form.get('reminder_days_before', 7),
            request.form.get('next_due_date'),
            request.form.get('current_status', 'pending'),
            request.form.get('notes'), session['user_id'], update_time_utc, bill_id
        ))
        db.commit()

        log_change(session['user_id'], 'update', bill_id, bill_name, 'Updated recurring bill')
        flash('Bill updated successfully.', 'success')
        return redirect(url_for('bills.view_bill', bill_id=bill_id))

    # GET – decrypt credentials + parse links
    fernet = Fernet(current_app.config['FERNET_KEY'])
    bill['username'] = ''
    if bill['encrypted_username']:
        try:
            bill['username'] = fernet.decrypt(bill['encrypted_username']).decode()
        except InvalidToken:
            bill['username'] = '[Decryption failed]'
    bill['password'] = ''
    if bill['encrypted_password']:
        try:
            bill['password'] = fernet.decrypt(bill['encrypted_password']).decode()
        except InvalidToken:
            bill['password'] = '[Decryption failed]'

    additional_links = json.loads(bill['additional_links'] or '[]')

    return render_template('bills/edit_bill.html', bill=bill, additional_links=additional_links)


# ----------------------------------------------------------------------
# View Single Bill – /bills/<int:bill_id>
# ----------------------------------------------------------------------
@bills_bp.route('/<int:bill_id>')
@login_required
def view_bill(bill_id):
    user_id = session['user_id']
    is_manager = user_is_manager()

    if not has_bill_access(bill_id, user_id):
        flash('You do not have access to this bill.', 'error')
        return redirect(url_for('bills.bills'))

    db = get_db()
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    cur.execute("SELECT * FROM recurring_bills WHERE id = ?", (bill_id,))
    bill_row = cur.fetchone()
    if not bill_row:
        flash('Bill not found.', 'error')
        return redirect(url_for('bills.bills'))
    bill = dict(bill_row)

    # Decrypt credentials
    fernet = Fernet(current_app.config['FERNET_KEY'])
    bill['username'] = None
    if bill['encrypted_username']:
        try:
            bill['username'] = fernet.decrypt(bill['encrypted_username']).decode()
        except InvalidToken:
            bill['username'] = '[Decryption failed]'
    bill['password'] = None
    if bill['encrypted_password']:
        try:
            bill['password'] = fernet.decrypt(bill['encrypted_password']).decode()
        except InvalidToken:
            bill['password'] = '[Decryption failed]'

    bill['links'] = json.loads(bill['additional_links'] or '[]')

    # Format dates/times in church local time
    if bill['next_due_date']:
        due_date = datetime.strptime(bill['next_due_date'], '%Y-%m-%d')
        bill['nice_next_due'] = due_date.strftime('%A, %B %d, %Y')
    else:
        bill['nice_next_due'] = 'Not set'

    bill['last_reminder_formatted'] = format_church_full(bill['last_reminder_sent']) if bill['last_reminder_sent'] else 'Never'

    # Assignments
    cur.execute("""
        SELECT u.id, u.username, u.first_name, u.last_name, u.email, a.remind_me
        FROM recurring_bill_assignments a
        JOIN users u ON a.user_id = u.id
        WHERE a.bill_id = ?
    """, (bill_id,))
    assignments = [dict(row) for row in cur.fetchall()]

    # Payment history – format payment_date (date only)
    cur.execute("""
        SELECT h.*, u.username AS paid_by_name
        FROM bill_payment_history h
        LEFT JOIN users u ON h.paid_by = u.id
        WHERE h.bill_id = ?
        ORDER BY h.payment_date DESC
    """, (bill_id,))
    history = [dict(row) for row in cur.fetchall()]

    for h in history:
        if h['payment_date']:
            pay_date = datetime.strptime(h['payment_date'], '%Y-%m-%d')
            h['nice_payment_date'] = pay_date.strftime('%A, %B %d, %Y')
        else:
            h['nice_payment_date'] = 'Unknown'

    log_change(user_id, 'view', bill_id, change_details=f"Viewed bill: {bill['bill_name']}")

    return render_template('bills/view_bill.html',
                           bill=bill,
                           assignments=assignments,
                           history=history,
                           is_manager=is_manager)


# ----------------------------------------------------------------------
# Assign Users to Bill – /bills/assign/<int:bill_id>
# ----------------------------------------------------------------------
@bills_bp.route('/assign/<int:bill_id>', methods=['GET', 'POST'])
@login_required
@role_required(REQUIRED_ROLES)
def assign_bill(bill_id):
    db = get_db()
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    cur.execute("SELECT id, bill_name FROM recurring_bills WHERE id = ?", (bill_id,))
    bill_row = cur.fetchone()
    if not bill_row:
        flash('Bill not found.', 'error')
        return redirect(url_for('bills.bills'))
    bill = dict(bill_row)

    # All users
    cur.execute("SELECT id, username, first_name, last_name, email FROM users ORDER BY first_name, last_name")
    all_users = [dict(row) for row in cur.fetchall()]

    # Current assignments
    cur.execute("SELECT user_id, remind_me FROM recurring_bill_assignments WHERE bill_id = ?", (bill_id,))
    current = {row['user_id']: bool(row['remind_me']) for row in cur.fetchall()}

    if request.method == 'POST':
        selected_users = request.form.getlist('assigned')

        # Clear existing
        cur.execute("DELETE FROM recurring_bill_assignments WHERE bill_id = ?", (bill_id,))

        # Add new
        for uid_str in selected_users:
            uid = int(uid_str)
            remind = 1 if request.form.get(f'remind_{uid}') else 0
            cur.execute("INSERT INTO recurring_bill_assignments (bill_id, user_id, remind_me) VALUES (?, ?, ?)",
                        (bill_id, uid, remind))

        db.commit()
        log_change(session['user_id'], 'assign', bill_id, change_details='Updated bill assignments')
        flash('Assignments updated successfully.', 'success')
        return redirect(url_for('bills.view_bill', bill_id=bill_id))

    return render_template('bills/assign_bill.html',
                           bill=bill,
                           all_users=all_users,
                           current=current)


# ----------------------------------------------------------------------
# Record Payment – /bills/record_payment/<int:bill_id> (POST only)
# ----------------------------------------------------------------------
@bills_bp.route('/record_payment/<int:bill_id>', methods=['POST'])
@login_required
def record_payment(bill_id):
    user_id = session['user_id']

    if not has_bill_access(bill_id, user_id):
        flash('You do not have access to record payment for this bill.', 'error')
        return redirect(url_for('bills.bills'))

    amount = request.form.get('amount')
    payment_date = request.form.get('payment_date') or datetime.today().strftime('%Y-%m-%d')
    notes = request.form.get('notes', '').strip()

    if not amount:
        flash('Amount is required.', 'error')
        return redirect(url_for('bills.view_bill', bill_id=bill_id))

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO bill_payment_history (bill_id, payment_date, amount, paid_by, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (bill_id, payment_date, amount, user_id, notes))
    cur.execute("UPDATE recurring_bills SET current_status = 'paid', updated_by = ? WHERE id = ?",
                (user_id, bill_id))
    db.commit()

    log_change(user_id, 'payment', bill_id, change_details=f"Recorded payment of {amount}")
    flash('Payment recorded successfully.', 'success')
    return redirect(url_for('bills.view_bill', bill_id=bill_id))


# ----------------------------------------------------------------------
# Send Manual Reminder – /bills/send_reminder/<int:bill_id> (POST only)
# ----------------------------------------------------------------------
@bills_bp.route('/send_reminder/<int:bill_id>', methods=['POST'])
@login_required
@role_required(REQUIRED_ROLES)
def send_reminder(bill_id):
    db = get_db()
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    cur.execute("SELECT * FROM recurring_bills WHERE id = ?", (bill_id,))
    bill_row = cur.fetchone()
    if not bill_row:
        flash('Bill not found.', 'error')
        return redirect(url_for('bills.bills'))
    bill = dict(bill_row)

    cur.execute("""
        SELECT u.email, u.first_name
        FROM recurring_bill_assignments a
        JOIN users u ON a.user_id = u.id
        WHERE a.bill_id = ? AND a.remind_me = 1 AND u.accepts_emails = 1
    """, (bill_id,))
    recipients = [dict(row) for row in cur.fetchall()]

    if not recipients:
        flash('No eligible recipients for reminder.', 'info')
        return redirect(url_for('bills.view_bill', bill_id=bill_id))

    subject = f"Reminder: {bill['bill_name']} due soon"
    body = f"""
    Hello {{name}},

    This is a friendly reminder that the recurring bill "{bill['bill_name']}" is due soon.

    Typical amount: ${bill['typical_amount'] or 'N/A'}
    Due date: {bill['next_due_date'] or 'Not set'}

    {"Payment URL: " + bill['payment_url'] if bill['payment_url'] else ''}

    Please log in to myvinechurch.online/bills/{bill_id} for full details.

    Thank you!
    """

    for rec in recipients:
        personalized = body.replace('{{name}}', rec['first_name'] or 'Member')
        send_email(rec['email'], subject, personalized)

    reminder_time_utc = utc_now()  # Store in UTC

    cur.execute("UPDATE recurring_bills SET last_reminder_sent = ? WHERE id = ?", (reminder_time_utc, bill_id))
    db.commit()

    log_change(session['user_id'], 'reminder', bill_id, change_details='Sent manual reminder emails')
    flash(f'Reminder emails sent to {len(recipients)} recipient(s).', 'success')
    return redirect(url_for('bills.view_bill', bill_id=bill_id))


# ----------------------------------------------------------------------
# Delete Bill – /bills/delete/<int:bill_id> (POST only)
# ----------------------------------------------------------------------
@bills_bp.route('/delete/<int:bill_id>', methods=['POST'])
@login_required
@role_required(['Admin', 'Owner'])
def delete_bill(bill_id):
    db = get_db()
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    cur.execute("SELECT bill_name FROM recurring_bills WHERE id = ?", (bill_id,))
    bill_row = cur.fetchone()
    if not bill_row:
        flash('Bill not found.', 'error')
        return redirect(url_for('bills.bills'))
    bill_name = bill_row['bill_name']

    cur.execute("DELETE FROM recurring_bills WHERE id = ?", (bill_id,))
    db.commit()

    log_change(session['user_id'], 'delete', bill_id, bill_name, 'Deleted recurring bill')
    flash('Recurring bill deleted permanently.', 'success')
    return redirect(url_for('bills.bills'))