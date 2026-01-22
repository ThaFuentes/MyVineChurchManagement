# app/routes/pastoral/planning.py
# Full path: WebChurchMan/app/routes/pastoral/planning.py
# File name: planning.py
# Brief, detailed purpose:
#   Blueprint for Service Planning within the Pastoral Area.
#   Provides:
#     - /planning/ → list all service plans (upcoming first – next closest at top)
#     - /planning/edit/<date_str> → view/edit/create a plan by date (upsert behavior)
#     - /planning/assignments/<int:plan_id> → AJAX endpoint to get/save role assignments
#     - /planning/delete/<date_str> → POST delete a service plan (with assignment cleanup)
#   All routes require @pastoral_required()
#   Delegates all DB work to app/models/pastoral/service_plans.py
#   Passes next_sunday_str, service_date (date object), today, assignable_users (Pastoral Group members),
#     linkable_sermons (visible sermons for dropdown), and assignments (existing role assignments)
#   Now fully supports start_time and worship_start_time editing with defaults (10:00 / 10:15)
#   RECURRENCE LOGIC:
#     - count > 0: create exactly that many future plans (limited series)
#     - count = 0: ongoing main service mode – always maintain 70 future instances (~1.3 years weekly) ahead from TODAY
#       On every save with count=0, it checks from today and adds missing plans to reach 70
#       This keeps main services always ~1.3 years ahead with no extra work – pastor just saves when updating (e.g., roles)
#       No cron needed – buffer topped up on normal saves
#   FUTURE COUNT DISPLAY: Shows how many future weekly plans exist and last date (for main weekly series)
#   Everything preserved from original code – no features lost, only enhanced for busy pastors
#   Endpoints: pastoral.planning.index, pastoral.planning.edit, pastoral.planning.delete
#   Fully rebuilt for consistency, correctness, and smoothness.

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime, timedelta
import calendar  # For monthly recurrence helper
import pymysql

from . import pastoral_required
from app.models.pastoral.service_plans import (
    get_all_service_plans,
    get_service_plan_by_date,
    create_or_update_service_plan,
    get_service_plan_assignments,
    save_service_plan_assignments
)
from app.models.pastoral.sermons import get_visible_sermons  # For linked sermon dropdown
from app.models.db import get_db
from app.models.log import log_change

planning_bp = Blueprint('planning', __name__, url_prefix='/planning')


def _load_assignable_users():
    """Load all members of the Pastoral Group for role assignment dropdown."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT u.id,
               CONCAT(u.first_name, ' ', u.last_name) AS full_name,
               u.username
        FROM users u
        JOIN user_groups ug ON u.id = ug.user_id
        JOIN groups g ON ug.group_id = g.id
        WHERE g.name = 'Pastoral Group'
        ORDER BY u.first_name, u.last_name
    """)
    return cur.fetchall()


# Helper for monthly recurrence
def add_months(source_date: datetime.date, months: int) -> datetime.date:
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day).date()


@planning_bp.route('/')
@pastoral_required()
def index():
    """Display list of all service plans with next Sunday suggestion."""
    plans = get_all_service_plans()

    # Calculate next Sunday for "New Service Plan" button
    today = datetime.today().date()
    days_to_sunday = (6 - today.weekday()) % 7
    if days_to_sunday == 0:  # Today is Sunday → use next week
        days_to_sunday = 7
    next_sunday = today + timedelta(days=days_to_sunday)
    next_sunday_str = next_sunday.strftime('%Y-%m-%d')

    return render_template(
        'pastoral/planning_list.html',
        plans=plans,
        next_sunday_str=next_sunday_str,
        today=today
    )


