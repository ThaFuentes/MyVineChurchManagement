# app/routes/tickets/utils.py
# Full path: myvinechurchonline/app/routes/tickets/utils.py
# File name: utils.py
# Brief, detailed purpose: Constants (none in this module) + small helper functions for the tickets blueprint.
# 100% identical behavior: permission checks (session + groups), email notification orchestration.
# All DB calls delegated to .queries. utc_now() assumed to be in app.utils.time_utils (used in views).

from flask import session
from app.utils.emailer import send_email
from .queries import (
    user_has_manage_tickets_group_permission,
    get_staff_emails,
    get_creator_email,
    get_ticket_for_notification
)


def can_manage_tickets(user_id):
    """Return True if user is Owner/Admin OR belongs to any group with 'manage_tickets' permission.
    Exact original logic preserved."""
    if session.get('user_role') in ['Owner', 'Admin']:
        return True
    return user_has_manage_tickets_group_permission(user_id)


def send_ticket_notification(ticket, subject, body, notify_staff=False, notify_creator=False, always_creator=False):
    """Orchestrate emails to staff and/or creator. Exact original behavior."""
    staff_emails = get_staff_emails() if notify_staff else []
    creator_email = get_creator_email(ticket) if (notify_creator or always_creator) else None

    emails = set()
    if staff_emails:
        emails.update(staff_emails)
    if creator_email:
        emails.add(creator_email)

    if not emails:
        return

    full_body = body + f"\n\nView ticket: https://myvinechurch.online/tickets/{ticket['id']}"

    for email in emails:
        send_email(email, subject, full_body)