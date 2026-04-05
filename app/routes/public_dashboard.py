# app/routes/public_dashboard.py
# Full path: WebChurchMan/app/routes/public_dashboard.py
# File name: public_dashboard.py
# Brief, detailed purpose: Blueprint for the PUBLIC dashboard (welcome page for guests).
# Route '/' – root URL shown to all visitors (logged-in or not).
# Displays ONLY public-visibility content (prayers, dreams, prophecies, sermons, announcements, upcoming events).
# No @login_required – fully accessible to guests.
# Completely separate from private dashboard (dashboard.py at '/dashboard').
# Logged-in users can visit '/' to see the public view.
# Blueprint name changed to 'public' to match existing url_for('public.public_dashboard') calls (e.g., logout redirect).
# FULL REBUILD: Cleaned variable typo in sermons loop, added safe datetime import for event_time parsing,
#   consistent church-local timezone formatting, robust None handling, server-side censorship.

from flask import Blueprint, render_template
from datetime import datetime
from app.models.db import get_db
from app.utils.helpers import censor_text
from app.utils.time_utils import now_church, format_church
import pymysql

public_bp = Blueprint('public', __name__)  # Name matches expected url_for('public.public_dashboard')


@public_bp.route('/')
def public_dashboard():
    """
    Public welcome dashboard – site root.
    Shows recent public content and upcoming public events.
    Accessible to everyone (guests and logged-in).
    All user-generated text censored server-side.
    Times displayed in church local timezone.
    """
    prayers = []
    dreams = []
    prophecies = []
    sermons = []
    announcements = []
    events = []

    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

        # Recent Public Prayers
        cur.execute("""
            SELECT title, date_posted AS post_datetime
            FROM prayers
            WHERE visibility = 'public'
            ORDER BY date_posted DESC
            LIMIT 5
        """)
        prayers = cur.fetchall()
        for item in prayers:
            item['title'] = censor_text(item['title'])
            dt = item.get('post_datetime')
            if dt:
                item['formatted_date'] = format_church(dt, '%B %d, %Y')
                item['formatted_time'] = format_church(dt, '%I:%M %p')
            else:
                item['formatted_date'] = 'Unknown date'
                item['formatted_time'] = ''

        # Recent Public Dreams & Visions
        cur.execute("""
            SELECT title, date_posted AS post_datetime
            FROM dreams
            WHERE visibility = 'public'
            ORDER BY date_posted DESC
            LIMIT 5
        """)
        dreams = cur.fetchall()
        for item in dreams:
            item['title'] = censor_text(item['title'])
            dt = item.get('post_datetime')
            if dt:
                item['formatted_date'] = format_church(dt, '%B %d, %Y')
                item['formatted_time'] = format_church(dt, '%I:%M %p')
            else:
                item['formatted_date'] = 'Unknown date'
                item['formatted_time'] = ''

        # Recent Public Prophecies
        cur.execute("""
            SELECT title, created_at AS post_datetime
            FROM prophecies
            WHERE visibility = 'public'
            ORDER BY created_at DESC
            LIMIT 5
        """)
        prophecies = cur.fetchall()
        for item in prophecies:
            item['title'] = censor_text(item['title'])
            dt = item.get('post_datetime')
            if dt:
                item['formatted_date'] = format_church(dt, '%B %d, %Y')
                item['formatted_time'] = format_church(dt, '%I:%M %p')
            else:
                item['formatted_date'] = 'Unknown date'
                item['formatted_time'] = ''

        # Recent Public Sermons
        cur.execute("""
            SELECT title, uploaded_at AS post_datetime
            FROM sermons
            WHERE visibility = 'public'
            ORDER BY uploaded_at DESC
            LIMIT 5
        """)
        sermons = cur.fetchall()
        for item in sermons:
            item['title'] = censor_text(item['title'])
            dt = item.get('post_datetime')
            if dt:
                item['formatted_date'] = format_church(dt, '%B %d, %Y')
                item['formatted_time'] = format_church(dt, '%I:%M %p')
            else:
                item['formatted_date'] = 'Unknown date'
                item['formatted_time'] = ''

        # Active Public Announcements
        cur.execute("""
            SELECT title, content, created_at AS post_datetime
            FROM announcements
            WHERE visibility = 'public' AND is_active = 1
            ORDER BY created_at DESC
            LIMIT 10
        """)
        announcements = cur.fetchall()
        for item in announcements:
            item['title'] = censor_text(item['title'])
            item['content'] = censor_text(item['content'])
            dt = item.get('post_datetime')
            if dt:
                item['formatted_date'] = format_church(dt, '%B %d, %Y')
                item['formatted_time'] = format_church(dt, '%I:%M %p')
            else:
                item['formatted_date'] = 'Unknown date'
                item['formatted_time'] = ''

        # Upcoming Public Events (starting today in church local time)
        today_local = now_church().date()
        today_str = today_local.strftime('%Y-%m-%d')

        cur.execute("""
            SELECT event_name AS title, event_date, event_time, location
            FROM events
            WHERE visibility = 'public' AND event_date >= %s
            ORDER BY event_date ASC, event_time ASC
            LIMIT 5
        """, (today_str,))
        events = cur.fetchall()
        for item in events:
            item['title'] = censor_text(item['title'])
            item['location'] = censor_text(item.get('location') or '')

            if item['event_date']:
                item['formatted_date'] = item['event_date'].strftime('%A, %B %d, %Y')

                if item['event_time']:
                    try:
                        time_obj = datetime.strptime(item['event_time'], '%H:%M:%S')
                        item['formatted_time'] = time_obj.strftime('%I:%M %p')
                    except (ValueError, TypeError):
                        item['formatted_time'] = 'Time not set'
                    item['formatted_full'] = f"{item['formatted_date']} at {item['formatted_time']}"
                else:
                    item['formatted_time'] = 'All Day'
                    item['formatted_full'] = item['formatted_date']
            else:
                item['formatted_date'] = 'Date not set'
                item['formatted_time'] = ''
                item['formatted_full'] = 'Date not set'

    except Exception as e:
        print(f"Public dashboard error: {e}")

    return render_template(
        'public/public_dashboard.html',
        prayers=prayers,
        dreams=dreams,
        prophecies=prophecies,
        sermons=sermons,
        announcements=announcements,
        events=events
    )