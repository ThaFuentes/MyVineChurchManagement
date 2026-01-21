# app/models/pastoral/bible.py
# Full path: WebChurchMan/app/models/pastoral/bible.py
# File name: bible.py
# Brief, detailed purpose:
#   All database operations related to offline Bible translations and verse lookup.
#   Handles:
#     - Listing available translations with code, name, default status
#     - Setting/unsetting default translation (single default enforced)
#     - Deleting a translation (cascades to all verses)
#     - Full-text verse search (partial match, optional translation filter)
#     - Fetching complete chapters (with fallback to default translation)
#   No visibility enforcement needed — scripture content is neutral/public.
#   All queries use parameterized %s placeholders for MariaDB/PyMySQL safety.
#   Returns dict-like rows via DictCursor for consistent template access.

import pymysql
from app.models.db import get_db


# ----------------------------------------------------------------------
# Bible Translations Management
# ----------------------------------------------------------------------
def get_bible_translations():
    """
    Retrieve all uploaded Bible translations, sorted by name.

    Returns:
        list[dict]: Each dict contains 'code' (str), 'name' (str), 'is_default' (int 0/1)
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute("""
        SELECT code, name, is_default
        FROM bible_translations
        ORDER BY name
    """)
    return cur.fetchall()


def set_bible_default(code: str):
    """
    Set the specified translation as the default one.
    Unsets default flag on all other translations first.

    Args:
        code (str): Translation code to make default (e.g. 'KJV', 'NIV')
    """
    db = get_db()
    cur = db.cursor()

    # Clear existing defaults
    cur.execute("UPDATE bible_translations SET is_default = 0")

    # Set new default
    cur.execute("""
        UPDATE bible_translations
        SET is_default = 1
        WHERE code = %s
    """, (code,))

    db.commit()


def delete_bible_translation(code: str):
    """
    Permanently delete a Bible translation and all its verses.

    Args:
        code (str): Translation code to remove (e.g. 'ESV')
    """
    db = get_db()
    cur = db.cursor()

    # Delete verses first (cascade protection)
    cur.execute("""
                DELETE FROM bible_verses
                WHERE translation = %s
    """, (code,))

    # Delete translation metadata
    cur.execute("""
        DELETE FROM bible_translations
        WHERE code = %s
    """, (code,))

    db.commit()


# ----------------------------------------------------------------------
# Bible Content Queries
# ----------------------------------------------------------------------
def bible_search(query: str, translation: str = None, limit: int = 30):
    """
    Search verses containing the given query text (partial match).

    Args:
        query (str): Search term (e.g. "love" or "grace")
        translation (str, optional): Limit results to specific translation code
        limit (int): Maximum number of results (default 30)

    Returns:
        list[dict]: Matching verses with 'translation', 'book', 'chapter', 'verse',
                    'text', and computed 'reference' (e.g. "John 3:16")
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    sql = """
        SELECT translation, book, chapter, verse, text,
               CONCAT(book, ' ', chapter, ':', verse) AS reference
        FROM bible_verses
        WHERE text LIKE %s
    """
    params = [f"%{query}%"]

    if translation:
        sql += " AND translation = %s"
        params.append(translation)

    sql += """
        ORDER BY translation, book, chapter, verse
        LIMIT %s
    """
    params.append(limit)

    cur.execute(sql, params)
    return cur.fetchall()


def bible_get_chapter(book: str, chapter: int, translation: str = None):
    """
    Fetch all verses for a specific book and chapter number.

    Args:
        book (str): Book name (e.g. "John", "Genesis")
        chapter (int): Chapter number
        translation (str, optional): Specific translation code.
                                     If omitted, uses the current default translation.

    Returns:
        list[dict]: Verses with 'verse' (int) and 'text' (str), ordered by verse number
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    sql = """
        SELECT verse, text
        FROM bible_verses
        WHERE book = %s AND chapter = %s
    """
    params = [book, chapter]

    if translation:
        sql += " AND translation = %s"
        params.append(translation)
    else:
        # Fallback to default translation
        sql += """
            AND translation = (
                SELECT code
                FROM bible_translations
                WHERE is_default = 1
                LIMIT 1
            )
        """

    sql += " ORDER BY verse"

    cur.execute(sql, params)
    return cur.fetchall()