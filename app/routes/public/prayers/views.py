# MYVINECHURCH.ONLINE/app/routes/public/prayers/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/prayers/views.py
# File name: views.py
# Brief, detailed purpose: Public Prayers routes for unauthenticated guests only.
# • Listing shows only public prayers (with creator_name).
# • Detail page supports guest responses/replies (one-level) + potluck-style censorship.
# • Logged-in users are redirected to private prayers.
# • Uses local queries.py, forms.py and utils.py for modularity.
# • 100% rebuilt clean version - identical structure and style to the working public/events/views.py gold standard.
# • FIXED: Correct nested blueprint endpoints, response aliasing for new template, creator_name handling, and clean production code (debug prints removed).

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import prayers_bp
from .queries import get_public_prayers, get_public_prayer
from .forms import validate_guest_comment_form
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word


# ----------------------------------------------------------------------
# Public Prayers Listing (Guests Only)
# ----------------------------------------------------------------------
@prayers_bp.route('/')
def public_prayers():
    """Public prayers listing – upcoming public prayers only.
    Logged-in users are redirected to the private prayers dashboard.
    """
    if 'user_id' in session:
        return redirect(url_for('prayers.prayers'))

    # Guest view only
    prayers = get_public_prayers()

    # Censorship first
    prayers = censor_public_content(prayers)

    # Prepare data for template
    for p in prayers:
        p['formatted_date'] = p.get('date_posted').strftime('%B %d, %Y') if p.get('date_posted') else 'Unknown'
        p['posted_by'] = p.get('creator_name', 'Anonymous')

    return render_template('public/prayers/prayers.html', prayers=prayers)


# ----------------------------------------------------------------------
# Public Single Prayer Detail (Guests Only + Responses/Replies)
# ----------------------------------------------------------------------
@prayers_bp.route('/<int:prayer_id>', methods=['GET', 'POST'])
def public_prayer_detail(prayer_id):
    """Public single prayer detail with guest responses/replies."""
    if 'user_id' in session:
        return redirect(url_for('prayers.view_prayer', prayer_id=prayer_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    prayer = get_public_prayer(prayer_id)
    if not prayer:
        abort(404)

    # Censor content for public view
    prayer['title']       = censor_text(prayer.get('title', ''))
    prayer['description'] = censor_text(prayer.get('description', ''))

    # Load responses (using prayers_added table - exact same pattern as events)
    responses = []
    try:
        cur.execute("""
            SELECT 
                id,
                contributor_name AS name,
                prayer AS comment_text,
                parent_id,
                DATE_FORMAT(date_added, '%%b %%e, %%Y %%h:%%i %%p') as created_at_nice
            FROM prayers_added 
            WHERE prayer_request_id = %s 
            ORDER BY date_added ASC
        """, (prayer_id,))
        responses = cur.fetchall()
    except Exception:
        pass

    # Handle POST - guest response or reply
    if request.method == 'POST':
        action = request.form.get('action')

        if action in ('comment', 'reply'):
            clean = validate_guest_comment_form(request.form)
            if not clean:
                return redirect(url_for('public.public_prayers.public_prayer_detail', prayer_id=prayer_id))

            parent_id = clean.get('parent_id')
            try:
                cur.execute("""
                    INSERT INTO prayers_added 
                    (prayer_request_id, contributor_name, prayer, parent_id, date_added)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (prayer_id, clean['name'], clean['comment'], parent_id))
                db.commit()
                flash('Response posted successfully!', 'success')
            except Exception:
                flash('Failed to post response.', 'error')

        # Always redirect using the CORRECT nested blueprint endpoint
        return redirect(url_for('public.public_prayers.public_prayer_detail', prayer_id=prayer_id))

    return render_template('public/prayers/view_prayer.html',
                           prayer=prayer,
                           responses=responses)


