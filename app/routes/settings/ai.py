# myvinechurchonline/app/routes/settings/ai.py
# Full path: myvinechurchonline/app/routes/settings/ai.py
# File name: ai.py
# Brief, detailed purpose: AI provider/key/base URL configuration.
# CONFIRMED CORRECT: Package-relative imports – loads shared items from settings/__init__.py.
# Optimized DB access: single load_settings() call, reload after save for fresh data.
# Standardized 5-argument log_change.

from flask import render_template, request, redirect, url_for, flash, session
from app.models.db import get_db
from app.models.log import log_change
from . import settings_bp, encrypt, has_section_permission, load_settings

@settings_bp.route('/ai', methods=['GET', 'POST'])
def ai():
    if request.method == 'POST' and not has_section_permission('ai'):
        flash('Insufficient permission to edit AI settings.', 'error')
        return redirect(url_for('settings.ai'))

    db = get_db()
    user_id = session['user_id']

    # Single load at start – used for preservation and initial render
    settings = load_settings()

    if request.method == 'POST':
        new_key = request.form.get('ai_api_key', '').strip()

        updates = {
            'ai_provider': request.form.get('ai_provider', 'grok'),
            'ai_api_key': encrypt(new_key) if new_key else settings.get('ai_api_key'),
            'ai_base_url': request.form.get('ai_base_url', '').strip() or None,
        }
        set_clause = ", ".join(f"{k} = %s" for k in updates)
        values = list(updates.values())
        cur = db.cursor()
        cur.execute(f"UPDATE settings SET {set_clause} WHERE id = 1", values)
        db.commit()

        log_change(user_id, 'update', None, None, 'Updated AI configuration')
        flash('AI settings saved.', 'success')

        # Reload fresh data after save
        settings = load_settings()

    return render_template('settings/ai.html', settings=settings)