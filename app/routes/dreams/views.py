# app/routes/dreams/views.py
# Full path: MyVineChurch/app/routes/dreams/views.py
# File name: views.py
# Brief, detailed purpose: Clean, thin route handlers for the Dreams blueprint.
# • All database work moved to queries.py
# • All form validation + censorship moved to forms.py
# • All helpers moved to utils.py
# • FULL GROUP PERMISSIONS INTEGRATED (using user_has_permission inside functions)
# • Fixed RuntimeError by moving permission checks inside routes (no more import-time context error)

from flask import render_template, request, redirect, url_for, flash, session

from . import dreams_bp
from .queries import (
    get_dreams_list,
    get_dream_by_id,
    create_dream,
    update_dream,
    delete_dream,
    get_dream_comments,
    add_dream_comment,
    update_dream_comment,
    delete_dream_comment
)
from .forms import validate_submit_dream_form, validate_edit_dream_form, validate_comment_form
from .utils import ADMIN_ROLES

from app.utils.decorators import login_required, user_has_permission
from app.models.log import log_change
from app.utils.helpers import censor_text


# ----------------------------------------------------------------------
# Main Listing
# ----------------------------------------------------------------------
@dreams_bp.route('/')
def dreams():
    is_logged_in = 'user_id' in session
    user_id = session.get('user_id')
    search_query = request.args.get('q', '').strip().lower()

    dreams_list = get_dreams_list(is_logged_in, user_id, search_query)

    for dream in dreams_list:
        dream['title'] = censor_text(dream['title'])
        dream['description'] = censor_text(dream['description'] or '')
        dream['notes'] = censor_text(dream['notes'] or '')

    if user_id:
        log_change(user_id, 'view', change_details='Viewed dreams & visions list')

    template = 'public/dreams/dreams.html' if not is_logged_in else 'dreams/dreams.html'
    return render_template(template, dream_data=dreams_list, search_query=search_query, is_logged_in=is_logged_in)


# ----------------------------------------------------------------------
# Single Dream Detail
# ----------------------------------------------------------------------
@dreams_bp.route('/<int:dream_id>')
def view_dream(dream_id):
    is_logged_in = 'user_id' in session
    user_id = session.get('user_id')

    dream = get_dream_by_id(dream_id)
    if not dream:
        flash('Dream not found.', 'error')
        return redirect(url_for('dreams.dreams'))

    # Visibility enforcement
    if dream['visibility'] == 'personal' and (not is_logged_in or dream['user_id'] != user_id):
        flash('This is a personal dream – visible only to the submitter.', 'error')
        return redirect(url_for('dreams.dreams'))
    if dream['visibility'] == 'private' and not is_logged_in:
        flash('This is a private dream – login required.', 'error')
        return redirect(url_for('dreams.dreams'))

    # Display censorship
    dream['title'] = censor_text(dream['title'])
    dream['description'] = censor_text(dream['description'] or '')
    dream['notes'] = censor_text(dream['notes'] or '')

    comments = get_dream_comments(dream_id)
    for c in comments:
        c['comment'] = censor_text(c['comment'])

    # Group-aware permissions (fixed)
    can_edit = user_has_permission('moderate_dreams') or (is_logged_in and dream['user_id'] == user_id)
    can_delete = user_has_permission('moderate_dreams')
    can_comment = is_logged_in

    if user_id:
        log_change(user_id, 'view_dream', target_id=dream_id, change_details=f"Viewed dream {dream_id}")

    return render_template('dreams/view_dream.html',
                           dream=dream,
                           comments=comments,
                           is_logged_in=is_logged_in,
                           can_edit=can_edit,
                           can_delete=can_delete,
                           can_comment=can_comment,
                           current_user_id=user_id)


# ----------------------------------------------------------------------
# Submit New Dream
# ----------------------------------------------------------------------
@dreams_bp.route('/submit', methods=['GET', 'POST'])
@login_required
def submit_dream():
    # Group permission check inside function
    if not user_has_permission('create_dreams'):
        flash('You do not have permission to submit dreams.', 'error')
        return redirect(url_for('dreams.dreams'))

    user_id = session['user_id']

    if request.method == 'POST':
        clean_data = validate_submit_dream_form(request.form)
        if not clean_data:
            return render_template('dreams/add_dream.html', **request.form.to_dict())

        try:
            dream_id = create_dream(user_id, **clean_data)
            log_change(user_id, 'create_dream', target_id=dream_id,
                       change_details=f"Submitted dream '{clean_data['title']}' (visibility: {clean_data['visibility']})")
            flash('Dream submitted successfully.', 'success')
            return redirect(url_for('dreams.dreams'))
        except Exception as e:
            flash('Failed to submit dream.', 'error')

    return render_template('dreams/add_dream.html')


