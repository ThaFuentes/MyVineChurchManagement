# MYVINECHURCH.ONLINE/app/routes/public/public_events.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/public_events.py
# File name: public_events.py
# Brief, detailed purpose: Public Events routes for unauthenticated guests only.
# • Public upcoming events list
# • Single event detail with potluck signups + guest comments + one-level replies (parent_id)
# • Logged-in users are NOT redirected here (public view only)
# • Exact mirror of the working public_sermons / public_dreams pattern.

from flask import render_template, abort, request, flash, redirect, url_for
import pymysql

from . import public_bp
from .queries import get_public_list
from .forms import validate_potluck_signup_form
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word


@public_bp.route('/events')
def public_events():
    """Public events listing – shows only upcoming public events."""
    events = get_public_list(
        'events',
        where="event_date >= CURDATE()",
        order_by="event_date ASC, event_time ASC"
    )
    events = censor_public_content(events)
    return render_template('public/events/events.html', events=events)


@public_bp.route('/events/<int:event_id>', methods=['GET', 'POST'])
def public_event_detail(event_id):
    """Public single event detail page with potluck signups, guest comments, and simple one-level replies."""
    print(f"\n[DEBUG] PUBLIC EVENT DETAIL ROUTE – event_id={event_id} | method={request.method}")

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    # Fetch the public event
    cur.execute("""
        SELECT * FROM events 
        WHERE id = %s AND visibility = 'public'
    """, (event_id,))
    event = cur.fetchone()

    if not event:
        print("[DEBUG] Event not found or not public → 404")
        abort(404)

    # Server-side censorship for public view
    event['event_name']   = censor_text(event.get('event_name', ''))
    event['location']     = censor_text(event.get('location', ''))
    event['description']  = censor_text(event.get('description', ''))

    # Potluck signups (if enabled)
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
        except Exception as e:
            print(f"[DEBUG] Potluck signups load error: {e}")

    # Load comments with one-level replies (parent_id)
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

        print(f"[DEBUG] Loaded {len(comments)} comments (including replies) for public event {event_id}")
    except Exception as e:
        print(f"[DEBUG] ERROR loading comments for event {event_id}: {e}")

    # === HANDLE POST (potluck signup OR comment/reply) ===
    if request.method == 'POST':
        action = request.form.get('action')
        print(f"[DEBUG] POST action = '{action}'")

        if action == 'potluck' and event.get('potluck_enabled'):
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
                print(f"[DEBUG] Potluck signup inserted for event {event_id}")
            except Exception as e:
                flash('Signup failed – please try again.', 'error')
                print(f"[DEBUG] Potluck insert error: {e}")

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
                    print(f"[DEBUG] Guest comment/reply inserted for event {event_id}")
                except Exception as e:
                    flash('Failed to post comment.', 'error')
                    print(f"[DEBUG] Comment insert error: {e}")

        # Refresh page to show new signup/comment
        return redirect(url_for('public.public_event_detail', event_id=event_id))

    # Render public template
    print("[DEBUG] Rendering public/events/event_detail.html for guest")
    return render_template('public/events/event_detail.html',
                           event=event,
                           signups=signups,
                           comments=comments)