@planning_bp.route('/edit/<date_str>', methods=['GET', 'POST'])
@pastoral_required()
def edit(date_str: str):
    """Edit or create a service plan for a specific date (YYYY-MM-DD)."""
    user_id = session['user_id']

    try:
        service_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format.', 'error')
        return redirect(url_for('pastoral.planning.index'))

    plan = get_service_plan_by_date(date_str)
    assignable_users = _load_assignable_users()
    linkable_sermons = get_visible_sermons(user_id)
    assignments = get_service_plan_assignments(plan['id']) if plan else []

    # Detect existing future weekly plans for display (weekly only – for main services)
    future_count = 0
    last_future_date = None
    if plan:
        current = service_date_obj + timedelta(weeks=1)
        while True:
            next_str = current.strftime('%Y-%m-%d')
            if get_service_plan_by_date(next_str):
                future_count += 1
                last_future_date = current
                current += timedelta(weeks=1)
            else:
                break

    if request.method == 'POST':
        title = request.form.get('title', '').strip() or None
        notes = request.form.get('notes', '').strip() or None
        sermon_id = request.form.get('pastoral_sermon_id')
        sermon_id = int(sermon_id) if sermon_id and sermon_id.isdigit() else None
        start_time = request.form.get('start_time') or None
        worship_start_time = request.form.get('worship_start_time') or None

        data = {
            'service_date': date_str,
            'title': title,
            'notes': notes,
            'pastoral_sermon_id': sermon_id,
            'start_time': start_time,
            'worship_start_time': worship_start_time
        }

        # Save main plan (upsert)
        create_or_update_service_plan(data, user_id)

        # Reload plan to get fresh ID
        plan = get_service_plan_by_date(date_str)
        if not plan or not plan.get('id'):
            flash('Error: Could not retrieve plan ID after save.', 'error')
            return redirect(url_for('pastoral.planning.edit', date_str=date_str))
        plan_id = plan['id']

        # Save role assignments
        role_names = request.form.getlist('role_name')
        user_ids = request.form.getlist('user_id')

        assignments_to_save = []
        for i, role in enumerate(role_names):
            role = role.strip()
            if role:
                uid = None
                if i < len(user_ids) and user_ids[i]:
                    try:
                        uid = int(user_ids[i])
                    except ValueError:
                        pass
                assignments_to_save.append({'role_name': role, 'user_id': uid})

        save_service_plan_assignments(plan_id, assignments_to_save)

        # Recurrence handling
        if 'enable_recurrence' in request.form:
            freq = request.form.get('recurrence_freq', 'weekly')
            count_str = request.form.get('recurrence_count', '0')
            try:
                count = int(count_str)
            except ValueError:
                count = 0

            today = datetime.today().date()
            generated = 0

            if count == 0:
                # Ongoing main service mode: maintain 70 future instances (~1.3 years weekly) ahead from TODAY
                target_buffer = 70
            else:
                target_buffer = min(max(count, 1), 104)

            # Start from the next instance after today (based on this plan's weekday/frequency)
            current_date = service_date_obj
            # Advance to first future date
            while current_date <= today:
                if freq == 'monthly':
                    current_date = add_months(current_date, 1)
                elif freq == 'biweekly':
                    current_date += timedelta(weeks=2)
                else:
                    current_date += timedelta(weeks=1)

            instances = 0
            while instances < target_buffer:
                next_str = current_date.strftime('%Y-%m-%d')
                if get_service_plan_by_date(next_str) is None:
                    future_data = data.copy()
                    future_data['service_date'] = next_str
                    create_or_update_service_plan(future_data, user_id)
                    future_plan = get_service_plan_by_date(next_str)
                    if future_plan:
                        save_service_plan_assignments(future_plan['id'], assignments_to_save)
                        generated += 1

                instances += 1

                if freq == 'monthly':
                    current_date = add_months(current_date, 1)
                elif freq == 'biweekly':
                    current_date += timedelta(weeks=2)
                else:
                    current_date += timedelta(weeks=1)

            if generated:
                flash(f'Maintained ongoing buffer: created {generated} new future plans (~1.3 years ahead from today).', 'success')

        log_change(user_id, 'planning_save', plan_id, title or 'Service Plan', f'Saved plan for {date_str}')
        flash('Service plan saved successfully.', 'success')
        return redirect(url_for('pastoral.planning.edit', date_str=date_str))

    today = datetime.today().date()

    return render_template(
        'pastoral/planning_edit.html',
        plan=plan,
        date_str=date_str,
        service_date=service_date_obj,
        today=today,
        assignable_users=assignable_users,
        linkable_sermons=linkable_sermons,
        assignments=assignments,
        future_count=future_count,
        last_future_date=last_future_date
    )


@planning_bp.route('/assignments/<int:plan_id>', methods=['GET', 'POST'])
@pastoral_required()
def assignments(plan_id: int):
    """AJAX endpoint for role assignments (GET: fetch, POST: replace)."""
    if request.method == 'POST':
        assignments = request.get_json() or []
        try:
            save_service_plan_assignments(plan_id, assignments)
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400

    assignments = get_service_plan_assignments(plan_id)
    return jsonify(assignments)


@planning_bp.route('/delete/<date_str>', methods=['POST'])
@pastoral_required()
def delete(date_str):
    """Delete a service plan by date (permanent Sundays can be deleted – they will reseed on next init if needed)."""
    user_id = session['user_id']
    plan = get_service_plan_by_date(date_str)
    if not plan:
        flash('Service plan not found.', 'error')
        return redirect(url_for('pastoral.planning.index'))

    # Clear assignments first
    save_service_plan_assignments(plan['id'], [])

    # Delete plan
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM service_plans WHERE service_date = %s", (date_str,))
    db.commit()

    log_change(user_id, 'delete', None, plan.get('title') or 'Service Plan', f'Deleted plan for {date_str}')
    flash('Service plan deleted.', 'success')
    return redirect(url_for('pastoral.planning.index'))