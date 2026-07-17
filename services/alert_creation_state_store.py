"""Thread-safe in-memory alert-creation state.

State is process-local: it is lost on restart and is not shared by multiple
application instances.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import RLock
from typing import Callable

from core.models.alert_creation import AlertCreationSession


SESSION_TTL = timedelta(minutes=15)


class AlertCreationStateStore:
    def __init__(
        self,
        *,
        ttl: timedelta = SESSION_TTL,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._ttl = ttl
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._sessions: dict[str, AlertCreationSession] = {}
        self._expired_users: set[str] = set()
        self._lock = RLock()

    def get(self, user_id: str) -> AlertCreationSession | None:
        key = _user_id(user_id)
        if key is None:
            return None
        with self._lock:
            session = self._sessions.get(key)
            if session is not None and self._expired(session):
                self._sessions.pop(key, None)
                self._expired_users.add(key)
                return None
            return session

    def set(self, session: AlertCreationSession) -> None:
        if not isinstance(session, AlertCreationSession) or _user_id(session.user_id) is None:
            raise ValueError("valid session user_id is required")
        with self._lock:
            self._expired_users.discard(session.user_id.strip())
            self._sessions[session.user_id.strip()] = session

    def delete(self, user_id: str) -> None:
        key = _user_id(user_id)
        if key is None:
            return
        with self._lock:
            self._sessions.pop(key, None)
            self._expired_users.discard(key)

    def has(self, user_id: str) -> bool:
        return self.get(user_id) is not None

    def consume_expired(self, user_id: str) -> bool:
        key = _user_id(user_id)
        if key is None:
            return False
        with self._lock:
            if key not in self._expired_users:
                return False
            self._expired_users.remove(key)
            return True

    def _expired(self, session: AlertCreationSession) -> bool:
        updated_at = session.updated_at
        if not isinstance(updated_at, datetime) or updated_at.tzinfo is None:
            return True
        try:
            return self._clock() - updated_at > self._ttl
        except Exception:
            return True


def _user_id(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
