# app/routes/pastoral/illustrations.py
# Full path: WebChurchMan/app/routes/pastoral/illustrations.py
# File name: illustrations.py
# Brief, detailed purpose:
#   Routes and Blueprint for the rebuilt Illustration Library (pastoral area only).
#   All routes protected by @pastoral_required.
#   Single /library route handles:
#     - Browsing with keyword search (?q=)
#     - Optional vault scope inclusion (future-ready via ?scope=my_vault&scope=shared_vault)
#     - Inline rich Quill edit/add card at top (prefilled via ?edit_id=)
#     - Unified POST for create/update (content from hidden field synced by Quill JS)
#     - Delete via POST
#   New: /view/<id> read-only viewer – private notes visible only to owner or Admin/Owner
#   New: Session-based temp dock (dock/undock/clear) for illustrations – easy individual control
#   Edit permission: Private (owner) or Admin/Owner; Shared only Admin/Owner
#   Visibility: 'private' → user_id = current, 'pastoral_group' → user_id = None
#   Tags: comma-separated input → JSON list in DB (always stored as JSON string)
#   Source/Reference: free text (book, person, conversation – NO URL REQUIRED EVER)
#   Private Notes: personal field, only visible to creator or Admin/Owner
#   Robust handling for legacy/bad tags data
#   Censorship check on all editable text fields.
#   Audit-logged create/update/delete/insert.
#   Delegates DB work to app/models/pastoral/illustrations.py.
#   FULL REBUILD – complete, production-ready.

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
import json

from . import pastoral_required
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


def _collect_text_for_censorship(data: dict) -> str:
    """Combine all user-editable text fields for single censorship scan."""
    return ' '.join(filter(None, [
        data.get('title', ''),
        data.get('content', ''),
        data.get('source', ''),
        data.get('notes', ''),
        data.get('tags_input', '')
    ]))


def _safe_load_tags(tags_raw) -> list:
    """Safely convert tags field to list – handles str JSON, list, malformed, or None."""
    if tags_raw is None:
        return []
    if isinstance(tags_raw, list):
        return tags_raw
    if isinstance(tags_raw, str):
        try:
            return json.loads(tags_raw)
        except json.JSONDecodeError:
            return []
    return []


