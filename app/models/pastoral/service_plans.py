# app/models/pastoral/service_plans.py
# Full path: WebChurchMan/app/models/pastoral/service_plans.py
# File name: service_plans.py
# Brief, detailed purpose:
#   All database operations related to Service Planning module.
#   Handles:
#     - Listing all service plans with creator and linked sermon info – UPCOMING FIRST (next closest at top)
#     - Fetching a single plan by exact date
#     - Creating or updating a plan (true upsert: UPDATE if exists, INSERT if new)
#     - Managing role assignments for a plan (full replace pattern: delete then insert)
#     - Returning the next upcoming service (real plan or fallback recurring Sunday with defaults)
#     - Seeding recurring Sunday plans for the next 52 weeks (idempotent, fully editable/deletable rows)
#   Now fully supports start_time and worship_start_time columns with sensible defaults (10:00 / 10:15).
#   UPDATED: Normalizes start_time / worship_start_time if PyMySQL returns timedelta (rare edge case for TIME columns)
#   NEW: Global default role assignments – pre-fill new plans, overridable per week
#   No visibility enforcement needed (pastoral group only via routes/decorator).
#   Routes handle audit logging (log_change) and input validation/censorship separately.
#   Uses DictCursor for consistent dict results.
#   Parameterized queries for MariaDB / PyMySQL safety.

import pymysql
from datetime import datetime, timedelta, time
from app.models.db import get_db


def _normalize_time(value):
    """
    Normalize TIME column values from DB.
    PyMySQL sometimes returns timedelta for TIME columns (especially if negative or edge cases).
    Convert to datetime.time if possible, preserve None.
    """
    if value is None:
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, timedelta):
        # Positive timedelta to time (ignore days, assume <24h)
        total_seconds = value.days * 86400 + value.seconds
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return time(hours % 24, minutes)
    return value  # Unexpected – leave as-is


# ----------------------------------------------------------------------
# Service Plans – Core CRUD / Upsert
# ----------------------------------------------------------------------
def get_all_service_plans():
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT sp.*,
               u.username AS creator_name,
               ps.title   AS linked_sermon_title
        FROM service_plans sp
        JOIN users u ON sp.created_by = u.id
        LEFT JOIN pastoral_sermons ps ON sp.pastoral_sermon_id = ps.id
        ORDER BY (sp.service_date >= CURRENT_DATE) DESC, sp.service_date ASC
    """)

    plans = cur.fetchall()

    # Normalize times in all plans
    for plan in plans:
        plan['start_time'] = _normalize_time(plan['start_time'])
        plan['worship_start_time'] = _normalize_time(plan['worship_start_time'])

    return plans


def get_service_plan_by_date(service_date):
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT sp.*,
               u.username AS creator_name,
               ps.title   AS linked_sermon_title
        FROM service_plans sp
        JOIN users u ON sp.created_by = u.id
        LEFT JOIN pastoral_sermons ps ON sp.pastoral_sermon_id = ps.id
        WHERE sp.service_date = %s
    """, (service_date,))

    plan = cur.fetchone()
    if plan:
        plan['start_time'] = _normalize_time(plan['start_time'])
        plan['worship_start_time'] = _normalize_time(plan['worship_start_time'])

    return plan


