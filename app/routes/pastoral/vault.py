# app/routes/pastoral/vault.py
# Full path: WebChurchMan/app/routes/pastoral/vault.py
# File name: vault.py
# Brief, detailed purpose:
#   Blueprint for the Pastoral Vault module (personal + pastoral_group shared items).
#   • Main view: unified list with tabs for My Vault / Shared Vault
#   • Add/edit/delete items (private or shared)
#   • Unified search across vault + sermons (reuses model function)
#   • All routes require @pastoral_required()
#   • Censorship check on content/reference/notes/tags
#   • Audit-logged create/update/delete

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


def _collect_vault_text(data: dict) -> str:
    """Combine all text fields for censorship scan."""
    texts = [
        data.get('content', ''),
        data.get('reference', ''),
        data.get('notes', ''),
        data.get('tags', '')
    ]
    return ' '.join(filter(None, texts))


@vault_bp.route('/')
@pastoral_required()
def library():
    """Main vault view – shows My Vault + Shared Vault with tabs."""
    user_id = session['user_id']
    search = request.args.get('search', '').strip()

    if search:
        # Unified search across vault + sermons
        results = search_vault_and_sermons(search, user_id, limit=100)
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
        shared_items=shared_items,
        search=''
    )


@vault_bp.route('/add', methods=['GET', 'POST'])
@vault_bp.route('/edit/<int:item_id>', methods=['GET', 'POST'])
@pastoral_required()
def edit(item_id: int | None = None):
    user_id = session['user_id']
    is_edit = item_id is not None

    item = None
    if is_edit:
        # Fetch from unified model – ownership enforced in model
        my = get_my_vault(user_id)
        shared = get_shared_vault()
        all_items = my + shared
        item = next((i for i in all_items if i['id'] == item_id), None)
        if not item:
            flash('Item not found or access denied.', 'error')
            return redirect(url_for('pastoral.vault.library'))

    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        item_type = request.form.get('type', '').strip()
        visibility = request.form.get('visibility', 'private')  # 'private' or 'pastoral_group'
        reference = request.form.get('reference', '').strip() or None
        notes = request.form.get('notes', '').strip() or None
        tags_input = request.form.get('tags', '').strip()

        if not content or not item_type:
            flash('Content and type are required.', 'error')
            return redirect(request.url)

        tags_list = [t.strip() for t in tags_input.split(',') if t.strip()]
        tags_json = json.dumps(tags_list)

        data = {
            'content': content,
            'type': item_type,
            'visibility': visibility,
            'reference': reference,
            'notes': notes,
            'tags': tags_json
        }

        all_text = _collect_vault_text(data)
        if contains_censored_word(all_text):
            flash('Prohibited content detected.', 'error')
            return redirect(request.url)

        try:
            if is_edit:
                update_vault_item(item_id, data, user_id)
                log_change(user_id, 'update', item_id, content[:50], 'Updated vault item')
                flash('Vault item updated.', 'success')
            else:
                new_id = add_vault_item(data, user_id)
                log_change(user_id, 'create', new_id, content[:50], 'Created vault item')
                flash('Vault item created.', 'success')
            return redirect(url_for('pastoral.vault.library'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')

    return render_template(
        'pastoral/vault_edit.html',
        item=item,
        is_edit=is_edit
    )


@vault_bp.route('/delete/<int:item_id>', methods=['POST'])
@pastoral_required()
def delete(item_id: int):
    user_id = session['user_id']
    delete_vault_item(item_id, user_id)
    log_change(user_id, 'delete', item_id, None, 'Deleted vault item')
    flash('Vault item deleted.', 'success')
    return redirect(url_for('pastoral.vault.library'))