@illustrations_bp.route('/library', methods=['GET', 'POST'])
@pastoral_required()
def library():
    user_id = session['user_id']
    user_role = session.get('user_role', 'Member')
    q = request.args.get('q', '').strip()
    edit_id = request.args.get('edit_id')

    illustration = None
    if edit_id:
        try:
            edit_id = int(edit_id)
            illustration = get_illustration_by_id(edit_id, user_id)
            if not illustration:
                flash('Illustration not found or access denied.', 'error')
                return redirect(url_for('pastoral.illustrations.library'))
        except ValueError:
            flash('Invalid illustration ID.', 'error')
            return redirect(url_for('pastoral.illustrations.library'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        source = request.form.get('source', '').strip()
        notes = request.form.get('notes', '').strip()
        tags_input = request.form.get('tags', '').strip()
        visibility = request.form.get('visibility', 'private')

        if not title or not content:
            flash('Title and content are required.', 'error')
            return redirect(request.url)

        tag_list = [t.strip() for t in tags_input.split(',') if t.strip()]
        tags_json = json.dumps(tag_list)

        data = {
            'title': title,
            'content': content,
            'source': source,
            'notes': notes,
            'tags': tags_json
        }

        check_text = _collect_text_for_censorship({
            'title': title,
            'content': content,
            'source': source,
            'notes': notes,
            'tags_input': tags_input
        })
        if contains_censored_word(check_text):
            flash('Prohibited content detected.', 'error')
            return redirect(request.url)

        owner_id = user_id if visibility == 'private' else None

        try:
            if illustration:
                update_illustration(edit_id, data, owner_id)
                log_change(user_id, 'update', edit_id, title, 'Updated illustration')
                flash('Illustration updated.', 'success')
            else:
                new_id = create_illustration(data, owner_id)
                log_change(user_id, 'create', new_id, title, 'Created illustration')
                flash('Illustration created.', 'success')
            return redirect(url_for('pastoral.illustrations.library') + (f'?q={q}' if q else ''))
        except Exception as e:
            flash(f'Error saving illustration: {str(e)}', 'error')
            return redirect(request.url)

    illustrations = get_visible_illustrations(user_id, q or None)
    total_count = len(illustrations)

    docked_ids = session.get('docked_illustrations', [])

    for illus in illustrations:
        illus['tag_list'] = _safe_load_tags(illus.get('tags'))
        illus['can_edit'] = (illus.get('user_id') == user_id or user_role in ['Admin', 'Owner'])
        illus['is_docked'] = illus['id'] in docked_ids

    if illustration:
        illustration['tag_list'] = _safe_load_tags(illustration.get('tags'))
        illustration['tags_input'] = ', '.join(illustration['tag_list'])

    return render_template(
        'pastoral/illustrations_library.html',
        illustrations=illustrations,
        total_count=total_count,
        q=q,
        illustration=illustration,
        docked_count=len(docked_ids)
    )


@illustrations_bp.route('/view/<int:illus_id>')
@pastoral_required()
def view(illus_id: int):
    user_id = session['user_id']
    user_role = session.get('user_role', 'Member')

    illustration = get_illustration_by_id(illus_id, user_id)
    if not illustration:
        flash('Illustration not found or access denied.', 'error')
        return redirect(url_for('pastoral.illustrations.library'))

    illustration['tag_list'] = _safe_load_tags(illustration.get('tags'))

    return render_template(
        'pastoral/illustration_view.html',
        illustration=illustration,
        current_user_id=user_id,
        current_user_role=user_role
    )


@illustrations_bp.route('/delete/<int:illus_id>', methods=['POST'])
@pastoral_required()
def delete(illus_id: int):
    user_id = session['user_id']
    illustration = get_illustration_by_id(illus_id, user_id)
    if illustration:
        title = illustration['title']
        delete_illustration(illus_id, user_id)
        log_change(user_id, 'delete', illus_id, None, f'Deleted illustration "{title}"')
        flash('Illustration permanently deleted.', 'success')
    else:
        flash('Illustration not found or access denied.', 'error')
    return redirect(url_for('pastoral.illustrations.library'))


@illustrations_bp.route('/dock', methods=['POST'])
@pastoral_required()
def dock():
    data = request.get_json() or {}
    illus_ids = data.get('illustration_ids', [])
    if not illus_ids:
        return jsonify({'status': 'error', 'message': 'No illustrations selected'}), 400

    docked = session.get('docked_illustrations', [])
    for illus_id in illus_ids:
        if illus_id not in docked:
            docked.append(illus_id)
    session['docked_illustrations'] = docked

    return jsonify({'status': 'success', 'count': len(docked)})


@illustrations_bp.route('/undock', methods=['POST'])
@pastoral_required()
def undock():
    data = request.get_json() or {}
    illus_ids = data.get('illustration_ids', [])
    if not illus_ids:
        return jsonify({'status': 'error', 'message': 'No illustrations selected'}), 400

    docked = session.get('docked_illustrations', [])
    for illus_id in illus_ids:
        if illus_id in docked:
            docked.remove(illus_id)
    session['docked_illustrations'] = docked

    return jsonify({'status': 'success', 'count': len(docked)})


@illustrations_bp.route('/clear_dock', methods=['POST'])
@pastoral_required()
def clear_dock():
    session.pop('docked_illustrations', None)
    return jsonify({'status': 'success', 'count': 0})


@illustrations_bp.route('/insert/<int:sermon_id>', methods=['POST'])
@pastoral_required()
def insert_into_sermon(sermon_id: int):
    user_id = session['user_id']
    data = request.get_json() or {}
    illus_id = data.get('illustration_id')
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