# ----------------------------------------------------------------------
# Edit Dream
# ----------------------------------------------------------------------
@dreams_bp.route('/edit/<int:dream_id>', methods=['GET', 'POST'])
@login_required
def edit_dream(dream_id):
    user_id = session['user_id']
    dream = get_dream_by_id(dream_id)

    if not dream:
        flash('Dream not found.', 'error')
        return redirect(url_for('dreams.dreams'))

    # Group-aware permission check
    if not (user_has_permission('moderate_dreams') or dream['user_id'] == user_id):
        flash('Not authorized to edit this dream.', 'error')
        return redirect(url_for('dreams.dreams'))

    if request.method == 'POST':
        clean_data = validate_edit_dream_form(request.form)
        if not clean_data:
            return render_template('dreams/edit_dream.html', dream=dream)

        try:
            update_dream(dream_id, **clean_data)
            log_change(user_id, 'update_dream', target_id=dream_id,
                       change_details=f"Updated dream '{clean_data['title']}'")
            flash('Dream updated successfully.', 'success')
            return redirect(url_for('dreams.dreams'))
        except Exception as e:
            flash('Failed to update dream.', 'error')

    return render_template('dreams/edit_dream.html', dream=dream)


# ----------------------------------------------------------------------
# Delete Dream
# ----------------------------------------------------------------------
@dreams_bp.route('/delete/<int:dream_id>', methods=['POST'])
@login_required
def delete_dream(dream_id):
    user_id = session['user_id']
    dream = get_dream_by_id(dream_id)

    if not dream:
        flash('Dream not found.', 'error')
        return redirect(url_for('dreams.dreams'))

    if not (user_has_permission('moderate_dreams') or dream['user_id'] == user_id):
        flash('Not authorized to delete this dream.', 'error')
        return redirect(url_for('dreams.dreams'))

    try:
        delete_dream(dream_id)
        log_change(user_id, 'delete_dream', target_id=dream_id,
                   change_details=f"Deleted dream '{dream['title']}'")
        flash('Dream deleted successfully.', 'success')
    except Exception as e:
        flash('Failed to delete dream.', 'error')

    return redirect(url_for('dreams.dreams'))


# ----------------------------------------------------------------------
# Comment Routes
# ----------------------------------------------------------------------
@dreams_bp.route('/comment/add/<int:dream_id>', methods=['POST'])
@login_required
def add_comment(dream_id):
    clean_comment = validate_comment_form(request.form)
    if not clean_comment:
        return redirect(url_for('dreams.view_dream', dream_id=dream_id))

    try:
        add_dream_comment(dream_id, session['user_id'], clean_comment)
        log_change(session['user_id'], 'add_comment', target_id=dream_id, change_details='Added comment to dream')
        flash('Comment added.', 'success')
    except Exception:
        flash('Failed to add comment.', 'error')

    return redirect(url_for('dreams.view_dream', dream_id=dream_id))


@dreams_bp.route('/comment/update/<int:dream_id>/<int:comment_id>', methods=['POST'])
@login_required
def update_comment(dream_id, comment_id):
    clean_comment = validate_comment_form(request.form)
    if not clean_comment:
        return redirect(url_for('dreams.view_dream', dream_id=dream_id))

    try:
        update_dream_comment(comment_id, clean_comment)
        log_change(session['user_id'], 'update_comment', target_id=dream_id, change_details='Updated dream comment')
        flash('Comment updated.', 'success')
    except Exception:
        flash('Failed to update comment.', 'error')

    return redirect(url_for('dreams.view_dream', dream_id=dream_id))


@dreams_bp.route('/comment/delete/<int:dream_id>/<int:comment_id>', methods=['POST'])
@login_required
def delete_comment(dream_id, comment_id):
    try:
        delete_dream_comment(comment_id)
        log_change(session['user_id'], 'delete_comment', target_id=dream_id, change_details='Deleted dream comment')
        flash('Comment deleted.', 'success')
    except Exception:
        flash('Failed to delete comment.', 'error')

    return redirect(url_for('dreams.view_dream', dream_id=dream_id))