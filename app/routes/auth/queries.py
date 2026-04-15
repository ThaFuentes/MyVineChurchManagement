# app/routes/auth/queries.py
# Full path: MyVineChurch/app/routes/auth/queries.py
# File name: queries.py
# Brief, detailed purpose: All database queries and operations for the Auth module.
# • Pure data-access layer – no Flask routes, no templates, no flash messages.
# • Every SELECT/INSERT/UPDATE from the original auth.py is now here.
# • 100% MariaDB/pymysql compatible, parameterized, reusable functions.
# • Designed for easy growth – add new query functions anytime without touching views.

import pymysql
from app.models.db import get_db


# ----------------------------------------------------------------------
# User Count & First-User Logic
# ----------------------------------------------------------------------
def get_total_user_count():
    """Return total number of users in the system (used to decide Owner vs pending)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute('SELECT COUNT(*) AS total FROM users')
    result = cur.fetchone()
    return result['total'] if result else 0


# ----------------------------------------------------------------------
# Lookup Users
# ----------------------------------------------------------------------
def get_user_by_username(username):
    """Return full user row for login (or None)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute('SELECT * FROM users WHERE username = %s', (username,))
    return cur.fetchone()


def get_user_by_email(email):
    """Return user row by email (used for password reset & forgot username)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute('SELECT id, username FROM users WHERE email = %s', (email,))
    return cur.fetchone()


# ----------------------------------------------------------------------
# Create & Update
# ----------------------------------------------------------------------
def create_new_user(first_name, last_name, email, phone, address, birthday,
                    username, hashed_password, role, needs_approval,
                    accepts_emails, show_birthday):
    """Insert new user. Returns new user ID or raises on error."""
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute('''
            INSERT INTO users 
            (first_name, last_name, email, phone, address, birthday, username, password,
             role, needs_approval, accepts_emails, show_birthday)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (first_name, last_name, email, phone, address, birthday, username,
              hashed_password, role, needs_approval, accepts_emails, show_birthday))
        db.commit()
        return cur.lastrowid
    except Exception as e:
        db.rollback()
        print(f"Create new user error: {e}")  # For debugging during rebuild
        raise


def update_user_password(user_id, hashed_password):
    """Update password (used for reset code)."""
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute('UPDATE users SET password = %s WHERE id = %s',
                    (hashed_password, user_id))
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"Update user password error: {e}")
        raise