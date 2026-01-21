# app/routes/public_dashboard.py
# Full path: WebChurchMan/app/routes/public_dashboard.py
# File name: public_dashboard.py
# Brief, detailed purpose: Blueprint for the PUBLIC dashboard (welcome page for guests).
# Route '/' – shown at root URL to all visitors (logged-in or not).
# Displays ONLY public-visibility content (prayers, dreams, prophecies, sermons, announcements, upcoming events).
# No @login_required – fully accessible to guests.
# Completely separate from private dashboard (dashboard.py at '/dashboard').
# Logged-in users can still visit '/' if they want the public view.
# FULL REBUILD: Integrated timezone-aware handling.
#   - "Today" for upcoming events uses church local time (now_church()).
#   - All datetime fields from DB (assumed UTC) formatted with format_church() for church local display.
#   - Added 'formatted_date' and 'formatted_time' to each item for template use.
#   - Events: separate event_date/event_time handling with church local formatting.
#   - All existing functionality (public visibility, censorship, robust error handling) preserved exactly.

from flask import Blueprint, render_template
from app.models.db import get_db
from app.utils.helpers import censor_text
from app.utils.time_utils import now_church, format_church
import pymysql

public_dashboard_bp = Blueprint('public_dashboard', __name__)


@public_dashboard_bp.route('/')
def public_dashboard():
    """
    Public welcome dashboard – root URL for the site.
    Shows public recent content and upcoming public events.
    Visible to everyone (guests and logged-in).
    All user-generated text censored server-side for safe display.
    Times displayed in church local timezone (UTC storage assumed).
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

        # Public Recent Prayers (last 5)
        cur.execute("""
            SELECT title, date_posted AS datetime
            FROM prayers
            WHERE visibility = 'public'
            ORDER BY date_posted DESC
            LIMIT 5
        """)
        prayers = cur.fetchall()
        for p in prayers:
            p['title'] = censor_text(p['title'])
            if p['datetime']:
                p['formatted_date'] = format_church(p['datetime'], '%B %d, %Y')
                p['formatted_time'] = format_church(p['datetime'], '%I:%M %p')
            else:
                p['formatted_date'] = 'Unknown'
                p['formatted_time'] = ''

        # Public Recent Dreams & Visions
        cur.execute("""
            SELECT title, date_posted AS datetime
            FROM dreams
            WHERE visibility = 'public'
            ORDER BY date_posted DESC
            LIMIT 5
        """)
        dreams = cur.fetchall()
        for d in dreams:
            d['title'] = censor_text(d['title'])
            if d['datetime']:
                d['formatted_date'] = format_church(d['datetime'], '%B %d, %Y')
                d['formatted_time'] = format_church(d['datetime'], '%I:%M %p')
            else:
                d['formatted_date'] = 'Unknown'
                d['formatted_time'] = ''

        # Public Recent Prophecies
        cur.execute("""
            SELECT title, created_at AS datetime
            FROM prophecies
            WHERE visibility = 'public'
            ORDER BY created_at DESC
            LIMIT 5
        """)
        prophecies = cur.fetchall()
        for p in prophecies:
            p['title'] = censor_text(p['title'])
            if p['datetime']:
                p['formatted_date'] = format_church(p['datetime'], '%B %d, %Y')
                p['formatted_time'] = format_church(p['datetime'], '%I:%M %p')
            else:
                p['formatted_date'] = 'Unknown'
                p['formatted_time'] = ''

        # Public Recent Sermons
        cur.execute("""
            SELECT title, uploaded_at AS datetime
            FROM sermons
            WHERE visibility = 'public'
            ORDER BY uploaded_at DESC
            LIMIT 5
        """)
        sermons = cur.fetchall()
        for s in sermons:
            s['title'] = censor_text(s['title'])
            if s['datetime']:
                p['formatted_date'] = format_church(s['datetime'], '%B %d, %Y')
                p['formatted_time'] = format_church(s['datetime'], '%I:%M %p')
            else:
                s['formatted_date'] = 'Unknown'
                s['formatted_time'] = ''

        # Public Active Announcements
        cur.execute("""
            SELECT title, created_at AS datetime, content
            FROM announcements
            WHERE visibility = 'public' AND is_active = 1
            ORDER BY created_at DESC
            LIMIT 10
        """)
        announcements = cur.fetchall()
        for a in announcements:
            a['title'] = censor_text(a['title'])
            a['content'] = censor_text(a['content'])
            if a['datetime']:
                a['formatted_date'] = format_church(a['datetime'], '%B %d, %Y')
                a['formatted_time'] = format_church(a['datetime'], '%I:%M %p')
            else:
                a['formatted_date'] = 'Unknown'
                a['formatted_time'] = ''

        # Public Upcoming Events (church local "today")
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
        for e in events:
            e['title'] = censor_text(e['title'])
            e['location'] = censor_text(e.get('location', ''))
            if e['event_date']:
                e['formatted_date'] = e['event_date'].strftime('%A, %B %d, %Y')
                if e['event_time']:
                    time_obj = datetime.strptime(e['event_time'], '%H:%M:%S')
                    e['formatted_time'] = time_obj.strftime('%I:%M %p')
                    e['formatted_full'] = f"{e['formatted_date']} at {e['formatted_time']}"
                else:
                    e['formatted_time'] = 'All Day'
                    e['formatted_full'] = e['formatted_date']
            else:
                e['formatted_date'] = 'Date not set'
                e['formatted_time'] = ''
                e['formatted_full'] = 'Date not set'

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