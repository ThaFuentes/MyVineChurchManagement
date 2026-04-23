# MYVINECHURCH.ONLINE/app/routes/the_gathering/dashboard/utils.py
# Full path: MYVINECHURCH.ONLINE/app/routes/the_gathering/dashboard/utils.py
# File name: utils.py
# Brief, detailed purpose: Feature-specific utility functions for the main Gathering Place Manager Dashboard.
# • Provides manager-focused censorship (with flagging of censored content), datetime formatting, and safe truncation.
# • 100% rebuilt to match the exact clean, modular style of public/events/utils.py and public/dreams/utils.py
#   (detailed section comments, enhanced docstrings, consistent naming, no behavior changes).
# • All original functions (censor_for_manager, format_manager_datetime, safe_truncate) and their exact logic
#   are preserved 100% — only readability, documentation, and consistency with the public gold standard were updated.

from app.utils.helpers import censor_text
from app.utils.time_utils import format_church
import html


# ----------------------------------------------------------------------
# Gathering Place Manager Helpers
# ----------------------------------------------------------------------
def censor_for_manager(items, fields=None):
    """Apply light censorship for internal manager views with flagging.

    Unlike public censorship, this version marks items that contained censored content
    (sets 'has_censored_content' flag) and stores both the original and censored versions
    (e.g. title_censored) for manager review and audit purposes.
    Used by the dashboard recent activity feed and any manager list views.
    """
    if fields is None:
        fields = ['title', 'name', 'comment_text']

    for item in items:
        item['has_censored_content'] = False
        for key in fields:
            if key in item and item[key]:
                original = str(item[key])
                censored = censor_text(original)
                if censored != original:
                    item['has_censored_content'] = True
                    item[f'{key}_censored'] = censored
    return items


def format_manager_datetime(date_value):
    """Format any datetime for manager dashboard display using the church's timezone helper.

    Uses a compact, readable format suitable for internal admin views (exact same behavior
    as the original version).
    """
    if date_value:
        return format_church(date_value, '%b %d, %Y • %I:%M %p')
    return 'Unknown date'


def safe_truncate(text, length=180):
    """Safely truncate text with HTML escaping to prevent template rendering issues.

    Used for previews on the dashboard recent activity feed and any long-text summaries.
    Exact same logic as original (escapes, truncates at word boundary, adds ellipsis).
    """
    if not text:
        return ''
    text = html.escape(str(text))
    if len(text) > length:
        return text[:length].rsplit(' ', 1)[0] + '…'
    return text


print("✅ MYVINECHURCH.ONLINE the_gathering/dashboard/utils.py loaded successfully (public-style rebuilt)")