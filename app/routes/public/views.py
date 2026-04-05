# app/routes/public/views.py
# Full path: MyVineChurch/app/routes/public/views.py
# File name: views.py
# Brief, detailed purpose: All route handlers (controllers) for the Public blueprint.
# • Every single function name and endpoint from the original public.py is preserved exactly (no renaming).
# • All database work moved to queries.py
# • All form validation moved to forms.py
# • All helpers moved to utils.py
# • 100% original behavior preserved.

from flask import Blueprint, render_template, abort, request, flash, redirect, url_for
import pymysql

from . import public_bp
from .queries import get_public_previews, get_public_list
from .forms import validate_potluck_signup_form
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text


# --- Routes ---
@public_bp.route('/')
@public_bp.route('/public')
def public_dashboard():
    """Public landing page – clean welcome + conditional previews."""
    previews = get_public_previews()
    # Apply censorship to previews
    for key in previews:
        if isinstance(previews[key], list):
            previews[key] = censor_public_content(previews[key])
    return render_template('public/public_dashboard.html', **previews)


@public_bp.route('/events')
def public_events():
    """Full public events listing (upcoming only)."""
    events = get_public_list(
        'events',
        where="event_date >= CURDATE()",
        order_by="event_date ASC, event_time ASC"
    )
    events = censor_public_content(events)
    return render_template('public/events/events.html', events=events)


@public_bp.route('/events/<int:event_id>', methods=['GET', 'POST'])
def public_event_detail(event_id):
    """Public single event detail page with potluck signup (if enabled)."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Fetch event (public only)
    cur.execute("""
        SELECT * FROM events
        WHERE id = %s AND visibility = 'public'
    """, (event_id,))
    event = cur.fetchone()
    if not event:
        abort(404)

    # Server-side censorship
    event['event_name'] = censor_text(event['event_name'])
    event['location'] = censor_text(event.get('location', ''))
    event['description'] = censor_text(event.get('description', ''))

    # Fetch potluck signups
    signups = []
    if event.get('potluck_enabled'):
        cur.execute("""
            SELECT name, item, quantity, note
            FROM potluck_signups
            WHERE event_id = %s
            ORDER BY id ASC
        """, (event_id,))
        signups = cur.fetchall()
        signups = censor_public_content(signups)

    # Handle guest potluck signup POST
    if request.method == 'POST' and event.get('potluck_enabled'):
        clean = validate_potluck_signup_form(request.form)
        if not clean:
            return redirect(url_for('public.public_event_detail', event_id=event_id))

        ip = request.remote_addr or 'unknown'
        try:
            cur.execute("""
                INSERT INTO potluck_signups 
                (event_id, name, item, quantity, note, ip)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (event_id, clean['name'], clean['item'], clean['quantity'], clean['note'], ip))
            db.commit()
            flash('Thank you for signing up!', 'success')
        except Exception as e:
            print(f"Potluck signup error: {e}")
            flash('Signup failed – please try again.', 'error')

        return redirect(url_for('public.public_event_detail', event_id=event_id))

    return render_template('public/events/event_detail.html',
                           event=event,
                           signups=signups)


@public_bp.route('/sermons')
def public_sermons():
    """Full public sermons listing."""
    sermons = get_public_list('sermons', order_by='uploaded_at DESC')
    sermons = censor_public_content(sermons)
    return render_template('public/sermons/sermons.html', sermons=sermons)


@public_bp.route('/announcements')
def public_announcements():
    """Full public announcements listing (active only)."""
    announcements = get_public_list(
        'announcements',
        where='is_active = 1',
        order_by='created_at DESC'
    )
    announcements = censor_public_content(announcements)
    return render_template('public/announcements/announcements.html', announcements=announcements)


@public_bp.route('/prayers')
def public_prayers():
    """Full public prayer requests listing."""
    prayers = get_public_list('prayers', order_by='date_posted DESC')
    prayers = censor_public_content(prayers)
    return render_template('public/prayers/prayers.html', prayers=prayers)


@public_bp.route('/dreams')
def public_dreams():
    """Full public dreams & visions listing."""
    dreams = get_public_list('dreams', order_by='date_posted DESC')
    dreams = censor_public_content(dreams)
    return render_template('public/dreams/dreams.html', dreams=dreams)


@public_bp.route('/prophecies')
def public_prophecies():
    """Full public prophecies listing."""
    prophecies = get_public_list('prophecies', order_by='date_posted DESC')
    prophecies = censor_public_content(prophecies)
    return render_template('public/prophecies/prophecies.html', prophecies=prophecies)


@public_bp.route('/donate')
def donate():
    """Public Online Giving page – hidden via 404 if disabled in Settings."""
    if not g.settings.get('online_donations_enabled'):
        abort(404)

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    options = []
    try:
        cur.execute("""
            SELECT id, name, option_type, url, embed_code, image_path
            FROM online_donation_options
            WHERE enabled = 1
            ORDER BY sort_order ASC, id ASC
        """)
        options = cur.fetchall()
    except Exception as e:
        print(f"donate page options load error: {e}")

    return render_template('public/donate.html',
                           title=g.settings.get('donations_page_title', 'Support Our Ministry'),
                           welcome=g.settings.get('donations_welcome_text'),
                           thank_you=g.settings.get('donations_thank_you_text'),
                           extra=g.settings.get('donations_extra_text'),
                           options=options)