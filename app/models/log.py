# myvinechurchonline/app/models/log.py
# Full path: myvinechurchonline/app/models/log.py
# File name: log.py
# Brief, detailed purpose: Centralizes audit logging for the entire application in MariaDB.
# Provides a single, reusable log_change function that records all significant user actions
# (create, update, delete, view, email, etc.) into the change_records table.
# Used by every route/model to ensure complete audit trail without code duplication.
# Never fails the app — errors are printed but swallowed.

from app.models.db import get_db


def log_change(user_id: int, action: str, target_id: int | None = None,
               target_username: str | None = None, change_details: str | None = None) -> None:
    """
    Logs a user action into the change_records table for full audit trail.

    :param user_id: ID of the user performing the action (required)
    :param action: Short action name (e.g., 'create', 'update', 'delete', 'view', 'email', 'login')
    :param target_id: ID of the affected record (optional)
    :param target_username: Name/username of the affected record (optional, improves readability)
    :param change_details: Human-readable description of what changed (optional)
    """
    if not user_id:
        return  # Silently skip if no user (e.g., public actions)

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("""
            INSERT INTO change_records 
            (user_id, action, target_id, target_username, change_details, timestamp)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (user_id, action, target_id, target_username, change_details))
    except Exception as e:
        # Never break the app because of logging failure
        print(f"[LOG ERROR] Failed to log change: {e}")


# Simple test when file is run directly (requires running app context or manual db setup)
if __name__ == "__main__":
    # Note: Direct run will fail without Flask app context / MariaDB connection
    print("This module is intended for use within the Flask app. Direct execution is for reference only.")