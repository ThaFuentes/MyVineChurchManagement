# MYVINECHURCH.ONLINE/app/routes/public/announcements/views.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/announcements/views.py
# File name: views.py
# Brief, detailed purpose: Public Announcements routes for unauthenticated guests only.
# • Listing shows only public + active announcements with creator_name.
# • Detail page supports guest comments/replies (one-level).
# • Logged-in users are redirected to private announcements.
# • Uses local queries.py, forms.py and utils.py for modularity.
# • 100% rebuilt clean version - identical structure to the working public/events/views.py and public/dreams/views.py gold standard.
# • ADDED: extensive console debugging + guaranteed key names.

from flask import render_template, abort, request, flash, redirect, url_for, session
import pymysql

from . import announcements_bp
from .queries import get_public_announcements, get_public_announcement
from .forms import validate_guest_comment_form
from .utils import censor_public_content

from app.models.db import get_db
from app.utils.helpers import censor_text, contains_censored_word


# ----------------------------------------------------------------------
# Public Announcements Listing (Guests Only)
# ----------------------------------------------------------------------
@announcements_bp.route('/')
def public_announcements():
    """Public announcements listing – logged-in users are redirected to the private announcements dashboard."""
    print("🔍 [PUBLIC ANNOUNCEMENTS] Route /public-announcements/ hit (sub-blueprint)")

    if 'user_id' in session:
        print("🔄 [PUBLIC ANNOUNCEMENTS] Logged-in user → redirecting to private announcements")
        return redirect(url_for('announcements.announcements'))

    # Guest view only
    announcements = get_public_announcements()
    print(f"📊 [PUBLIC ANNOUNCEMENTS] Raw announcements returned from query: {len(announcements)} records")

    # Censorship first
    announcements = censor_public_content(announcements)

    # Prepare data for template (EXACT keys that the template expects)
    for a in announcements:
        # Safe date formatting
        posted = a.get('created_at')
        if posted:
            if hasattr(posted, 'strftime'):
                a['datetime'] = posted.strftime('%B %d, %Y')
            else:
                a['datetime'] = str(posted)[:10]
        else:
            a['datetime'] = 'Unknown'

        # Guarantee creator_name and posted_by
        a['creator_name'] = a.get('creator_name') or a.get('posted_by') or 'Anonymous'
        a['posted_by'] = a['creator_name']

        print(f"   → Announcement ID {a.get('id')}: '{a.get('title')}' by {a['creator_name']}")

    print(f"✅ [PUBLIC ANNOUNCEMENTS] Final announcements list passed to template: {len(announcements)} items")
    return render_template('public/announcements/announcements.html', announcements=announcements)


# ----------------------------------------------------------------------
# Public Single Announcement Detail (Guests Only + Comments/Replies)
# ----------------------------------------------------------------------
@announcements_bp.route('/<int:ann_id>', methods=['GET', 'POST'])
def public_announcement_detail(ann_id):
    """Public single announcement detail with guest comments/replies."""
    print(f"🔍 [PUBLIC ANNOUNCEMENT DETAIL] Route /public-announcements/{ann_id} hit")

    if 'user_id' in session:
        print("🔄 [PUBLIC ANNOUNCEMENT DETAIL] Logged-in user → redirecting to private view")
        return redirect(url_for('announcements.view_announcement', ann_id=ann_id))

    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    announcement = get_public_announcement(ann_id)
    if not announcement:
        print(f"❌ [PUBLIC ANNOUNCEMENT DETAIL] Announcement {ann_id} not found or not public/active")
        abort(404)

    # Censor content for public view
    announcement['title']   = censor_text(announcement.get('title', ''))
    announcement['content'] = censor_text(announcement.get('content', ''))

    # Load comments (including one-level replies)
    comments = []
    try:
        cur.execute("""
            SELECT 
                c.id,
                c.comment,
                DATE_FORMAT(c.date_added, '%%b %%e, %%Y %%h:%%i %%p') as date,
                c.parent_id,
                COALESCE(u.username, c.contributor_name, 'Guest') AS name
            FROM announcement_comments c
            LEFT JOIN users u ON c.user_id = u.id
            WHERE c.announcement_id = %s
            ORDER BY c.date_added ASC
        """, (ann_id,))
        comments = cur.fetchall()
        print(f"📝 [PUBLIC ANNOUNCEMENT DETAIL] Loaded {len(comments)} comments/replies")
    except Exception as e:
        print(f"⚠️ [PUBLIC ANNOUNCEMENT DETAIL] Comments query failed: {e}")

    announcement['comments'] = comments

    # Handle POST - guest comment or reply
    if request.method == 'POST':
        action = request.form.get('action')
        print(f"📤 [PUBLIC ANNOUNCEMENT DETAIL] POST action = {action}")

        if action in ('comment', 'reply'):
            clean = validate_guest_comment_form(request.form)
            if not clean:
                return redirect(url_for('public.public_announcements.public_announcement_detail', ann_id=ann_id))

            try:
                cur.execute("""
                    INSERT INTO announcement_comments 
                    (announcement_id, contributor_name, comment, parent_id, date_added)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (ann_id, clean['name'], clean['comment'], clean['parent_id']))
                db.commit()
                flash('Comment posted successfully!', 'success')
                print("✅ Comment inserted")
            except Exception as e:
                flash('Failed to post comment.', 'error')
                print(f"❌ Insert failed: {e}")

        return redirect(url_for('public.public_announcements.public_announcement_detail', ann_id=ann_id))

    return render_template('public/announcements/view_announcement.html', announcement=announcement)


print("✅ MYVINECHURCH.ONLINE public/announcements/views.py rebuilt successfully (full debug + gold standard applied)")