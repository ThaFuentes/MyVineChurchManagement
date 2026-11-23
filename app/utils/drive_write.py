"""Write one media file into a linked Google Drive folder.

Off unless the owner sets DRIVE_WRITE_MODE. Two backends exist: a Google
Cloud service account JSON, or an OAuth refresh token. A missing setting
is a plain refusal; no credential, path, or stack trace is ever returned
to the caller or written to a log.
"""

from __future__ import annotations

import json
import os
import secrets
import time
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
DEFAULT_SCOPE = "https://www.googleapis.com/auth/drive"
MODES = ("off", "service_account", "oauth")
TIMEOUT = 90

_NOT_SET_UP = "Drive uploads are not set up yet. The owner still needs to finish the Google account for the site."


class DriveWriteOff(Exception):
    """Writes are off, or the credentials the chosen mode needs are missing."""


class DriveWriteError(Exception):
    """Google refused the upload."""


def mode() -> str:
    """Which backend the owner chose. Anything unrecognized is off."""
    raw = (os.environ.get("DRIVE_WRITE_MODE") or "off").strip().lower().replace("-", "_")
    return raw if raw in MODES else "off"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _post(url: str, body: bytes, headers: dict) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except Exception:
        raise DriveWriteError("Google Drive refused that file just now.") from None


def _read_json_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        raise DriveWriteOff(_NOT_SET_UP) from None
    return data if isinstance(data, dict) else {}


def _jwt(account: dict) -> str:
    """Sign the service-account assertion. RS256, one hour."""
    import base64

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    email = account.get("client_email")
    private_key = account.get("private_key")
    if not email or not private_key:
        raise DriveWriteOff(_NOT_SET_UP)
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": email,
        "scope": _env("DRIVE_OAUTH_SCOPES") or DEFAULT_SCOPE,
        "aud": account.get("token_uri") or TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }

    def _b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    signing = _b64(json.dumps(header).encode()) + b"." + _b64(json.dumps(claims).encode())
    try:
        key = serialization.load_pem_private_key(private_key.encode(), password=None)
        signature = key.sign(signing, padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        raise DriveWriteOff(_NOT_SET_UP) from None
    return (signing + b"." + _b64(signature)).decode()


def _token_from(payload: dict) -> str:
    body = urllib.parse.urlencode(payload).encode()
    raw = _post(
        TOKEN_URL,
        body,
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        token = json.loads(raw.decode("utf-8", "replace") or "{}").get("access_token")
    except ValueError:
        token = None
    if not token:
        raise DriveWriteOff(_NOT_SET_UP)
    return token


def service_account_token() -> str:
    path = _env("DRIVE_SERVICE_ACCOUNT_FILE")
    if not path:
        raise DriveWriteOff(_NOT_SET_UP)
    account = _read_json_file(path)
    return _token_from({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": _jwt(account),
    })


def oauth_token() -> str:
    refresh = _env("DRIVE_OAUTH_REFRESH_TOKEN")
    if not refresh:
        path = _env("DRIVE_OAUTH_TOKEN_FILE")
        if not path:
            raise DriveWriteOff(_NOT_SET_UP)
        stored = _read_json_file(path)
        refresh = str(stored.get("refresh_token") or "").strip()
    client_id = _env("DRIVE_OAUTH_CLIENT_ID")
    client_secret = _env("DRIVE_OAUTH_CLIENT_SECRET")
    if not refresh or not client_id or not client_secret:
        raise DriveWriteOff(_NOT_SET_UP)
    return _token_from({
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": client_id,
        "client_secret": client_secret,
    })


def _create(token: str, folder_id: str, filename: str, payload: bytes, mime: str) -> str:
    boundary = "mvos" + secrets.token_hex(12)
    meta = json.dumps({"name": filename, "parents": [folder_id]})
    head = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{meta}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {mime}\r\n\r\n"
    ).encode()
    body = head + payload + f"\r\n--{boundary}--\r\n".encode()
    url = f"{UPLOAD_URL}?uploadType=multipart&fields=id&supportsAllDrives=true"
    raw = _post(url, body, {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/related; boundary={boundary}",
    })
    try:
        file_id = json.loads(raw.decode("utf-8", "replace") or "{}").get("id")
    except ValueError:
        file_id = None
    if not file_id:
        raise DriveWriteError("Google Drive refused that file just now.")
    return file_id


def _share_anyone(token: str, file_id: str) -> None:
    """Public embeds stay the playback model. A private folder would need the follow-up player."""
    body = json.dumps({"role": "reader", "type": "anyone"}).encode()
    _post(
        f"{FILES_URL}/{file_id}/permissions?supportsAllDrives=true",
        body,
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


def upload_media(folder_id, filename, payload, mime) -> str:
    """Upload one file into the folder and return its Drive file id."""
    selected = mode()
    if selected == "off":
        raise DriveWriteOff("Drive uploads are not turned on.")
    if not folder_id or not filename or not payload:
        raise DriveWriteError("That file could not be uploaded just now.")
    token = service_account_token() if selected == "service_account" else oauth_token()
    file_id = _create(token, folder_id, filename, payload, mime)
    try:
        _share_anyone(token, file_id)
    except DriveWriteError:
        # The file is in Drive. A missing share is the owner's to fix.
        pass
    return file_id
