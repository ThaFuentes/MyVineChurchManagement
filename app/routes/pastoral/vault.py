# app/routes/pastoral/vault.py
# Full path: WebChurchMan/app/routes/pastoral/vault.py
# File name: vault.py
# Brief, detailed purpose:
#   Blueprint for the Pastoral Vault module (personal + pastoral_group shared items).
#   • Main view: unified list with tabs for My Vault / Shared Vault
#   • Manual add/edit/delete items (private or shared) via form
#   • NEW: AJAX endpoints for sermon editor integration
#       - save_section_ajax: Save a single sermon section directly to vault (title, tags, visibility choice)
#       - search_ajax: Live search vault items only (for "Insert from Vault" modal)
#   • Unified search across vault + sermons (reuses model function)
#   • All routes require @pastoral_required()
#   • Censorship check on all text fields (title, content, scripture_reference, source_url, reference, notes, tags)
#   • Audit-logged create/update/delete
#   • Fully aligned with updated pastoral_vault schema (title required, section_type, scripture_reference, source_url)

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
import json

from . import pastoral_required
from app.models.log import log_change
from app.utils.helpers import contains_censored_word
from app.models.pastoral.vault import (
    get_my_vault,
    get_shared_vault,
    add_vault_item,
    update_vault_item,
    delete_vault_item,
    search_vault_and_sermons
)

vault_bp = Blueprint('vault', __name__, url_prefix='/vault')


def _collect_text_for_censor(data: dict) -> str:
    """
    Combine every text field for a single censorship scan.
    """
    fields = [
        data.get('title', ''),
        data.get('content', ''),
        data.get('scripture_reference', ''),
        data.get('source_url', ''),
        data.get('reference', ''),      # legacy field
        data.get('notes', ''),
        ' '.join(data.get('tags', [])) if isinstance(data.get('tags'), list) else data.get('tags', '')
    ]
    return ' '.join(fields)


@vault_bp.route('/')
@pastoral_required()
def library():
    """Main vault view – shows My Vault + Shared Vault with tabs."""
    user_id = session['user_id']
    search = request.args.get('search', '').strip()

    if search:
        results = search_vault_and_sermons(user_id, search, visibility='all', limit=100)
        return render_template(
            'pastoral/vault_search.html',
            results=results,
            search=search
        )

    my_items = get_my_vault(user_id)
    shared_items = get_shared_vault()

    return render_template(
        'pastoral/vault_library.html',
        my_items=my_items,
        shared_items=shared_items
    )


@vault_bp.route('/add', methods=['GET', 'POST'])
@vault_bp.route('/edit/<int:item_id>', methods=['GET', 'POST'])
@pastoral_required()
def edit(item_id: int | None = None):
    user_id = session['user_id']
    item = None

    if item_id:
        # Combine personal + shared to find the item (ownership enforced in model)
        candidates = get_my_vault(user_id) + get_shared_vault()
        item = next((i for i in candidates if i['id'] == item_id), None)
        if not item:
            flash('Item not found or access denied.', 'error')
            return redirect(url_for('pastoral.vault.library'))

    if request.method == 'POST':
        visibility = request.form.get('visibility', 'private')
        owner_id = user_id if visibility == 'private' else None

        data = {
            'title': request.form.get('title', '').strip(),
            'content': request.form.get('content', '').strip(),
            'section_type': request.form.get('section_type', 'point'),
            'scripture_reference': request.form.get('scripture_reference', '').strip() or None,
            'source_url': request.form.get('source_url', '').strip() or None,
            'reference': request.form.get('reference', '').strip() or None,
            'notes': request.form.get('notes', '').strip() or None,
            'visibility': visibility,
        }

        tags_input = request.form.get('tags', '').strip()
        data['tags'] = [t.strip() for t in tags_input.split(',') if t.strip()]

        if not data['title'] or not data['content']:
            flash('Title and content are required.', 'error')
            return redirect(request.url)

        if contains_censored_word(_collect_text_for_censor(data)):
            flash('Prohibited content detected.', 'error')
            return redirect(request.url)

        try:
            if item_id:
                update_vault_item(item_id, data, user_id)
                log_change(user_id, 'vault_update', item_id, data['title'][:50], 'Updated vault item')
                flash('Vault item updated.', 'success')
            else:
                new_id = add_vault_item(data, owner_id)
                log_change(user_id, 'vault_create', new_id, data['title'][:50], 'Created vault item')
                flash('Vault item created.', 'success')
            return redirect(url_for('pastoral.vault.library'))
        except Exception as e:
            flash(f'Database error: {e}', 'error')

    return render_template('pastoral/vault_edit.html', item=item)


@vault_bp.route('/delete/<int:item_id>', methods=['POST'])
@pastoral_required()
def delete(item_id: int):
    user_id = session['user_id']
    delete_vault_item(item_id, user_id)
    log_change(user_id, 'vault_delete', item_id, None, 'Deleted vault item')
    flash('Vault item deleted.', 'success')
    return redirect(url_for('pastoral.vault.library'))


# ----------------------------------------------------------------------
# AJAX: Save a sermon section directly to the vault (used by sermon editor)
# ----------------------------------------------------------------------
@vault_bp.route('/save_section_ajax', methods=['POST'])
@pastoral_required()
def save_section_ajax():
    user_id = session['user_id']
    payload = request.get_json() or {}

    required = ['title', 'content']
    if not all(payload.get(k) for k in required):
        return jsonify({'status': 'error', 'message': 'Title and content are required'}), 400

    visibility = payload.get('visibility', 'private')
    if visibility not in ['private', 'pastoral_group']:
        visibility = 'private'

    owner_id = user_id if visibility == 'private' else None

    # Build data dict matching manual edit expectations
    data = {
        'title': payload['title'].strip(),
        'content': payload['content'],
        'section_type': payload.get('section_type', 'point'),
        'scripture_reference': payload.get('scripture_reference', '').strip() or None,
        'source_url': payload.get('source_url', '').strip() or None,
        'reference': payload.get('reference', '').strip() or None,  # legacy/support
        'notes': payload.get('notes', '').strip() or None,
        'visibility': visibility,
    }

    tags_input = payload.get('tags', '')
    data['tags'] = [t.strip() for t in tags_input.split(',') if t.strip()]

    if contains_censored_word(_collect_text_for_censor(data)):
        return jsonify({'status': 'error', 'message': 'Prohibited content detected.'}), 400

    try:
        new_id = add_vault_item(data, owner_id)
        log_change(user_id, 'vault_create', new_id, data['title'][:50], 'Saved sermon section to vault')
        return jsonify({'status': 'success', 'id': new_id})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ----------------------------------------------------------------------
# AJAX: Search vault items only (for "Insert from Vault" modal in sermon editor)
# ----------------------------------------------------------------------
@vault_bp.route('/search_ajax')
@pastoral_required()
def search_ajax():
    user_id = session['user_id']
    query = request.args.get('q', '').strip()
    limit = int(request.args.get('limit', 30))

    if not query:
        return jsonify({'items': []})

    # Use unified search then filter to vault items only
    # Vault items have 'section_type' field; sermons do not
    all_results = search_vault_and_sermons(query, user_id, limit=limit + 20)  # slight over-fetch for safety

    vault_items = [
        item for item in all_results
        if 'section_type' in item  # distinguishes vault from sermons
    ][:limit]

    # Ensure tags are parsed as list for frontend
    for item in vault_items:
        tags_json = item.get('tags')
        item['tags'] = json.loads(tags_json) if tags_json else []

    return jsonify({'items': vault_items})