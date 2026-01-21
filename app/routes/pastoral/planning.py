# app/routes/pastoral/planning.py
# Full path: WebChurchMan/app/routes/pastoral/planning.py
# File name: planning.py
# Brief, detailed purpose:
#   Blueprint for Service Planning within the Pastoral Area.
#   Provides:
#     - /planning/ → list all service plans (newest first)
#     - /planning/edit/<date> → view/edit a specific plan by date (upsert behavior)
#     - /planning/assignments/<int:plan_id> → AJAX endpoint to get/save role assignments
#   All routes require @pastoral_required()
#   Delegates all DB work to app/models/pastoral/service_plans.py
#   Templates: planning_list.html (index), planning_edit.html (edit form)

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime

from . import pastoral_required  # Defined in app/routes/pastoral/__init__.py
from app.models.pastoral.service_plans import (
    get_all_service_plans,
    get_service_plan_by_date,
    create_or_update_service_plan,
    get_service_plan_assignments,
    save_service_plan_assignments
)

planning_bp = Blueprint('planning', __name__, url_prefix='/planning')


@planning_bp.route('/')
@pastoral_required()
def index():
    """Display list of all service plans."""
    plans = get_all_service_plans()
    return render_template('pastoral/planning_list.html', plans=plans)


@planning_bp.route('/edit/<date_str>', methods=['GET', 'POST'])
@pastoral_required()
def edit(date_str: str):
    """
    Edit (or create) a service plan for a specific date (YYYY-MM-DD).
    Uses upsert logic from the model.
    """
    user_id = session['user_id']

    # Validate date format
    try:
        service_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format.', 'error')
        return redirect(url_for('pastoral.planning.index'))

    plan = get_service_plan_by_date(date_str)

    if request.method == 'POST':
        title = request.form.get('title', '').strip() or None
        notes = request.form.get('notes', '').strip() or None
        sermon_id = request.form.get('pastoral_sermon_id')
        sermon_id = int(sermon_id) if sermon_id and sermon_id.isdigit() else None

        data = {
            'service_date': date_str,
            'title': title,
            'notes': notes,
            'pastoral_sermon_id': sermon_id
        }

        try:
            create_or_update_service_plan(data, user_id)
            flash('Service plan saved successfully.', 'success')
            return redirect(url_for('pastoral.planning.index'))
        except Exception as e:
            flash(f'Error saving plan: {str(e)}', 'error')

    return render_template(
        'pastoral/planning_edit.html',
        plan=plan,
        date=date_str
    )


@planning_bp.route('/assignments/<int:plan_id>', methods=['GET', 'POST'])
@pastoral_required()
def assignments(plan_id: int):
    """
    AJAX endpoint:
      GET  → return current assignments as JSON
      POST → replace all assignments with new list (full replace pattern)
    """
    if request.method == 'POST':
        assignments = request.get_json() or []
        # Expected: list of dicts [{'role_name': 'Worship Leader', 'user_id': 12}, ...]
        try:
            save_service_plan_assignments(plan_id, assignments)
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400

    # GET
    assignments = get_service_plan_assignments(plan_id)
    return jsonify(assignments)