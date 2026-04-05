# app/routes/bills/dashboard.py
# Full path: MyVineChurch/app/routes/bills/dashboard.py
# File name: dashboard.py
# Brief, detailed purpose: Bills dashboard listing (/bills).
# Managers see all bills with assigned count.
# Regular assigned users see only their assigned bills.
# Nice next due date formatting + passes is_manager flag.

from flask import render_template, session
from app.utils.decorators import login_required
from app.models.db import get_db
from app.models.log import log_change
from datetime import datetime, date
import pymysql

def register_dashboard_routes(bp):
    @bp.route('/')
    @login_required
    def bills():
        user_id = session['user_id']
        is_manager = session.get('user_role') in ['Staff', 'Admin', 'Owner']

        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

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
                WHERE a.user_id = %s
                ORDER BY b.next_due_date ASC, b.bill_name ASC
            """, (user_id,))

        bills_list = cur.fetchall()

        # Nice next due date formatting
        for b in bills_list:
            next_due = b.get('next_due_date')
            if next_due:
                try:
                    if isinstance(next_due, str):
                        due_date = datetime.strptime(next_due, '%Y-%m-%d').date()
                    elif isinstance(next_due, datetime):
                        due_date = next_due.date()
                    else:
                        due_date = next_due
                    b['nice_next_due'] = due_date.strftime('%A, %B %d, %Y')
                except Exception:
                    b['nice_next_due'] = 'Invalid date'
            else:
                b['nice_next_due'] = 'Not set'

        log_change(user_id, 'view', change_details='Viewed recurring bills dashboard')

        return render_template('bills/bills_dashboard.html',
                               bills=bills_list,
                               is_manager=is_manager)