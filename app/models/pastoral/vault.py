# app/models/pastoral/vault.py
# Full path: WebChurchMan/app/models/pastoral/vault.py
# File name: vault.py
# Brief, detailed purpose:
#   All database operations related to the Pastoral Vault module.
#   Handles:
#     - Personal vault items (private to user)
#     - Shared vault items (pastoral_group visibility)
#     - CRUD operations with ownership enforcement
#     - Unified search across vault + visible sermons
#   Visibility: 'private' (user_id = owner) or 'pastoral_group' (shared)
#   Routes handle audit logging (log_change) and censorship checks separately.
#   Tags stored as JSON string; parsed to list on fetch.
#   Uses DictCursor for consistent dict results.
#   Parameterized queries for MariaDB / PyMySQL safety.

import pymysql
import json
from app.models.db import get_db


# ----------------------------------------------------------------------
# Personal & Shared Vault Fetching
# ----------------------------------------------------------------------
def get_my_vault(user_id):
    """
    Fetch all private vault items belonging to the current user.

    Args:
        user_id (int): Current user's ID

    Returns:
        list[dict]: Personal vault items with parsed tags list
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT *
        FROM pastoral_vault
        WHERE user_id = %s AND visibility = 'private'
        ORDER BY created_at DESC
    """, (user_id,))

    results = cur.fetchall()

    # Parse JSON tags into list (safe handling)
    for result in results:
        tags_str = result.get('tags')
        result['tags'] = json.loads(tags_str) if tags_str else []

    return results


def get_shared_vault():
    """
    Fetch all group-shared vault items (visible to entire pastoral team).

    Returns:
        list[dict]: Shared vault items with parsed tags list
    """
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT *
        FROM pastoral_vault
        WHERE visibility = 'pastoral_group'
        ORDER BY created_at DESC
    """)

    results = cur.fetchall()

    # Parse JSON tags into list (safe handling)
    for result in results:
        tags_str = result.get('tags')
        result['tags'] = json.loads(tags_str) if tags_str else []

    return results


# ----------------------------------------------------------------------
# Vault Item CRUD Operations
# ----------------------------------------------------------------------
def add_vault_item(data, user_id):
    """
    Create a new vault item (personal or shared).

    Args:
        data (dict): Must contain 'visibility', 'type', 'content';
                     optional: reference, notes, tags (JSON string)
        user_id (int): Owner for private items

    Returns:
        int: Newly created vault item ID
    """
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        INSERT INTO pastoral_vault (
            user_id, visibility, type, content, reference, notes, tags
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
                    user_id,
                    data['visibility'],
                    data['type'],
                    data['content'],
                    data.get('reference'),
                    data.get('notes'),
                    data.get('tags')  # JSON string from route/form
    ))

    db.commit()
    return cur.lastrowid


def update_vault_item(item_id, data, user_id):
    """
    Update an existing vault item (must be owned by user_id).

    Args:
        item_id (int): ID of the vault item to update
        data (dict): Fields to update (partial allowed)
        user_id (int): Must match owner for security
    """
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        UPDATE pastoral_vault
        SET visibility = %s,
            type       = %s,
            content    = %s,
            reference  = %s,
            notes      = %s,
            tags       = %s,
            updated_at = NOW()
        WHERE id = %s AND user_id = %s
    """, (
        data['visibility'],
        data['type'],
        data['content'],
        data.get('reference'),
        data.get('notes'),
        data.get('tags'),
        item_id,
        user_id
    ))

    db.commit()


def delete_vault_item(item_id, user_id):
    """
    Permanently delete a vault item (only if owned by user_id).

    Args:
        item_id (int): ID of item to delete
        user_id (int): Current user (ownership check)
    """
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        DELETE FROM pastoral_vault
        WHERE id = %s AND user_id = %s
    """, (item_id, user_id))

    db.commit()


# ----------------------------------------------------------------------
# Unified Vault + Sermon Search
# ----------------------------------------------------------------------
def search_vault_and_sermons(query, user_id, limit=50):
    """
    Unified search across user's personal vault, shared vault, and visible sermons.

    Searches content, reference/notes/tags in vault;
    title, passage, notes, tags in sermons.

    Args:
        query (str): Search term
        user_id (int): Current user (for visibility filtering)
        limit (int): Max results (default 50)

    Returns:
        list[dict]: Mixed results with source_type ('vault' or 'sermon')
    """
    query_like = f"%{query}%"
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    sql = """
        SELECT id, 'vault' AS source_type, type AS subtype, content, reference, notes, tags, created_at
        FROM pastoral_vault
        WHERE (user_id = %s AND visibility = 'private')
           OR visibility = 'pastoral_group'
          AND (content LIKE %s OR reference LIKE %s OR notes LIKE %s OR tags LIKE %s)

        UNION ALL

        SELECT id, 'sermon' AS source_type, visibility AS subtype, title AS content,
               primary_passage AS reference, notes, series_tags AS tags, created_at
        FROM pastoral_sermons
        WHERE (created_by = %s
               OR (visibility = 'collaborators' AND EXISTS (
                   SELECT 1 FROM sermon_collaborators
                   WHERE sermon_id = pastoral_sermons.id AND user_id = %s
               ))
               OR visibility = 'pastoral_group')
          AND (title LIKE %s OR primary_passage LIKE %s OR notes LIKE %s OR series_tags LIKE %s)

        ORDER BY created_at DESC LIMIT %s
    """
    params = [
        user_id, query_like, query_like, query_like, query_like,
        user_id, user_id, query_like, query_like, query_like, query_like,
        limit
    ]

    cur.execute(sql, params)
    results = cur.fetchall()

    # Parse tags for all results (safe handling)
    for result in results:
        tags_str = result.get('tags')
        result['tags'] = json.loads(tags_str) if tags_str else []

    return results