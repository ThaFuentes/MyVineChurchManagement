# MYVINECHURCH.ONLINE/app/routes/public/events/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/events/views.py
# File name: views.py
# Brief, detailed purpose: Public Events routes for unauthenticated guests only.
# • Listing shows only upcoming public events with potluck signups.
# • Detail page supports potluck signup + guest comments/replies.
# • Logged-in users redirected to private events.
# • Uses new feature-specific queries.py, utils.py, and forms.py.
# • 100% original public_events.py + views.py events logic preserved (LEFT JOIN, censor order, potluck, comments).

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import events_bp
from .queries import get_public_events, get_public_event
from .forms import validate_potluck_signup_form
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word
from app.utils.time_utils import format_church


@events_bp.route('/')
def public_events():
    """Public events listing – shows only upcoming public events."""
    if 'user_id' in session:
        print("[PUBLIC EVENTS] Logged-in user → redirecting to PRIVATE events list")
        return redirect(url_for('events.events'))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Use dedicated query (already includes LEFT JOIN for creator_name)
    events = get_public_events()

    # Censorship first (exactly like original)
    events = censor_public_content(events)

    # Then set keys the template expects
    for e in events:
        e['datetime'] = format_church(e.get('created_at')) if e.get('created_at') else 'Unknown'
        e['posted_by'] = e.get('creator_name', 'Anonymous')

        # Potluck signups
        if e.get('potluck_enabled'):
            try:
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


@events_bp.route('/<int:event_id>', methods=['GET', 'POST'])
def public_event_detail(event_id):
    """Public single event detail page with potluck signups + guest comments/replies."""
    print(f"\n[DEBUG] PUBLIC EVENT DETAIL ROUTE – event_id={event_id} | method={request.method}")

    # Logged-in users go to private view
    if 'user_id' in session:
        print("[DEBUG] Logged-in user → redirecting to PRIVATE event detail")
        return redirect(url_for('events.view_event', event_id=event_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Fetch the public event using dedicated query
    event = get_public_event(event_id)
    if not event:
        print("[DEBUG] Event not found or not public → 404")
        abort(404)

    # Censor fields
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

    # Load comments (exact aliases template expects)
    comments = []
    try:
        cur.execute("""
            SELECT id, name, comment_text, parent_id,
                   DATE_FORMAT(created_at, '%%b %%e, %%Y %%h:%%i %%p') as created_at_nice
            FROM event_comments 
            WHERE event_id = %s 
            ORDER BY created_at ASC
        """, (event_id,))
        comments = cur.fetchall()
        print(f"[DEBUG] Loaded {len(comments)} comments for event {event_id}")
    except Exception as e:
        print(f"[DEBUG] ERROR loading comments: {e}")

    # === HANDLE POST (potluck or comment/reply) ===
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'potluck' and event.get('potluck_enabled'):
            clean = validate_potluck_signup_form(request.form)
            if not clean:
                return redirect(url_for('public_events.public_event_detail', event_id=event_id))
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
                    cur.execute("""
                        INSERT INTO event_comments 
                        (event_id, name, comment_text, parent_id, created_at)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, (event_id, name, comment_text, parent_id))
                    db.commit()
                    flash('Comment posted successfully!', 'success')
                except Exception:
                    flash('Failed to post comment.', 'error')

        return redirect(url_for('public_events.public_event_detail', event_id=event_id))

    print("[DEBUG] Rendering template 'public/events/event_detail.html' for guest")
    return render_template('public/events/event_detail.html',
                           event=event,
                           signups=signups,
                           comments=comments)


print("✅ MYVINECHURCH.ONLINE public/events/views.py loaded successfully")