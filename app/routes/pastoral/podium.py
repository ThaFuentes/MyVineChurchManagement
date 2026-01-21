# app/routes/pastoral/podium.py
# Full path: WebChurchMan/app/routes/pastoral/podium.py
# File name: podium.py
# Brief, detailed purpose:
#   Blueprint for Podium / Teleprompter mode within the Pastoral Area.
#   Provides a clean, full-screen preaching view optimized for pulpit/projector use.
#   Features:
#     - Large readable text with high contrast dark theme
#     - Ordered sermon sections (title, scripture, content, notes)
#     - Auto-scroll toggle, manual next/prev navigation
#     - Elapsed timer, full-screen support
#     - Toggle preacher notes and scripture highlighting
#     - Audit log access to podium mode
#   All routes require @pastoral_required()
#   Delegates DB work to app/models/pastoral/sermons.py

from flask import Blueprint, render_template, session, abort, jsonify

from . import pastoral_required  # Defined in app/routes/pastoral/__init__.py
from app.models.pastoral.sermons import get_sermon_by_id, get_sermon_sections
from app.models.log import log_change

podium_bp = Blueprint('podium', __name__, url_prefix='/podium', template_folder='templates/pastoral')


@podium_bp.route('/<int:sermon_id>')
@pastoral_required()
def view(sermon_id: int):
    """Full-featured podium/teleprompter view for live sermon delivery."""
    user_id = session['user_id']

    sermon = get_sermon_by_id(sermon_id, user_id)
    if not sermon:
        abort(404)

    sections = get_sermon_sections(sermon_id)

    # Audit log access (tracks when a sermon was actually preached)
    log_change(user_id, 'podium_access', sermon_id, sermon['title'], 'Accessed podium mode for preaching')

    return render_template(
        'podium_view.html',
        sermon=sermon,
        sections=sections,
        page_title=f"Podium – {sermon['title']}"
    )


@podium_bp.route('/data/<int:sermon_id>')
@pastoral_required()
def data(sermon_id: int):
    """Lightweight JSON endpoint for dynamic podium features (e.g., mobile controller sync)."""
    user_id = session['user_id']

    sermon = get_sermon_by_id(sermon_id, user_id)
    if not sermon:
        abort(404)

    sections = get_sermon_sections(sermon_id)

    return jsonify({
        'sermon': sermon,
        'sections': sections
    })