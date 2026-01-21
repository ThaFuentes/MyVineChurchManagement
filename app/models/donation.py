# myvinechurchonline/app/models/donation.py
# Full path: myvinechurchonline/app/models/donation.py
# File name: donation.py
# Brief, detailed purpose: Centralized, reusable database helpers for all donation operations in MariaDB.
# Handles member selector data, dashboard summaries, full CRUD, view-all with search/year filtering,
# detailed reports, and all export-related queries.
# All direct SQL lives here – routes only handle flow, permissions, logging, flashing, and rendering.
# Consistent use of pymysql.cursors.DictCursor → dict-like rows (row['column'] safe everywhere).
# Date field is TEXT ('YYYY-MM-DD'); STR_TO_DATE(date, '%%Y-%%m-%%d') for reliable parsing (%% escapes % for Python formatting).
# COALESCE on aggregates to guarantee values even with no rows.
# db.commit() added on all write operations for persistence.
# FULL REBUILD: Integrated timezone-aware current year calculation using now_church().
#   All existing functionality preserved exactly – only current_year source updated for consistency.

from app.models.db import get_db
from app.utils.time_utils import now_church  # Church local time for current year
import pymysql
from datetime import datetime
import traceback

# ------------------------------
# Member Selection Helpers
# ------------------------------
def get_members_for_selector():
    """Rich member data for form autocomplete/search (full name + contact details)."""
    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT first_name, last_name, email, phone, address
            FROM users 
            WHERE first_name IS NOT NULL AND last_name IS NOT NULL
            ORDER BY last_name, first_name
        """)
        rows = cur.fetchall()

        members = []
        for row in rows:
            full_name = f"{row['first_name'].strip()} {row['last_name'].strip()}"
            email = row['email'].strip() if row['email'] else ''
            phone = row['phone'].strip() if row['phone'] else ''
            address = row['address'].strip() if row['address'] else ''

            display = full_name
            if email or phone or address:
                parts = [p for p in [email, phone, address] if p]
                display += " — " + " • ".join(parts)

            search = f"{full_name} {email} {phone} {address}".lower()

            members.append({
                'value': full_name,
                'display': display,
                'search': search,
                'phone': phone,
                'address': address
            })
        return members
    except Exception as e:
        print(f"get_members_for_selector error: {e}\n{traceback.format_exc()}")
        return []


def get_member_for_export(member_id):
    """Member details for individual receipt exports."""
    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT first_name, last_name, phone, address
            FROM users 
            WHERE id = %s
        """, (member_id,))
        return cur.fetchone()
    except Exception as e:
        print(f"get_member_for_export error: {e}")
        return None


# ------------------------------
# Dashboard Helpers
# ------------------------------
def get_dashboard_data():
    """Total for current church local year + 10 most recent donations (dicts)."""
    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)
        current_year = now_church().year  # Church local current year (timezone-aware)

        cur.execute("""
            SELECT COALESCE(SUM(amount), 0.0) AS total_this_year
            FROM donations 
            WHERE YEAR(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s
        """, (current_year,))
        total_this_year = cur.fetchone()['total_this_year']

        cur.execute("""
            SELECT id, name, amount, date, method, notes,
                   confirmation_number, goods_services_provided
            FROM donations 
            ORDER BY STR_TO_DATE(date, '%%Y-%%m-%%d') DESC 
            LIMIT 10
        """)
        recent_donations = cur.fetchall()

        return float(total_this_year), recent_donations

    except Exception as e:
        print(f"get_dashboard_data error: {e}\n{traceback.format_exc()}")
        return 0.0, []


# ------------------------------
# CRUD Operations
# ------------------------------
def add_donation(name, amount, date, method, notes='', confirmation_number='', goods_services_provided=0):
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO donations 
            (name, amount, date, method, notes, confirmation_number, goods_services_provided)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (name, amount, date, method, notes or None, confirmation_number or None, goods_services_provided))
        db.commit()
    except Exception as e:
        print(f"add_donation error: {e}\n{traceback.format_exc()}")
        raise


def get_donation_by_id(donation_id):
    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT * FROM donations WHERE id = %s", (donation_id,))
        return cur.fetchone()
    except Exception as e:
        print(f"get_donation_by_id error: {e}")
        return None


