# app/routes/public/utils.py
# Full path: MyVineChurch/app/routes/public/utils.py
# File name: utils.py
# Brief, detailed purpose: Utility functions and constants for the Public module.
# • Public-facing helpers (censoring for previews and listings, formatting).
# • Keeps views.py clean and consistent with other packages.
# • 100% matches the original public.py intent.

from app.utils.helpers import censor_text


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
# No role restrictions for public routes (guest-friendly)
PUBLIC_ROLES = []  # Placeholder for future consistency


# ----------------------------------------------------------------------
# Public Helpers
# ----------------------------------------------------------------------
def censor_public_content(items):
    """Apply server-side censorship to a list of public items (titles, descriptions, names, notes, etc.)."""
    for item in items:
        for key in ['title', 'description', 'content', 'name', 'item', 'note', 'location', 'event_name']:
            if key in item and item[key]:
                item[key] = censor_text(item[key])
    return items


def format_public_datetime(date_value):
    """Optional helper for public date formatting (can be expanded)."""
    from app.utils.time_utils import format_church
    if date_value:
        return format_church(date_value, '%B %d, %Y at %I:%M %p')
    return 'Unknown date'