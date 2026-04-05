# app/routes/tickets/views.py
# Full path: myvinechurchonline/app/routes/tickets/views.py
# File name: views.py
# Brief, detailed purpose: All the route functions (the @route decorators) for the tickets blueprint – main controller file.
# Every endpoint name, function name, logic flow, flash message, redirect, logging call, email trigger, and formatting exactly as original tickets.py.
# Only DB/form/permission/email logic delegated to sibling modules. 100% identical behavior preserved.

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app.utils.decorators import login_required, role_required
from app.models.log import log_change
from app.utils.time_utils import format_church, utc_now

from .queries import (
    get_user_tickets, get_open_user_ticket_count,
    get_all_tickets, get_open_ticket_count, get_staff_list,
    get_ticket, get_ticket_comments, get_ticket_categories,
    create_ticket, get_ticket_for_notification,
    add_ticket_comment, update_ticket_status, assign_ticket,
    update_ticket_priority, get_ticket_title, delete_ticket,
    get_ticket_manager_user_ids, add_to_ticket_managers,
    remove_from_ticket_managers, get_all_users
)
from .forms import (
    validate_ticket_submission, validate_ticket_comment,
    validate_status_update, validate_priority_update
)
from .utils import can_manage_tickets, send_ticket_notification


tickets_bp = Blueprint('tickets', __name__, url_prefix='/tickets')


# ----------------------------------------------------------------------
# Member view – "Tickets" tab (root URL – only own tickets)
# ----------------------------------------------------------------------
@tickets_bp.route('/')
def tickets():
    if not session.get('user_id'):
        flash('Please log in to view your tickets.', 'error')
        return redirect(url_for('auth.login'))

    user_id = session['user_id']
    tickets_list = get_user_tickets(user_id)

    # Format timestamps in church local time
    for t in tickets_list:
        if t['created_at']:
            t['formatted_created'] = format_church(t['created_at'], '%B %d, %Y at %I:%M %p')
        else:
            t['formatted_created'] = 'Unknown'
        if t['updated_at']:
            t['formatted_updated'] = format_church(t['updated_at'], '%B %d, %Y at %I:%M %p')
        else:
            t['formatted_updated'] = 'Never'

    open_count = get_open_user_ticket_count(user_id)

    log_change(user_id, 'view', change_details='Viewed own tickets list')

    return render_template('tickets/tickets_dashboard.html',
                           tickets=tickets_list,
                           open_count=open_count,
                           can_manage=can_manage_tickets(user_id))


# ----------------------------------------------------------------------
# Manager view – "Ticket Manager" (Owners/Admins OR group permission – all tickets)
# ----------------------------------------------------------------------
@tickets_bp.route('/manage', endpoint='manager_dashboard')
@login_required
def manager_dashboard():
    user_id = session['user_id']
    if not can_manage_tickets(user_id):
        flash('You do not have permission to access ticket management.', 'error')
        return redirect(url_for('tickets.tickets'))

    tickets_list = get_all_tickets()

    # Format timestamps in church local time
    for t in tickets_list:
        if t['created_at']:
            t['formatted_created'] = format_church(t['created_at'], '%B %d, %Y at %I:%M %p')
        else:
            t['formatted_created'] = 'Unknown'
        if t['updated_at']:
            t['formatted_updated'] = format_church(t['updated_at'], '%B %d, %Y at %I:%M %p')
        else:
            t['formatted_updated'] = 'Never'

    open_count = get_open_ticket_count()
    staff = get_staff_list()

    log_change(user_id, 'view', change_details='Viewed ticket manager dashboard')

    return render_template('tickets/ticket_manager.html',
                           tickets=tickets_list,
                           open_count=open_count,
                           staff=staff,
                           can_manage=True)


# ----------------------------------------------------------------------
# Manage Ticket Managers Group – Admin/Owner only
# ----------------------------------------------------------------------
@tickets_bp.route('/manage-group', methods=['GET', 'POST'], endpoint='manage_group')
@login_required
@role_required(['Admin', 'Owner'])
def manage_group():
    """Admin/Owner page to add/remove users from the dedicated ticket_managers group."""
    all_users = get_all_users()
    manager_ids = get_ticket_manager_user_ids()

    if request.method == 'POST':
        action = request.form.get('action')
        user_id = request.form.get('user_id')

        if action == 'add':
            add_to_ticket_managers(user_id)
        elif action == 'remove':
            remove_from_ticket_managers(user_id)

        flash('Ticket Managers group updated.', 'success')
        return redirect(url_for('tickets.manage_group'))

    return render_template('tickets/ticket_managers.html',
                           all_users=all_users,
                           manager_ids=manager_ids)