def update_donation(donation_id, name, amount, date, method, notes=''):
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            UPDATE donations 
            SET name = %s, amount = %s, date = %s, method = %s, notes = %s
            WHERE id = %s
        """, (name, amount, date, method, notes or None, donation_id))
        db.commit()
    except Exception as e:
        print(f"update_donation error: {e}")
        raise


def delete_donation(donation_id):
    try:
        donation = get_donation_by_id(donation_id)
        if donation:
            db = get_db()
            cur = db.cursor()
            cur.execute("DELETE FROM donations WHERE id = %s", (donation_id,))
            db.commit()
        return donation
    except Exception as e:
        print(f"delete_donation error: {e}")
        return None


# ------------------------------
# View All Donations
# ------------------------------
def get_view_all_data(search_term='', selected_year=None):
    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

        sql_summary = """
            SELECT name, 
                   COALESCE(SUM(amount), 0.0) AS total_donations, 
                   COUNT(*) AS number_of_donations
            FROM donations 
            WHERE name LIKE %s
        """
        params = [f'%{search_term}%']
        if selected_year:
            sql_summary += " AND YEAR(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s"
            params.append(selected_year)
        sql_summary += " GROUP BY name ORDER BY MAX(STR_TO_DATE(date, '%%Y-%%m-%%d')) DESC"

        cur.execute(sql_summary, params)
        summary = cur.fetchall()

        detailed = {}
        for donor in summary:
            sql_detail = """
                SELECT id, date, amount, method, notes 
                FROM donations 
                WHERE name = %s
            """
            params_detail = [donor['name']]
            if selected_year:
                sql_detail += " AND YEAR(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s"
                params_detail.append(selected_year)
            sql_detail += " ORDER BY STR_TO_DATE(date, '%%Y-%%m-%%d') DESC"
            cur.execute(sql_detail, params_detail)
            detailed[donor['name']] = cur.fetchall()

        cur.execute("""
            SELECT DISTINCT YEAR(STR_TO_DATE(date, '%%Y-%%m-%%d')) AS year 
            FROM donations 
            ORDER BY year DESC
        """)
        years = [row['year'] for row in cur.fetchall() if row['year']]

        return summary, detailed, years

    except Exception as e:
        print(f"get_view_all_data error: {e}\n{traceback.format_exc()}")
        return [], {}, []


# ------------------------------
# Reports
# ------------------------------
def get_reports_data(selected_year, selected_month=None):
    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

        cur.execute("""
            SELECT DISTINCT YEAR(STR_TO_DATE(date, '%%Y-%%m-%%d')) AS year 
            FROM donations 
            ORDER BY year DESC
        """)
        years = [row['year'] for row in cur.fetchall()]

        month_names = ["January", "February", "March", "April", "May", "June",
                       "July", "August", "September", "October", "November", "December"]

        sql = """
            SELECT name, amount, date, method, notes 
            FROM donations 
            WHERE YEAR(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s
        """
        params = [selected_year]
        if selected_month:
            sql += " AND MONTH(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s"
            params.append(int(selected_month))
        sql += " ORDER BY STR_TO_DATE(date, '%%Y-%%m-%%d') DESC"
        cur.execute(sql, params)
        donations = cur.fetchall()

        cur.execute("""
            SELECT COALESCE(SUM(amount), 0.0) AS total_amount, 
                   COALESCE(COUNT(*), 0) AS total_count
            FROM donations 
            WHERE YEAR(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s
            AND (%s IS NULL OR MONTH(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s)
        """, (selected_year, selected_month, int(selected_month) if selected_month else None))
        totals = cur.fetchone()

        cur.execute("""
            SELECT method, 
                   COALESCE(SUM(amount), 0.0) AS total_amount, 
                   COALESCE(COUNT(*), 0) AS total_count
            FROM donations 
            WHERE YEAR(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s
            AND (%s IS NULL OR MONTH(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s)
            GROUP BY method 
            ORDER BY total_amount DESC
        """, (selected_year, selected_month, int(selected_month) if selected_month else None))
        donation_types = cur.fetchall()

        monthly_totals = []
        if not selected_month and selected_year:
            for m in range(1, 13):
                cur.execute("""
                    SELECT COALESCE(SUM(amount), 0.0) AS total_amount, COALESCE(COUNT(*), 0) AS total_count
                    FROM donations 
                    WHERE YEAR(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s 
                      AND MONTH(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s
                """, (selected_year, m))
                row = cur.fetchone()
                monthly_totals.append({
                    'month': month_names[m-1],
                    'total_amount': row['total_amount'],
                    'total_count': row['total_count']
                })

        return {
            'years': years,
            'donations': donations,
            'totals': totals,
            'donation_types': donation_types,
            'monthly_totals': monthly_totals
        }

    except Exception as e:
        print(f"get_reports_data error: {e}\n{traceback.format_exc()}")
        return {'years': [], 'donations': [], 'totals': {'total_amount': 0.0, 'total_count': 0},
                'donation_types': [], 'monthly_totals': []}


# ------------------------------
# Export Helpers
# ------------------------------
def get_export_years():
    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT DISTINCT YEAR(STR_TO_DATE(date, '%%Y-%%m-%%d')) AS year 
            FROM donations 
            ORDER BY year DESC
        """)
        years = [row['year'] for row in cur.fetchall() if row['year']]
        return years
    except Exception as e:
        print(f"get_export_years error: {e}")
        return []


def get_donations_for_export(name, year):
    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT date, amount, method, confirmation_number, notes, goods_services_provided
            FROM donations
            WHERE name = %s 
              AND YEAR(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s
            ORDER BY STR_TO_DATE(date, '%%Y-%%m-%%d') DESC
        """, (name, year))
        return cur.fetchall()
    except Exception as e:
        print(f"get_donations_for_export error: {e}")
        return []


def get_unique_donor_names(year):
    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT DISTINCT name 
            FROM donations 
            WHERE YEAR(STR_TO_DATE(date, '%%Y-%%m-%%d')) = %s
        """, (year,))
        names = [row['name'] for row in cur.fetchall()]
        return sorted(names)
    except Exception as e:
        print(f"get_unique_donor_names error: {e}")
        return []


def get_members_with_donations(year):
    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)
        cur.execute("""
            SELECT u.id, u.first_name, u.last_name
            FROM users u
            WHERE EXISTS (
                SELECT 1 FROM donations d
                WHERE d.name = CONCAT(u.first_name, ' ', u.last_name)
                  AND YEAR(STR_TO_DATE(d.date, '%%Y-%%m-%%d')) = %s
            )
            ORDER BY u.last_name, u.first_name
        """, (year,))
        members = [
            {'id': row['id'], 'first_name': row['first_name'], 'last_name': row['last_name']}
            for row in cur.fetchall()
        ]
        return members
    except Exception as e:
        print(f"get_members_with_donations error: {e}")
        return []