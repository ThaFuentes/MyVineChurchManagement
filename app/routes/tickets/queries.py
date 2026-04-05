# app/routes/tickets/queries.py
# Full path: myvinechurchonline/app/routes/tickets/queries.py
# File name: queries.py
# Brief, detailed purpose: All database operations (SELECT, INSERT, UPDATE, DELETE) for the tickets blueprint.
# MariaDB/PyMySQL ready (%s placeholders). Every query from original tickets.py extracted here.
# All timestamps (created_at/updated_at/date_added) expect UTC values. Behavior 100% identical.

import pymysql.cursors
import json
from app.models.db import get_db


def user_has_manage_tickets_group_permission(user_id):
    """Return True if user belongs to any group with 'manage_tickets' permission (DB part only)."""
    if not user_id:
        return False
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT g.permissions
        FROM groups g
        JOIN user_groups ug ON g.id = ug.group_id
        WHERE ug.user_id = %s
    """, (user_id,))
    rows = cur.fetchall()

    for row in rows:
        try:
            perms = json.loads(row['permissions'] or '[]')
            if 'manage_tickets' in perms:
                return True
        except (json.JSONDecodeError, TypeError):
            continue
    return False


def get_staff_emails():
    """Return list of staff/admin/owner emails who accept emails."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT email FROM users WHERE role IN ('Staff', 'Admin', 'Owner') AND accepts_emails = 1")
    return [row['email'] for row in cur.fetchall() if row.get('email')]


def get_creator_email(ticket):
    """Get creator email (handles registered user or guest contact_email)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    if ticket.get('created_by'):
        cur.execute("SELECT email FROM users WHERE id = %s", (ticket['created_by'],))
        row = cur.fetchone()
        return row['email'] if row and row.get('email') else None
    return ticket.get('contact_email')


def get_user_tickets(user_id):
    """Get all tickets created by user (for /tickets/ dashboard)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT t.*, c.name AS category_name
        FROM tickets t
        JOIN ticket_categories c ON t.category_id = c.id
        WHERE t.created_by = %s
        ORDER BY t.updated_at DESC
    """, (user_id,))
    return cur.fetchall()


def get_open_user_ticket_count(user_id):
    """Count open tickets for a specific user."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT COUNT(*) AS cnt
        FROM tickets
        WHERE created_by = %s AND status NOT IN ('resolved', 'closed')
    """, (user_id,))
    row = cur.fetchone()
    return row['cnt'] if row else 0


def get_all_tickets():
    """Get ALL tickets for manager dashboard with priority sorting."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT t.*, c.name AS category_name, 
               u.username AS creator_name, a.username AS assignee_name
        FROM tickets t
        JOIN ticket_categories c ON t.category_id = c.id
        LEFT JOIN users u ON t.created_by = u.id
        LEFT JOIN users a ON t.assigned_to = a.id
        ORDER BY 
            CASE t.priority 
                WHEN 'urgent' THEN 1 
                WHEN 'high' THEN 2 
                WHEN 'medium' THEN 3 
                WHEN 'low' THEN 4 
                ELSE 5 
            END ASC,
            t.created_at ASC
    """)
    return cur.fetchall()


def get_open_ticket_count():
    """Count ALL open tickets (for manager dashboard)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT COUNT(*) AS cnt FROM tickets WHERE status NOT IN ('resolved', 'closed')")
    row = cur.fetchone()
    return row['cnt'] if row else 0


