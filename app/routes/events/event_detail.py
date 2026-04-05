# app/routes/events/event_detail.py
# Full path: MyVineChurch/app/routes/events/event_detail.py
# File name: event_detail.py
# Brief, detailed purpose: Contains only the single event VIEW route (/events/view/<event_id> GET + POST).
# Explicit /view/ in URL to clearly indicate "view event" (no longer /events/<id>).
# Handles visibility enforcement, potluck signup fetch (robust), and potluck contribution submission.
# Server-side censorship on all contribution fields.
# Renders events/view_event.html (private/internal view).
# Private events require login – guests redirected to login.
# No other routes or logic – pure extraction + URL clarification.

from flask import render_template, request, redirect, url_for, flash, session
from app.utils.decorators import login_required
from app.utils.helpers import contains_censored_word
from app.models.db import get_db
from app.models.log import log_change
from app.utils.time_utils import format_church
import pymysql

def register_detail_routes(bp):
    @bp.route('/view/<int:event_id>', methods=['GET', 'POST'])
    @login_required  # Private view – forces login
    def view_event(event_id):
        db = get_db()
        cur = db.cursor(pymysql.cursors.DictCursor)

        # Fetch event (private events allowed since login required)
        cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
        event = cur.fetchone()
        if not event:
            flash('Event not found.', 'error')
            return redirect(url_for('events.events'))

        # Potluck signups (robust – survives missing table/old DB)
        signups = []
        if event.get('potluck_enabled'):
            try:
                cur.execute("""
                    SELECT *, created_at AS created_at_utc
                    FROM potluck_signups
                    WHERE event_id = %s
                    ORDER BY created_at DESC
                """, (event_id,))
                signups = cur.fetchall()
                for s in signups:
                    s['created_at_nice'] = format_church(s['created_at_utc'])
            except Exception:
                pass  # Old DB without table – ignore

        # ---------- POST: Potluck contribution ----------
        if request.method == 'POST':
            if not event.get('potluck_enabled'):
                flash('Potluck is not enabled for this event.', 'error')
                return redirect(url_for('events.view_event', event_id=event_id))

            # Auto-fill name for logged-in members
            cur.execute("""
                SELECT first_name, last_name FROM users WHERE id = %s
            """, (session['user_id'],))
            user = cur.fetchone()
            name = f"{user['first_name']} {user['last_name']}".strip() if user else 'Member'

            item = request.form.get('item', '').strip()
            quantity = request.form.get('quantity', '').strip()
            note = request.form.get('note', '').strip()

            if not item:
                flash('Item description is required.', 'error')
                return redirect(url_for('events.view_event', event_id=event_id))

            # Censorship check
            if any(contains_censored_word(field) for field in [name, item, quantity or '', note or '']):
                flash('Contribution contains a prohibited word or phrase.', 'error')
                return redirect(url_for('events.view_event', event_id=event_id))

            try:
                cur = db.cursor()
                cur.execute("""
                    INSERT INTO potluck_signups
                    (event_id, name, item, quantity, note)
                    VALUES (%s, %s, %s, %s, %s)
                """, (event_id, name, item, quantity or None, note or None))
                db.commit()

                log_change(session['user_id'], 'potluck_contribution',
                           target_id=event_id,
                           change_details=f"Contributed {quantity or ''} {item}")

                flash('Thank you for your potluck contribution!', 'success')
            except Exception:
                db.rollback()
                flash('Failed to record contribution.', 'error')

            return redirect(url_for('events.view_event', event_id=event_id))

        # GET – render private detail view
        return render_template(
            'events/view_event.html',
            event=event,
            signups=signups
        )