# ----------------------------------------------------------------------
# Submit Ticket – public guest + private member
# ----------------------------------------------------------------------
@tickets_bp.route('/submit', methods=['GET', 'POST'], endpoint='submit_ticket')
def submit_ticket():
    is_logged_in = 'user_id' in session
    user_id = session.get('user_id')

    categories = get_ticket_categories(allow_guest_only=not is_logged_in)

    if not categories and not is_logged_in:
        flash('Guest submissions are currently disabled.', 'error')
        return redirect(url_for('public.public_dashboard'))

    if request.method == 'POST':
        is_valid, errors, cleaned = validate_ticket_submission(request.form, is_logged_in)

        if not is_valid:
            for err in errors:
                flash(err, 'error')
            return render_template('tickets/submit_ticket.html',
                                   categories=categories,
                                   is_logged_in=is_logged_in)

        title = cleaned['title']
        description = cleaned['description']
        category_id = cleaned['category_id']
        priority = cleaned['priority']
        contact_name = cleaned['contact_name']
        contact_email = cleaned['contact_email']

        ip_address = request.remote_addr if not is_logged_in else None
        created_at_utc = utc_now()

        ticket_id = create_ticket(
            title, description, category_id, priority,
            user_id if is_logged_in else None,
            contact_name, contact_email, ip_address, created_at_utc
        )

        ticket = get_ticket_for_notification(ticket_id)

        subject = f"New Support Ticket #{ticket_id}: {title}"
        body = f"""
A new ticket has been submitted.

Title: {title}
Category: {ticket['category_name']}
Priority: {priority.capitalize()}
Submitted by: {contact_name or session.get('username', 'Member')}

Description:
{description}
        """
        send_ticket_notification(ticket, subject, body, notify_staff=True)

        log_change(
            user_id if is_logged_in else None,
            'create',
            ticket_id,
            title,
            'Guest ticket submitted' if not is_logged_in else 'Ticket created'
        )

        flash('Ticket submitted successfully! We will respond soon.', 'success')
        return redirect(url_for('tickets.tickets') if is_logged_in else url_for('public.public_dashboard'))

    return render_template('tickets/submit_ticket.html',
                           categories=categories,
                           is_logged_in=is_logged_in)