def create_or_update_service_plan(data: dict, user_id: int):
    db = get_db()
    cur = db.cursor()

    service_date = data['service_date']

    # Apply defaults for times if missing
    start_time = data.get('start_time') or '10:00'
    worship_start_time = data.get('worship_start_time') or '10:15'

    existing = get_service_plan_by_date(service_date)

    if existing:
        cur.execute("""
            UPDATE service_plans
            SET title               = %s,
                notes               = %s,
                pastoral_sermon_id  = %s,
                start_time          = %s,
                worship_start_time  = %s,
                updated_at          = CURRENT_TIMESTAMP
            WHERE service_date = %s
        """, (
            data.get('title'),
            data.get('notes'),
            data.get('pastoral_sermon_id'),
            start_time,
            worship_start_time,
            service_date
        ))
    else:
        cur.execute("""
            INSERT INTO service_plans (
                service_date, title, notes, pastoral_sermon_id,
                created_by, start_time, worship_start_time
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            service_date,
            data.get('title'),
            data.get('notes'),
            data.get('pastoral_sermon_id'),
            user_id,
            start_time,
            worship_start_time
        ))

    db.commit()


def get_upcoming_service():
    plan = get_service_plan_by_date(datetime.today().date().strftime('%Y-%m-%d'))
    if plan and plan['service_date'] >= datetime.today().date():
        return plan

    # Fallback to next Sunday
    today_dt = datetime.today()
    days_to_sunday = (6 - today_dt.weekday()) % 7
    if days_to_sunday == 0:
        days_to_sunday = 7
    next_sunday = today_dt + timedelta(days=days_to_sunday)

    return {
        'service_date': next_sunday.date(),
        'title': 'Regular Sunday Service',
        'start_time': time(10, 0),
        'worship_start_time': time(10, 15),
        'linked_sermon_title': None,
        'creator_name': None,
        'is_recurring_default': True
    }


# ----------------------------------------------------------------------
# Seeding recurring Sunday plans
# ----------------------------------------------------------------------
def seed_recurring_sunday_plans(weeks_ahead: int = 52):
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT id FROM users WHERE role = 'Owner' LIMIT 1")
    owner = cur.fetchone()
    if not owner:
        print("Warning: No Owner account found – cannot seed recurring plans.")
        return
    creator_id = owner['id']

    today = datetime.today().date()
    seeded = 0

    for i in range(1, weeks_ahead + 1):
        days_to_sunday = (6 - today.weekday()) % 7
        if days_to_sunday == 0:
            days_to_sunday = 7
        sunday = today + timedelta(days=days_to_sunday + (i - 1) * 7)
        date_str = sunday.strftime('%Y-%m-%d')

        if get_service_plan_by_date(date_str):
            continue

        cur.execute("""
            INSERT INTO service_plans (
                service_date, title, created_by, start_time, worship_start_time
            ) VALUES (%s, %s, %s, %s, %s)
        """, (date_str, "Sunday Service", creator_id, "10:00", "10:15"))
        seeded += 1

    db.commit()
    if seeded:
        print(f"Seeded {seeded} recurring Sunday service plans.")


# ----------------------------------------------------------------------
# Service Plan Assignments
# ----------------------------------------------------------------------
def get_service_plan_assignments(plan_id):
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT spa.*,
               u.username,
               u.first_name,
               u.last_name
        FROM service_plan_assignments spa
        LEFT JOIN users u ON spa.user_id = u.id
        WHERE spa.service_plan_id = %s
        ORDER BY spa.role_name
    """, (plan_id,))

    return cur.fetchall()


def save_service_plan_assignments(plan_id, assignments):
    db = get_db()
    cur = db.cursor()

    cur.execute("DELETE FROM service_plan_assignments WHERE service_plan_id = %s", (plan_id,))

    for ass in assignments:
        cur.execute("""
            INSERT INTO service_plan_assignments (
                service_plan_id, role_name, user_id
            ) VALUES (%s, %s, %s)
        """, (plan_id, ass['role_name'], ass.get('user_id')))

    db.commit()


# ----------------------------------------------------------------------
# Default Role Assignments (Global – pre-fill new plans)
# ----------------------------------------------------------------------
def get_default_assignments():
    """Fetch global default role assignments – used to pre-fill new service plans."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT role_name, user_id FROM default_service_plan_assignments ORDER BY role_name")
    rows = cur.fetchall()
    # Ensure at least one empty row for the form
    if not rows:
        rows = [{'role_name': '', 'user_id': None}]
    return rows


def save_default_assignments(assignments):
    """Save global default role assignments (full replace)."""
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM default_service_plan_assignments")
    for ass in assignments:
        if ass['role_name'].strip():
            cur.execute("""
                INSERT INTO default_service_plan_assignments (role_name, user_id)
                VALUES (%s, %s)
            """, (ass['role_name'], ass['user_id']))
    db.commit()