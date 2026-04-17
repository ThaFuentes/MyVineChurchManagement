# MYVINECHURCH.ONLINE/app/routes/public/public_dashboard/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/public_dashboard/views.py
# File name: views.py
# Brief, detailed purpose: Public Dashboard routes – rich social-media style feed on the home page (/ and /public).
# • Reuses ALL existing public queries with smart priority ordering (upcoming events first, newest sermons, recent announcements, dreams, prophecies, prayers).
# • Easy click-to-detail cards with recent comment previews where possible.
# • 100% rebuilt clean version - identical structure to the working public/events/views.py gold standard.
# • FIXED: Added missing url_for import so detail links work.

from flask import render_template, url_for
from . import dashboard_bp
from .queries import get_public_dashboard_feed
from .utils import censor_public_content

from app.utils.helpers import censor_text
from app.utils.time_utils import format_church
from datetime import datetime


@dashboard_bp.route('/')
@dashboard_bp.route('/public')
def public_dashboard():
    """Rich public dashboard feed (homepage) with smart priority ordering."""
    print("🔍 [PUBLIC DASHBOARD] Building rich homepage feed...")

    feed = get_public_dashboard_feed()

    # Censor the entire feed
    feed = censor_public_content(feed)

    for item in feed:
        item['title'] = censor_text(item.get('title') or item.get('event_name') or '')

        if item.get('body'):
            item['body'] = censor_text(item['body'])
        elif item.get('description'):
            item['body'] = censor_text(item['description'])
        elif item.get('content'):
            item['body'] = censor_text(item['content'])

        # Safe date handling
        dt = item.get('datetime') or item.get('created_at') or item.get('date_posted') or item.get('uploaded_at') or item.get('event_date')
        if isinstance(dt, str):
            try:
                if ' ' in dt:
                    dt = datetime.strptime(dt[:19], '%Y-%m-%d %H:%M:%S')
                else:
                    dt = datetime.strptime(dt[:10], '%Y-%m-%d')
            except:
                dt = None

        if dt:
            item['formatted_date'] = format_church(dt, '%B %d, %Y')
            item['formatted_time'] = format_church(dt, '%I:%M %p')
        else:
            item['formatted_date'] = 'Unknown'
            item['formatted_time'] = ''

        # Add direct link to the correct detail page
        item_type = item.get('type')
        if item_type == 'event':
            item['detail_url'] = url_for('public.public_events.public_event_detail', event_id=item['id'])
        elif item_type == 'sermon':
            item['detail_url'] = url_for('public.public_sermons.public_sermon_detail', sermon_id=item['id'])
        elif item_type == 'announcement':
            item['detail_url'] = url_for('public.public_announcements.public_announcement_detail', ann_id=item['id'])
        elif item_type == 'dream':
            item['detail_url'] = url_for('public.public_dreams.public_dream_detail', dream_id=item['id'])
        elif item_type == 'prophecy':
            item['detail_url'] = url_for('public.public_prophecies.public_prophecy_detail', prophecy_id=item['id'])
        elif item_type == 'prayer':
            item['detail_url'] = url_for('public.public_prayers.public_prayer_detail', prayer_id=item['id'])
        else:
            item['detail_url'] = '#'

    print(f"✅ [PUBLIC DASHBOARD] Final homepage feed has {len(feed)} items (priority ordered)")

    return render_template('public/public_dashboard.html', feed=feed)


print("✅ MYVINECHURCH.ONLINE public/public_dashboard/views.py rebuilt successfully (url_for import fixed + smart priority ordering)")