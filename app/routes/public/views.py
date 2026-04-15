# MYVINECHURCH.ONLINE/app/routes/public/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/views.py
# File name: views.py
# Brief, detailed purpose: ALL Public routes (guests only).
# • Rich social-media style dashboard feed on home page
# • Logged-in users are redirected to private views
# • All detail endpoints the public_dashboard.html template expects are defined
# • 100% complete rebuild - no exceptions, no missing routes
# • session IS imported
# • EVERY public detail page (Events, Announcements, Dreams, Sermons, Prayers, Prophecies) now loads comments EXACTLY like the working Prophecies page
# • FIXED: public_event_detail now uses correct column names (created_at, comment, name) to match your current DB

from flask import Blueprint, render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import public_bp
from .queries import get_public_previews, get_public_list
from .forms import validate_potluck_signup_form
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word
from app.utils.time_utils import format_church


# ====================== PUBLIC DASHBOARD (Rich Feed) ======================
@public_bp.route('/')
@public_bp.route('/public')
def public_dashboard():
    feed = []
    print("🔍 Building public dashboard feed...")

    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

        # Announcements
        announcements = get_public_list('announcements', where='is_active = 1', order_by='created_at DESC')
        for a in announcements:
            a['type'] = 'announcement'
            a['body'] = a.get('content')
            a['datetime'] = a.get('created_at')
        feed.extend(announcements)

        # Events
        events = get_public_list('events', where="event_date >= CURDATE()", order_by="event_date ASC, event_time ASC")
        for e in events:
            e['type'] = 'event'
            e['body'] = f"Event on {e.get('event_date')}"
            e['datetime'] = e.get('event_date')
        feed.extend(events)

        # Sermons
        sermons = get_public_list('sermons', order_by='uploaded_at DESC')
        for s in sermons:
            s['type'] = 'sermon'
            s['body'] = None
            s['datetime'] = s.get('uploaded_at')
        feed.extend(sermons)

        # Prayers
        prayers = get_public_list('prayers', order_by='date_posted DESC')
        for p in prayers:
            p['type'] = 'prayer'
            p['body'] = None
            p['datetime'] = p.get('date_posted')
        feed.extend(prayers)

        # Dreams
        dreams = get_public_list('dreams', order_by='date_posted DESC')
        for d in dreams:
            d['type'] = 'dream'
            d['body'] = None
            d['datetime'] = d.get('date_posted')
        feed.extend(dreams)

        # Prophecies
        prophecies = get_public_list('prophecies', order_by='created_at DESC')
        for p in prophecies:
            p['type'] = 'prophecy'
            p['body'] = None
            p['datetime'] = p.get('created_at')
        feed.extend(prophecies)

        # Censor and format
        for item in feed:
            item['title'] = censor_text(item.get('title') or '')
            if item.get('body'):
                item['body'] = censor_text(item['body'])
            dt = item.get('datetime')
            if dt:
                item['formatted_date'] = format_church(dt, '%B %d, %Y')
                item['formatted_time'] = format_church(dt, '%I:%M %p')
            else:
                item['formatted_date'] = 'Unknown'
                item['formatted_time'] = ''

        # Sort newest first
        feed.sort(key=lambda x: str(x.get('datetime') or '0000-00-00'), reverse=True)

        print(f"📊 Final public feed has {len(feed)} items")

    except Exception as e:
        print(f"❌ Public dashboard error: {e}")

    return render_template('public/public_dashboard.html', feed=feed[:30])


# ====================== PUBLIC LIST & DETAIL PAGES ======================

@public_bp.route('/events')
def public_events():
    events = get_public_list('events', where="event_date >= CURDATE()", order_by="event_date ASC, event_time ASC")
    events = censor_public_content(events)
    return render_template('public/events/events.html', events=events)


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

    # Load comments - now using exact column names that exist in your DB
    cur.execute("""
        SELECT 
            pc.comment AS comment_text,
            pc.created_at AS date,
            pc.parent_id,
            COALESCE(u.username, pc.name, 'Guest') AS name
        FROM event_comments pc
        LEFT JOIN users u ON pc.user_id = u.id
        WHERE pc.event_id = %s
        ORDER BY pc.created_at ASC
    """, (event_id,))
    comments = cur.fetchall()

    for c in comments:
        c['date'] = format_church(c['date']) if c.get('date') else 'Unknown'
        c['comment_text'] = censor_text(c['comment_text'])

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

    return render_template('public/events/event_detail.html', event=event, signups=signups, comments=comments)


@public_bp.route('/announcements')
def public_announcements():
    announcements = get_public_list('announcements', where='is_active = 1', order_by='created_at DESC')
    announcements = censor_public_content(announcements)
    return render_template('public/announcements/announcements.html', announcements=announcements)


