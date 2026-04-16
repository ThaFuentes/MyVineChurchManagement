# MYVINECHURCH.ONLINE/app/routes/public/public_dashboard/queries.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/public_dashboard/queries.py
# File name: queries.py
# Brief, detailed purpose: Reusable database query functions for the Public Dashboard (rich social-media style feed on homepage).
# • Provides get_public_dashboard_feed() – the full combined feed used on the public home page.
# • Also includes get_public_previews() for backward compatibility with any template that expects it.
# • Pure data-access layer – no Flask routes, no templates, no flash messages.
# • 100% original behavior from the old shared queries.py + rich feed logic preserved.

from app.models.db import get_db
import pymysql.cursors


def get_public_previews(limit=5):
    """Return limited public previews for the public dashboard (kept for any template compatibility)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    previews = {}

    # Upcoming Events
    try:
        cur.execute("""
            SELECT id, event_name AS title,
                   CONCAT(event_date, ' ', COALESCE(event_time, '')) AS datetime,
                   location
            FROM events
            WHERE visibility = 'public' 
              AND event_date >= CURDATE()
            ORDER BY event_date ASC, event_time ASC
            LIMIT %s
        """, (limit,))
        previews['events'] = cur.fetchall()
    except Exception:
        previews['events'] = []

    # Recent Prayers
    try:
        cur.execute("""
            SELECT title, date_posted AS datetime
            FROM prayers
            WHERE visibility = 'public'
            ORDER BY date_posted DESC
            LIMIT %s
        """, (limit,))
        previews['prayers'] = cur.fetchall()
    except Exception:
        previews['prayers'] = []

    # Recent Dreams & Visions
    try:
        cur.execute("""
            SELECT d.title, d.date_posted AS datetime,
                   COALESCE(u.username, d.contributor_name, 'Anonymous') AS posted_by
            FROM dreams d
            LEFT JOIN users u ON d.user_id = u.id
            WHERE d.visibility = 'public'
            ORDER BY d.date_posted DESC
            LIMIT %s
        """, (limit,))
        previews['dreams'] = cur.fetchall()
    except Exception:
        previews['dreams'] = []

    # Recent Prophecies
    try:
        cur.execute("""
            SELECT p.title, p.created_at AS datetime,
                   COALESCE(u.username, p.contributor_name, 'Anonymous') AS posted_by
            FROM prophecies p
            LEFT JOIN users u ON p.user_id = u.id
            WHERE p.visibility = 'public'
            ORDER BY p.created_at DESC
            LIMIT %s
        """, (limit,))
        previews['prophecies'] = cur.fetchall()
    except Exception:
        previews['prophecies'] = []

    # Recent Sermons
    try:
        cur.execute("""
            SELECT s.title, s.uploaded_at AS datetime,
                   COALESCE(u.username, 'Anonymous') AS posted_by
            FROM sermons s
            LEFT JOIN users u ON s.uploaded_by = u.id
            WHERE s.visibility = 'public'
            ORDER BY s.uploaded_at DESC
            LIMIT %s
        """, (limit,))
        previews['sermons'] = cur.fetchall()
    except Exception:
        previews['sermons'] = []

    # Recent Announcements
    try:
        cur.execute("""
            SELECT a.title, a.content, a.created_at AS datetime,
                   COALESCE(u.username, 'Anonymous') AS posted_by
            FROM announcements a
            LEFT JOIN users u ON a.created_by = u.id
            WHERE a.visibility = 'public' AND a.is_active = 1
            ORDER BY a.created_at DESC
            LIMIT %s
        """, (limit,))
        previews['announcements'] = cur.fetchall()
    except Exception:
        previews['announcements'] = []

    cur.close()
    return previews


def get_public_dashboard_feed():
    """Build the full rich social-media style dashboard feed (used on / and /public)."""
    feed = []
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    try:
        # Announcements
        cur.execute("""
            SELECT id, title, content, created_at
            FROM announcements
            WHERE visibility = 'public' AND is_active = 1
            ORDER BY created_at DESC
            LIMIT 8
        """)
        announcements = cur.fetchall()
        for a in announcements:
            a['type'] = 'announcement'
            a['body'] = a.get('content')
            a['datetime'] = a.get('created_at')
        feed.extend(announcements)

        # Events (upcoming only)
        cur.execute("""
            SELECT id, event_name AS title, event_date, description, created_at
            FROM events
            WHERE visibility = 'public' AND event_date >= CURDATE()
            ORDER BY event_date ASC, event_time ASC
            LIMIT 6
        """)
        events = cur.fetchall()
        for e in events:
            e['type'] = 'event'
            e['body'] = f"Event on {e.get('event_date')}"
            e['datetime'] = e.get('event_date')
        feed.extend(events)

        # Sermons
        cur.execute("""
            SELECT id, title, uploaded_at
            FROM sermons
            WHERE visibility = 'public'
            ORDER BY uploaded_at DESC
            LIMIT 6
        """)
        sermons = cur.fetchall()
        for s in sermons:
            s['type'] = 'sermon'
            s['body'] = None
            s['datetime'] = s.get('uploaded_at')
        feed.extend(sermons)

        # Prayers
        cur.execute("""
            SELECT id, title, date_posted
            FROM prayers
            WHERE visibility = 'public'
            ORDER BY date_posted DESC
            LIMIT 6
        """)
        prayers = cur.fetchall()
        for p in prayers:
            p['type'] = 'prayer'
            p['body'] = None
            p['datetime'] = p.get('date_posted')
        feed.extend(prayers)

        # Dreams
        cur.execute("""
            SELECT id, title, date_posted
            FROM dreams
            WHERE visibility = 'public'
            ORDER BY date_posted DESC
            LIMIT 6
        """)
        dreams = cur.fetchall()
        for d in dreams:
            d['type'] = 'dream'
            d['body'] = None
            d['datetime'] = d.get('date_posted')
        feed.extend(dreams)

        # Prophecies
        cur.execute("""
            SELECT id, title, created_at
            FROM prophecies
            WHERE visibility = 'public'
            ORDER BY created_at DESC
            LIMIT 6
        """)
        prophecies = cur.fetchall()
        for p in prophecies:
            p['type'] = 'prophecy'
            p['body'] = None
            p['datetime'] = p.get('created_at')
        feed.extend(prophecies)

        # Sort newest first
        feed.sort(key=lambda x: str(x.get('datetime') or '0000-00-00'), reverse=True)

    except Exception as e:
        print(f"❌ Public dashboard feed query error: {e}")

    cur.close()
    return feed[:30]   # limit to 30 items for the homepage feed


print("✅ MYVINECHURCH.ONLINE public/public_dashboard/queries.py loaded successfully")