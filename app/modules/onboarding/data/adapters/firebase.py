"""Firebase Admin SDK adapter.

app_old (and the first app_new port) called `_get_firebase_app()` at *module
import time*, so importing the onboarding module — and therefore profile, post
and verification, which import it transitively — raised FileNotFoundError
whenever backend/service.json was absent. Initialisation is now lazy and cached,
so importing the module is free and the credential is only needed on first use.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials

from app.modules.onboarding.domain.exceptions import InvalidFirebaseTokenError
from app.modules.onboarding.domain.interfaces.firebase import IFirebaseVerifier

_app = None


def _get_firebase_app() -> "firebase_admin.App":
    """Initialise (once) and return the Firebase app. Called on first verify."""
    global _app
    if _app is not None:
        return _app
    try:
        _app = firebase_admin.get_app()
        return _app
    except ValueError:
        pass

    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        cred = credentials.Certificate(json.loads(sa_json))
    else:
        service_json_path = Path(__file__).resolve().parents[4] / "backend" / "service.json"
        cred = credentials.Certificate(str(service_json_path))

    _app = firebase_admin.initialize_app(cred)
    return _app


class FirebaseVerifier(IFirebaseVerifier):

    def verify_id_token(self, firebase_id_token: str) -> dict:
        try:
            return firebase_auth.verify_id_token(firebase_id_token, app=_get_firebase_app())
        except Exception as exc:
            raise InvalidFirebaseTokenError(f"Invalid Firebase token: {exc}") from exc
