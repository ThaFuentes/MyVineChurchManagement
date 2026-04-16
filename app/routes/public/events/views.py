# MYVINECHURCH.ONLINE/app/routes/public/events/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/events/views.py
# File name: views.py
# Brief, detailed purpose: Public Events routes for unauthenticated guests only.
# • Listing shows only upcoming public events with potluck signups.
# • Detail page supports potluck signup + full guest comments/replies (one-level).
# • Logged-in users are redirected to private events.
# • Uses local queries.py, forms.py and utils.py for modularity.
# • 100% rebuilt clean version - consistent with working prophecies/dreams pattern.
# • FIXED: All url_for calls now use the correct nested blueprint endpoint
#   'public.public_events.public_event_detail' (matches how the sub-blueprint
#   is registered under the public blueprint).
# • FIXED: event_comments table uses column 'comment' (per builddb/events.py).
#   We now SELECT 'comment AS comment_text' and INSERT into 'comment' so the
#   existing event_detail.html template continues to work unchanged.
# • All debug prints removed for production cleanliness.

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import events_bp
from .queries import get_public_events, get_public_event
from .forms import validate_potluck_signup_form
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word
from app.utils.time_utils import format_church


# ----------------------------------------------------------------------
# Public Events Listing (Guests Only)
# ----------------------------------------------------------------------
@events_bp.route('/')
def public_events():
    """Public events listing – upcoming public events only.
    Logged-in users are redirected to the private events dashboard.
    """
    if 'user_id' in session:
        return redirect(url_for('events.events'))

    # Guest view only
    events = get_public_events()

    # Censorship first
    events = censor_public_content(events)

    # Prepare data for template
    for e in events:
        e['datetime'] = format_church(e.get('created_at')) if e.get('created_at') else 'Unknown'
        e['posted_by'] = e.get('creator_name', 'Anonymous')

        # Potluck signups
        if e.get('potluck_enabled'):
            try:
                db = get_db()
                cur = db.cursor(pymysql.cursors.DictCursor)
                cur.execute("""
                    SELECT name, item, quantity, note 
                    FROM potluck_signups 
                    WHERE event_id = %s 
                    ORDER BY id ASC
                """, (e['id'],))
                e['signups'] = cur.fetchall()
                e['signups'] = censor_public_content(e['signups'])
            except Exception:
                e['signups'] = []
        else:
            e['signups'] = []

    return render_template('public/events/events.html', events=events)


# ----------------------------------------------------------------------
# Public Single Event Detail (Guests Only + Potluck + Comments)
# ----------------------------------------------------------------------
@events_bp.route('/<int:event_id>', methods=['GET', 'POST'])
def public_event_detail(event_id):
    """Public single event detail with potluck signups + guest comments/replies."""
    if 'user_id' in session:
        return redirect(url_for('events.view_event', event_id=event_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    event = get_public_event(event_id)
    if not event:
        abort(404)

    # Censor content for public view
    event['event_name']   = censor_text(event.get('event_name', ''))
    event['location']     = censor_text(event.get('location', ''))
    event['description']  = censor_text(event.get('description', ''))

    signups = []
    if event.get('potluck_enabled'):
        try:
            cur.execute("""
                SELECT name, item, quantity, note 
                FROM potluck_signups 
                WHERE event_id = %s 
                ORDER BY id ASC
            """, (event_id,))
            signups = cur.fetchall()
            signups = censor_public_content(signups)
        except Exception:
            pass

    # Load comments - use correct column name 'comment' and alias to match template
    comments = []
    try:
        cur.execute("""
            SELECT 
                id,
                name,
                comment AS comment_text,
                parent_id,
                DATE_FORMAT(created_at, '%%b %%e, %%Y %%h:%%i %%p') as created_at_nice
            FROM event_comments 
            WHERE event_id = %s 
            ORDER BY created_at ASC
        """, (event_id,))
        comments = cur.fetchall()
    except Exception:
        pass

    # Handle POST - potluck signup or guest comment/reply
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'potluck' and event.get('potluck_enabled'):
            clean = validate_potluck_signup_form(request.form)
            if not clean:
                return redirect(url_for('public.public_events.public_event_detail', event_id=event_id))
            ip = request.remote_addr or 'unknown'
            try:
                cur.execute("""
                    INSERT INTO potluck_signups 
                    (event_id, name, item, quantity, note, ip)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (event_id, clean['name'], clean['item'], clean['quantity'], clean['note'], ip))
                db.commit()
                flash('Thank you for signing up!', 'success')
            except Exception:
                flash('Signup failed – please try again.', 'error')

        elif action in ('comment', 'reply'):
            name         = request.form.get('name', '').strip()
            comment_text = request.form.get('comment', '').strip()
            parent_id    = request.form.get('parent_id') if action == 'reply' else None

            if not name or not comment_text:
                flash('Name and comment are required.', 'error')
            elif contains_censored_word(name + ' ' + comment_text):
                flash('Your comment contains prohibited content.', 'error')
            else:
                try:
                    # Use correct column 'comment' (per builddb/events.py)
                    cur.execute("""
                        INSERT INTO event_comments 
                        (event_id, name, comment, parent_id, created_at)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, (event_id, name, comment_text, parent_id))
                    db.commit()
                    flash('Comment posted successfully!', 'success')
                except Exception:
                    flash('Failed to post comment.', 'error')

        # Always redirect using the CORRECT nested blueprint endpoint
        return redirect(url_for('public.public_events.public_event_detail', event_id=event_id))

    return render_template('public/events/event_detail.html',
                           event=event,
                           signups=signups,
                           comments=comments)


print("✅ MYVINECHURCH.ONLINE public/events/views.py loaded successfully (nested blueprint + comment column fixes applied)")