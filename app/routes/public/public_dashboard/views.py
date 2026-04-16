# MYVINECHURCH.ONLINE/app/routes/public/public_dashboard/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/public_dashboard/views.py
# File name: views.py
# Brief, detailed purpose: Public Dashboard routes – rich social-media style feed on the home page (/ and /public).
# • Builds combined feed from announcements, events, sermons, prayers, dreams, prophecies.
# • FIXED: Safe date handling so strings from MariaDB never crash format_church().
# • Uses the new feature-specific queries.py and utils.py.
# • 100% original rich feed logic preserved with improved robustness.

from flask import render_template
from . import dashboard_bp
from .queries import get_public_dashboard_feed
from .utils import censor_public_content

from app.utils.helpers import censor_text
from app.utils.time_utils import format_church
from datetime import datetime


@dashboard_bp.route('/')
@dashboard_bp.route('/public')
def public_dashboard():
    """Rich public dashboard feed (homepage)."""
    print("🔍 Building public dashboard feed...")

    feed = get_public_dashboard_feed()

    # Censor the feed items
    feed = censor_public_content(feed)

    for item in feed:
        item['title'] = censor_text(item.get('title') or '')
        if item.get('body'):
            item['body'] = censor_text(item['body'])

        dt = item.get('datetime')

        # FIXED: Safe handling for strings coming from MariaDB
        if isinstance(dt, str):
            try:
                # Try common formats used in your DB
                if ' ' in dt:  # has time
                    dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
                else:
                    dt = datetime.strptime(dt, '%Y-%m-%d')
            except:
                dt = None

        if dt:
            item['formatted_date'] = format_church(dt, '%B %d, %Y')
            item['formatted_time'] = format_church(dt, '%I:%M %p')
        else:
            item['formatted_date'] = 'Unknown'
            item['formatted_time'] = ''

    print(f"📊 Final public feed has {len(feed)} items")

    return render_template('public/public_dashboard.html', feed=feed)


print("✅ MYVINECHURCH.ONLINE public/public_dashboard/views.py loaded successfully (safe date handling added)")