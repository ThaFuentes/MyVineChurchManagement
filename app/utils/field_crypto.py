# Fernet encryption for stored credentials (email passwords, usernames, etc.)

import os
from cryptography.fernet import Fernet

_key_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config_key.bin')
_env_key = os.environ.get('ENCRYPTION_KEY')
if _env_key:
    _key = _env_key.encode()
elif os.path.exists(_key_path):
    with open(_key_path, 'rb') as f:
        _key = f.read()
else:
    # Do not write a new key into the document root. Apache serves real
    # files there before Flask can refuse them.
    outside_dir = os.path.join(os.path.expanduser('~'), '.config', 'poweredbytop')
    os.makedirs(outside_dir, exist_ok=True)
    os.chmod(outside_dir, 0o700)
    outside = os.path.join(outside_dir, 'field_key')
    if os.path.exists(outside):
        with open(outside, 'rb') as handle:
            _key = handle.read()
    else:
        _key = Fernet.generate_key()
        descriptor = os.open(outside, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(_key)

_cipher = Fernet(_key)


def encrypt(text: str) -> str:
    return _cipher.encrypt(text.encode()).decode() if text else ''


def decrypt(token: str) -> str:
    if not token:
        return ''
    try:
        return _cipher.decrypt(token.encode()).decode()
    except Exception:
        return ''