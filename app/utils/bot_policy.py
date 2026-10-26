"""Owner switches, posting voices, and soft undo rules for the church bot.

Nothing here talks to the database. Routes and the key store call these
rules so a key can only do what the owner turned on.
"""

from __future__ import annotations

import hashlib
import json
import secrets

GREETING = "Hello. I am ready to help My Vine Church."

POST_KINDS = ("post", "quote", "verse", "blog", "book")
VISIBILITIES = ("public", "private", "personal", "followers")

# kind: write | security | read. Only these ids can be stored on a key.
SWITCHES = [
    {
        "id": "bot_writes_off",
        "kind": "safety",
        "group": "Safety",
        "label": "Bot writes OFF",
        "detail": "Master switch. When this is on, this bot can still sign in and read. Every change is refused until you turn it off.",
    },
    {
        "id": "posts",
        "kind": "write",
        "group": "Wall",
        "label": "Post on the wall",
        "detail": "Verses, quotes, and other posts as the church or a person you attach.",
    },
    {
        "id": "security",
        "kind": "security",
        "group": "Security",
        "label": "Read security",
        "detail": "Recent events, ban counts, and whether security logging is still recording.",
    },
    {
        "id": "members",
        "kind": "read",
        "group": "People",
        "label": "Members",
        "detail": "Directory names, email, phone, and role, plus add, edit, and soft-delete. No passwords or check-in PINs. Access templates and export use their own switches.",
    },
    {
        "id": "groups",
        "kind": "read",
        "group": "People",
        "label": "Read groups",
        "detail": "Group names and visibility.",
    },
    {
        "id": "attendance",
        "kind": "read",
        "group": "People",
        "label": "Read attendance",
        "detail": "How many people checked in on each service date.",
    },
    {
        "id": "events",
        "kind": "read",
        "group": "Church life",
        "label": "Events",
        "detail": "Event names, dates, places, and the calendar. Add, edit, soft-delete, and signups. Emailing the list needs Send email.",
    },
    {
        "id": "announcements",
        "kind": "read",
        "group": "Church life",
        "label": "Read announcements",
        "detail": "Announcement titles and a short body.",
    },
    {
        "id": "sermons",
        "kind": "read",
        "group": "Church life",
        "label": "Read the public sermon library",
        "detail": "Uploaded sermon titles and a short note. The sermon builder is its own switch.",
    },
    {
        "id": "sermon_builder",
        "kind": "sermon",
        "group": "Sermon desk",
        "label": "Sermon builder",
        "detail": "Illustrations, sermon drafts, verses, the research vault, and who is speaking on which day. Drafts are saved as the one account you chose for this bot. The bot cannot switch accounts. Undo hides a draft or puts the previous words back.",
    },
    {
        "id": "prayers",
        "kind": "read",
        "group": "Church life",
        "label": "Read prayers",
        "detail": "Prayer titles and a short request.",
    },
    {
        "id": "dreams",
        "kind": "read",
        "group": "Church life",
        "label": "Read dreams",
        "detail": "Dream and vision titles and a short description.",
    },
    {
        "id": "prophecies",
        "kind": "read",
        "group": "Church life",
        "label": "Read prophecies",
        "detail": "Prophecy titles and a short description.",
    },
    {
        "id": "worship",
        "kind": "read",
        "group": "Church life",
        "label": "Read worship songs",
        "detail": "Song titles and artists. Lyrics files stay in the worship tools.",
    },
    {
        "id": "donations",
        "kind": "read",
        "group": "Office",
        "label": "Read giving",
        "detail": "Gift amounts and dates. No card numbers, and no way to add or change a gift.",
    },
    {
        "id": "bills",
        "kind": "read",
        "group": "Office",
        "label": "Read bills",
        "detail": "Bill names, amounts, and due dates. No account numbers or logins.",
    },
    {
        "id": "tickets",
        "kind": "read",
        "group": "Office",
        "label": "Read tickets",
        "detail": "Ticket titles, status, and a short description.",
    },
    {
        "id": "inventory",
        "kind": "read",
        "group": "Office",
        "label": "Read inventory",
        "detail": "Item names and stock levels.",
    },
    {
        "id": "audit",
        "kind": "read",
        "group": "Office",
        "label": "Read the change log",
        "detail": "Recent rows from the church change log.",
    },
    {
        "id": "comments",
        "kind": "monitor",
        "group": "Church life",
        "label": "Comments",
        "detail": "Read, reply, edit, and hide comments on events, sermons, prayers, dreams, prophecies, announcements, photos, wall posts, and tickets. No IP addresses. A censored word is refused. A hard delete needs the Hard delete switch.",
    },
    {
        "id": "moderation",
        "kind": "write",
        "group": "Church life",
        "label": "Moderate",
        "detail": "Approve, reject, or hide a post, event, announcement, dream, prophecy, prayer, or sermon. Church office still covers the older moderation call.",
    },
    {
        "id": "office",
        "kind": "office",
        "group": "Church office",
        "label": "Church office",
        "detail": "Every column of every church desk, as the one account you chose. That account must be you, or an admin you allowed. GET /api/bot/desks lists each area. Study courses, the apps menu, moderation, and AI insights have their own calls. POST /api/bot/upload places a picture on a study lesson, a church or member page, the sign-in page, a ministry partner, a giving option, or a song chart. A wall picture also needs Posts. Help pages update on the help desk. Membership rows can be removed and put back. Pickup codes, family PINs, passwords, mail logins, API keys, card numbers, payroll, and sending email stay off.",
    },
    {
        "id": "members_access",
        "kind": "write",
        "group": "High risk",
        "high_risk": True,
        "label": "Member access",
        "detail": "Change tool access and access templates. This bot cannot change an owner, or its own access. Stays on until you turn it off.",
    },
    {
        "id": "members_export",
        "kind": "write",
        "group": "High risk",
        "high_risk": True,
        "label": "Export members",
        "detail": "Download the directory as JSON or CSV. No passwords. Stays on until you turn it off.",
    },
    {
        "id": "hard_delete",
        "kind": "write",
        "group": "High risk",
        "high_risk": True,
        "label": "Hard delete",
        "detail": "Permanently remove a sermon, post, comment, event, or member. The body must say DELETE and the id. Stays on until you turn it off.",
    },
    {
        "id": "comms_send",
        "kind": "write",
        "group": "High risk",
        "high_risk": True,
        "label": "Send email",
        "detail": "Send an event email to people who accept event mail. Stays on until you turn it off.",
    },
]

