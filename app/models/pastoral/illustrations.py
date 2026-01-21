# app/models/pastoral/illustrations.py
# Full path: WebChurchMan/app/models/pastoral/illustrations.py
# File name: illustrations.py
# Brief, detailed purpose:
#   Pure database layer for the Illustration Library.
#   Handles fetching, CRUD, search, and tag parsing.
#   Visibility: 'private' (user_id = owner), 'pastoral_group' (user_id IS NULL).
#   NO Flask imports — models must remain independent of routes.

import pymysql
import json
from app.models.db import get_db


def get_visible_illustrations(user_id: int, search: str | None = None) -> list[dict]:
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    sql = """
        SELECT il.*,
               u.username AS creator_name,
               CASE WHEN il.user_id = %s THEN 'private' ELSE 'pastoral_group' END AS visibility
        FROM illustration_library il
        LEFT JOIN users u ON il.user_id = u.id
        WHERE il.user_id = %s OR il.user_id IS NULL
    """
    params = [user_id, user_id]

    if search:
        like = f"%{search}%"
        sql += " AND (il.title LIKE %s OR il.content LIKE %s OR il.source LIKE %s OR il.tags LIKE %s)"
        params.extend([like] * 4)

    sql += " ORDER BY il.created_at DESC"

    cur.execute(sql, params)
    results = cur.fetchall()

    for r in results:
        r['tags'] = json.loads(r['tags']) if r['tags'] else []

    return results


def get_illustration_by_id(illus_id: int, user_id: int) -> dict | None:
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT il.*,
               u.username AS creator_name,
               CASE WHEN il.user_id = %s THEN 'private' ELSE 'pastoral_group' END AS visibility
        FROM illustration_library il
        LEFT JOIN users u ON il.user_id = u.id
        WHERE il.id = %s
          AND (il.user_id = %s OR il.user_id IS NULL)
    """, (user_id, illus_id, user_id))

    result = cur.fetchone()
    if result:
        result['tags'] = json.loads(result['tags']) if result['tags'] else []
    return result


def create_illustration(data: dict, user_id: int) -> int:
    db = get_db()
    cur = db.cursor()

    owner = user_id if data.get('visibility') == 'private' else None

    cur.execute("""
        INSERT INTO illustration_library (user_id, title, content, source, tags)
        VALUES (%s, %s, %s, %s, %s)
    """, (owner, data['title'], data['content'], data.get('source'), data.get('tags')))

    db.commit()
    return cur.lastrowid


def update_illustration(illus_id: int, data: dict, user_id: int) -> None:
    db = get_db()
    cur = db.cursor()

    owner = user_id if data.get('visibility') == 'private' else None

    cur.execute("""
        UPDATE illustration_library
        SET user_id = %s, title = %s, content = %s, source = %s, tags = %s
        WHERE id = %s AND (user_id = %s OR user_id IS NULL)
    """, (owner, data['title'], data['content'], data.get('source'), data.get('tags'), illus_id, user_id))

    db.commit()


def delete_illustration(illus_id: int, user_id: int) -> None:
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        DELETE FROM illustration_library
        WHERE id = %s AND (user_id = %s OR user_id IS NULL)
    """, (illus_id, user_id))

    db.commit()