"""Вхід через корпоративну пошту коледжу (OpenID Connect: Google Workspace, Microsoft 365 тощо).

Потік Authorization Code + PKCE:
  /api/auth/oidc/login     → редірект до провайдера (state, nonce і code_verifier — у підписаному cookie)
  /api/auth/oidc/callback  → обмін коду на id_token, перевірка підпису (JWKS), iss, aud, nonce, домену пошти,
                             пошук акаунта за email (або створення студента, якщо дозволено) і видача cookie порталу.

Налаштування (.env):
  CD_OIDC_ISSUER           https://accounts.google.com
                           або https://login.microsoftonline.com/<ID-тенанта>/v2.0
  CD_OIDC_CLIENT_ID / CD_OIDC_CLIENT_SECRET
  CD_OIDC_ALLOWED_DOMAINS  college.edu.ua (через кому; порожньо — будь-який домен, але лише наявні акаунти)
  CD_OIDC_AUTO_CREATE      1 — створювати студента при першому вході (без групи)
  CD_PUBLIC_URL            https://desk.college.edu.ua (для redirect_uri)
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from functools import lru_cache

import httpx
import jwt

from .config import config


class OIDCError(Exception):
    """Помилка входу, яку можна показати користувачу."""


def enabled() -> bool:
    return bool(config.oidc_issuer and config.oidc_client_id)


@lru_cache(maxsize=4)
def discovery(issuer: str) -> dict:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def make_state_cookie(state: str, nonce: str, verifier: str) -> str:
    payload = {"state": state, "nonce": nonce, "pkce": verifier, "exp": int(time.time()) + 600, "typ": "oidc"}
    return jwt.encode(payload, config.secret_key, algorithm="HS256")


def read_state_cookie(value: str | None) -> dict:
    if not value:
        raise OIDCError("Сеанс входу застарів. Спробуйте ще раз.")
    try:
        data = jwt.decode(value, config.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise OIDCError("Сеанс входу застарів. Спробуйте ще раз.") from exc
    if data.get("typ") != "oidc":
        raise OIDCError("Некоректний сеанс входу")
    return data


def authorization_url(redirect_uri: str, state: str, nonce: str, challenge: str) -> str:
    meta = discovery(config.oidc_issuer)
    params = {
        "response_type": "code", "client_id": config.oidc_client_id, "redirect_uri": redirect_uri,
        "scope": "openid email profile", "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account",
    }
    if len(config.oidc_allowed_domains) == 1 and "accounts.google.com" in config.oidc_issuer:
        params["hd"] = next(iter(config.oidc_allowed_domains))   # Google показує лише акаунти домену
    return str(httpx.URL(meta["authorization_endpoint"], params=params))


def exchange_code(code: str, redirect_uri: str, verifier: str) -> dict:
    meta = discovery(config.oidc_issuer)
    resp = httpx.post(meta["token_endpoint"], timeout=15, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": config.oidc_client_id, "client_secret": config.oidc_client_secret, "code_verifier": verifier,
    })
    if resp.status_code != 200:
        raise OIDCError("Провайдер входу відхилив запит. Зверніться до адміністратора.")
    return resp.json()


def signing_key(id_token: str):
    meta = discovery(config.oidc_issuer)
    return _jwks_client(meta["jwks_uri"]).get_signing_key_from_jwt(id_token).key


@lru_cache(maxsize=4)
def _jwks_client(uri: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(uri, cache_keys=True)


def verify_id_token(id_token: str, nonce: str) -> dict:
    try:
        claims = jwt.decode(
            id_token, signing_key(id_token), algorithms=["RS256", "ES256", "PS256"],
            audience=config.oidc_client_id,
            # Google іноді пише iss без https://
            issuer=[config.oidc_issuer.rstrip("/"), config.oidc_issuer.rstrip("/").removeprefix("https://")],
            options={"require": ["iss", "aud", "exp", "iat", "sub"]}, leeway=60,
        )
    except jwt.PyJWTError as exc:
        raise OIDCError("Не вдалося перевірити відповідь провайдера входу.") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OIDCError("Некоректна відповідь провайдера входу (nonce).")
    return claims


def email_from_claims(claims: dict) -> str:
    # Google: email + email_verified; Microsoft: email або preferred_username (UPN).
    email = (claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise OIDCError("Провайдер не передав адресу пошти.")
    if claims.get("email_verified") is False:
        raise OIDCError("Адресу пошти не підтверджено.")
    domain = email.rsplit("@", 1)[1]
    if config.oidc_allowed_domains and domain not in config.oidc_allowed_domains:
        raise OIDCError(f"Вхід дозволено лише з пошти {', '.join(sorted(config.oidc_allowed_domains))}.")
    return email


def username_from_email(email: str, taken) -> str:
    """ivan.Petrenko+x@college.edu.ua → ivan.petrenko (з цифрою, якщо логін зайнятий)."""
    base = re.sub(r"[^a-z0-9._-]", ".", email.split("@")[0].lower()).strip(".-_") or "user"
    base = re.sub(r"\.{2,}", ".", base)[:56]
    if len(base) < 2:
        base = f"user.{base}"
    name, i = base, 1
    while taken(name):
        i += 1
        name = f"{base}{i}"
    return name
