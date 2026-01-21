# app/routes/events.py
# Full path: WebChurchMan/app/routes/events.py
# File name: events.py
# Brief, detailed purpose: Blueprint for all event-related routes (private/internal + public handling).
# • /events → listing: internal dashboard for logged-in, public list for guests.
# • /events/<event_id> → GET: single event detail (internal template for logged-in, public template for guests).
# • /events/<event_id> → POST: potluck contribution submission (endpoint 'events.add_potluck_contribution').
#   - Guests: require name, capture IP, check banned IPs + censored words.
#   - Logged-in members: auto-use full name, no IP.
#   - Server-side censored words check using contains_censored_word() on name/item/quantity/note.
# • /events/<event_id>/delete_contribution/<signup_id> → POST: delete potluck contribution (Admin/Owner only).
# • Visibility strictly enforced (private events hidden from guests).
# • Potluck signups fetched robustly (try/except to avoid crashes on old DB/missing table).
# • Add/edit/delete events restricted to Staff/Admin/Owner.
# • Email invitations route.
# • All significant actions audit-logged.
# • Consistent DictCursor usage for safety.
# • FULL REBUILD: Added server-side censored word check on event creation and edit (all text fields).
#   - If censored word found, flash error and repopulate form (no save).
#   - Uses contains_censored_word() on concatenated text fields.
#   - Preserved every existing feature/logic exactly.
# TIMEZONE INTEGRATION: Uses church local time for "today" calculations and display formatting.
#   - event_date formatted as local calendar date.
#   - event_time displayed as local time string.
#   - potluck_signups.created_at (UTC in DB) formatted in church local time.

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app.utils.decorators import login_required, role_required
from app.utils.helpers import contains_censored_word
from app.models.db import get_db
from app.models.log import log_change
from app.utils.time_utils import now_church, format_church
from datetime import date
import pymysql
import traceback

events_bp = Blueprint('events', __name__, url_prefix='/events')

REQUIRED_ROLES = ['Staff', 'Admin', 'Owner']
ADMIN_OWNER_ONLY = ['Admin', 'Owner']


# ----------------------------------------------------------------------
# Events Listing – /events (single URL)
# ----------------------------------------------------------------------
@events_bp.route('/')
def events():
    is_logged_in = 'user_id' in session
    user_id = session.get('user_id')

    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

        if is_logged_in:
            cur.execute("""
                SELECT *, CONCAT(event_date, ' ', COALESCE(event_time, '')) AS datetime
                FROM events
                ORDER BY event_date DESC, event_time DESC
            """)
        else:
            cur.execute("""
                SELECT *, CONCAT(event_date, ' ', COALESCE(event_time, '')) AS datetime
                FROM events
                WHERE visibility = 'public'
                ORDER BY event_date DESC, event_time DESC
            """)

        events_list = cur.fetchall()

        # Church local "today" for upcoming count
        today_local = now_church().date()
        today_str = today_local.strftime('%Y-%m-%d')

        # Add nice formatted dates
        for e in events_list:
            if e['event_date']:
                e['nice_date'] = e['event_date'].strftime('%A, %B %d, %Y')
                if e['event_time']:
                    e['nice_time'] = datetime.strptime(e['event_time'], '%H:%M:%S').strftime('%I:%M %p')
                    e['nice_full'] = f"{e['nice_date']} at {e['nice_time']}"
                else:
                    e['nice_time'] = 'All Day'
                    e['nice_full'] = e['nice_date']
            else:
                e['nice_date'] = 'Date not set'
                e['nice_time'] = ''
                e['nice_full'] = 'Date not set'

    except Exception as e:
        flash('Failed to load events.', 'error')
        events_list = []

    total_count = len(events_list)
    upcoming_count = sum(1 for e in events_list if e.get('event_date') and e['event_date'] >= today_local)
    potluck_count = sum(1 for e in events_list if e.get('potluck_enabled', 0))

    if user_id:
        log_change(user_id=user_id, action='view', change_details='Viewed events dashboard')

    template = 'events/events_dashboard.html' if is_logged_in else 'public/events/events.html'

    return render_template(
        template,
        events=events_list,
        total_count=total_count,
        upcoming_count=upcoming_count,
        potluck_count=potluck_count,
        is_logged_in=is_logged_in
    )


