"""
EDGEWISE AI — Authentication & Trust Boundary Abstraction

Defines the security architecture, trust boundaries, and authorization interfaces
for the offline-first edge AI appliance.

Current Security Posture & Trust Model:
- Architecture: Single-tenant Edge Appliance / Field Terminal.
- Current Trust Boundary: Localhost & Private Physical Field LAN.
- Deployment Assumption: Edge devices run in physically secured or isolated local
  subnets (e.g., control rooms, field terminals at Site Alpha). Calls originating
  within this perimeter are currently treated as authorized operator operations.
- Current Limitation: Endpoints are unauthenticated by default. There is NO multi-user
  login system, session cookie, or RBAC enforcement on raw local HTTP ports.
- Protection Requirement for Production / Remote Deployments:
  When edge nodes are exposed beyond the local field subnet or synchronizing across
  untrusted networks, authentication MUST be enabled via API key, mutual TLS (mTLS),
  or an upstream API Gateway (e.g., Envoy, Traefik, Nginx with client certificates).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status


class TrustBoundary(str, Enum):
    """Trust boundary classification for edge operations."""
    LOCAL_EDGE_TRUSTED = "local_edge_trusted"
    PRIVATE_SUBNET = "private_subnet"
    REMOTE_UNTRUSTED = "remote_untrusted"


class Permission(str, Enum):
    """Granular permissions for edge operations."""
    READ = "read"
    WRITE = "write"
    INGEST = "ingest"
    SYNC = "sync"
    ADMIN = "admin"


@dataclass
class AuthSubject:
    """The authenticated subject initiating a request."""
    subject_id: str
    subject_type: str  # "terminal_operator", "device", "sync_daemon", "anonymous"
    trust_boundary: TrustBoundary
    permissions: set[Permission] = field(default_factory=set)
    is_authenticated: bool = False


@dataclass
class AuthContext:
    """Carries authorization context for a request."""
    subject: AuthSubject
    client_ip: Optional[str] = None
    auth_method: str = "none"  # "none", "api_key", "bearer_token", "mtls"


class BaseAuthProvider(ABC):
    """Abstract authentication provider contract."""

    @abstractmethod
    async def authenticate(self, request: Request) -> AuthContext:
        """Authenticate an incoming request and return its AuthContext."""
        pass


class LocalEdgeTrustedAuthProvider(BaseAuthProvider):
    """
    Default provider for single-tenant offline edge terminal.

    Truthful Behavior:
    - Does NOT pretend to validate non-existent tokens or credentials.
    - Accurately reports that requests from the local edge network operate under
      the LOCAL_EDGE_TRUSTED boundary with operator privileges.
    - Rejects unauthenticated requests if strict authentication is explicitly enabled
      via environment configuration.
    """

    def __init__(self, require_auth: bool = False, api_key: Optional[str] = None):
        self.require_auth = require_auth
        self.api_key = api_key

    async def authenticate(self, request: Request) -> AuthContext:
        client_ip = request.client.host if request.client else "unknown"

        # Check for API key if provided in headers
        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-API-Key", "")

        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif api_key_header:
            token = api_key_header.strip()

        if self.require_auth:
            if not token or not self.api_key or token != self.api_key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required: invalid or missing API key/token.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return AuthContext(
                subject=AuthSubject(
                    subject_id="authenticated_operator",
                    subject_type="terminal_operator",
                    trust_boundary=TrustBoundary.PRIVATE_SUBNET,
                    permissions={
                        Permission.READ,
                        Permission.WRITE,
                        Permission.INGEST,
                        Permission.SYNC,
                        Permission.ADMIN,
                    },
                    is_authenticated=True,
                ),
                client_ip=client_ip,
                auth_method="api_key",
            )

        # Unauthenticated local edge appliance mode (truthful reporting)
        return AuthContext(
            subject=AuthSubject(
                subject_id="local_operator",
                subject_type="terminal_operator",
                trust_boundary=TrustBoundary.LOCAL_EDGE_TRUSTED,
                permissions={
                    Permission.READ,
                    Permission.WRITE,
                    Permission.INGEST,
                    Permission.SYNC,
                    Permission.ADMIN,
                },
                is_authenticated=False,
            ),
            client_ip=client_ip,
            auth_method="none",
        )


_default_provider = LocalEdgeTrustedAuthProvider()


def get_auth_provider() -> BaseAuthProvider:
    """Return the configured authentication provider singleton."""
    return _default_provider


def set_auth_provider(provider: BaseAuthProvider) -> None:
    """Override the auth provider (used for testing or custom gateway integration)."""
    global _default_provider
    _default_provider = provider


async def get_current_auth(
    request: Request,
    provider: BaseAuthProvider = Depends(get_auth_provider),
) -> AuthContext:
    """FastAPI dependency: resolves current request auth context."""
    return await provider.authenticate(request)


def require_permission(required_perm: Permission):
    """Dependency factory to enforce specific permissions."""
    async def _permission_dependency(
        auth: AuthContext = Depends(get_current_auth),
    ) -> AuthContext:
        if required_perm not in auth.subject.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires '{required_perm.value}' permission.",
            )
        return auth
    return _permission_dependency
