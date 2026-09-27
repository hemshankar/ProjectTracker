from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import config

_serializer = URLSafeTimedSerializer(config.SESSION_SECRET_KEY, salt="scatterboard-session")
_state_serializer = URLSafeTimedSerializer(config.SESSION_SECRET_KEY, salt="scatterboard-oauth-state")


def sign_session(user_id: str) -> str:
    return _serializer.dumps(user_id)


def verify_session(token: str) -> str | None:
    try:
        return _serializer.loads(token, max_age=config.SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def sign_state(value: str) -> str:
    return _state_serializer.dumps(value)


def verify_state(token: str) -> str | None:
    try:
        return _state_serializer.loads(token, max_age=600)
    except (BadSignature, SignatureExpired):
        return None
