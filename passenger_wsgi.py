import sys
import os

# Force UTF-8 encoding to fix emoji/unicode errors
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Add project directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Import your Flask app from main.py
from main import app as application


# DOMAIN_FRONT_WRAP (President 2026-11-20): requests relayed by the central
# PHP domain front carry a server-side token. For those only, restore the
# visitor's real IP, the public host and https so bans, rate limits, tenant
# gating and cookies behave exactly as a direct visit. Without the token
# nothing changes. The token header is always removed before the app sees it.
import hmac as _dfw_hmac
import ipaddress as _dfw_ip
import os as _dfw_os
import re as _dfw_re

_dfw_inner = globals().get("application")
try:
    with open(_dfw_os.path.expanduser("~/.aegisx_front_token")) as _dfw_f:
        _DFW_TOKEN = _dfw_f.read().strip()
except Exception:
    _DFW_TOKEN = ""
_DFW_HOST_RE = _dfw_re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def _dfw_application(environ, start_response):
    tok = environ.pop("HTTP_X_AEGISX_FRONT", None)
    if _DFW_TOKEN and tok and _dfw_hmac.compare_digest(str(tok), _DFW_TOKEN):
        cip = (environ.get("HTTP_CF_CONNECTING_IP") or "").strip()
        try:
            _dfw_ip.ip_address(cip)
            environ["REMOTE_ADDR"] = cip
        except ValueError:
            pass
        host = (environ.get("HTTP_X_FORWARDED_HOST") or "").split(",")[0].strip().lower()
        if host and len(host) <= 253 and _DFW_HOST_RE.match(host):
            environ["HTTP_HOST"] = host
            environ["SERVER_NAME"] = host
        environ["SERVER_PORT"] = "443"
        environ["wsgi.url_scheme"] = "https"
        environ["HTTPS"] = "on"
    return _dfw_inner(environ, start_response)


if _dfw_inner is not None:
    application = _dfw_application