# ----------------------------------------------------------------------
# View Single Event – /events/<event_id> (GET only)
# ----------------------------------------------------------------------
@events_bp.route('/<int:event_id>', methods=['GET'])
def view_event(event_id: int):
    user_id = session.get('user_id')
    is_logged_in = bool(user_id)

    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

        # Fetch event
        cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
        event = cur.fetchone()
        if not event:
            flash('Event not found.', 'error')
            return redirect(url_for('events.events'))

        # Enforce visibility
        visibility = event.get('visibility', 'private')
        if visibility.lower() == 'private' and not is_logged_in:
            flash('You must be logged in to view this private event.', 'error')
            return redirect(url_for('auth.login'))

        # Format event date/time in church local
        if event['event_date']:
            event['nice_date'] = event['event_date'].strftime('%A, %B %d, %Y')
            if event['event_time']:
                time_obj = datetime.strptime(event['event_time'], '%H:%M:%S')
                event['nice_time'] = time_obj.strftime('%I:%M %p')
                event['nice_full'] = f"{event['nice_date']} at {event['nice_time']}"
            else:
                event['nice_time'] = 'All Day'
                event['nice_full'] = event['nice_date']
        else:
            event['nice_date'] = 'Date not set'
            event['nice_time'] = ''
            event['nice_full'] = 'Date not set'

        # Fetch potluck signups – robust
        signups = []
        if event.get('potluck_enabled'):
            try:
                cur.execute("""
                    SELECT id, name, item, quantity, note, created_at
                    FROM potluck_signups
                    WHERE event_id = %s
                    ORDER BY created_at ASC
                """, (event_id,))
                signups = cur.fetchall()
                # Format created_at (UTC in DB) to church local
                for s in signups:
                    if s['created_at']:
                        s['formatted_created'] = format_church(s['created_at'], '%B %d, %Y at %I:%M %p')
                    else:
                        s['formatted_created'] = 'Unknown'
            except Exception:
                signups = []

        # Current member name
        current_name = None
        if is_logged_in:
            cur.execute("""
                SELECT CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, '')) AS full_name
                FROM users WHERE id = %s
            """, (user_id,))
            row = cur.fetchone()
            current_name = row['full_name'].strip() if row and row['full_name'].strip() else 'Member'
            log_change(user_id, 'view', change_details=f"Viewed event ID {event_id}")

        template = 'events/view_event.html' if is_logged_in else 'public/events/event_detail.html'

        context = {
            'event': event,
            'signups': signups,
            'is_logged_in': is_logged_in
        }
        if is_logged_in:
            context['current_name'] = current_name

        return render_template(template, **context)

    except Exception as e:
        flash('Failed to load event details.', 'error')
        return redirect(url_for('events.events'))


