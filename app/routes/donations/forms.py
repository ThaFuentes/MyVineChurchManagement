# app/routes/donations/forms.py
# Full path: MyVineChurch/app/routes/donations/forms.py
# File name: forms.py
# Brief, detailed purpose: Form validation and data cleaning for the Donations module.
# • Validates add and edit donation forms (required fields, amount as float, server-side censored word check on name + notes).
# • Handles Company EIN appending to notes for permanent record.
# • Returns clean data dict on success, or None + flash message + repopulates form on error (keeps views.py clean).
# • 100% matches the original censorship + repopulation logic from donations.py.

from flask import flash
from app.utils.helpers import contains_censored_word


def validate_add_donation_form(form_data):
    """
    Validate and clean the Add Donation form.
    Returns clean dict on success, or None + flash + repopulates form on error.
    """
    name = form_data.get('name', '').strip()
    amount_str = form_data.get('amount', '').strip()
    date = form_data.get('date', '').strip()
    method = form_data.get('method', '').strip()
    notes = form_data.get('notes', '').strip()
    confirmation_number = form_data.get('confirmation_number', '').strip()
    goods_services_provided = 1 if 'goods_services_provided' in form_data else 0

    # Required fields
    if not name or not amount_str or not date or not method:
        flash('Name, Amount, Date, and Payment Method are required.', 'error')
        return None

    try:
        amount = float(amount_str)
    except ValueError:
        flash('Amount must be a valid number.', 'error')
        return None

    # Censored word check on visible text (name + notes)
    combined_text = f"{name} {notes}"
    if contains_censored_word(combined_text):
        flash('Donation record contains a prohibited word or phrase.', 'error')
        return None

    # Handle Company EIN
    company_ein = form_data.get('company_ein', '').strip()
    if company_ein:
        ein_text = f"Company EIN: {company_ein}"
        notes = notes + ("\n" if notes else "") + ein_text

    return {
        'name': name,
        'amount': amount,
        'date': date,
        'method': method,
        'notes': notes,
        'confirmation_number': confirmation_number,
        'goods_services_provided': goods_services_provided
    }


def validate_edit_donation_form(form_data):
    """
    Validate and clean the Edit Donation form.
    Returns clean dict on success, or None + flash on error.
    """
    name = form_data.get('name', '').strip()
    amount_str = form_data.get('amount', '').strip()
    date = form_data.get('date', '').strip()
    method = form_data.get('method', '').strip()
    notes = form_data.get('notes', '').strip()

    if not name or not amount_str or not date or not method:
        flash('Name, Amount, Date, and Payment Method are required.', 'error')
        return None

    try:
        amount = float(amount_str)
    except ValueError:
        flash('Amount must be a valid number.', 'error')
        return None

    # Censored word check
    combined_text = f"{name} {notes}"
    if contains_censored_word(combined_text):
        flash('Donation record contains a prohibited word or phrase.', 'error')
        return None

    return {
        'name': name,
        'amount': amount,
        'date': date,
        'method': method,
        'notes': notes
    }