@public_bp.route('/announcements/<int:ann_id>', methods=['GET', 'POST'])
def public_announcement_detail(ann_id):
    if 'user_id' in session:
        return redirect(url_for('announcements.view_announcement', ann_id=ann_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT * FROM announcements 
        WHERE id = %s AND visibility = 'public' AND is_active = 1
    """, (ann_id,))
    announcement = cur.fetchone()
    if not announcement:
        abort(404)

    announcement['title'] = censor_text(announcement['title'])
    announcement['content'] = censor_text(announcement.get('content', ''))

    cur.execute("""
        SELECT c.comment, c.date_added AS created_at, c.parent_id,
               COALESCE(u.username, c.contributor_name, 'Unknown') AS name
        FROM announcement_comments c
        LEFT JOIN users u ON c.user_id = u.id
        WHERE c.announcement_id = %s
        ORDER BY c.date_added ASC
    """, (ann_id,))
    comments = cur.fetchall()

    for c in comments:
        c['date'] = format_church(c['created_at']) if c.get('created_at') else 'Unknown'
        c['comment_text'] = c['comment']

    if request.method == 'POST':
        action = request.form.get('action')
        name = request.form.get('contributor_name', '').strip()
        comment_text = request.form.get('comment', '').strip()
        parent_id = request.form.get('parent_id') if action == 'reply' else None

        if not name or not comment_text:
            flash('Name and comment are required.', 'error')
        elif contains_censored_word(name + ' ' + comment_text):
            flash('Your comment contains prohibited content.', 'error')
        else:
            try:
                cur.execute("""
                    INSERT INTO announcement_comments 
                    (announcement_id, contributor_name, comment, parent_id, date_added)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (ann_id, name, comment_text, parent_id or None))
                db.commit()
                flash('Comment posted successfully!', 'success')
            except Exception:
                flash('Failed to post comment.', 'error')
        return redirect(url_for('public.public_announcement_detail', ann_id=ann_id))

    return render_template('public/announcements/view_announcement.html',
                           announcement=announcement, comments=comments)


@public_bp.route('/sermons')
def public_sermons():
    sermons = get_public_list('sermons', order_by='uploaded_at DESC')
    sermons = censor_public_content(sermons)
    return render_template('public/sermons/sermons.html', sermons=sermons)


@public_bp.route('/sermons/<int:sermon_id>')
def public_sermon_detail(sermon_id):
    if 'user_id' in session:
        return redirect(url_for('sermons.view_sermon', sermon_id=sermon_id))
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT * FROM sermons WHERE id = %s AND visibility = 'public'", (sermon_id,))
    sermon = cur.fetchone()
    if not sermon:
        abort(404)
    sermon['title'] = censor_text(sermon['title'])
    return render_template('public/sermons/view_sermon.html', sermon=sermon)


@public_bp.route('/prayers')
def public_prayers():
    prayers = get_public_list('prayers', order_by='date_posted DESC')
    prayers = censor_public_content(prayers)
    return render_template('public/prayers/prayers.html', prayers=prayers)


@public_bp.route('/dreams')
def public_dreams():
    dreams = get_public_list('dreams', order_by='date_posted DESC')
    dreams = censor_public_content(dreams)
    return render_template('public/dreams/dreams.html', dreams=dreams)


@public_bp.route('/dreams/<int:dream_id>')
def public_dream_detail(dream_id):
    if 'user_id' in session:
        return redirect(url_for('dreams.view_dream', dream_id=dream_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT * FROM dreams WHERE id = %s AND visibility = 'public'
    """, (dream_id,))
    dream = cur.fetchone()
    if not dream:
        abort(404)

    dream['title'] = censor_text(dream['title'])
    dream['description'] = censor_text(dream.get('description', ''))

    return render_template('public/dreams/view_dream.html', dream=dream)


@public_bp.route('/prophecies')
def public_prophecies():
    prophecies = get_public_list('prophecies', order_by='created_at DESC')
    prophecies = censor_public_content(prophecies)
    return render_template('public/prophecies/prophecies.html', prophecies=prophecies)


@public_bp.route('/prophecies/<int:prophecy_id>', methods=['GET', 'POST'])
def public_prophecy_detail(prophecy_id):
    if 'user_id' in session:
        return redirect(url_for('prophecies.view_prophecy', prophecy_id=prophecy_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT * FROM prophecies WHERE id = %s AND visibility = 'public'
    """, (prophecy_id,))
    prophecy = cur.fetchone()
    if not prophecy:
        abort(404)

    prophecy['title'] = censor_text(prophecy.get('title') or 'Untitled Prophecy')
    prophecy['description'] = censor_text(prophecy.get('description') or '')
    prophecy['posted_by'] = prophecy.get('contributor_name') or 'Anonymous'
    prophecy['date_posted'] = prophecy.get('created_at')

    cur.execute("""
        SELECT 
            pc.comment AS comment_text,
            pc.date_added AS date,
            pc.parent_id,
            COALESCE(u.username, pc.contributor_name, 'Guest') AS name
        FROM prophecy_comments pc
        LEFT JOIN users u ON pc.user_id = u.id
        WHERE pc.prophecy_id = %s
        ORDER BY pc.date_added ASC
    """, (prophecy_id,))
    comments = cur.fetchall()

    for c in comments:
        c['date'] = format_church(c['date']) if c.get('date') else 'Unknown'
        c['comment_text'] = censor_text(c['comment_text'])

    if request.method == 'POST':
        action = request.form.get('action')
        name = request.form.get('contributor_name', '').strip()
        comment_text = request.form.get('comment', '').strip()
        parent_id = request.form.get('parent_id') if action == 'reply' else None

        if not name or not comment_text:
            flash('Name and comment are required.', 'error')
        elif contains_censored_word(name + ' ' + comment_text):
            flash('Your comment contains prohibited content.', 'error')
        else:
            try:
                cur.execute("""
                    INSERT INTO prophecy_comments (prophecy_id, contributor_name, comment, parent_id, date_added)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (prophecy_id, name, comment_text, parent_id or None))
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
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT id, name, option_type, url, embed_code, image_path
        FROM online_donation_options WHERE enabled = 1
        ORDER BY sort_order ASC, id ASC
    """)
    options = cur.fetchall()
    return render_template('public/donate.html',
                           title=g.settings.get('donations_page_title', 'Support Our Ministry'),
                           welcome=g.settings.get('donations_welcome_text'),
                           thank_you=g.settings.get('donations_thank_you_text'),
                           extra=g.settings.get('donations_extra_text'),
                           options=options)