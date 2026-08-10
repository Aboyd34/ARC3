"""Permission enforcement for authenticated Connectivity requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .models import TrustedDevice
from .protocol import ReplayGuard, SignedRequest, VerificationError, system_clock_ms


class PermissionDenied(VerificationError):
    """Raised when a valid trusted request lacks the required capability."""


DEFAULT_ACTION_PERMISSIONS: Mapping[str, str] = {
    "health.read": "health.read",
}


@dataclass(frozen=True, slots=True)
class AuthorizedRequest:
    request: SignedRequest
    trusted_device: TrustedDevice
    permission: str


class PermissionPolicy:
    def __init__(self, action_permissions: Mapping[str, str] | None = None) -> None:
        self._action_permissions = dict(action_permissions or DEFAULT_ACTION_PERMISSIONS)

    def verify_and_authorize(
        self,
        request: SignedRequest,
        trusted_device: TrustedDevice,
        replay_guard: ReplayGuard,
        *,
        now_ms: int | None = None,
    ) -> AuthorizedRequest:
        current = system_clock_ms() if now_ms is None else int(now_ms)
        request.verify(trusted_device, replay_guard, now_ms=current, record_replay=False)
        permission = self._action_permissions.get(request.action)
        if permission is None:
            raise PermissionDenied(f"remote action is not registered: {request.action}")
        if permission not in trusted_device.permissions:
            raise PermissionDenied(f"trusted device lacks permission: {permission}")
        replay_guard.check_and_record(request.sender_id, request.nonce, request.timestamp_ms, current)
        return AuthorizedRequest(request, trusted_device, permission)
