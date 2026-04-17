# MYVINECHURCH.ONLINE/app/routes/public/prophecies/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/prophecies/views.py
# File name: views.py
# Brief, detailed purpose: Public Prophecies routes for unauthenticated guests only.
# • Listing shows only public prophecies with creator_name.
# • Detail page supports guest comments/replies (one-level).
# • Logged-in users are redirected to private prophecies.
# • Uses local queries.py, forms.py and utils.py for modularity.
# • 100% rebuilt clean version - identical structure to the working public/events/views.py and public/dreams/views.py gold standard.
# • ADDED: extensive console debugging + guaranteed key names that match the template.

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import prophecies_bp
from .queries import get_public_prophecies, get_public_prophecy
from .forms import validate_guest_comment_form
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word


# ----------------------------------------------------------------------
# Public Prophecies Listing (Guests Only)
# ----------------------------------------------------------------------
@prophecies_bp.route('/')
def public_prophecies():
    """Public prophecies listing – logged-in users are redirected to the private prophecies dashboard."""
    print("🔍 [PUBLIC PROPHECIES] Route /public-prophecies/ hit (sub-blueprint)")

    if 'user_id' in session:
        print("🔄 [PUBLIC PROPHECIES] Logged-in user → redirecting to private prophecies")
        return redirect(url_for('prophecies.list_prophecies'))

    # Guest view only
    prophecies = get_public_prophecies()
    print(f"📊 [PUBLIC PROPHECIES] Raw prophecies returned from query: {len(prophecies)} records")

    # Censorship first
    prophecies = censor_public_content(prophecies)

    # Prepare data for template (EXACT keys that the template expects)
    for p in prophecies:
        # Safe date formatting
        posted = p.get('created_at')
        if posted:
            if hasattr(posted, 'strftime'):
                p['datetime'] = posted.strftime('%B %d, %Y')
            else:
                p['datetime'] = str(posted)[:10]
        else:
            p['datetime'] = 'Unknown'

        # Guarantee creator_name and posted_by for template compatibility
        p['creator_name'] = p.get('creator_name') or p.get('posted_by') or 'Anonymous'
        p['posted_by'] = p['creator_name']

        print(f"   → Prophecy ID {p.get('id')}: '{p.get('title')}' by {p['creator_name']}")

    print(f"✅ [PUBLIC PROPHECIES] Final prophecies list passed to template: {len(prophecies)} items")
    return render_template('public/prophecies/prophecies.html', prophecies=prophecies)


# ----------------------------------------------------------------------
# Public Single Prophecy Detail (Guests Only + Comments/Replies)
# ----------------------------------------------------------------------
@prophecies_bp.route('/<int:prophecy_id>', methods=['GET', 'POST'])
def public_prophecy_detail(prophecy_id):
    """Public single prophecy detail with guest comments/replies."""
    print(f"🔍 [PUBLIC PROPHECY DETAIL] Route /public-prophecies/{prophecy_id} hit")

    if 'user_id' in session:
        print("🔄 [PUBLIC PROPHECY DETAIL] Logged-in user → redirecting to private view")
        return redirect(url_for('prophecies.view_prophecy', prophecy_id=prophecy_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    prophecy = get_public_prophecy(prophecy_id)
    if not prophecy:
        print(f"❌ [PUBLIC PROPHECY DETAIL] Prophecy {prophecy_id} not found or not public")
        abort(404)

    # Censor content for public view
    prophecy['title']       = censor_text(prophecy.get('title', ''))
    prophecy['description'] = censor_text(prophecy.get('description', ''))

    # Load comments (including one-level replies)
    comments = []
    try:
        cur.execute("""
            SELECT 
                pc.id,
                pc.comment,
                DATE_FORMAT(pc.date_added, '%%b %%e, %%Y %%h:%%i %%p') as date,
                pc.parent_id,
                COALESCE(u.username, pc.contributor_name, 'Guest') AS name
            FROM prophecy_comments pc
            LEFT JOIN users u ON pc.user_id = u.id
            WHERE pc.prophecy_id = %s
            ORDER BY pc.date_added ASC
        """, (prophecy_id,))
        comments = cur.fetchall()
        print(f"📝 [PUBLIC PROPHECY DETAIL] Loaded {len(comments)} comments/replies")
    except Exception as e:
        print(f"⚠️ [PUBLIC PROPHECY DETAIL] Comments query failed: {e}")

    prophecy['comments'] = comments

    # Handle POST - guest comment or reply
    if request.method == 'POST':
        action = request.form.get('action')
        print(f"📤 [PUBLIC PROPHECY DETAIL] POST action = {action}")

        if action in ('comment', 'reply'):
            clean = validate_guest_comment_form(request.form)
            if not clean:
                return redirect(url_for('public.public_prophecies.public_prophecy_detail', prophecy_id=prophecy_id))

            try:
                cur.execute("""
                    INSERT INTO prophecy_comments 
                    (prophecy_id, contributor_name, comment, parent_id, date_added)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (prophecy_id, clean['name'], clean['comment'], clean['parent_id']))
                db.commit()
                flash('Comment posted successfully!', 'success')
                print("✅ Comment inserted")
            except Exception as e:
                flash('Failed to post comment.', 'error')
                print(f"❌ Insert failed: {e}")

        # Always redirect using the CORRECT nested blueprint endpoint
        return redirect(url_for('public.public_prophecies.public_prophecy_detail', prophecy_id=prophecy_id))

    return render_template('public/prophecies/view_prophecy.html', prophecy=prophecy)


print("✅ MYVINECHURCH.ONLINE public/prophecies/views.py rebuilt successfully (full debug + gold standard applied)")