# Static SELECTs only. The store binds the limit. Never add secrets here.
READS = {
    "members": (
        "SELECT id, username, first_name, last_name, email, phone, role "
        "FROM users ORDER BY id DESC LIMIT %s"
    ),
    "groups": (
        "SELECT id, name, visibility FROM groups ORDER BY id DESC LIMIT %s"
    ),
    "attendance": (
        "SELECT service_date, COUNT(*) AS people FROM attendance "
        "GROUP BY service_date ORDER BY service_date DESC LIMIT %s"
    ),
    "events": (
        "SELECT id, event_name, event_date, event_time, location, visibility, "
        "LEFT(description, 280) AS description FROM events ORDER BY id DESC LIMIT %s"
    ),
    "announcements": (
        "SELECT id, title, visibility, is_active, created_at, "
        "LEFT(content, 280) AS content FROM announcements ORDER BY id DESC LIMIT %s"
    ),
    "sermons": (
        "SELECT id, title, visibility, uploaded_at, "
        "LEFT(COALESCE(notes, details, ''), 240) AS notes "
        "FROM sermons ORDER BY id DESC LIMIT %s"
    ),
    "prayers": (
        "SELECT id, title, visibility, date_posted, "
        "LEFT(description, 280) AS description FROM prayers ORDER BY id DESC LIMIT %s"
    ),
    "dreams": (
        "SELECT id, title, category, visibility, date_posted, "
        "LEFT(description, 280) AS description FROM dreams "
        # Bots never read personal / pastor-only / branch-only / unaccepted journal entries.
        "WHERE visibility IN ('public', 'private') AND COALESCE(moderation_hidden, 0) = 0 "
        "AND COALESCE(ownership_status, 'owned') <> 'pending' ORDER BY id DESC LIMIT %s"
    ),
    "prophecies": (
        "SELECT id, title, visibility, created_at, "
        "LEFT(COALESCE(description, ''), 280) AS description "
        "FROM prophecies WHERE visibility IN ('public', 'private') AND COALESCE(moderation_hidden, 0) = 0 "
        "AND COALESCE(ownership_status, 'owned') <> 'pending' ORDER BY id DESC LIMIT %s"
    ),
    "worship": (
        "SELECT id, title, artist FROM worship_songs ORDER BY id DESC LIMIT %s"
    ),
    "donations": (
        "SELECT id, name, amount, date, method FROM donations ORDER BY id DESC LIMIT %s"
    ),
    "bills": (
        "SELECT id, bill_name, vendor_name, typical_amount, frequency, "
        "next_due_date, current_status FROM recurring_bills ORDER BY id DESC LIMIT %s"
    ),
    "tickets": (
        "SELECT id, title, status, priority, created_at, "
        "LEFT(description, 180) AS description FROM tickets ORDER BY id DESC LIMIT %s"
    ),
    "inventory": (
        "SELECT id, name, unit_of_measure, min_stock_level, typical_cost_per_unit "
        "FROM items ORDER BY id DESC LIMIT %s"
    ),
    "audit": (
        "SELECT id, user_id, action, target_id, target_username, timestamp, "
        "LEFT(COALESCE(change_details, ''), 180) AS change_details "
        "FROM change_records ORDER BY id DESC LIMIT %s"
    ),
}

CLOSED = [
    "Child check-in rooms, children, guardians, and the board are on this API. Pickup codes, family PINs, and the check-in kiosk are not. Bill logins and passwords are not. Event email needs the Send email switch.",
    "Deleting a post, sermon, comment, event, or member hides it. Hard delete needs the Hard delete switch and confirm set to DELETE plus the id.",
    "Sermon drafts, illustrations, sections, and research notes can be hidden and put back. A lineup change can be undone for that one date.",
    "Comment replies post as the account the owner chose. A censored word is refused. This key does not email anyone about a comment.",
    "Card numbers, account numbers, bill site logins, bank details, and passwords stay off this key.",
    "Gifts, bills, and expenses save every safe column. Card numbers, account numbers, bill site logins, and bank details are left off the row. Reverse does not void a gift or an expense.",
    "Only the owner allows an admin to use a bot. That bot acts only as that admin. The owner chooses the one account every bot acts as.",
    "The desk catalog does not return child check-in PINs or pickup codes, mail passwords, API keys, payment secrets, private messages, or payroll. Adding a member emails a temporary password and does not return it.",
    "POST /api/bot/upload does not delete the previous file. Reverse does not remove a picture, a study course, an apps-menu change, a moderation action, or an insight run.",
]


READ_ABOUT = {
    "members": "Directory rows newest first: id, username, first_name, last_name, email, phone, role. Query limit= up to 100. No passwords, family PINs, or pickup codes.",
    "groups": "Group rows: id, name, visibility. Members of a group are GET /api/bot/groups when Church office is on.",
    "attendance": "How many people checked in on each service date: service_date and people. Checking someone in is POST /api/bot/attendance when Church office is on.",
    "events": "Event rows: id, event_name, event_date, event_time, location, visibility, and a short description. The full row is GET /api/bot/desk/events when Church office is on.",
    "announcements": "Announcement rows: id, title, visibility, is_active, created_at, and a short body. The full row is the announcements desk.",
    "sermons": "Public sermon rows: id, title, visibility, uploaded_at, and a short note. Sermon builder drafts are a different switch.",
    "prayers": "Prayer rows: id, title, visibility, date_posted, and a short request.",
    "dreams": "Dream titles and a short description. Only public and private rows that are not hidden and not waiting on journal acceptance.",
    "prophecies": "Prophecy titles and a short description. Only public and private rows that are not hidden and not waiting on journal acceptance.",
    "worship": "Song rows: id, title, artist. Lyrics and chord charts stay on the worship tools. A chart file is POST /api/bot/upload place=song when Church office is on.",
    "donations": "Gift rows: id, name, amount, date, method. No card numbers. Recording a gift is POST /api/bot/donations when Church office is on. Reverse does not void it.",
    "bills": "Bill rows: id, bill_name, vendor_name, typical_amount, frequency, next_due_date, current_status. No account numbers or site logins.",
    "tickets": "Ticket rows: id, title, status, priority, created_at, and a short description. Comments are GET /api/bot/comments?area=ticket when Monitor comments is on.",
    "inventory": "Item rows: id, name, unit_of_measure, min_stock_level, typical_cost_per_unit. Quantity on hand is GET /api/bot/inventory when Church office is on.",
    "audit": "Recent change-log rows: id, user_id, action, target_id, target_username, timestamp, and a short change_details. New child check-in rows do not store the pickup code here.",
}


def switch_groups() -> list[dict]:
    groups = []
    for row in SWITCHES:
        if not groups or groups[-1]["name"] != row["group"]:
            groups.append({"name": row["group"], "switches": []})
        groups[-1]["switches"].append(row)
    return groups


def switch_by_id(switch_id: str) -> dict | None:
    for row in SWITCHES:
        if row["id"] == switch_id:
            return row
    return None


def default_controls() -> dict:
    return {row["id"]: False for row in SWITCHES}


