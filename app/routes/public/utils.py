# app/routes/public/utils.py
# Full path: MyVineChurch/app/routes/public/utils.py
# File name: utils.py
# Brief, detailed purpose: Utility functions and constants for the Public module.
# • Public-facing helpers (censoring for previews and listings).
# • Keeps all feature files (events, dreams, etc.) clean and consistent.
# • 100% original behavior preserved.

from app.utils.helpers import censor_text
from app.utils.time_utils import format_church   # ← Moved to top for best practice


# ----------------------------------------------------------------------
# Public Helpers
# ----------------------------------------------------------------------
def censor_public_content(items):
    """Apply server-side censorship to a list of public items.
    Used by all public listing routes (events, sermons, dreams, etc.)."""
    for item in items:
        for key in ['title', 'description', 'content', 'name', 'item', 'note', 'location', 'event_name']:
            if key in item and item[key]:
                item[key] = censor_text(item[key])
    return items


def format_public_datetime(date_value):
    """Format datetime for public pages using the church's timezone helper."""
    if date_value:
        return format_church(date_value, '%B %d, %Y at %I:%M %p')
    return 'Unknown date'