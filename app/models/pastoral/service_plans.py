# app/models/pastoral/service_plans.py
# Full path: WebChurchMan/app/models/pastoral/service_plans.py
# File name: service_plans.py
# Brief, detailed purpose:
#   All database operations related to Service Planning module.
#   Handles:
#     - Listing all service plans with creator and linked sermon info
#     - Fetching a single plan by exact date
#     - Creating or updating a plan (upsert behavior keyed on service_date)
#     - Managing role assignments for a plan (full replace pattern: delete then insert)
#   No visibility enforcement needed (pastoral group only via routes/decorator).
#   Routes handle audit logging (log_change) and input validation/censorship separately.
#   Uses DictCursor for consistent dict results.
#   Parameterized queries for MariaDB / PyMySQL safety.

import pymysql
from app.models.db import get_db


# ----------------------------------------------------------------------
# Service Plans – Core CRUD / Upsert
# ----------------------------------------------------------------------
def get_all_service_plans():
    """
    Fetch all service plans, ordered by date descending.
    Includes creator username and linked sermon title (if any).

    Returns:
        list[dict]: All service plans with extra display fields
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT sp.*,
               u.username AS creator_name,
               ps.title   AS linked_sermon_title
        FROM service_plans sp
        JOIN users u ON sp.created_by = u.id
        LEFT JOIN pastoral_sermons ps ON sp.pastoral_sermon_id = ps.id
        ORDER BY sp.service_date DESC
    """)

    return cur.fetchall()


def get_service_plan_by_date(service_date):
    """
    Fetch a single service plan by its exact service date.
    Includes creator username and linked sermon title.

    Args:
        service_date (date or str): The service date (YYYY-MM-DD format)

    Returns:
        dict or None: Plan details if found
    """
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

    return cur.fetchone()


def create_or_update_service_plan(data, user_id):
    """
    Create a new service plan or update an existing one by service_date (upsert).

    Args:
        data (dict): Must contain 'service_date'; optional: title, notes, pastoral_sermon_id
        user_id (int): ID of the user creating/updating the plan

    Returns:
        int: The plan ID (new or existing)
    """
    db = get_db()
    cur = db.cursor()

    service_date = data['service_date']
    existing = get_service_plan_by_date(service_date)

    if existing:
        # Update existing plan
        cur.execute("""
            UPDATE service_plans
            SET title              = %s,
                notes              = %s,
                pastoral_sermon_id = %s,
                updated_at         = NOW()
            WHERE service_date = %s
        """, (
            data.get('title'),
            data.get('notes'),
            data.get('pastoral_sermon_id'),
            service_date
        ))
        plan_id = existing['id']
    else:
        # Create new plan
        cur.execute("""
            INSERT INTO service_plans (
                service_date, title, notes, pastoral_sermon_id, created_by
            ) VALUES (%s, %s, %s, %s, %s)
        """, (
            service_date,
            data.get('title'),
            data.get('notes'),
            data.get('pastoral_sermon_id'),
            user_id
        ))
        plan_id = cur.lastrowid

    db.commit()
    return plan_id


# ----------------------------------------------------------------------
# Service Plan Assignments (Role-Based Staffing)
# ----------------------------------------------------------------------
def get_service_plan_assignments(plan_id):
    """
    Fetch all role assignments for a specific service plan.

    Args:
        plan_id (int): ID of the service plan

    Returns:
        list[dict]: Assignments with role_name, user_id, username, first_name, last_name
    """
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
    """
    Replace all existing assignments for a plan with a new list.
    (Full replace pattern — delete then insert.)

    Args:
        plan_id (int): Service plan ID
        assignments (list[dict]): Each dict must have 'role_name' and 'user_id'
    """
    db = get_db()
    cur = db.cursor()

    # Clear existing assignments
    cur.execute("""
        DELETE FROM service_plan_assignments
        WHERE service_plan_id = %s
    """, (plan_id,))

    # Insert new ones
    for ass in assignments:
        cur.execute("""
            INSERT INTO service_plan_assignments (
                service_plan_id, role_name, user_id
            ) VALUES (%s, %s, %s)
        """, (plan_id, ass['role_name'], ass['user_id']))

    db.commit()