def normalize_controls(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    out = default_controls()
    for row in SWITCHES:
        value = raw.get(row["id"])
        out[row["id"]] = value in (True, 1, "1", "true", "True", "on", "yes")
    return out


def switch_on(controls, switch_id: str) -> bool:
    return bool(normalize_controls(controls).get(switch_id))


def writes_blocked(controls) -> bool:
    """The master switch. On means every change is refused. Reads stay open."""
    return switch_on(controls, "bot_writes_off")


def hash_key(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def new_key_material() -> tuple[str, str, str]:
    raw = "mvos_" + secrets.token_urlsafe(32)
    while raw.startswith("mvos_s_") or raw.startswith("mvos_2"):
        raw = "mvos_" + secrets.token_urlsafe(32)
    return raw, hash_key(raw), raw[:14]


def new_twofa_material() -> tuple[str, str, str]:
    raw = "mvos_2fa_" + secrets.token_urlsafe(32)
    return raw, hash_key(raw), raw[:18]


def new_session_material() -> tuple[str, str, str]:
    raw = "mvos_s_" + secrets.token_urlsafe(32)
    return raw, hash_key(raw), raw[:16]


TWOFA_TTL_SECONDS = 3600
SESSION_TTL_SECONDS = 3600
# Only the replaced API key expires, and only for this long. The new key does not.
PREV_KEY_GRACE_SECONDS = 15 * 60
MAX_OPEN_SESSIONS = 5
RESET_LIMIT_PER_HOUR = 3
RESET_WINDOW_SECONDS = 3600
COMMENT_RATE_PER_HOUR = 30
RESET_REQUEST_REPLY = "If that inbox belongs to a bot, a new API key is on its way."
ADMIN_NOT_GRANTED = "The owner has not allowed this admin to use a bot."

# A bearer the church already issued. An expired one is a retry, not an attack.
_KNOWN_BOT_BEARERS = frozenset({
    "live_session",
    "live_key",
    "grace_key",
    "expired_session",
    "expired_prev",
    "key_off",
})


def should_penalize_bot_bearer(kind: str) -> bool:
    """True when this bearer should count as a bad bot key.

    A live session, a live key, a previous key still in its grace window,
    an expired session, an expired previous key, and a key the owner turned
    off are all credentials this church issued. Retrying one of those must
    not push the caller's IP toward the reputation jail.
    """
    return (kind or "") not in _KNOWN_BOT_BEARERS


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def email_ok(value: str) -> bool:
    text = normalize_email(value)
    if len(text) < 6 or len(text) > 160 or " " in text or text.count("@") != 1:
        return False
    local, domain = text.split("@")
    return bool(local) and "." in domain and "/" not in text


def inbox_problem(key_email: str, twofa_email: str) -> str | None:
    """The API key and the 2FA key have to use two different inboxes."""
    key_email = normalize_email(key_email)
    twofa_email = normalize_email(twofa_email)
    if not email_ok(key_email):
        return "Enter the inbox that should receive the API key."
    if not email_ok(twofa_email):
        return "Enter the inbox that should receive the 2FA key."
    if key_email == twofa_email:
        return "The API key and the 2FA key need two different inboxes."
    return None


def api_key_mail(name: str, raw_key: str, base_url: str) -> tuple[str, str]:
    """Permanent key only. The 2FA inbox is not named here."""
    base = (base_url or "").rstrip("/")
    subject = "Your My Vine Church bot API key"
    body = "\n".join([
        "Hello. A My Vine Church bot API key is ready.",
        "",
        f"name: {name}",
        f"api_key: {raw_key}",
        "expires: never",
        "authorization: Bearer " + raw_key,
        f"sign_in: POST {base}/api/bot/login",
        "twofa: A separate 2FA key is emailed to the other inbox when you sign in. It expires in 1 hour. It is not in this message.",
        f"exchange: POST {base}/api/bot/login/exchange",
        "twofa_header: X-Bot-2FA",
        f"help: GET {base}/api/bot/help",
    ])
    return subject, body


def twofa_key_mail(name: str, raw_key: str, base_url: str) -> tuple[str, str]:
    """One-hour 2FA key only. The permanent API key is not included."""
    base = (base_url or "").rstrip("/")
    subject = "Your My Vine Church bot 2FA key"
    body = "\n".join([
        "Hello. Your My Vine Church bot 2FA key is ready.",
        "",
        f"name: {name}",
        f"twofa_key: {raw_key}",
        "expires: 1 hour",
        f"expires_in: {TWOFA_TTL_SECONDS}",
        "header: X-Bot-2FA",
        f"exchange: POST {base}/api/bot/login/exchange",
        "authorization: Bearer and the API key from the other inbox",
        f"help: GET {base}/api/bot/help",
    ])
    return subject, body


def person_label(row: dict | None) -> str:
    row = row or {}
    name = " ".join(
        part for part in (row.get("first_name"), row.get("last_name")) if part
    ).strip()
    username = (row.get("username") or "").strip()
    if name and username:
        return f"{name} ({username})"
    if name or username:
        return name or username
    uid = row.get("user_id") or row.get("id")
    return f"User {uid}" if uid else "Member"


def resolve_voice(token: str, voices: list[dict]) -> tuple[dict | None, str | None]:
    """Map as=church or as=user:ID onto a voice the owner attached."""
    raw = (token or "").strip().lower()
    voices = voices or []
    if raw in ("church", "as:church"):
        row = next((v for v in voices if (v.get("voice_type") or "") == "church"), None)
        if not row:
            return None, "This key cannot post as the church."
        uid = row.get("user_id")
        if not uid:
            return None, "The church voice needs an author. The owner picks that person on Bot Access."
        return {
            "posted_as": "church",
            "user_id": int(uid),
            "campus_id": 0,
            "as": "church",
        }, None
    if raw.startswith("user:"):
        part = raw.split(":", 1)[1]
        if not part.isdigit():
            return None, "Use as=user:ID with a numeric member id."
        uid = int(part)
        row = next(
            (
                v for v in voices
                if (v.get("voice_type") or "") == "user" and int(v.get("user_id") or 0) == uid
            ),
            None,
        )
        if not row:
            return None, "This key cannot post as that person."
        return {
            "posted_as": "member",
            "user_id": uid,
            "campus_id": 0,
            "as": f"user:{uid}",
        }, None
    return None, "Say which voice with as=church or as=user:ID."


def assigned_people(voices: list[dict] | None) -> list[int]:
    """Member ids the owner attached as people. The church wall is not one of them."""
    people = []
    for voice in voices or []:
        if (voice.get("voice_type") or "") != "user":
            continue
        try:
            uid = int(voice.get("user_id") or 0)
        except (TypeError, ValueError):
            continue
        if uid and uid not in people:
            people.append(uid)
    return people


def _one_account(voices: list[dict] | None) -> tuple[int | None, str | None]:
    """The single account the owner saved. The caller does not get to pick."""
    people = assigned_people(voices)
    if len(people) > 1:
        return None, "The owner chooses one account for this bot. Ask the owner to save a single account."
    if len(people) == 1:
        return people[0], None
    return None, "The owner has not chosen which account this bot acts as."


def _admin_blocked(role, admin_granted: bool) -> str | None:
    if role == "Admin" and not admin_granted:
        return ADMIN_NOT_GRANTED
    return None


def _as_matches(token, uid: int) -> str | None:
    """Empty as= is the saved account. A different as= is refused."""
    raw = (token or "").strip().lower()
    if raw in ("church", "as:church"):
        return "church"
    if raw.startswith("user:"):
        part = raw.split(":", 1)[1]
        if not part.isdigit():
            return "This bot acts only as the account the owner chose."
        if int(part) != int(uid):
            return "This bot acts only as the account the owner chose."
        return None
    if raw:
        return "This bot acts only as the account the owner chose."
    return None


def resolve_sermon_user(token, voices: list[dict] | None, created_by, *,
                        role=None, admin_granted: bool = False) -> tuple[dict | None, str | None]:
    """The one account the owner chose. created_by is not a fallback.

    The bot cannot send a different as=. An admin account works only after
    the owner allows that admin, and then only as that admin.
    """
    del created_by
    uid, err = _one_account(voices)
    if err:
        return None, err
    blocked = _admin_blocked(role, admin_granted)
    if blocked:
        return None, blocked
    mismatch = _as_matches(token, uid)
    if mismatch == "church":
        return None, "This bot acts as the account the owner chose, not the church wall."
    if mismatch:
        return None, mismatch
    return {"user_id": uid, "as": f"user:{uid}", "role": role}, None


def church_save(act_role, author_role, act_as_id, author_id, requested, prior_author):
    """Whether the church wall stays on, and which member authors those posts.

    Picking an author turns the wall on. A blank author on an owner bot uses
    that owner. Any other bot can post on the wall only when the author is an owner.
    """
    acting_owner = (act_role or "") == "Owner"
    if author_id and not requested:
        requested = True
    if requested and not author_id and acting_owner and act_as_id:
        author_id = int(act_as_id)
        author_role = "Owner"
    if requested and not author_id and prior_author:
        author_id = int(prior_author)
        author_role = author_role or "Owner"
    if not requested:
        return False, None, None
    if not author_id:
        return False, None, "Choose an owner as the author for church posts."
    if not acting_owner and (author_role or "") != "Owner":
        return False, None, "Church posts stay off unless this bot acts as an owner, or the author is an owner."
    return True, int(author_id), None


def resolve_bot_post(token, voices: list[dict] | None, *,
                     role=None, admin_granted: bool = False) -> tuple[dict | None, str | None]:
    """Wall posts use the one saved account. Church posts use the saved owner author."""
    uid, err = _one_account(voices)
    if err:
        return None, err
    blocked = _admin_blocked(role, admin_granted)
    if blocked:
        return None, blocked
    raw = (token or "").strip().lower()
    if raw in ("church", "as:church"):
        if role not in ("Owner", "Admin"):
            return None, "This bot acts only as the account the owner chose. It cannot post as the church."
        return resolve_voice("church", voices or [])
    mismatch = _as_matches(token, uid)
    if mismatch:
        return None, mismatch
    return {
        "posted_as": "member",
        "user_id": uid,
        "campus_id": 0,
        "as": f"user:{uid}",
    }, None


def office_blocked(role, admin_granted: bool) -> str | None:
    """Church office runs as an owner, or as an admin the owner allowed."""
    if role == "Owner":
        return None
    if role == "Admin" and admin_granted:
        return None
    if role == "Admin":
        return ADMIN_NOT_GRANTED
    return "Church office is only for an owner, or an admin the owner allowed to use a bot."


def validate_post(kind: str, title: str, body: str, visibility: str) -> tuple[dict | None, str | None]:
    kind = (kind or "post").strip().lower()
    if kind not in POST_KINDS:
        return None, "kind must be post, quote, verse, blog, or book."
    title = (title or "").strip()[:255]
    body = (body or "").strip()[:8000]
    if kind in ("verse", "quote", "blog", "book") and not body:
        return None, "That kind needs a body."
    if kind == "post" and not title and not body:
        return None, "Write a title or a body."
    visibility = (visibility or "public").strip().lower()
    if visibility not in VISIBILITIES:
        visibility = "public"
    if not title:
        title = {"quote": "Quote", "verse": "Verse", "blog": "Blog", "book": "Book"}.get(kind, "Post")
    return {"kind": kind, "title": title, "body": body, "visibility": visibility}, None


# First step, then the step after it has already been reversed.
UNDO_STEPS = {
    "post.create": ("hide", "show"),
    "sermon.create": ("hide", "show"),
    "illustration.create": ("hide", "show"),
    "illustration.hide": ("hide", "show"),
    "section.add": ("hide", "show"),
    "section.hide": ("hide", "show"),
    "sermon.hide": ("hide", "show"),
    "vault.create": ("hide", "show"),
    "sermon.update": ("restore", "reapply"),
    "section.update": ("restore", "reapply"),
    "section.reorder": ("restore", "reapply"),
    "illustration.update": ("restore", "reapply"),
    "vault.update": ("restore", "reapply"),
    "lineup.set": ("restore", "reapply"),
    "group.add": ("restore", "reapply"),
    "group.remove": ("restore", "reapply"),
    "group.role": ("restore", "reapply"),
    "worship.role": ("restore", "reapply"),
    "worship.defaults": ("restore", "reapply"),
    "bill.update": ("restore", "reapply"),
    "inventory.adjust": ("restore", "reapply"),
    "attendance.checkin": ("restore", "reapply"),
    "desk.update": ("restore", "reapply"),
    "desk.hide": ("restore", "reapply"),
    "desk.link": ("restore", "reapply"),
    "bot_member_create": ("hide", "show"),
    "bot_member_update": ("restore", "reapply"),
    "bot_member_delete": ("show", "hide"),
    "bot_member_reject": ("show", "hide"),
    "bot_event_update": ("restore", "reapply"),
    "bot_event_delete": ("show", "hide"),
    "bot_event_signup": ("show", "hide"),
    "bot_sermon_delete": ("show", "hide"),
    "bot_sermon_unhide": ("hide", "show"),
    "bot_section_delete": ("show", "hide"),
    "bot_illustration_delete": ("show", "hide"),
    "bot_vault_delete": ("show", "hide"),
    "bot_post_edit": ("restore", "reapply"),
    "bot_post_hide": ("show", "hide"),
    "bot_post_unhide": ("hide", "show"),
    "bot_post_delete": ("show", "hide"),
    "bot_illustration_unhide": ("hide", "show"),
    "bot_lineup_delete": ("show", "hide"),
    "bot_comment_edit": ("restore", "reapply"),
    "bot_comment_delete": ("show", "hide"),
}

UNDO_LABELS = {
    "hide": "Hide",
    "show": "Put back",
    "restore": "Undo",
    "reapply": "Redo",
}


def undo_plan(action: str, already_reversed: bool) -> str | None:
    """Soft undo. hide sets removed_at. show clears it. Never a hard delete."""
    steps = UNDO_STEPS.get(action or "")
    if not steps:
        return None
    return steps[1] if already_reversed else steps[0]


def undo_label(action: str, already_reversed: bool) -> str | None:
    plan = undo_plan(action, already_reversed)
    if not plan:
        return None
    return UNDO_LABELS.get(plan, "Undo")


def call_map(controls, blocked_why: str | None = None) -> list[dict]:
    on = normalize_controls(controls)
    calls = [
        {"method": "GET", "path": "/api/bot/help", "switch": None,
         "about": "This map of calls, switches, named areas, and what stays closed. GET /api/bot/helper is the same map. Work calls use Authorization: Bearer and the session from exchange, not the permanent API key."},
        {"method": "GET", "path": "/api/bot/helper", "switch": None,
         "about": "Same map as GET /api/bot/help: calls, switches, areas, closed items, and how to sign in. Session bearer."},
        {"method": "POST", "path": "/api/bot/login", "switch": None,
         "about": "Send the permanent API key as Authorization: Bearer. Emails a 2FA key to the other inbox. That key expires in 1 hour. This does not open a session."},
        {"method": "POST", "path": "/api/bot/login/exchange", "switch": None,
         "about": "Send the permanent API key as Authorization: Bearer and the emailed 2FA key as X-Bot-2FA. Returns a session token that expires in 1 hour."},
        {"method": "POST", "path": "/api/bot/password-reset", "switch": None,
         "about": "Send a live session, or the current API key, as Authorization: Bearer. Emails a new API key to the main inbox. It does not email a 2FA key. POST /api/bot/login with the new key mails a 2FA key. The old key stops working in 15 minutes. Sessions that are already open stay open. POST /api/bot/key/reset is the same call."},
        {"method": "POST", "path": "/api/bot/key/reset", "switch": None,
         "about": "Same as POST /api/bot/password-reset. The API key or a live session is enough. The new API key goes to the main inbox only. The old key stops working in 15 minutes."},
        {"method": "POST", "path": "/api/bot/key/reset-request", "switch": None,
         "about": "No working API key is required. Body: {\"email\": \"the main API-key inbox\"}. If that inbox is saved on a bot, a new API key is emailed there. A 2FA key is not emailed until the next POST /api/bot/login. The reply is the same either way."},
        {"method": "GET", "path": "/api/bot/whoami", "switch": None,
         "about": "Which switches are on, the one account this bot acts as, and whether this bot is blocked. A blocked admin still gets this answer, with missing and the fix. GET /api/bot/me is the same. Session bearer."},
        {"method": "GET", "path": "/api/bot/diagnostics", "switch": None,
         "about": "Same as whoami, plus the key prefix, how long the session has left, whether a 2FA key is waiting, reset count this hour, and whether the previous API key is still in its 15-minute window. No secrets."},
        {"method": "GET", "path": "/api/bot/me", "switch": None,
         "about": "Same as GET /api/bot/whoami. Returns name, prefix, switches, voices, and acts_as. The caller cannot name a different account."},
        {"method": "GET", "path": "/api/bot/log", "switch": None,
         "about": "What this key did, and the undo label for each change."},
        {"method": "POST", "path": "/api/bot/reverse", "switch": None,
         "about": "Undo one of this key's changes. Body: {\"log_id\": N}."},
        {"method": "POST", "path": "/api/bot/posts", "switch": "posts",
         "about": "Publish text as the one account the owner chose. Body: {\"kind\":\"post|quote|verse|blog|book\", \"title\":\"\", \"body\":\"\", \"visibility\":\"public|private|personal|followers\", \"as\":\"church\"}. as=church posts on the church wall as the owner saved under Author for church posts. An admin bot may use as=church only as that owner. A picture on the wall is POST /api/bot/upload place=post and also needs this switch. Reverse hides the post and can show it again. The row is kept."},
        {"method": "GET", "path": "/api/bot/posts", "switch": "posts",
         "about": "Recent live wall posts for the account the owner chose. as=church lists the church wall when that author is saved."},
        {"method": "GET", "path": "/api/bot/posts/<id>", "switch": "posts",
         "about": "One wall post, including a hidden one."},
        {"method": "POST", "path": "/api/bot/posts/<id>", "switch": "posts",
         "about": "Edit a post's title, body, or visibility. Reverse puts the previous words back."},
        {"method": "POST", "path": "/api/bot/posts/<id>/hide", "switch": "posts",
         "about": "Hide a post. Reverse puts it back."},
        {"method": "POST", "path": "/api/bot/posts/<id>/unhide", "switch": "posts",
         "about": "Show a hidden post again."},
        {"method": "POST", "path": "/api/bot/posts/<id>/delete", "switch": "posts",
         "about": "Soft-hide a post. Hard delete needs the Hard delete switch and {\"confirm\":\"DELETE <id>\"}."},
        {"method": "GET", "path": "/api/bot/security", "switch": "security",
         "about": "Summary, recent events, events_newest_at, and recording."},
        {"method": "GET", "path": "/api/bot/sermons", "switch": "sermon_builder",
         "about": "Sermon builder drafts the account the owner chose can open. ?id= or GET /api/bot/sermons/<id> opens one with its sections. ?q= searches title and passage. The bot cannot switch accounts."},
        {"method": "POST", "path": "/api/bot/sermons", "switch": "sermon_builder",
         "about": "Start a draft as the account the owner chose. Body: {\"title\":\"\", \"primary_passage\":\"\", \"preacher_id\": N, \"service_date\":\"YYYY-MM-DD\", \"notes\":\"\"}. The bot cannot switch accounts."},
        {"method": "GET", "path": "/api/bot/sermons/<id>", "switch": "sermon_builder",
         "about": "One draft that account can open, with its sections. Same as GET /api/bot/sermons?id=."},
        {"method": "POST", "path": "/api/bot/sermons/<id>", "switch": "sermon_builder",
         "about": "Change a draft that person created: title, passage, preacher, date, notes, or conclusion."},
        {"method": "POST", "path": "/api/bot/sermons/<id>/sections", "switch": "sermon_builder",
         "about": "Add a section, or change one when section_id is set. section_type is introduction, point, scripture, application, illustration, conclusion, or other. Body: {\"section_type\":\"point\", \"title\":\"\", \"content\":\"\", \"scripture_reference\":\"\", \"source\":\"\", \"notes\":\"\"} or {\"illustration_id\": N} or {\"reference\":\"John 3:16\"}."},
        {"method": "GET", "path": "/api/bot/illustrations", "switch": "sermon_builder",
         "about": "Illustration library, including private stories. ?q= searches. ?id= opens one."},
        {"method": "POST", "path": "/api/bot/illustrations", "switch": "sermon_builder",
         "about": "Save an illustration. Body: {\"title\":\"\", \"content\":\"\", \"source\":\"\", \"tags\":\"\"}."},
        {"method": "POST", "path": "/api/bot/illustrations/<id>", "switch": "sermon_builder",
         "about": "Change an illustration's title, story, source, or tags."},
        {"method": "POST", "path": "/api/bot/illustrations/<id>/hide", "switch": "sermon_builder",
         "about": "Hide an illustration that assigned person owns, or a shared one they can open. Undo puts it back. It is not deleted."},
        {"method": "POST", "path": "/api/bot/illustrations/<id>/unhide", "switch": "sermon_builder",
         "about": "Show a hidden illustration again."},
        {"method": "GET", "path": "/api/bot/illustrations/<id>/download", "switch": "sermon_builder",
         "about": "Download one illustration. format=md returns the words in JSON. format=docx, or file=1, returns the file."},
        {"method": "POST", "path": "/api/bot/sermons/<id>/hide", "switch": "sermon_builder",
         "about": "Hide a draft that assigned person created. Undo puts it back."},
        {"method": "POST", "path": "/api/bot/sermons/<id>/unhide", "switch": "sermon_builder",
         "about": "Show a hidden sermon draft again."},
        {"method": "POST", "path": "/api/bot/sermons/<id>/delete", "switch": "sermon_builder",
         "about": "Soft-hide a sermon draft. Hard delete needs the Hard delete switch and {\"confirm\":\"DELETE <id>\"}."},
        {"method": "POST", "path": "/api/bot/sermons/<id>/sections/<sid>/delete", "switch": "sermon_builder",
         "about": "Soft-hide one section. Hard delete needs the Hard delete switch and the confirm phrase."},
        {"method": "POST", "path": "/api/bot/illustrations/<id>/delete", "switch": "sermon_builder",
         "about": "Soft-hide an illustration. Hard delete needs the Hard delete switch and the confirm phrase."},
        {"method": "POST", "path": "/api/bot/vault/<id>/delete", "switch": "sermon_builder",
         "about": "Soft-hide a research note. Hard delete needs the Hard delete switch and the confirm phrase."},
        {"method": "POST", "path": "/api/bot/lineup/<id>/delete", "switch": "sermon_builder",
         "about": "Clear the sermon on one lineup day. Hard delete removes that one-day plan when the Hard delete switch is on."},
        {"method": "POST", "path": "/api/bot/sermons/<id>/sections/hide", "switch": "sermon_builder",
         "about": "Hide one section. Body: {\"section_id\": N}."},
        {"method": "POST", "path": "/api/bot/sermons/<id>/sections/reorder", "switch": "sermon_builder",
         "about": "Put sections in a new order. Body: {\"ids\": [3, 1, 2]}. Send every live section id."},
        {"method": "GET", "path": "/api/bot/comments", "switch": "comments",
         "about": "Recent comments. ?area=event|sermon|prayer|dream|prophecy|announcement|photo|post|ticket &parent= &q= &status=visible|removed|shadowed|all."},
        {"method": "GET", "path": "/api/bot/comments/<area>/<id>", "switch": "comments",
         "about": "One comment the monitor can already see. No IP address."},
        {"method": "POST", "path": "/api/bot/comments/<area>/<id>", "switch": "comments",
         "about": "Reply on that item as the account the owner chose. Body: {\"body\":\"\"}. A censored word is refused. 30 replies an hour."},
        {"method": "POST", "path": "/api/bot/comments/<area>/<id>/<cid>", "switch": "comments",
         "about": "Edit one comment. Body: {\"body\":\"\"}."},
        {"method": "POST", "path": "/api/bot/comments/<area>/<id>/<cid>/hide", "switch": "comments",
         "about": "Hide one comment. Reverse puts it back."},
        {"method": "POST", "path": "/api/bot/comments/<area>/<id>/<cid>/delete", "switch": "comments",
         "about": "Hide one comment. Hard delete needs the Hard delete switch and {\"confirm\":\"DELETE <cid>\"}."},
        {"method": "POST", "path": "/api/bot/content/<kind>/<id>/moderate", "switch": "moderation", "also": "office",
         "about": "Approve, reject, or hide. Body: {\"action\":\"approve|reject|hide\"}. kind is post, event, announcement, dream, prophecy, prayer, or sermon. Church office also allows this call."},
        {"method": "GET", "path": "/api/bot/members", "switch": "members",
         "about": "Member directory. ?q= and ?page=. No passwords, pins, or tokens."},
        {"method": "GET", "path": "/api/bot/members/<id>", "switch": "members",
         "about": "One member. No password or pin."},
        {"method": "POST", "path": "/api/bot/members", "switch": "members",
         "about": "Add a member. Body: {\"first_name\":\"\", \"last_name\":\"\", \"email\":\"\", \"role\":\"Member|Staff|Admin\"}. The password is emailed and is not in the reply."},
        {"method": "POST", "path": "/api/bot/members/<id>", "switch": "members",
         "about": "Edit a member. An owner cannot be demoted or have their email changed. This bot cannot change its own role."},
        {"method": "POST", "path": "/api/bot/members/<id>/delete", "switch": "members",
         "about": "Soft-delete a member. Hard delete needs the Hard delete switch and {\"confirm\":\"DELETE <id>\"}. An owner cannot be deleted."},
        {"method": "POST", "path": "/api/bot/members/registrations/<user_id>/approve", "switch": "members",
         "about": "Approve a registration."},
        {"method": "POST", "path": "/api/bot/members/registrations/<user_id>/reject", "switch": "members",
         "about": "Reject a registration. The row is hidden, not erased."},
        {"method": "GET", "path": "/api/bot/members/visitors", "switch": "members",
         "about": "People waiting on approval, and visitor roles."},
        {"method": "GET", "path": "/api/bot/members/export", "switch": "members_export",
         "about": "Directory export. ?format=json or csv. No passwords."},
        {"method": "GET", "path": "/api/bot/members/<id>/access", "switch": "members_access",
         "about": "Tool roles on one member."},
        {"method": "POST", "path": "/api/bot/members/<id>/access", "switch": "members_access",
         "about": "Replace tool roles. Body: {\"roles\":[\"Greeter\"], \"template_id\": N}. Refuses the owner and this bot's own account."},
        {"method": "GET", "path": "/api/bot/members/access/templates", "switch": "members_access",
         "about": "Access templates."},
        {"method": "POST", "path": "/api/bot/members/access/templates", "switch": "members_access",
         "about": "Create an access template. Body: {\"name\":\"\", \"permissions\":[]}."},
        {"method": "POST", "path": "/api/bot/members/access/templates/<id>", "switch": "members_access",
         "about": "Update a template, or {\"delete\": true} to remove it."},
        {"method": "GET", "path": "/api/bot/events", "switch": "events",
         "about": "Calendar. ?from=YYYY-MM-DD &to=YYYY-MM-DD &campus_id=."},
        {"method": "GET", "path": "/api/bot/events/<id>", "switch": "events",
         "about": "One event."},
        {"method": "POST", "path": "/api/bot/events", "switch": "events",
         "about": "Create an event. Body: {\"event_name\":\"\", \"event_date\":\"YYYY-MM-DD\", \"event_time\":\"\", \"end_date\":\"\", \"end_time\":\"\", \"location\":\"\", \"visibility\":\"public|private\"}. The end cannot be earlier than the start."},
        {"method": "POST", "path": "/api/bot/events/<id>", "switch": "events",
         "about": "Edit an event."},
        {"method": "POST", "path": "/api/bot/events/<id>/delete", "switch": "events",
         "about": "Soft-hide an event. Hard delete needs the Hard delete switch and the confirm phrase."},
        {"method": "GET", "path": "/api/bot/events/<id>/signups", "switch": "events",
         "about": "Potluck signups for one event."},
        {"method": "POST", "path": "/api/bot/events/<id>/signups", "switch": "events",
         "about": "Add a signup. Body: {\"name\":\"\", \"item\":\"\"}."},
        {"method": "POST", "path": "/api/bot/events/<id>/signups/<signup_id>/delete", "switch": "events",
         "about": "Hide one signup."},
        {"method": "POST", "path": "/api/bot/events/<id>/comments/<cid>", "switch": "comments",
         "about": "Edit or hide an event comment. Body: {\"body\":\"\"} or {\"hide\": true}."},
        {"method": "POST", "path": "/api/bot/events/<id>/email", "switch": "comms_send",
         "about": "Email people who accept event mail. Body: {\"subject\":\"\", \"message\":\"\", \"user_ids\":[]}. Refused when Send email is off."},
        {"method": "GET", "path": "/api/bot/vault", "switch": "sermon_builder",
         "about": "Sermon research vault. Shared notes plus this owner's private notes. ?q= searches. ?id= opens one."},
        {"method": "POST", "path": "/api/bot/vault", "switch": "sermon_builder",
         "about": "Save a research note. Body: {\"title\":\"\", \"content\":\"\", \"scripture_reference\":\"\"}."},
        {"method": "POST", "path": "/api/bot/vault/<id>", "switch": "sermon_builder",
         "about": "Change a research note the key can already see."},
        {"method": "GET", "path": "/api/bot/verses", "switch": "sermon_builder",
         "about": "Look up scripture. Query: ref=John 3:16 or ref=Romans 8:28-30."},
        {"method": "GET", "path": "/api/bot/lineup", "switch": "sermon_builder",
         "about": "Who is speaking, and which sermon, on upcoming service days. Query: days=21."},
        {"method": "POST", "path": "/api/bot/lineup", "switch": "sermon_builder",
         "about": "Set the speaker or sermon for one date. Body: {\"date\":\"YYYY-MM-DD\", \"preacher_id\": N, \"sermon_id\": N}. One Sunday only, not every week."},
        {"method": "GET", "path": "/api/bot/groups", "switch": "office",
         "about": "Groups and their members. No email addresses. Roles on a group are member or leader."},
        {"method": "GET", "path": "/api/bot/groups/<id>", "switch": "office",
         "about": "One group and its members. No email addresses."},
        {"method": "POST", "path": "/api/bot/groups/<id>/members", "switch": "office",
         "about": "Add, change, or remove a member. Body: {\"user_id\": N, \"role\":\"member\" or \"leader\", \"remove\": true}. Undo puts that membership back."},
        {"method": "GET", "path": "/api/bot/worship/team", "switch": "office",
         "about": "Worship team members and the people who are actually group leaders. Owners are not listed unless they are a leader."},
        {"method": "POST", "path": "/api/bot/worship/team", "switch": "office",
         "about": "Set a person's worship team role. Body: {\"user_id\": N, \"role\":\"member\" or \"leader\"}."},
        {"method": "GET", "path": "/api/bot/worship/songs", "switch": "office",
         "about": "Worship song titles. POST saves a title and artist. Songs are not deleted from the bot."},
        {"method": "POST", "path": "/api/bot/worship/songs", "switch": "office",
         "about": "Save a song title. Body: {\"title\":\"\", \"artist\":\"\", \"id\": N}. Does not delete a song."},
        {"method": "GET", "path": "/api/bot/worship/defaults", "switch": "office",
         "about": "Weekly worship role defaults."},
        {"method": "POST", "path": "/api/bot/worship/defaults", "switch": "office",
         "about": "Replace worship defaults. Body: {\"roles\":[{\"role_name\":\"Worship Leader\", \"user_id\": N}]}. Undo puts the previous list back."},
        {"method": "POST", "path": "/api/bot/donations", "switch": "office",
         "about": "Record a gift. Body: {\"name\":\"\", \"amount\":\"10.00\", \"date\":\"YYYY-MM-DD\", \"method\":\"cash\"}. No card numbers. Reverse does not void it."},
        {"method": "POST", "path": "/api/bot/bills/<id>", "switch": "office",
         "about": "Change a bill's amount, status, due date, or notes. Status is pending, paid, overdue, or partial. No account numbers or logins."},
        {"method": "GET", "path": "/api/bot/accounting", "switch": "office",
         "about": "Accounts, recent expenses, and budgets. No payroll, bank details, or tax ids."},
        {"method": "POST", "path": "/api/bot/accounting/expenses", "switch": "office",
         "about": "Record an expense. Body: {\"expense_date\":\"YYYY-MM-DD\", \"amount\":\"10.00\", \"expense_account_id\": N, \"vendor_name\":\"\", \"description\":\"\"}."},
        {"method": "GET", "path": "/api/bot/inventory", "switch": "office",
         "about": "Items, locations, and quantity on hand."},
        {"method": "POST", "path": "/api/bot/inventory/adjust", "switch": "office",
         "about": "Change stock. Body: {\"item_id\": N, \"location_id\": N, \"quantity_change\": 1, \"notes\":\"\"}."},
        {"method": "POST", "path": "/api/bot/attendance", "switch": "office",
         "about": "Check a member in for a service date. Body: {\"user_id\": N, \"service_date\":\"YYYY-MM-DD\"}. Member attendance is separate from the child check-in desk."},
        {"method": "GET", "path": "/api/bot/courses", "switch": "office",
         "about": "Study courses. ?status=draft|published|archived and ?q= search the title. Lessons and who is enrolled come back with the count."},
        {"method": "GET", "path": "/api/bot/courses/<id>", "switch": "office",
         "about": "One study course with its lessons, blocks, choices, and enrollments."},
        {"method": "POST", "path": "/api/bot/courses", "switch": "office",
         "about": "Create a study course. Body: {\"title\":\"\", \"subtitle\":\"\", \"description\":\"\", \"audience\":\"everyone\", \"status\":\"draft|published|archived\", \"visibility\":\"pastoral\", \"tags\":\"\", \"estimated_minutes\": N, \"sort_order\": N, \"lessons\":[{\"title\":\"\", \"summary\":\"\", \"status\":\"draft\", \"blocks\":[{\"block_type\":\"text\", \"title\":\"\", \"body\":\"\", \"media_url\":\"\", \"media_alt\":\"\", \"question_prompt\":\"\", \"explanation\":\"\", \"points\":1, \"choices\":[{\"label\":\"\", \"is_correct\": false}]}]}]}. block_type is text, image, video, choice, true_false, fill, or scripture. At most 40 lessons and 40 blocks each. A picture or video file is POST /api/bot/upload with place=course and lesson_id. A web address can stay in media_url. Edit a lesson later on the curriculum desks. Reverse does not delete the course."},
        {"method": "POST", "path": "/api/bot/upload", "switch": "office",
         "about": "Multipart picture upload. The file field is file, photo, image, hero_image, media_file, option_image, or chords_file. place is required. place=course needs lesson_id. Optional block_id replaces that block. title or caption, and media_alt or alt. png, jpg, jpeg, gif, webp, or video mp4, webm, mov. place=page uses scope=church|member (mypage and member_page mean member) and slot=photo|banner|avatar (gallery and picture mean photo; portrait and profile mean avatar). campus_id 0 is the main church page. banner_x and banner_y set the banner focus from 0 to 100, even with no new file. A member picture stays on the account the owner chose. place=login saves a sign-in background (up to 8). surface=welcome is refused. caption or title. place=partner needs partner_id or a title. Optional subtitle, body, link_url, link_label, badge, published=1. A new partner stays unpublished unless published=1. place=giving needs option_id. place=song needs song_id and png, jpg, jpeg, pdf, doc, docx, or txt. place=post needs the Posts switch too. Fields title or caption, body, visibility public|private|personal|followers, and as=church only for an owner bot with the church wall on. Reverse does not remove the file. A wall picture hides with the post undo."},
        {"method": "GET", "path": "/api/bot/modules", "switch": "office",
         "about": "The church apps menu: which modules are on, and which stay on. Custom apps are the custom_modules desk."},
        {"method": "POST", "path": "/api/bot/modules", "switch": "office",
         "about": "Turn apps on or off. Body: {\"modules\":{\"curriculum\": true}}. Apps you do not name stay as they are. Core apps stay on."},
        {"method": "GET", "path": "/api/bot/moderation", "switch": "office",
         "about": "The gathering monitor and site moderation: the review ledger and reports. ?status=active|reversed|upheld|all and ?flags=open|hidden|dismissed|restored."},
        {"method": "POST", "path": "/api/bot/moderation", "switch": "office",
         "about": "Body: {\"action\":\"hide|restore|review|report|warn|shadow|unshadow\", \"note\":\"\"}. hide and restore need kind and id. review needs action_id and decision reverse or uphold. report needs kind, id, and decision hide, dismiss, or restore. warn needs user_id and a note. shadow and unshadow need user_id. The moderation ledger is the record. Reverse does not undo it. An admin bot cannot warn or shadow an owner or admin, or its own account."},
        {"method": "GET", "path": "/api/bot/insights", "switch": "office",
         "about": "AI insight report names. The church AI key is not returned."},
        {"method": "POST", "path": "/api/bot/insights", "switch": "office",
         "about": "Run one insight. Body: {\"report\":\"overview\", \"question\":\"\"}. Report is overview, donations, attendance, security, or tickets. Addresses are prefixes only. This spends the church AI key."},
        {"method": "GET", "path": "/api/bot/desks", "switch": "office",
         "about": "Every church desk and every column on it. The areas list in this helper names each menu area and the desks under it: My Page, the church page, notes, people, events, prayers, sermons, announcements, dreams, prophecies, bible, study courses, members, donations, bills, accounting, inventory, attendance, child check-in, volunteers, communications, pastoral, worship lyrics and setlists, the gathering monitor, site moderation, mod reviews, AI insights, settings, the church apps menu, modules, and help. Not a short summary."},
        {"method": "GET", "path": "/api/bot/desk/<area>", "switch": "office",
         "about": "Full rows for that desk. ?id= opens one. The church page opens with campus_id. My Page opens with user_id. ?q= searches names and titles. A query name that matches a column filters that column. limit= up to 100."},
        {"method": "POST", "path": "/api/bot/desk/<area>", "switch": "office",
         "about": "Create or update every safe column. id updates that row. Link desks use their key columns. Help pages are help_articles: send id, title, and body_md, or is_published=0 to unpublish. hide=true soft-hides content that has a hide column. remove=true drops a membership or assignment row and reverse puts it back. Songs, sermons, posts, gifts, help pages, and people are not deleted. Passwords, card numbers, family PINs, pickup codes, and mail logins are refused."},
    ]
    for row in SWITCHES:
        if row["kind"] != "read":
            continue
        calls.append({
            "method": "GET",
            "path": f"/api/bot/read/{row['id']}",
            "switch": row["id"],
            "about": READ_ABOUT.get(row["id"], row["detail"]),
        })
    for call in calls:
        need = call.get("switch")
        also = call.pop("also", None)
        if blocked_why:
            call["allowed"] = False
            call["why"] = blocked_why
            continue
        call["allowed"] = True if need is None else bool(on.get(need))
        if also and on.get(also):
            call["allowed"] = True
        call["why"] = "" if call["allowed"] else (need or "switch")
    return calls


def _areas() -> list[dict]:
    """Menu areas the desks cover. Imported here so this file stays free of SQL."""
    try:
        from app.utils.bot_areas import covers
    except Exception:
        return []
    rows = []
    for key, area in covers().items():
        if key == "still_closed" or not isinstance(area, dict):
            continue
        rows.append({
            "id": key,
            "path": area.get("path") or f"/api/bot/desk/{(area.get('desks') or [''])[0]}",
            "desks": list(area.get("desks") or []),
            "about": area.get("about") or "",
        })
    return rows


def help_payload(controls, voices: list[dict] | None = None, blocked_why: str | None = None) -> dict:
    calls = call_map(controls, blocked_why=blocked_why)
    areas = _areas()
    lines = []
    for call in calls:
        mark = "on" if call["allowed"] else "off"
        lines.append(f"{call['method']} {call['path']} [{mark}] {call['about']}")
    for area in areas:
        desks = ", ".join(area["desks"])
        lines.append(f"AREA {area['id']} {area['path']} desks: {desks}. {area['about']}")
    voice_rows = []
    for voice in voices or []:
        kind = voice.get("voice_type") or ""
        if kind == "church":
            voice_rows.append({"as": "church", "author_user_id": voice.get("user_id"), "label": voice.get("label") or "Church"})
        elif kind == "user" and voice.get("user_id"):
            voice_rows.append({
                "as": f"user:{int(voice['user_id'])}",
                "author_user_id": int(voice["user_id"]),
                "label": voice.get("label") or person_label(voice),
            })
    return {
        "lines": lines,
        "calls": calls,
        "areas": areas,
        "switches": normalize_controls(controls),
        "voices": voice_rows,
        "closed": list(CLOSED),
        "undo": "POST /api/bot/reverse with {\"log_id\": N} hides a post, sermon draft, illustration, or section, or puts the previous text, group role, worship defaults, bill, stock change, attendance check-in, or desk edit back. A recorded gift or expense is not voided. A study course, an uploaded file, an apps-menu change, a moderation action, and an insight run are not reversed.",
        "sign_in": {
            "api_key": "Does not expire. Emailed only to the API-key inbox. Never shown on the dashboard. After a reset, the previous key works for 15 minutes.",
            "twofa_key": "Expires in 1 hour. Emailed only to the other inbox by POST /api/bot/login. A second sign-in keeps the previous unused code. Asking for one does not close an open session. Up to three unused codes stay valid.",
            "session": "POST /api/bot/login/exchange returns a session. Several sessions can be open at once. Send one as Authorization: Bearer on work calls. Each session expires in 1 hour. A new sign-in does not close the others.",
            "twofa_header": "X-Bot-2FA",
            "expires_in": TWOFA_TTL_SECONDS,
            "reset": "If the API key does not work, POST /api/bot/key/reset-request with the main inbox. A new API key is emailed there. A 2FA key is not emailed until POST /api/bot/login. The old key stops working in 15 minutes.",
        },
    }
