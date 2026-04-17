# MYVINECHURCH.ONLINE/app/routes/public/dreams/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/dreams/views.py
# File name: views.py
# Brief, detailed purpose: Public Dreams & Visions routes for unauthenticated guests only.
# • Listing shows only public + approved dreams with creator_name.
# • Detail page supports guest comments/replies (one-level).
# • Logged-in users are redirected to private dreams.
# • 100% rebuilt clean version - identical structure to the working public/events/views.py gold standard.
# • ADDED: extensive console debugging + guaranteed key names that match dreams.html template.

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import dreams_bp
from .queries import get_public_dreams, get_public_dream
from .forms import validate_guest_comment_form
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word


# ----------------------------------------------------------------------
# Public Dreams Listing (Guests Only)
# ----------------------------------------------------------------------
@dreams_bp.route('/')
def public_dreams():
    """Public dreams listing – logged-in users are redirected to the private dreams dashboard."""
    print("🔍 [PUBLIC DREAMS] Route /dreams hit (sub-blueprint)")

    if 'user_id' in session:
        print("🔄 [PUBLIC DREAMS] Logged-in user → redirecting to private dreams")
        return redirect(url_for('dreams.dreams'))

    # Guest view only
    dreams = get_public_dreams()
    print(f"📊 [PUBLIC DREAMS] Raw dreams returned from query: {len(dreams)} records")

    # Censorship first
    dreams = censor_public_content(dreams)

    # Prepare data for template (EXACT keys that dreams.html expects)
    for d in dreams:
        # Safe date formatting (handles both datetime and string)
        posted = d.get('date_posted')
        if posted:
            if hasattr(posted, 'strftime'):
                d['date_posted'] = posted  # keep original object so .strftime works in template
                d['datetime'] = posted.strftime('%B %d, %Y')
            else:
                d['datetime'] = str(posted)[:10]
                # ensure date_posted is still present for template
        else:
            d['datetime'] = 'Unknown'

        # Guarantee both creator_name and poster_name (template uses either)
        d['creator_name'] = d.get('creator_name') or d.get('contributor_name') or 'Anonymous'
        d['posted_by'] = d['creator_name']          # alias for older template compatibility
        d['poster_name'] = d['creator_name']

        print(f"   → Dream ID {d.get('id')}: '{d.get('title')}' by {d['creator_name']}")

    print(f"✅ [PUBLIC DREAMS] Final dreams list passed to template: {len(dreams)} items")
    return render_template('public/dreams/dreams.html', dreams=dreams)


# ----------------------------------------------------------------------
# Public Single Dream Detail (Guests Only + Comments/Replies)
# ----------------------------------------------------------------------
@dreams_bp.route('/<int:dream_id>', methods=['GET', 'POST'])
def public_dream_detail(dream_id):
    """Public single dream detail with guest comments/replies."""
    print(f"🔍 [PUBLIC DREAM DETAIL] Route /dreams/{dream_id} hit")

    if 'user_id' in session:
        print("🔄 [PUBLIC DREAM DETAIL] Logged-in user → redirecting to private view")
        return redirect(url_for('dreams.view_dream', dream_id=dream_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    dream = get_public_dream(dream_id)
    if not dream:
        print(f"❌ [PUBLIC DREAM DETAIL] Dream {dream_id} not found or not public")
        abort(404)

    # Censor content for public view
    dream['title']       = censor_text(dream.get('title', ''))
    dream['description'] = censor_text(dream.get('description', ''))
    dream['notes']       = censor_text(dream.get('notes', ''))

    # Load comments (including one-level replies)
    comments = []
    try:
        cur.execute("""
            SELECT 
                c.id,
                c.comment,
                DATE_FORMAT(c.date_posted, '%%b %%e, %%Y %%h:%%i %%p') as date,
                c.parent_id,
                COALESCE(u.username, c.contributor_name, 'Guest') AS name
            FROM dream_comments c
            LEFT JOIN users u ON c.user_id = u.id
            WHERE c.dream_id = %s
            ORDER BY c.date_posted ASC
        """, (dream_id,))
        comments = cur.fetchall()
        print(f"📝 [PUBLIC DREAM DETAIL] Loaded {len(comments)} comments/replies")
    except Exception as e:
        print(f"⚠️ [PUBLIC DREAM DETAIL] Comments query failed: {e}")

    dream['comments'] = comments

    # Handle POST - guest comment or reply
    if request.method == 'POST':
        action = request.form.get('action')
        print(f"📤 [PUBLIC DREAM DETAIL] POST action = {action}")

        if action in ('comment', 'reply'):
            clean = validate_guest_comment_form(request.form)
            if not clean:
                return redirect(url_for('public.public_dreams.public_dream_detail', dream_id=dream_id))

            try:
                cur.execute("""
                    INSERT INTO dream_comments 
                    (dream_id, contributor_name, comment, parent_id, date_posted)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (dream_id, clean['name'], clean['comment'], clean['parent_id']))
                db.commit()
                flash('Comment posted successfully!', 'success')
                print("✅ Comment inserted")
            except Exception as e:
                flash('Failed to post comment.', 'error')
                print(f"❌ Insert failed: {e}")

        return redirect(url_for('public.public_dreams.public_dream_detail', dream_id=dream_id))

    return render_template('public/dreams/view_dream.html', dream=dream)


print("✅ MYVINECHURCH.ONLINE public/dreams/views.py rebuilt successfully (full debug + key compatibility)")