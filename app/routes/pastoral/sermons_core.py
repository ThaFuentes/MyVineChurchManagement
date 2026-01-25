# app/routes/pastoral/sermons_core.py
# Full path: WebChurchMan/app/routes/pastoral/sermons_core.py
# File name: sermons_core.py
# Brief, detailed purpose:
#   Dedicated blueprint for core sermon management in the Pastoral Area.
#   • List visible sermons
#   • Create new sermon
#   • Full editor with metadata, visibility, collaborators
#   • Main save, autosave, delete
#   • Unified censorship check across all fields and sections
#   • Audit logging for all actions
#   • Consistent with other pastoral sub-blueprints (illustrations, planning, podium)
#   FULL REBUILD: Complete, production-ready version.
#   • Passes all service plans (including permanent seeded Sundays) to editor for dropdown
#   • Auto-pre-selects next upcoming Sunday for new sermons
#   • Save fully functional with inline JS in template (no external dependency)
#   • All existing logic preserved exactly
#   • UPDATED: source_url renamed to source (free text – books, conversations, etc., NO URL REQUIRED)
#   • Private notes per section (personal, matches illustrations)
#   • Vault integration ready (save to vault uses section content, source, notes – title separate for sermon structure)

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime, timedelta
import json
import pymysql

from . import pastoral_required
from app.models.pastoral.sermons import (
    get_visible_sermons, get_sermon_by_id, create_sermon, update_sermon,
    delete_sermon, get_sermon_sections, save_sermon_sections,
    get_collaborators, add_collaborator, remove_collaborator
)
from app.models.pastoral.service_plans import get_all_service_plans
from app.models.log import log_change
from app.utils.helpers import contains_censored_word
from app.models.db import get_db

sermons_bp = Blueprint('sermons', __name__, url_prefix='/sermons')


