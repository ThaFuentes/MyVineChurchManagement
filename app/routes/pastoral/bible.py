# app/routes/pastoral/bible.py
# Full path: WebChurchMan/app/routes/pastoral/bible.py
# File name: bible.py
# Brief, detailed purpose:
#   Blueprint for offline Bible tools within the Pastoral Area.
#   Provides:
#     - Upload/replace Bible translation (JSON format, Admin/Owner only)
#     - AJAX verse search endpoint for sermon editor integration
#     - JSON chapter fetch for reader/editor views
#   All routes require @pastoral_required()
#   Upload restricted to Admin/Owner via @role_required
#   Audit-logged uploads/deletes

from flask import Blueprint, render_template, request, jsonify, abort, flash, redirect, url_for, session
from werkzeug.utils import secure_filename
import json
import os
import tempfile
import pymysql

from . import pastoral_bp, pastoral_required
from app.utils.decorators import role_required  # Admin/Owner restriction
from app.models.db import get_db
from app.models.log import log_change

bible_bp = Blueprint('bible', __name__, url_prefix='/bible')

ALLOWED_EXTENSIONS = {'json'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ----------------------------------------------------------------------
# Upload / Replace Bible Translation (Admin/Owner only)
# ----------------------------------------------------------------------
@bible_bp.route('/upload', methods=['GET', 'POST'])
@pastoral_required()
@role_required(['Admin', 'Owner'])
def bible_upload():
    if request.method == 'POST':
        if 'bible_file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)

        file = request.files['bible_file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            # Save to temp location
            temp_dir = tempfile.mkdtemp()
            filename = secure_filename(file.filename)
            file_path = os.path.join(temp_dir, filename)
            file.save(file_path)

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    bible_data = json.load(f)

                # Basic validation (expand as needed)
                if not isinstance(bible_data, dict):
                    raise ValueError("Invalid JSON format - expected object/dictionary")

                # TODO: Insert into bible_translations and bible_verses tables
                # For now: placeholder success
                flash(f'Bible translation "{filename}" uploaded successfully (processing placeholder)', 'success')
                log_change(
                    session['user_id'], 'upload', None, filename,
                    f'Uploaded Bible JSON translation: {filename}'
                )

            except Exception as e:
                flash(f'Error processing file: {str(e)}', 'error')

            finally:
                # Cleanup temp file
                if os.path.exists(file_path):
                    os.remove(file_path)
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)

            return redirect(url_for('pastoral.bible.bible_upload'))

    return render_template('pastoral/bible_upload.html')


# ----------------------------------------------------------------------
# AJAX Verse Search (for sermon editor integration)
# ----------------------------------------------------------------------
@bible_bp.route('/search')
@pastoral_required()
def bible_search_route():
    query = request.args.get('q', '').strip()
    translation = request.args.get('translation')
    limit = int(request.args.get('limit', 30))

    if not query:
        return jsonify({'verses': []})

    from app.models.pastoral.bible import bible_search
    verses = bible_search(query, translation, limit)

    return jsonify({'verses': verses})


# ----------------------------------------------------------------------
# JSON Chapter Fetch (for reader/editor views)
# ----------------------------------------------------------------------
@bible_bp.route('/chapter/<book>/<int:chapter>')
@pastoral_required()
def bible_chapter(book, chapter):
    translation = request.args.get('translation')

    from app.models.pastoral.bible import bible_get_chapter
    verses = bible_get_chapter(book, chapter, translation)

    if not verses:
        abort(404)

    return jsonify({
        'book': book,
        'chapter': chapter,
        'verses': verses
    })