# MYVINECHURCH.ONLINE/app/routes/public/public_dashboard/forms.py
# Full path: MYVINECHURCH.ONLINE/app/routes/public/public_dashboard/forms.py
# File name: forms.py
# Brief, detailed purpose: Form validation and data cleaning for the Public Dashboard module.
# • The public dashboard is a read-only rich feed (no guest forms, no potluck, no comments on the homepage itself).
# • This file exists for full structural consistency with every other public feature (dreams, events, announcements, etc.).
# • No validation functions are needed – kept minimal and clean so the modular layout remains identical across all sub-folders.

from flask import flash
from app.utils.helpers import contains_censored_word


# No forms are used on the public dashboard feed.
# All guest comment / potluck / reply forms live in their individual feature folders (events, dreams, etc.).
# This file is intentionally empty (except for the standard header) to maintain 100% consistent project structure.

print("✅ MYVINECHURCH.ONLINE public/public_dashboard/forms.py loaded successfully (no forms required for dashboard feed)")