def load_pastoral_users():
    """Return list of pastoral group members for dropdowns."""
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT u.id, u.username, CONCAT(u.first_name, ' ', u.last_name) AS full_name
        FROM users u
        JOIN user_groups ug ON u.id = ug.user_id
        JOIN groups g ON ug.group_id = g.id
        WHERE g.name = 'Pastoral Group'
        ORDER BY u.last_name, u.first_name
    """)
    return cur.fetchall()


def collect_all_text(sermon_data: dict, sections: list) -> str:
    """Collect every editable text field for censorship scan."""
    texts = [
        sermon_data.get('title', ''),
        sermon_data.get('primary_passage', ''),
        sermon_data.get('header_text', ''),
        sermon_data.get('footer_text', ''),
        sermon_data.get('conclusion_text', ''),
        sermon_data.get('notes', ''),
        sermon_data.get('series_tags', '')
    ]
    for sec in sections:
        texts.extend([
            sec.get('title', ''),
            sec.get('content', ''),
            sec.get('source', ''),  # Updated from source_url
            sec.get('notes', ''),
            sec.get('scripture_reference', '')
        ])
    return ' '.join(filter(None, texts))


@sermons_bp.route('/')
@pastoral_required()
def list():
    user_id = session['user_id']
    sermons = get_visible_sermons(user_id, limit=100)
    return render_template('pastoral/sermons_list.html', sermons=sermons)


@sermons_bp.route('/new', methods=['GET', 'POST'])
@pastoral_required()
def new():
    user_id = session['user_id']
    pastoral_users = load_pastoral_users()
    service_plans = get_all_service_plans()

    # Auto-pre-select next upcoming Sunday for new sermons
    today = datetime.today().date()
    days_to_sunday = (6 - today.weekday()) % 7
    if days_to_sunday == 0:
        days_to_sunday = 7
    next_sunday = today + timedelta(days=days_to_sunday)
    next_upcoming_date = next_sunday.strftime('%Y-%m-%d')

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Title is required.', 'error')
            return render_template('pastoral/sermon_editor.html',
                                   sermon=None, sections=[], collaborators=[], pastoral_users=pastoral_users,
                                   service_plans=service_plans, next_upcoming_date=next_upcoming_date)

        if contains_censored_word(title):
            flash('Title contains prohibited content.', 'error')
            return render_template('pastoral/sermon_editor.html',
                                   sermon=None, sections=[], collaborators=[], pastoral_users=pastoral_users,
                                   service_plans=service_plans, next_upcoming_date=next_upcoming_date)

        data = {
            'title': title,
            'preacher_id': request.form.get('preacher_id') or None,
            'primary_passage': request.form.get('primary_passage', '').strip() or None,
            'service_date': request.form.get('service_date') or None,
            'visibility': request.form.get('visibility', 'private'),
            'header_text': request.form.get('header_text', '').strip() or None,
            'footer_text': request.form.get('footer_text', '').strip() or None,
            'conclusion_text': request.form.get('conclusion_text', '').strip() or None,
            'series_tags': request.form.get('series_tags', '').strip() or None,
            'notes': request.form.get('notes', '').strip() or None,
        }

        sections_json = request.form.get('sections_json', '[]')
        try:
            sections_list = json.loads(sections_json)
        except json.JSONDecodeError:
            sections_list = []

        if contains_censored_word(collect_all_text(data, sections_list)):
            flash('Prohibited content detected in sermon.', 'error')
        else:
            sermon_id = create_sermon(data, user_id)
            save_sermon_sections(sermon_id, sections_list)
            log_change(user_id, 'create', sermon_id, title, 'Created new sermon')
            flash('Sermon created successfully.', 'success')
            return redirect(url_for('pastoral.sermons.edit', sermon_id=sermon_id))

    return render_template('pastoral/sermon_editor.html',
                           sermon=None, sections=[], collaborators=[], pastoral_users=pastoral_users,
                           service_plans=service_plans, next_upcoming_date=next_upcoming_date)


@sermons_bp.route('/edit/<int:sermon_id>', methods=['GET', 'POST'])
@pastoral_required()
def edit(sermon_id: int):
    user_id = session['user_id']
    sermon = get_sermon_by_id(sermon_id, user_id)
    if not sermon:
        flash('Sermon not found or access denied.', 'error')
        return redirect(url_for('pastoral.sermons.list'))

    sections = get_sermon_sections(sermon_id)
    collaborators = get_collaborators(sermon_id)
    pastoral_users = load_pastoral_users()
    service_plans = get_all_service_plans()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add_collaborator':
            collab_id = request.form.get('collaborator_id')
            if collab_id:
                add_collaborator(sermon_id, int(collab_id), user_id)
                log_change(user_id, 'update', sermon_id, sermon['title'], 'Added collaborator')
                flash('Collaborator added.', 'success')

        elif action == 'remove_collaborator':
            collab_id = request.form.get('collaborator_id')
            if collab_id:
                remove_collaborator(sermon_id, int(collab_id))
                log_change(user_id, 'update', sermon_id, sermon['title'], 'Removed collaborator')
                flash('Collaborator removed.', 'success')

        else:
            sermon_data = {
                'title': request.form.get('title', '').strip(),
                'preacher_id': request.form.get('preacher_id') or None,
                'primary_passage': request.form.get('primary_passage', '').strip() or None,
                'service_date': request.form.get('service_date') or None,
                'visibility': request.form.get('visibility', 'private'),
                'header_text': request.form.get('header_text', '').strip() or None,
                'footer_text': request.form.get('footer_text', '').strip() or None,
                'conclusion_text': request.form.get('conclusion_text', '').strip() or None,
                'series_tags': request.form.get('series_tags', '').strip() or None,
                'notes': request.form.get('notes', '').strip() or None,
            }

            sections_json = request.form.get('sections_json', '[]')
            try:
                sections_list = json.loads(sections_json)
            except json.JSONDecodeError:
                sections_list = []

            if contains_censored_word(collect_all_text(sermon_data, sections_list)):
                flash('Prohibited content detected in sermon.', 'error')
            else:
                update_sermon(sermon_id, sermon_data, user_id)
                save_sermon_sections(sermon_id, sections_list)
                log_change(user_id, 'update', sermon_id, sermon_data['title'], 'Saved sermon')
                flash('Sermon saved successfully.', 'success')

        sermon = get_sermon_by_id(sermon_id, user_id)
        sections = get_sermon_sections(sermon_id)
        collaborators = get_collaborators(sermon_id)

    return render_template('pastoral/sermon_editor.html',
                           sermon=sermon, sections=sections, collaborators=collaborators,
                           pastoral_users=pastoral_users, service_plans=service_plans)


@sermons_bp.route('/autosave/<int:sermon_id>', methods=['POST'])
@pastoral_required()
def autosave(sermon_id: int):
    user_id = session['user_id']
    sermon = get_sermon_by_id(sermon_id, user_id)
    if not sermon:
        return jsonify({'status': 'error', 'message': 'Access denied'}), 403

    payload = request.get_json(silent=True) or {}
    sermon_data = payload.get('sermon', {})
    sections_list = payload.get('sections', [])

    if contains_censored_word(collect_all_text(sermon_data, sections_list)):
        return jsonify({'status': 'error', 'message': 'Prohibited content'}), 400

    update_sermon(sermon_id, sermon_data, user_id)
    save_sermon_sections(sermon_id, sections_list)
    log_change(user_id, 'autosave', sermon_id, sermon_data.get('title', sermon['title']), 'Autosaved sermon')

    return jsonify({'status': 'success', 'saved_at': datetime.utcnow().isoformat()})


@sermons_bp.route('/delete/<int:sermon_id>', methods=['POST'])
@pastoral_required()
def delete(sermon_id: int):
    user_id = session['user_id']
    sermon = get_sermon_by_id(sermon_id, user_id)
    if sermon:
        title = sermon['title']
        delete_sermon(sermon_id)
        log_change(user_id, 'delete', sermon_id, title, 'Deleted sermon')
        flash('Sermon permanently deleted.', 'success')
    else:
        flash('Sermon not found.', 'error')
    return redirect(url_for('pastoral.sermons.list'))