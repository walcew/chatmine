from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

import jwt
import requests

from ...secrets import ChromiumVault, CookieRow, read_cookies
from ._paths import cookie_dbs, local_state

AUTHZ_URL = "https://authsvc.teams.microsoft.com/v1.0/authz"
USER_AGENT = "chatmine/0.1.0"

VAULT = ChromiumVault(
    keychain_service="Microsoft Teams Safe Storage",
    cookie_names=("authtoken", "authtoken_asm", "skypetoken_asm"),
    host_filters=("%teams.microsoft.com%", "%asm.skype.com"),
    cookie_dbs=cookie_dbs,
    local_state=local_state,
)


@dataclass(frozen=True)
class TeamsTokens:
    authtoken: str
    skypetoken: str
    region: str
    skypeid: str | None
    tenant_id: str | None
    upn: str | None
    authtoken_exp: datetime
    skypetoken_exp: datetime


@dataclass(frozen=True)
class TenantInfo:
    tenant_id: str
    upn: str | None
    skypeid_aad: str | None  # GUID do claim `oid` do authtoken
    region_hint: str | None  # do path do cookie, ex.: "emea-02"
    authtoken_exp: datetime
    _authtoken: str = field(repr=False, default="")


def _parse_claims(token: str) -> dict[str, Any]:
    return jwt.decode(token, options={"verify_signature": False, "verify_aud": False})


def _exp(claims: dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(int(claims.get("exp", 0)), tz=UTC)


def _strip_jwt_trailing(token: str) -> str:
    for sep in ("&", ";"):
        if sep in token:
            token = token.split(sep, 1)[0]
    return token.strip()


def _unwrap_bearer(raw: str) -> str:
    decoded = unquote(raw)
    for sep in ("Bearer=", "Bearer "):
        if decoded.startswith(sep):
            return _strip_jwt_trailing(decoded[len(sep):])
    return _strip_jwt_trailing(decoded)


def _unwrap_skype(raw: str) -> str:
    decoded = unquote(raw)
    if decoded.lower().startswith("skypetoken="):
        decoded = decoded.split("=", 1)[1]
    return _strip_jwt_trailing(decoded)


def _region_from_path(path: str) -> str | None:
    # paths tipo "/api/mt/amer/beta/users/..." ou "/api/mt/part/emea-02/beta/..."
    parts = [p for p in path.split("/") if p]
    if "mt" in parts:
        i = parts.index("mt")
        cand = parts[i + 1] if i + 1 < len(parts) else None
        if cand == "part" and i + 2 < len(parts):
            return parts[i + 2]
        return cand
    return None


def discover_tenants(profile: str = "tfw") -> list[TenantInfo]:
    """Tenants com authtoken (não expirado) cacheado localmente."""
    cookies = read_cookies(VAULT, profile=profile)
    seen: dict[str, TenantInfo] = {}
    now = datetime.now(tz=UTC)
    for c in cookies:
        if c.name != "authtoken" or c.host != "teams.microsoft.com":
            continue
        try:
            tok = _unwrap_bearer(c.value)
            claims = _parse_claims(tok)
        except Exception:
            continue
        tid = claims.get("tid")
        if not tid:
            continue
        exp = _exp(claims)
        if tid in seen:  # last_access_utc já vem DESC: mantém o mais recente por tid
            continue
        seen[tid] = TenantInfo(
            tenant_id=tid,
            upn=claims.get("upn"),
            skypeid_aad=claims.get("oid"),
            region_hint=_region_from_path(c.path),
            authtoken_exp=exp,
            _authtoken=tok,
        )
    return [t for t in seen.values() if (t.authtoken_exp - now).total_seconds() > 0]


def _match_tenant(tenants: list[TenantInfo], query: str) -> TenantInfo:
    q = query.strip().lower()
    for t in tenants:
        if t.tenant_id.lower() == q:
            return t
    for t in tenants:
        if q in t.tenant_id.lower():
            return t
    for t in tenants:
        if q == (t.upn or "").lower():
            return t
    for t in tenants:
        upn = (t.upn or "").lower()
        if upn.endswith("@" + q) or q in upn:
            return t
    available = ", ".join(f"{t.upn or t.tenant_id}" for t in tenants)
    raise RuntimeError(
        f"Nenhum tenant casa com {query!r}. Disponíveis: {available}. "
        f"Use --account com um domínio, UPN ou tenant-id (ou prefixo)."
    )


def _exchange_for_skypetoken(authtoken: str) -> tuple[str, dict[str, Any]]:
    r = requests.post(
        AUTHZ_URL,
        headers={
            "Authorization": f"Bearer {authtoken}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        timeout=20,
    )
    if not r.ok:
        raise RuntimeError(f"authsvc {r.status_code}: {r.text[:300]}")
    data = r.json()
    sk = (data.get("tokens") or {}).get("skypeToken")
    if not sk:
        raise RuntimeError(f"resposta inesperada do authsvc: {list(data.keys())}")
    return sk, _parse_claims(sk)


def _find_skype_cookie(cookies: list[CookieRow], tid: str) -> tuple[str, dict] | None:
    for c in cookies:
        if c.name != "skypetoken_asm":
            continue
        try:
            tok = _unwrap_skype(c.value)
            claims = _parse_claims(tok)
        except Exception:
            continue
        if claims.get("tid") == tid:
            return tok, claims
    return None


def get_tokens(profile: str = "tfw", tenant: str | None = None) -> TeamsTokens:
    cookies = read_cookies(VAULT, profile=profile)
    tenants = discover_tenants(profile=profile)
    if not tenants:
        raise RuntimeError(
            "Nenhum authtoken válido nos cookies locais. "
            "Abra o Teams e autentique em alguma conta."
        )

    if tenant is None:
        selected = max(tenants, key=lambda t: t.authtoken_exp)
    else:
        selected = _match_tenant(tenants, tenant)

    hit = _find_skype_cookie(cookies, selected.tenant_id)
    now = datetime.now(tz=UTC)
    if hit is not None:
        skypetoken, skype_claims = hit
        sk_exp = _exp(skype_claims)
        if (sk_exp - now).total_seconds() < 60:
            hit = None
    if hit is None:
        skypetoken, skype_claims = _exchange_for_skypetoken(selected._authtoken)
        sk_exp = _exp(skype_claims)

    claims = _parse_claims(selected._authtoken)
    region = (
        skype_claims.get("rgn") or claims.get("rgn") or selected.region_hint or "amer"
    ).lower()

    return TeamsTokens(
        authtoken=selected._authtoken,
        skypetoken=skypetoken,
        region=region,
        skypeid=(
            skype_claims.get("skypeid") or claims.get("skypeid") or claims.get("skype_id")
        ),
        tenant_id=selected.tenant_id,
        upn=selected.upn,
        authtoken_exp=selected.authtoken_exp,
        skypetoken_exp=sk_exp,
    )