def get_staff_list():
    """Get staff list for assignment dropdown."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT id, username FROM users WHERE role IN ('Staff', 'Admin', 'Owner') ORDER BY username")
    return cur.fetchall()


def get_ticket(ticket_id):
    """Get single ticket by ID (for view_ticket)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT t.*, c.name AS category_name,
               u.username AS creator_name, a.username AS assignee_name
        FROM tickets t
        JOIN ticket_categories c ON t.category_id = c.id
        LEFT JOIN users u ON t.created_by = u.id
        LEFT JOIN users a ON t.assigned_to = a.id
        WHERE t.id = %s
    """, (ticket_id,))
    return cur.fetchone()


def get_ticket_comments(ticket_id):
    """Get all comments for a ticket."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT tc.*, u.username
        FROM ticket_comments tc
        JOIN users u ON tc.user_id = u.id
        WHERE tc.ticket_id = %s
        ORDER BY tc.date_added ASC
    """, (ticket_id,))
    return cur.fetchall()


def get_ticket_categories(allow_guest_only=False):
    """Get ticket categories (filtered for guests if requested)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    if allow_guest_only:
        cur.execute("""
            SELECT id, name, default_priority 
            FROM ticket_categories 
            WHERE allow_guest_creation = 1 
            ORDER BY sort_order, name
        """)
    else:
        cur.execute("""
            SELECT id, name, default_priority 
            FROM ticket_categories 
            ORDER BY sort_order, name
        """)
    return cur.fetchall()


def create_ticket(title, description, category_id, priority, created_by=None,
                  contact_name=None, contact_email=None, ip_address=None, created_at=None):
    """Insert new ticket and return its ID."""
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO tickets (title, description, category_id, priority, status, created_by,
                             contact_name, contact_email, ip_address, created_at)
        VALUES (%s, %s, %s, %s, 'open', %s, %s, %s, %s, %s)
    """, (title, description, category_id, priority, created_by,
          contact_name, contact_email, ip_address, created_at))
    db.commit()
    return cur.lastrowid


def get_ticket_for_notification(ticket_id):
    """Get ticket + category for email notifications."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT t.*, c.name AS category_name
        FROM tickets t
        JOIN ticket_categories c ON t.category_id = c.id
        WHERE t.id = %s
    """, (ticket_id,))
    return cur.fetchone()


def add_ticket_comment(ticket_id, user_id, comment, notify_creator=False, date_added=None):
    """Insert new comment."""
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO ticket_comments (ticket_id, user_id, comment, notify_creator, date_added)
        VALUES (%s, %s, %s, %s, %s)
    """, (ticket_id, user_id, comment, 1 if notify_creator else 0, date_added))
    db.commit()


def update_ticket_status(ticket_id, new_status, updated_at):
    """Update status and timestamp."""
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE tickets SET status = %s, updated_at = %s WHERE id = %s",
                (new_status, updated_at, ticket_id))
    db.commit()


def assign_ticket(ticket_id, assigned_to, updated_at):
    """Assign ticket to staff member."""
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE tickets SET assigned_to = %s, updated_at = %s WHERE id = %s",
                (assigned_to, updated_at, ticket_id))
    db.commit()


def update_ticket_priority(ticket_id, new_priority, updated_at):
    """Update priority and timestamp."""
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE tickets SET priority = %s, updated_at = %s WHERE id = %s",
                (new_priority, updated_at, ticket_id))
    db.commit()


def get_ticket_title(ticket_id):
    """Get title only (used before delete)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT title FROM tickets WHERE id = %s", (ticket_id,))
    row = cur.fetchone()
    return row['title'] if row else None


def delete_ticket(ticket_id):
    """Permanently delete ticket."""
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM tickets WHERE id = %s", (ticket_id,))
    db.commit()


# ----------------------------------------------------------------------
# Ticket Managers Group (Admin/Owner only)
# ----------------------------------------------------------------------
def get_ticket_manager_user_ids():
    """Return list of user_ids currently in ticket_managers table."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT user_id FROM ticket_managers")
    return [row['user_id'] for row in cur.fetchall()]


def add_to_ticket_managers(user_id):
    """Add user to ticket_managers (IGNORE if already present)."""
    db = get_db()
    cur = db.cursor()
    cur.execute("INSERT OR IGNORE INTO ticket_managers (user_id) VALUES (%s)", (user_id,))
    db.commit()


def remove_from_ticket_managers(user_id):
    """Remove user from ticket_managers."""
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM ticket_managers WHERE user_id = %s", (user_id,))
    db.commit()


def get_all_users():
    """Get all users for manage-group page."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT id, username, first_name, last_name, role FROM users ORDER BY username")
    return cur.fetchall()