# MYVINECHURCH.ONLINE/app/routes/the_gathering/dashboard/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/dashboard/views.py
# File name: views.py
# Brief, detailed purpose: Main dashboard routes and permission logic for the Gathering Place Manager.
# • Handles the primary dashboard view at /the_gathering/dashboard/ (overview, stats, recent activity).
# • Includes the gathering_place_required decorator (kept exactly as original for now – will be centralized later).
# • 100% rebuilt to match the exact clean, consistent style of public/events/views.py and public/dreams/views.py
#   (detailed section comments, enhanced docstrings, route structure, flash handling, and template rendering).
# • Original behavior, role checks, stats/recent queries, and template keys preserved 100%.

from flask import render_template, session, redirect, url_for, flash
import pymysql

from . import dashboard_bp
from .queries import get_dashboard_stats, get_recent_activity
from app.models.db import get_db


# ----------------------------------------------------------------------
# Permission Decorator (Gathering Place Manager Access Control)
# ----------------------------------------------------------------------
def gathering_place_required(f):
    """Decorator that enforces login + specific role access for the Gathering Place Manager.

    Allowed roles (exact original logic preserved):
    - staff, admin, owner
    - gathering place manager / gathering manager (or any role containing 'manager' or 'admin')
    Redirects unauthorized users back to main dashboard with flash message.
    """

    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access the Gathering Place Manager.', 'error')
            return redirect(url_for('auth.login'))

        try:
            db = get_db()
            cur = db.cursor(pymysql.cursors.DictCursor)
            cur.execute("SELECT role FROM users WHERE id = %s", (session['user_id'],))
            user = cur.fetchone()
            cur.close()
        except Exception:
            flash('Unable to verify permissions.', 'error')
            return redirect(url_for('dashboard.dashboard'))

        if not user:
            flash('User not found.', 'error')
            return redirect(url_for('dashboard.dashboard'))

        role = (user.get('role') or '').lower().strip()
        allowed = ('staff', 'admin', 'owner', 'gathering place manager', 'gathering manager')

        if role in allowed or 'manager' in role or 'admin' in role:
            return f(*args, **kwargs)

        flash('You do not have permission to access this section.', 'error')
        return redirect(url_for('dashboard.dashboard'))

    return decorated_function


# ----------------------------------------------------------------------
# Main Gathering Place Manager Dashboard
# ----------------------------------------------------------------------
@dashboard_bp.route('/')
@gathering_place_required
def dashboard():
    """Main dashboard view for the Gathering Place Manager.

    Loads summary statistics and recent activity feed.
    Renders the dedicated template with all original context variables.
    """
    stats = get_dashboard_stats()
    recent = get_recent_activity(limit=10)

    return render_template(
        'the-gathering/dashboard/dashboard.html',
        stats=stats,
        recent=recent,
        page_title="Gathering Place Manager"
    )


print("✅ MYVINECHURCH.ONLINE the_gathering/dashboard/views.py loaded successfully (public-style rebuilt)")