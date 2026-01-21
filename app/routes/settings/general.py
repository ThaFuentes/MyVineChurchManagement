# myvinechurchonline/app/routes/settings/general.py
# Full path: myvinechurchonline/app/routes/settings/general.py
# File name: general.py
# Brief, detailed purpose: General church info settings (name, address, contact, paths).
# CONFIRMED CORRECT: Package-relative imports – loads shared items from settings/__init__.py.
# Uses centralized load_settings() from package __init__.py.
# Standardized 5-argument log_change.

from flask import render_template, request, redirect, url_for, flash, session
from app.models.db import get_db
from app.models.log import log_change
from . import settings_bp, has_section_permission, load_settings  # Package-relative
from app.utils.helpers import contains_censored_word

@settings_bp.route('/general', methods=['GET', 'POST'])
def general():
    if request.method == 'POST' and not has_section_permission('general'):
        flash('Insufficient permission to edit General settings.', 'error')
        return redirect(url_for('settings.general'))

    db = get_db()
    user_id = session['user_id']

    if request.method == 'POST':
        visible_text = ' '.join([
            request.form.get('church_name', ''),
            request.form.get('pastor', ''),
            request.form.get('address', ''),
            request.form.get('phone_number', ''),
        ])
        if contains_censored_word(visible_text):
            flash('General settings contain a prohibited word or phrase.', 'error')
            return redirect(url_for('settings.general'))

        updates = {
            'church_name': request.form.get('church_name', '').strip() or None,
            'tax_status': request.form.get('tax_status', '').strip() or None,
            'address': request.form.get('address', '').strip() or None,
            'phone_number': request.form.get('phone_number', '').strip() or None,
            'pastor': request.form.get('pastor', '').strip() or None,
            'icon_path': request.form.get('icon_path', '').strip() or None,
            'export_location': request.form.get('export_location', '').strip() or None,
            'sermon_folder_location': request.form.get('sermon_folder_location', '').strip() or None,
        }
        set_clause = ", ".join(f"{k} = %s" for k in updates if updates[k] is not None)
        values = [v for v in updates.values() if v is not None]
        if set_clause:
            cur = db.cursor()
            cur.execute(f"UPDATE settings SET {set_clause} WHERE id = 1", values)
            db.commit()
            log_change(user_id, 'update', None, None, 'Updated church & general settings')
            flash('Church & general settings saved.', 'success')

    settings = load_settings()
    return render_template('settings/general.html', settings=settings)