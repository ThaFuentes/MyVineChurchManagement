# app/routes/tickets/forms.py
# Full path: myvinechurchonline/app/routes/tickets/forms.py
# File name: forms.py
# Brief, detailed purpose: All form validation + censored word checks + repopulation logic for the tickets blueprint.
# Every original validation block, flash message, and censored-word check moved here 100% unchanged in behavior.
# Returns clean data + error lists so views.py can keep identical logic and template repopulation.

from app.utils.helpers import contains_censored_word


def validate_ticket_submission(form_data, is_logged_in=False):
    """
    Validate data from /tickets/submit form (member or guest).
    Returns tuple: (is_valid: bool, errors: list of str, cleaned_data: dict)
    """
    errors = []
    cleaned = {
        'title': '',
        'description': '',
        'category_id': None,
        'priority': 'medium',
        'contact_name': None,
        'contact_email': None
    }

    title = form_data.get('title', '').strip()
    description = form_data.get('description', '').strip()
    category_id = form_data.get('category_id')
    priority = form_data.get('priority', 'medium')

    cleaned['title'] = title
    cleaned['description'] = description
    cleaned['category_id'] = category_id
    cleaned['priority'] = priority

    if not title:
        errors.append('Title is required.')
    if not description:
        errors.append('Description is required.')
    if not category_id:
        errors.append('Category is required.')

    if not is_logged_in:
        contact_name = form_data.get('contact_name', '').strip()
        contact_email = form_data.get('contact_email', '').strip()
        cleaned['contact_name'] = contact_name
        cleaned['contact_email'] = contact_email

        if not contact_name:
            errors.append('Name is required for guest submissions.')
        if not contact_email:
            errors.append('Email is required for guest submissions.')

    # Censored word check (original exact combined string)
    if contains_censored_word(f"{title} {description}"):
        errors.append('Entry contains a prohibited word or phrase.')

    is_valid = len(errors) == 0
    return is_valid, errors, cleaned


def validate_ticket_comment(form_data, can_manage=False):
    """
    Validate data from view_ticket comment form.
    Returns tuple: (is_valid: bool, errors: list of str, cleaned_data: dict)
    """
    errors = []
    cleaned = {
        'comment': '',
        'notify_creator': False
    }

    comment = form_data.get('comment', '').strip()
    notify_creator = can_manage and 'notify_creator' in form_data

    cleaned['comment'] = comment
    cleaned['notify_creator'] = notify_creator

    if not comment:
        errors.append('Comment cannot be empty.')
    elif contains_censored_word(comment):
        errors.append('Comment contains a prohibited word.')

    is_valid = len(errors) == 0
    return is_valid, errors, cleaned


def validate_status_update(form_data):
    """Simple validation for status dropdown (manager only)."""
    new_status = form_data.get('status')
    valid = ['open', 'in_progress', 'resolved', 'closed']
    if new_status not in valid:
        return False, 'Invalid status selected.'
    return True, None


def validate_priority_update(form_data):
    """Simple validation for priority dropdown (manager only)."""
    new_priority = form_data.get('priority')
    valid = ['low', 'medium', 'high', 'urgent']
    if new_priority not in valid:
        return False, 'Invalid priority selected.'
    return True, None


def validate_assign_update(form_data):
    """No heavy validation needed for assign (staff list comes from DB)."""
    assigned_to = form_data.get('assigned_to')
    # empty string means unassign
    return True, None