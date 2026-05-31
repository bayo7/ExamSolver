"""
cloud/auth_middleware.py
-------------------------
Flask route'larını Firebase ID token ile korur.
"""

from flask import request
from .firebase_service import get_auth


def get_uid_from_request(req=None) -> str | None:
    """Authorization: Bearer <token> header'ından UID çıkarır; başarısız olursa None döner."""
    req = req or request
    header = req.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:]
    try:
        decoded = get_auth().verify_id_token(token)
        return decoded["uid"]
    except Exception:
        return None


def get_user_from_request(req=None) -> dict | None:
    """Token'dan {uid, email, name} sözlüğü döner; geçersizse None."""
    req = req or request
    header = req.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:]
    try:
        decoded = get_auth().verify_id_token(token)
        return {
            "uid": decoded["uid"],
            "email": decoded.get("email", ""),
            "name": decoded.get("name", decoded.get("email", "")),
        }
    except Exception:
        return None
