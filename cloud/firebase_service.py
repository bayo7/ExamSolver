"""
cloud/firebase_service.py
--------------------------
Firebase Admin SDK başlatma — uygulama genelinde tek seferlik.
FIREBASE_PROJECT_ID ortam değişkeni yoksa sessizce devre dışı kalır.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

FIREBASE_ENABLED = False
_app = None

try:
    import firebase_admin
    from firebase_admin import credentials, auth as _auth, firestore as _firestore

    _REQUIRED = ("FIREBASE_PROJECT_ID", "FIREBASE_PRIVATE_KEY", "FIREBASE_CLIENT_EMAIL")
    if all(os.environ.get(k) for k in _REQUIRED):
        FIREBASE_ENABLED = True
    else:
        logging.warning("[Firebase] Ortam değişkenleri eksik; bulut özellikleri devre dışı.")

except ImportError:
    logging.warning("[Firebase] firebase-admin kurulu değil; bulut özellikleri devre dışı.")


def _init():
    global _app
    if _app is not None:
        return
    if not FIREBASE_ENABLED:
        raise RuntimeError("Firebase yapılandırılmamış")

    cred = credentials.Certificate({
        "type": "service_account",
        "project_id": os.environ["FIREBASE_PROJECT_ID"],
        "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID", ""),
        "private_key": os.environ["FIREBASE_PRIVATE_KEY"].replace("\\n", "\n"),
        "client_email": os.environ["FIREBASE_CLIENT_EMAIL"],
        "client_id": os.environ.get("FIREBASE_CLIENT_ID", ""),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": (
            "https://www.googleapis.com/robot/v1/metadata/x509/"
            + os.environ["FIREBASE_CLIENT_EMAIL"].replace("@", "%40")
        ),
    })

    _app = firebase_admin.initialize_app(cred, {
        "storageBucket": os.environ.get("FIREBASE_STORAGE_BUCKET", ""),
    })


def get_auth():
    _init()
    return _auth


def get_db():
    _init()
    return _firestore.client()