# ----------------------------------------------------------------------
# Add Potluck Contribution – /events/<event_id> (POST only)
# ----------------------------------------------------------------------
@events_bp.route('/<int:event_id>', methods=['POST'])
def add_potluck_contribution(event_id: int):
    user_id = session.get('user_id')
    is_logged_in = bool(user_id)

    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

        # Verify event exists and potluck enabled
        cur.execute("SELECT potluck_enabled FROM events WHERE id = %s", (event_id,))
        row = cur.fetchone()
        if not row or not row['potluck_enabled']:
            flash('Potluck not enabled for this event.', 'error')
            return redirect(url_for('events.view_event', event_id=event_id))

        item = request.form.get('item', '').strip()
        quantity = request.form.get('quantity', '').strip() or None
        note = request.form.get('note', '').strip() or None

        if is_logged_in:
            cur.execute("""
                SELECT CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, '')) AS full_name
                FROM users WHERE id = %s
            """, (user_id,))
            user_row = cur.fetchone()
            name = user_row['full_name'].strip() if user_row and user_row['full_name'].strip() else 'Member'
            ip = None
        else:
            name = request.form.get('name', '').strip()
            ip = request.remote_addr

        if not item or (not is_logged_in and not name):
            flash('Required fields are missing.', 'error')
            return redirect(url_for('events.view_event', event_id=event_id))

        combined_text = f"{name} {item} {quantity or ''} {note or ''}"
        if contains_censored_word(combined_text):
            flash('Your submission contains a prohibited word or phrase.', 'error')
            return redirect(url_for('events.view_event', event_id=event_id))

        if not is_logged_in:
            cur.execute("SELECT 1 FROM banned_ips WHERE ip_address = %s", (ip,))
            if cur.fetchone():
                flash('Submission blocked from this IP.', 'error')
                return redirect(url_for('events.view_event', event_id=event_id))

        # Store created_at as UTC
        created_at_utc = utc_now()

        cur = db.cursor()
        cur.execute("""
            INSERT INTO potluck_signups (event_id, name, item, quantity, note, ip, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (event_id, name, item, quantity, note, ip, created_at_utc))
        db.commit()

        if is_logged_in:
            log_change(user_id, 'add_potluck_contribution', target_id=event_id, change_details=f"Added potluck item: {item}")

        flash('Your contribution has been added!', 'success')
        return redirect(url_for('events.view_event', event_id=event_id))

    except Exception as e:
        flash('Failed to add contribution.', 'error')
        return redirect(url_for('events.view_event', event_id=event_id))


# ----------------------------------------------------------------------
# Delete Potluck Contribution – /events/<event_id>/delete_contribution/<int:signup_id> (POST only)
# ----------------------------------------------------------------------
@events_bp.route('/<int:event_id>/delete_contribution/<int:signup_id>', methods=['POST'])
@login_required
@role_required(ADMIN_OWNER_ONLY)
def delete_potluck_contribution(event_id: int, signup_id: int):
    user_id = session['user_id']

    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

        cur.execute("""
            SELECT name, item FROM potluck_signups 
            WHERE id = %s AND event_id = %s
        """, (signup_id, event_id))
        contribution = cur.fetchone()
        if not contribution:
            flash('Contribution not found.', 'error')
            return redirect(url_for('events.view_event', event_id=event_id))

        cur = db.cursor()
        cur.execute("DELETE FROM potluck_signups WHERE id = %s", (signup_id,))
        db.commit()

        log_change(
            user_id=user_id,
            action='delete_potluck_contribution',
            target_id=event_id,
            change_details=f"Deleted contribution by {contribution['name']} ({contribution['item']})"
        )
        flash('Contribution deleted successfully.', 'success')

    except Exception as e:
        db.rollback()
        flash('Failed to delete contribution.', 'error')

    return redirect(url_for('events.view_event', event_id=event_id))


# ----------------------------------------------------------------------
# Add Event – /events/add
# ----------------------------------------------------------------------
@events_bp.route('/add', methods=['GET', 'POST'])
@login_required
@role_required(REQUIRED_ROLES)
def add_event():
    user_id = session['user_id']

    if request.method == 'POST':
        try:
            # Collect all text fields for censorship check
            text_fields = [
                request.form.get('event_name', ''),
                request.form.get('description', ''),
                request.form.get('speaker_host', ''),
                request.form.get('special_guests', ''),
                request.form.get('theme', ''),
                request.form.get('agenda', ''),
                request.form.get('registration_info', ''),
                request.form.get('contact_info', ''),
                request.form.get('promotional_materials', ''),
                request.form.get('volunteer_opportunities', ''),
                request.form.get('donation_info', ''),
                request.form.get('safety_protocols', ''),
                request.form.get('follow_up', ''),
                request.form.get('event_coordinator', ''),
                request.form.get('announcements_reminders', ''),
                request.form.get('live_streaming_details', ''),
                request.form.get('feedback_form', ''),
                request.form.get('event_objectives', ''),
                request.form.get('location', ''),
                request.form.get('parking_info', ''),
                request.form.get('dress_code', ''),
                request.form.get('food_beverages', ''),
                request.form.get('childcare_availability', ''),
                request.form.get('accessibility', ''),
                request.form.get('social_media_hashtag', ''),
                request.form.get('event_sponsor', ''),
            ]
            combined_text = ' '.join(field.strip() for field in text_fields if field.strip())

            if contains_censored_word(combined_text):
                flash('Event contains a prohibited word or phrase.', 'error')
                return render_template('events/add_event.html')

            event_name = request.form['event_name'].strip()
            event_date = request.form['event_date'].strip()
            if not event_name or not event_date:
                flash('Event name and date are required.', 'error')
                return render_template('events/add_event.html')

            cost_str = request.form.get('cost_fees', '').strip()
            cost_fees = float(cost_str) if cost_str else None

            data = {
                'event_name': event_name,
                'event_date': event_date,
                'event_time': request.form.get('event_time', '').strip() or None,
                'visibility': request.form.get('visibility', 'private'),
                'potluck_enabled': 1 if request.form.get('potluck_enabled') else 0,
                'location': request.form.get('location', '').strip() or None,
                'description': request.form.get('description', '').strip() or None,
                'speaker_host': request.form.get('speaker_host', '').strip() or None,
                'special_guests': request.form.get('special_guests', '').strip() or None,
                'theme': request.form.get('theme', '').strip() or None,
                'agenda': request.form.get('agenda', '').strip() or None,
                'registration_info': request.form.get('registration_info', '').strip() or None,
                'cost_fees': cost_fees,
                'contact_info': request.form.get('contact_info', '').strip() or None,
                'childcare_availability': request.form.get('childcare_availability', '').strip() or None,
                'accessibility': request.form.get('accessibility', '').strip() or None,
                'promotional_materials': request.form.get('promotional_materials', '').strip() or None,
                'volunteer_opportunities': request.form.get('volunteer_opportunities', '').strip() or None,
                'parking_info': request.form.get('parking_info', '').strip() or None,
                'dress_code': request.form.get('dress_code', '').strip() or None,
                'food_beverages': request.form.get('food_beverages', '').strip() or None,
                'event_sponsor': request.form.get('event_sponsor', '').strip() or None,
                'social_media_hashtag': request.form.get('social_media_hashtag', '').strip() or None,
                'donation_info': request.form.get('donation_info', '').strip() or None,
                'safety_protocols': request.form.get('safety_protocols', '').strip() or None,
                'follow_up': request.form.get('follow_up', '').strip() or None,
                'event_coordinator': request.form.get('event_coordinator', '').strip() or None,
                'announcements_reminders': request.form.get('announcements_reminders', '').strip() or None,
                'feedback_form': request.form.get('feedback_form', '').strip() or None,
                'live_streaming_details': request.form.get('live_streaming_details', '').strip() or None,
                'event_objectives': request.form.get('event_objectives', '').strip() or None,
                'created_by': user_id,
                'updated_by': user_id,
            }

            db = get_db()
            cur = db.cursor()

            columns = ', '.join(data.keys())
            placeholders = ', '.join(['%s'] * len(data))
            query = f"INSERT INTO events ({columns}) VALUES ({placeholders})"

            cur.execute(query, list(data.values()))
            new_id = cur.lastrowid
            db.commit()

            log_change(user_id, 'create_event', target_id=new_id, change_details=f"Created event: {event_name}")
            flash('Event created successfully!', 'success')
            return redirect(url_for('events.events'))

        except Exception as e:
            db.rollback()
            flash('Failed to create event.', 'error')
            return render_template('events/add_event.html')

    log_change(user_id, 'view', change_details='Viewed add event form')
    return render_template('events/add_event.html')


# ----------------------------------------------------------------------
# Edit Event – /events/<event_id>/edit
# ----------------------------------------------------------------------
@events_bp.route('/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(REQUIRED_ROLES)
def edit_event(event_id: int):
    user_id = session['user_id']

    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
        event = cur.fetchone()
        if not event:
            flash('Event not found.', 'error')
            return redirect(url_for('events.events'))
    except Exception:
        flash('Failed to load event.', 'error')
        return redirect(url_for('events.events'))

    if request.method == 'POST':
        try:
            # Collect all text fields for censorship check
            text_fields = [
                request.form.get('event_name', ''),
                request.form.get('description', ''),
                request.form.get('speaker_host', ''),
                request.form.get('special_guests', ''),
                request.form.get('theme', ''),
                request.form.get('agenda', ''),
                request.form.get('registration_info', ''),
                request.form.get('contact_info', ''),
                request.form.get('promotional_materials', ''),
                request.form.get('volunteer_opportunities', ''),
                request.form.get('donation_info', ''),
                request.form.get('safety_protocols', ''),
                request.form.get('follow_up', ''),
                request.form.get('event_coordinator', ''),
                request.form.get('announcements_reminders', ''),
                request.form.get('live_streaming_details', ''),
                request.form.get('feedback_form', ''),
                request.form.get('event_objectives', ''),
                request.form.get('location', ''),
                request.form.get('parking_info', ''),
                request.form.get('dress_code', ''),
                request.form.get('food_beverages', ''),
                request.form.get('childcare_availability', ''),
                request.form.get('accessibility', ''),
                request.form.get('social_media_hashtag', ''),
                request.form.get('event_sponsor', ''),
            ]
            combined_text = ' '.join(field.strip() for field in text_fields if field.strip())

            if contains_censored_word(combined_text):
                flash('Event contains a prohibited word or phrase.', 'error')
                return render_template('events/edit_event.html', event=event)

            event_name = request.form['event_name'].strip()
            event_date = request.form['event_date'].strip()
            if not event_name or not event_date:
                flash('Event name and date are required.', 'error')
                return render_template('events/edit_event.html', event=event)

            cost_str = request.form.get('cost_fees', '').strip()
            cost_fees = float(cost_str) if cost_str else None

            data = {
                'event_name': event_name,
                'event_date': event_date,
                'event_time': request.form.get('event_time', '').strip() or None,
                'visibility': request.form.get('visibility', 'private'),
                'potluck_enabled': 1 if request.form.get('potluck_enabled') else 0,
                'location': request.form.get('location', '').strip() or None,
                'description': request.form.get('description', '').strip() or None,
                'speaker_host': request.form.get('speaker_host', '').strip() or None,
                'special_guests': request.form.get('special_guests', '').strip() or None,
                'theme': request.form.get('theme', '').strip() or None,
                'agenda': request.form.get('agenda', '').strip() or None,
                'registration_info': request.form.get('registration_info', '').strip() or None,
                'cost_fees': cost_fees,
                'contact_info': request.form.get('contact_info', '').strip() or None,
                'childcare_availability': request.form.get('childcare_availability', '').strip() or None,
                'accessibility': request.form.get('accessibility', '').strip() or None,
                'promotional_materials': request.form.get('promotional_materials', '').strip() or None,
                'volunteer_opportunities': request.form.get('volunteer_opportunities', '').strip() or None,
                'parking_info': request.form.get('parking_info', '').strip() or None,
                'dress_code': request.form.get('dress_code', '').strip() or None,
                'food_beverages': request.form.get('food_beverages', '').strip() or None,
                'event_sponsor': request.form.get('event_sponsor', '').strip() or None,
                'social_media_hashtag': request.form.get('social_media_hashtag', '').strip() or None,
                'donation_info': request.form.get('donation_info', '').strip() or None,
                'safety_protocols': request.form.get('safety_protocols', '').strip() or None,
                'follow_up': request.form.get('follow_up', '').strip() or None,
                'event_coordinator': request.form.get('event_coordinator', '').strip() or None,
                'announcements_reminders': request.form.get('announcements_reminders', '').strip() or None,
                'feedback_form': request.form.get('feedback_form', '').strip() or None,
                'live_streaming_details': request.form.get('live_streaming_details', '').strip() or None,
                'event_objectives': request.form.get('event_objectives', '').strip() or None,
                'updated_by': user_id,
            }

            set_clause = ', '.join([f"{col} = %s" for col in data])
            query = f"UPDATE events SET {set_clause} WHERE id = %s"
            values = list(data.values()) + [event_id]

            cur = db.cursor()
            cur.execute(query, values)
            db.commit()

            log_change(user_id, 'update_event', target_id=event_id, change_details=f"Updated event: {event_name}")
            flash('Event updated successfully!', 'success')
            return redirect(url_for('events.events'))

        except Exception as e:
            db.rollback()
            flash('Failed to update event.', 'error')
            return render_template('events/edit_event.html', event=event)

    log_change(user_id, 'view', change_details=f"Viewed edit event form ID {event_id}")
    return render_template('events/edit_event.html', event=event)


# ----------------------------------------------------------------------
# Delete Event – /events/<event_id>/delete
# ----------------------------------------------------------------------
@events_bp.route('/<int:event_id>/delete', methods=['POST'])
@login_required
@role_required(ADMIN_OWNER_ONLY)
def delete_event(event_id: int):
    user_id = session['user_id']

    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

        cur.execute("SELECT event_name FROM events WHERE id = %s", (event_id,))
        row = cur.fetchone()
        if not row:
            flash('Event not found.', 'error')
            return redirect(url_for('events.events'))
        event_name = row['event_name']

        cur = db.cursor()
        cur.execute("DELETE FROM potluck_signups WHERE event_id = %s", (event_id,))
        cur.execute("DELETE FROM events WHERE id = %s", (event_id,))
        db.commit()

        log_change(user_id, 'delete_event', target_id=event_id, change_details=f"Deleted event: {event_name}")
        flash('Event deleted successfully.', 'success')

    except Exception as e:
        db.rollback()
        flash('Failed to delete event.', 'error')

    return redirect(url_for('events.events'))


# ----------------------------------------------------------------------
# Email Invitations – /events/email
# ----------------------------------------------------------------------
@events_bp.route('/email', methods=['POST'])
@login_required
@role_required(REQUIRED_ROLES)
def email_event():
    user_id = session['user_id']
    event_id = request.form.get('event_id')
    subject = request.form.get('subject', '').strip()
    message = request.form.get('message', '').strip()

    if not subject or not event_id:
        flash('Subject and event are required.', 'error')
        return redirect(url_for('events.events'))

    try:
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

        cur.execute("SELECT event_name FROM events WHERE id = %s", (event_id,))
        row = cur.fetchone()
        if not row:
            flash('Event not found.', 'error')
            return redirect(url_for('events.events'))
        event_name = row['event_name']

        if 'sendAll' in request.form:
            cur.execute("SELECT email FROM users WHERE accepts_event_emails = 1")
        else:
            member_ids = request.form.getlist('member_ids')
            if not member_ids:
                flash('No recipients selected.', 'error')
                return redirect(url_for('events.events'))
            placeholders = ','.join(['%s'] * len(member_ids))
            cur.execute(f"SELECT email FROM users WHERE id IN ({placeholders}) AND accepts_event_emails = 1", member_ids)

        emails = [r['email'] for r in cur.fetchall()]

        if not emails:
            flash('No valid recipients found.', 'error')
            return redirect(url_for('events.events'))

        body = f"{message}\n\nEvent: {event_name}\nView details at myvinechurch.online/events/{event_id}"

        from app.utils.emailer import send_email
        for email_addr in emails:
            send_email(email_addr, subject, body)

        log_change(user_id, 'email_event', target_id=event_id, change_details=f"Sent invitations for event: {event_name}")
        flash('Invitations sent successfully!', 'success')

    except Exception as e:
        flash('Failed to send emails.', 'error')

    return redirect(url_for('events.events'))