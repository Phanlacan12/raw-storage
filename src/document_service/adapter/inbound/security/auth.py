"""Xác thực và nhận diện chủ thể gọi API (D2, D3).

Dùng hệ định danh tập trung của tổ chức (mục 2.6 báo cáo): không tạo hệ tài khoản
nghiệp vụ riêng. Khi `security.auth_disabled = true` (chỉ dành cho phát triển và
test), chủ thể được đọc từ header để kịch bản curl chạy được mà không cần IdP.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from document_service.config import SecuritySettings
from document_service.domain.errors import PolicyDeniedError
from document_service.domain.model import Principal
from document_service.utils.logging_setup import get_logger

_LOGGER = get_logger(__name__)
HEADER_PRINCIPAL = "X-Principal-Id"
HEADER_GROUPS = "X-Principal-Groups"
HEADER_IDEMPOTENCY = "Idempotency-Key"


class OidcTokenVerifier:
    """Xác thực JWT bằng JWKS của IdP, có cache khóa công khai."""

    def __init__(self, settings: SecuritySettings) -> None:
        """Nhận cấu hình OIDC."""
        self._settings = settings
        self._jwk_client: PyJWKClient | None = None
        self._jwks_available = settings.auth_disabled

    @property
    def jwks_available(self) -> bool:
        """JWKS còn dùng được hay không, health indicator đọc giá trị này."""
        return self._jwks_available

    async def probe_jwks(self) -> bool:
        """Nạp khóa lúc khởi động và kiểm cả hạn cache khi chưa có request."""
        if self._settings.auth_disabled:
            return True
        if not self._settings.oidc_jwks_url:
            return False
        try:
            await asyncio.to_thread(self._client().get_signing_keys)
            self._jwks_available = True
        except jwt.PyJWKClientError:
            self._jwks_available = False
        return self.jwks_available

    def _client(self) -> PyJWKClient:
        """Một cache khóa dùng chung cho probe và xác thực token."""
        if self._jwk_client is None:
            self._jwk_client = PyJWKClient(self._settings.oidc_jwks_url)
        return self._jwk_client

    def verify(self, token: str) -> dict[str, Any]:
        """Giải mã và kiểm tra token, phát PolicyDeniedError nếu không hợp lệ."""
        try:
            signing_key = self._signing_key(token)
            return dict(
                jwt.decode(
                    token,
                    signing_key,
                    algorithms=["RS256", "ES256"],
                    audience=self._settings.oidc_audience or None,
                    issuer=self._settings.oidc_issuer or None,
                )
            )
        except (jwt.PyJWTError, httpx.HTTPError) as error:
            _LOGGER.warning("token verification failed", extra={"error": str(error)})
            raise PolicyDeniedError("invalid token") from error

    def _signing_key(self, token: str) -> Any:
        """Lấy khóa công khai tương ứng token."""
        if not self._settings.oidc_jwks_url:
            raise PolicyDeniedError("JWKS is not configured for the IdP")
        try:
            key = self._client().get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientConnectionError:
            self._jwks_available = False
            raise
        self._jwks_available = True
        return key


class PrincipalResolver:
    """Dựng `Principal` từ header của request."""

    def __init__(
        self, settings: SecuritySettings, verifier: OidcTokenVerifier | None = None
    ) -> None:
        """Nhận cấu hình bảo mật và bộ xác thực token."""
        self._settings = settings
        self._verifier = verifier or OidcTokenVerifier(settings)

    @property
    def verifier(self) -> OidcTokenVerifier:
        """Bộ xác thực token, dùng cho health check của IdP."""
        return self._verifier

    def resolve(self, authorization: str | None, headers: dict[str, str]) -> Principal:
        """Trả về chủ thể đã xác thực, hoặc chủ thể dev khi tắt xác thực."""
        if self._settings.auth_disabled:
            return self._from_headers(headers)
        if not authorization or not authorization.lower().startswith("bearer "):
            raise PolicyDeniedError("missing bearer token")
        claims = self._verifier.verify(authorization.split(" ", 1)[1].strip())
        groups = self._claim_groups(claims)
        return Principal(
            principal_id=str(claims.get("sub", "")),
            groups=groups,
            is_admin=bool(set(groups) & set(self._settings.admin_groups)),
        )

    def _from_headers(self, headers: dict[str, str]) -> Principal:
        """Chủ thể lấy từ header, chỉ dùng khi `auth_disabled = true`."""
        lowered = {key.lower(): value for key, value in headers.items()}
        principal_id = lowered.get(HEADER_PRINCIPAL.lower(), "dev-user")
        raw_groups = lowered.get(HEADER_GROUPS.lower(), "")
        groups = tuple(item.strip() for item in raw_groups.split(",") if item.strip())
        return Principal(
            principal_id=principal_id,
            groups=groups,
            is_admin=bool(set(groups) & set(self._settings.admin_groups)) or not groups,
        )

    def _claim_groups(self, claims: dict[str, Any]) -> tuple[str, ...]:
        """Đọc danh sách nhóm từ claim của token."""
        raw = claims.get("groups") or claims.get("roles") or []
        if isinstance(raw, str):
            return tuple(item.strip() for item in raw.split(",") if item.strip())
        return tuple(str(item) for item in raw)
