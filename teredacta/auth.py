import hashlib
import hmac
import os
import time
from functools import wraps
from typing import Optional

from fastapi import Request, Response
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from teredacta.config import TeredactaConfig


class AuthManager:
    def __init__(self, config: TeredactaConfig):
        self.config = config
        self.serializer = URLSafeTimedSerializer(config.secret_key)

    def create_session(self, response: Response) -> str:
        csrf_token = os.urandom(16).hex()
        session_data = {"csrf": csrf_token, "t": int(time.time())}
        cookie_value = self.serializer.dumps(session_data)
        response.set_cookie(
            "session", cookie_value, httponly=True, samesite="strict",
            max_age=self.config.session_timeout_minutes * 60,
            secure=not self.config.is_local_mode,
        )
        return csrf_token

    def validate_session(self, request: Request) -> Optional[dict]:
        cookie = request.cookies.get("session")
        if not cookie:
            return None
        try:
            return self.serializer.loads(cookie, max_age=self.config.session_timeout_minutes * 60)
        except (BadSignature, SignatureExpired):
            return None

    def validate_csrf(self, request: Request, session: dict) -> bool:
        token = request.headers.get("X-CSRF-Token", "")
        session_csrf = session.get("csrf", "")
        if not token or not session_csrf:
            return False
        return hmac.compare_digest(token, session_csrf)

    def is_admin(self, request: Request) -> bool:
        if not self.config.admin_enabled:
            return False
        if not self.config.admin_requires_login:
            return True
        return self.validate_session(request) is not None

    def get_csrf_token(self, request: Request) -> str:
        session = self.validate_session(request)
        if session:
            return session.get("csrf", "")
        return ""

    def clear_session(self, response: Response):
        response.delete_cookie("session")