# ----------------------------------------------------------------------
# View / Manage Individual Ticket
# ----------------------------------------------------------------------
@tickets_bp.route('/<int:ticket_id>', methods=['GET', 'POST'], endpoint='view_ticket')
@login_required
def view_ticket(ticket_id):
    ticket = get_ticket(ticket_id)
    if not ticket:
        flash('Ticket not found.', 'error')
        return redirect(url_for('tickets.tickets'))

    if ticket['created_by'] != session['user_id'] and not can_manage_tickets(session['user_id']):
        flash('Access denied.', 'error')
        return redirect(url_for('tickets.tickets'))

    can_manage = can_manage_tickets(session['user_id'])

    # Format ticket timestamps in church local time
    if ticket['created_at']:
        ticket['formatted_created'] = format_church(ticket['created_at'], '%B %d, %Y at %I:%M %p')
    else:
        ticket['formatted_created'] = 'Unknown'
    if ticket['updated_at']:
        ticket['formatted_updated'] = format_church(ticket['updated_at'], '%B %d, %Y at %I:%M %p')
    else:
        ticket['formatted_updated'] = 'Never'

    comments = get_ticket_comments(ticket_id)

    # Format comment timestamps in church local time
    for c in comments:
        if c['date_added']:
            c['formatted_date'] = format_church(c['date_added'], '%B %d, %Y at %I:%M %p')
        else:
            c['formatted_date'] = 'Unknown'

    staff = get_staff_list()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'comment':
            is_valid, errors, cleaned = validate_ticket_comment(request.form, can_manage)
            if not is_valid:
                for err in errors:
                    flash(err, 'error')
            else:
                comment_time_utc = utc_now()
                add_ticket_comment(
                    ticket_id,
                    session['user_id'],
                    cleaned['comment'],
                    cleaned['notify_creator'],
                    comment_time_utc
                )

                if can_manage and cleaned['notify_creator']:
                    subject = f"Update on Ticket #{ticket_id}: {ticket['title']}"
                    body = f"Staff member {session['username']} added a comment:\n\n{cleaned['comment']}"
                    send_ticket_notification(ticket, subject, body, notify_creator=True)
                elif not can_manage:
                    subject = f"Member comment on Ticket #{ticket_id}: {ticket['title']}"
                    body = f"Member {session['username']} added a comment:\n\n{cleaned['comment']}"
                    send_ticket_notification(ticket, subject, body, notify_staff=True)

                log_change(session['user_id'], 'comment', ticket_id, change_details='Added comment')
                flash('Comment added.', 'success')

        elif action in ['status', 'assign', 'priority'] and can_manage:
            updated = False
            message = ""
            update_time_utc = utc_now()

            if action == 'status':
                is_valid, err = validate_status_update(request.form)
                if not is_valid:
                    flash(err, 'error')
                else:
                    new_status = request.form.get('status')
                    old_status = ticket['status']
                    update_ticket_status(ticket_id, new_status, update_time_utc)
                    ticket['status'] = new_status
                    updated = True
                    message = f"Status changed to {new_status.replace('_', ' ').title()}"
                    log_change(session['user_id'], 'update', ticket_id,
                               change_details=f'Status {old_status} → {new_status}')

                    if new_status in ['resolved', 'closed']:
                        subject = f"Ticket #{ticket_id} {new_status.capitalize()}: {ticket['title']}"
                        body = f"Your ticket has been {new_status}. Thank you!"
                        send_ticket_notification(ticket, subject, body, always_creator=True)

            elif action == 'assign':
                assigned_to = request.form.get('assigned_to') or None
                assign_ticket(ticket_id, assigned_to, update_time_utc)
                assignee = 'unassigned' if not assigned_to else next(
                    (s['username'] for s in staff if str(s['id']) == assigned_to), 'unknown'
                )
                updated = True
                message = f"Assigned to {assignee}"
                log_change(session['user_id'], 'assign', ticket_id,
                           change_details=f'Assigned to {assignee}')

            elif action == 'priority':
                is_valid, err = validate_priority_update(request.form)
                if not is_valid:
                    flash(err, 'error')
                else:
                    new_pri = request.form.get('priority')
                    update_ticket_priority(ticket_id, new_pri, update_time_utc)
                    ticket['priority'] = new_pri
                    updated = True
                    message = f"Priority changed to {new_pri.capitalize()}"
                    log_change(session['user_id'], 'update', ticket_id,
                               change_details=f'Priority → {new_pri}')

            if updated and ticket['status'] not in ['resolved', 'closed']:
                subject = f"Update on Ticket #{ticket_id}: {ticket['title']}"
                body = f"Staff has updated your ticket:\n{message}"
                send_ticket_notification(ticket, subject, body, notify_creator=True)

            if updated:
                flash('Ticket updated.', 'success')

        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    log_change(session['user_id'], 'view', ticket_id, change_details=f"Viewed ticket #{ticket_id}")

    return render_template('tickets/view_ticket.html',
                           ticket=ticket,
                           comments=comments,
                           staff=staff,
                           can_manage=can_manage)


# ----------------------------------------------------------------------
# Delete Ticket – Admin/Owner only
# ----------------------------------------------------------------------
@tickets_bp.route('/delete/<int:ticket_id>', methods=['POST'], endpoint='delete_ticket')
@login_required
@role_required(['Admin', 'Owner'])
def delete_ticket(ticket_id):
    title = get_ticket_title(ticket_id)
    if not title:
        flash('Ticket not found.', 'error')
        return redirect(url_for('tickets.tickets'))

    delete_ticket(ticket_id)

    log_change(session['user_id'], 'delete', ticket_id, title, 'Deleted ticket')
    flash('Ticket deleted permanently.', 'success')
    return redirect(url_for('tickets.tickets'))