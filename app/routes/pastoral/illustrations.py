# app/routes/pastoral/illustrations.py
# Full path: WebChurchMan/app/routes/pastoral/illustrations.py
# File name: illustrations.py
# Brief, detailed purpose:
#   Routes and Blueprint for the Illustration Library (pastoral area only).
#   All routes protected by @pastoral_required.
#   Delegates all DB work to app/models/pastoral/illustrations.py.

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
import json

from . import pastoral_required  # Defined in app/routes/pastoral/__init__.py
from app.models.log import log_change
from app.utils.helpers import contains_censored_word
from app.models.pastoral.illustrations import (
    get_visible_illustrations,
    get_illustration_by_id,
    create_illustration,
    update_illustration,
    delete_illustration
)

illustrations_bp = Blueprint('illustrations', __name__, url_prefix='/illustrations')


def _collect_text(data: dict) -> str:
    return ' '.join(filter(None, [data.get('title', ''), data.get('content', ''), data.get('source', ''), data.get('tags', '')]))


@illustrations_bp.route('/library')
@pastoral_required()
def library():
    user_id = session['user_id']
    search = request.args.get('search', '').strip()
    illustrations = get_visible_illustrations(user_id, search or None)
    return render_template('pastoral/illustrations_library.html', illustrations=illustrations, search=search)


@illustrations_bp.route('/add', methods=['GET', 'POST'])
@illustrations_bp.route('/edit/<int:illus_id>', methods=['GET', 'POST'])
@pastoral_required()
def edit(illus_id: int | None = None):
    user_id = session['user_id']
    is_edit = illus_id is not None
    illustration = get_illustration_by_id(illus_id, user_id) if is_edit else None

    if is_edit and not illustration:
        flash('Illustration not found or access denied.', 'error')
        return redirect(url_for('pastoral.illustrations.library'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        source = request.form.get('source', '').strip()
        tags_input = request.form.get('tags', '').strip()
        visibility = request.form.get('visibility', 'private')

        if not title or not content:
            flash('Title and content are required.', 'error')
            return redirect(request.url)

        tags_json = json.dumps([t.strip() for t in tags_input.split(',') if t.strip()])

        data = {'title': title, 'content': content, 'source': source, 'tags': tags_json, 'visibility': visibility}

        if contains_censored_word(_collect_text(data)):
            flash('Prohibited content detected.', 'error')
            return redirect(request.url)

        try:
            if is_edit:
                update_illustration(illus_id, data, user_id)
                log_change(user_id, 'update', illus_id, title, 'Updated illustration')
                flash('Illustration updated.', 'success')
            else:
                new_id = create_illustration(data, user_id)
                log_change(user_id, 'create', new_id, title, 'Created illustration')
                flash('Illustration created.', 'success')
            return redirect(url_for('pastoral.illustrations.library'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')

    return render_template('pastoral/illustrations_edit.html', illustration=illustration, is_edit=is_edit)


@illustrations_bp.route('/delete/<int:illus_id>', methods=['POST'])
@pastoral_required()
def delete(illus_id: int):
    user_id = session['user_id']
    delete_illustration(illus_id, user_id)
    log_change(user_id, 'delete', illus_id, None, 'Deleted illustration')
    flash('Illustration deleted.', 'success')
    return redirect(url_for('pastoral.illustrations.library'))


@illustrations_bp.route('/insert/<int:sermon_id>', methods=['POST'])
@pastoral_required()
def insert_into_sermon(sermon_id: int):
    user_id = session['user_id']
    illus_id = (request.get_json() or {}).get('illustration_id')
    if not illus_id:
        return jsonify({'status': 'error', 'message': 'No illustration selected'}), 400

    illustration = get_illustration_by_id(illus_id, user_id)
    if not illustration:
        return jsonify({'status': 'error', 'message': 'Access denied'}), 404

    source_line = f"<p><em>Source: {illustration['source']}</em></p>" if illustration['source'] else ""
    html = f"""
    <div class="inserted-illustration" data-illustration-id="{illus_id}">
        <h3>{illustration['title']}</h3>
        <blockquote>{illustration['content']}</blockquote>
        {source_line}
    </div>
    """.strip()

    log_change(user_id, 'insert', sermon_id, illus_id, f'Inserted illustration {illus_id} into sermon {sermon_id}')
    return jsonify({'status': 'success', 'html': html})