import os
import hmac
import secrets
from pathlib import Path
from typing import List, Optional
from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader

TOKEN_FILE_PATH = Path(__file__).resolve().parent.parent / ".kela_local_token"
DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
]

api_key_header = APIKeyHeader(name="X-KELA-Token", auto_error=False)

def get_or_create_local_token() -> str:
    """
    Retrieve or securely generate a cryptographically strong local agent token.
    Stores the token in a gitignored local file if not supplied via environment.
    """
    env_token = os.environ.get("KELA_LOCAL_AGENT_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()

    if TOKEN_FILE_PATH.is_file():
        try:
            content = TOKEN_FILE_PATH.read_text(encoding="utf-8").strip()
            if len(content) >= 32:
                return content
        except Exception:
            pass

    # Generate a fresh 256-bit cryptographically secure token
    new_token = secrets.token_urlsafe(32)
    try:
        TOKEN_FILE_PATH.write_text(new_token, encoding="utf-8")
        if os.name != "nt":
            os.chmod(TOKEN_FILE_PATH, 0o600)
    except Exception:
        pass
    return new_token

LOCAL_AGENT_TOKEN = get_or_create_local_token()

class PermissionManager:
    """Manages origin validation, anti-DNS rebinding checks, and PC action authentication."""

    def __init__(self, token: Optional[str] = None):
        self._token = token or LOCAL_AGENT_TOKEN
        self._allowed_origins = self._load_allowed_origins()
        self._allowed_hosts = [
            "localhost",
            "127.0.0.1",
            "::1",
            "localhost:8000",
            "127.0.0.1:8000",
            "localhost:8001",
            "127.0.0.1:8001",
            "testserver",
        ]

    def _load_allowed_origins(self) -> List[str]:
        raw = os.environ.get("KELA_ALLOWED_ORIGINS", "")
        if raw.strip():
            return [o.strip() for o in raw.split(",") if o.strip()]
        return DEFAULT_ALLOWED_ORIGINS

    @property
    def allowed_origins(self) -> List[str]:
        return self._allowed_origins

    @property
    def local_token(self) -> str:
        return self._token

    def verify_token(self, provided_token: Optional[str]) -> bool:
        """Constant-time token comparison to prevent timing attacks."""
        if not provided_token:
            return False
        return hmac.compare_digest(self._token, provided_token.strip())

    def validate_origin(self, origin: Optional[str]) -> bool:
        """Validate request Origin header against allowed frontend origins."""
        if not origin:
            # Direct non-browser clients (curl, local tests) do not send Origin
            return True
        return origin.rstrip("/") in [o.rstrip("/") for o in self._allowed_origins]

    def validate_host(self, host: Optional[str]) -> bool:
        """DNS Rebinding mitigation: verify request Host header matches loopback."""
        if not host:
            return True
        clean_host = host.split(":")[0].lower()
        return clean_host in ["localhost", "127.0.0.1", "::1", "testserver"]

permission_manager = PermissionManager()

async def require_local_auth(
    request: Request,
    header_token: Optional[str] = Security(api_key_header),
) -> bool:
    """
    FastAPI dependency enforcing multi-layer protection on sensitive PC and system endpoints:
    1. Anti-DNS rebinding check (Host header).
    2. Cross-Origin validation (Origin header).
    3. Cryptographic token check (X-KELA-Token or Bearer token).
    """
    host = request.headers.get("host")
    if not permission_manager.validate_host(host):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: DNS rebinding protection rejected Host header.",
        )

    origin = request.headers.get("origin")
    if origin and not permission_manager.validate_origin(origin):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Origin not authorized for local PC operations.",
        )

    # Check X-KELA-Token header first
    candidate_token = header_token

    # Check Authorization: Bearer <token>
    if not candidate_token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            candidate_token = auth_header[7:].strip()

    # Check query param for websocket / direct links if needed
    if not candidate_token:
        candidate_token = request.query_params.get("token")

    if not permission_manager.verify_token(candidate_token):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Valid X-KELA-Token or Bearer token required for local PC operations.",
        )

    return True
