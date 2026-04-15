# app/routes/public/views.py
# Full path: MyVineChurch/app/routes/public/views.py
# File name: views.py
# Brief, detailed purpose: All public routes (guests only).
# Logged-in users are redirected to private views.
# NO duplicate routes. Clean and strict.

from flask import Blueprint, render_template, abort, request, flash, redirect, url_for
import pymysql

from . import public_bp
from .queries import get_public_previews, get_public_list
from .forms import validate_potluck_signup_form
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text


# Public Dashboard
@public_bp.route('/')
@public_bp.route('/public')
def public_dashboard():
    previews = get_public_previews()
    for key in previews:
        if isinstance(previews[key], list):
            previews[key] = censor_public_content(previews[key])
    return render_template('public/public_dashboard.html', **previews)


# Public Events List
@public_bp.route('/events')
def public_events():
    events = get_public_list('events', where="event_date >= CURDATE()", order_by="event_date ASC, event_time ASC")
    events = censor_public_content(events)
    return render_template('public/events/events.html', events=events)


# Public Event Detail
@public_bp.route('/events/<int:event_id>', methods=['GET', 'POST'])
def public_event_detail(event_id):
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT * FROM events WHERE id = %s AND visibility = 'public'", (event_id,))
    event = cur.fetchone()
    if not event:
        abort(404)

    event['event_name'] = censor_text(event['event_name'])
    event['location'] = censor_text(event.get('location', ''))
    event['description'] = censor_text(event.get('description', ''))

    signups = []
    if event.get('potluck_enabled'):
        cur.execute("SELECT name, item, quantity, note FROM potluck_signups WHERE event_id = %s ORDER BY id ASC", (event_id,))
        signups = cur.fetchall()
        signups = censor_public_content(signups)

    if request.method == 'POST' and event.get('potluck_enabled'):
        clean = validate_potluck_signup_form(request.form)
        if not clean:
            return redirect(url_for('public.public_event_detail', event_id=event_id))
        ip = request.remote_addr or 'unknown'
        try:
            cur.execute("""
                INSERT INTO potluck_signups (event_id, name, item, quantity, note, ip)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (event_id, clean['name'], clean['item'], clean['quantity'], clean['note'], ip))
            db.commit()
            flash('Thank you for signing up!', 'success')
        except Exception:
            flash('Signup failed – please try again.', 'error')
        return redirect(url_for('public.public_event_detail', event_id=event_id))

    return render_template('public/events/event_detail.html', event=event, signups=signups)


# Public Sermons
@public_bp.route('/sermons')
def public_sermons():
    sermons = get_public_list('sermons', order_by='uploaded_at DESC')
    sermons = censor_public_content(sermons)
    return render_template('public/sermons/sermons.html', sermons=sermons)


# Public Announcements
@public_bp.route('/announcements')
def public_announcements():
    announcements = get_public_list('announcements', where='is_active = 1', order_by='created_at DESC')
    announcements = censor_public_content(announcements)
    return render_template('public/announcements/announcements.html', announcements=announcements)


# Public Prayers
@public_bp.route('/prayers')
def public_prayers():
    prayers = get_public_list('prayers', order_by='date_posted DESC')
    prayers = censor_public_content(prayers)
    return render_template('public/prayers/prayers.html', prayers=prayers)


# Public Dreams
@public_bp.route('/dreams')
def public_dreams():
    dreams = get_public_list('dreams', order_by='date_posted DESC')
    dreams = censor_public_content(dreams)
    return render_template('public/dreams/dreams.html', dreams=dreams)


# Public Prophecies List
@public_bp.route('/prophecies')
def public_prophecies():
    prophecies = get_public_list('prophecies', order_by='date_posted DESC')
    prophecies = censor_public_content(prophecies)
    return render_template('public/prophecies/prophecies.html', prophecies=prophecies)


# Public Prophecy Detail (Guests Only)
@public_bp.route('/prophecies/<int:prophecy_id>', methods=['GET', 'POST'])
def public_prophecy_detail(prophecy_id):
    if 'user_id' in session:
        return redirect(url_for('prophecies.view_prophecy', prophecy_id=prophecy_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT p.*, COALESCE(p.contributor_name, 'Anonymous') AS poster_name
        FROM prophecies p
        WHERE p.id = %s AND p.visibility = 'public'
    """, (prophecy_id,))
    prophecy = cur.fetchone()
    if not prophecy:
        abort(404)

    prophecy['title'] = censor_text(prophecy['title'])
    prophecy['description'] = censor_text(prophecy.get('description', ''))

    cur.execute("""
        SELECT pc.comment, pc.date_added,
               COALESCE(u.username, pc.contributor_name, 'Anonymous') AS commenter_name
        FROM prophecy_comments pc
        LEFT JOIN users u ON pc.user_id = u.id
        WHERE pc.prophecy_id = %s
        ORDER BY pc.date_added ASC
    """, (prophecy_id,))
    comments = cur.fetchall()
    for c in comments:
        c['comment'] = censor_text(c['comment'])

    if request.method == 'POST':
        name = request.form.get('contributor_name', '').strip()
        comment_text = request.form.get('comment', '').strip()
        if not name or not comment_text:
            flash('Name and comment are required.', 'error')
        elif contains_censored_word(name + ' ' + comment_text):
            flash('Your comment contains prohibited content.', 'error')
        else:
            try:
                cur.execute("""
                    INSERT INTO prophecy_comments (prophecy_id, contributor_name, comment, date_added)
                    VALUES (%s, %s, %s, NOW())
                """, (prophecy_id, name, comment_text))
                db.commit()
                flash('Comment posted successfully!', 'success')
            except Exception:
                flash('Failed to post comment.', 'error')
        return redirect(url_for('public.public_prophecy_detail', prophecy_id=prophecy_id))

    return render_template('public/prophecies/view_prophecy.html', prophecy=prophecy, comments=comments)


@public_bp.route('/donate')
def donate():
    if not g.settings.get('online_donations_enabled'):
        abort(404)
    # ... (your existing donate code)
    return render_template('public/donate.html', ... )   # keep your original donate logic here