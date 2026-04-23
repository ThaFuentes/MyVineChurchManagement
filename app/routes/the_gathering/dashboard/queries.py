# MYVINECHURCH.ONLINE/app/routes/the_gathering/dashboard/queries.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/dashboard/queries.py
# File name: queries.py
# Brief, detailed purpose: Reusable database query functions specifically for the main Gathering Place Manager Dashboard.
# • Provides summary statistics (counts across all major content types) and recent activity feed.
# • 100% rebuilt to match the exact clean, safe, and consistent style of public/events/queries.py and public/dreams/queries.py.
# • All queries are parameterized, use DictCursor, and follow the public gold standard (no f-strings in SQL, detailed docstrings, cursor always closed).
# • Original behavior, table names, column aliases, and return values preserved 100%.

from app.models.db import get_db
import pymysql.cursors


def get_dashboard_stats():
    """
    Retrieve overall summary counts for the Gathering Place Manager dashboard.
    Counts total + public events, plus totals for prayers, sermons, dreams,
    prophecies, and announcements. Exact same queries and keys as the original version.
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    stats = {}

    # Events
    cur.execute("SELECT COUNT(*) AS count FROM events")
    stats['total_events'] = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) AS count FROM events WHERE visibility = 'public'")
    stats['public_events'] = cur.fetchone()['count']

    # Prayers
    cur.execute("SELECT COUNT(*) AS count FROM prayers")
    stats['total_prayers'] = cur.fetchone()['count']

    # Sermons
    cur.execute("SELECT COUNT(*) AS count FROM sermons")
    stats['total_sermons'] = cur.fetchone()['count']

    # Dreams
    cur.execute("SELECT COUNT(*) AS count FROM dreams")
    stats['total_dreams'] = cur.fetchone()['count']

    # Prophecies
    cur.execute("SELECT COUNT(*) AS count FROM prophecies")
    stats['total_prophecies'] = cur.fetchone()['count']

    # Announcements
    cur.execute("SELECT COUNT(*) AS count FROM announcements")
    stats['total_announcements'] = cur.fetchone()['count']

    cur.close()
    return stats


def get_recent_activity(limit=10):
    """
    Retrieve recent activity across major sections for the dashboard feed.
    Uses UNION ALL (exact same logic as original) and is now fully parameterized.
    Ordered by created_at DESC. Supports configurable limit for future flexibility.
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Combine recent items from multiple tables (simple version – exact original tables/columns)
    cur.execute("""
        SELECT 'event' AS type, id, event_name AS title, created_at
        FROM events
        UNION ALL
        SELECT 'prayer' AS type, id, title, created_at
        FROM prayers
        UNION ALL
        SELECT 'sermon' AS type, id, title, created_at
        FROM sermons
        ORDER BY created_at DESC
        LIMIT %s
    """, (int(limit),))

    recent = cur.fetchall()
    cur.close()
    return recent


print("✅ MYVINECHURCH.ONLINE the_gathering/dashboard/queries.py loaded successfully (public-style rebuilt – fully parameterized and consistent)")