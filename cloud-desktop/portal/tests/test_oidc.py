"""Вхід через пошту коледжу: імітуємо провайдера OpenID Connect з власним RSA-ключем."""
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from conftest import H

ISSUER = "https://login.example-college.test"
CLIENT = "portal-client"


@pytest.fixture()
def idp(monkeypatch, app_env):
    from app import oidc
    from app.config import config
    monkeypatch.setattr(config, "oidc_issuer", ISSUER)
    monkeypatch.setattr(config, "oidc_client_id", CLIENT)
    monkeypatch.setattr(config, "oidc_client_secret", "secret")
    monkeypatch.setattr(config, "oidc_allowed_domains", {"college.edu.ua"})
    monkeypatch.setattr(config, "oidc_auto_create", False)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    state = {"claims": {}, "key": key, "issuer": ISSUER}

    monkeypatch.setattr(oidc, "discovery", lambda issuer: {
        "authorization_endpoint": f"{ISSUER}/authorize", "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/keys"})

    def exchange(code, redirect_uri, verifier):
        assert code == "good-code" and redirect_uri.endswith("/api/auth/oidc/callback") and verifier
        now = int(time.time())
        claims = {"iss": state["issuer"], "aud": CLIENT, "sub": "123", "iat": now, "exp": now + 300,
                  "nonce": state["nonce"], **state["claims"]}
        return {"id_token": jwt.encode(claims, state["sign_with"], algorithm="RS256")}
    monkeypatch.setattr(oidc, "exchange_code", exchange)
    monkeypatch.setattr(oidc, "signing_key", lambda token: key.public_key())
    state["sign_with"] = key
    return state


def run_login(client, idp, claims, tamper_state=False):
    idp["claims"] = claims
    r = client.get("/api/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == [CLIENT]
    idp["nonce"] = q["nonce"][0]
    state = "forged" if tamper_state else q["state"][0]
    return client.get(f"/api/auth/oidc/callback?code=good-code&state={state}", follow_redirects=False)


def set_email(login, username, email):
    a = login("admin", "Admin12345")
    u = next(x for x in a.get("/api/admin/users").json() if x["username"] == username)
    body = {**u, "email": email, "password": None, "teaching_ids": [t["id"] for t in u["teaching"]]}
    assert a.put(f"/api/admin/users/{u['id']}", json=body, headers=H).status_code == 200


def test_login_with_college_email(client, idp, login):
    set_email(login, "student1", "a.kovalenko@college.edu.ua")
    assert client.get("/api/auth/oidc/config").json()["enabled"] is True
    r = run_login(client, idp, {"email": "A.Kovalenko@college.edu.ua", "email_verified": True})
    assert r.status_code == 302 and r.headers["location"] == "/"
    me = client.get("/api/auth/me").json()
    assert me["username"] == "student1" and me["login_method"] == "oidc"


def test_rejections(client, idp, login):
    set_email(login, "student1", "a.kovalenko@college.edu.ua")
    r = run_login(client, idp, {"email": "hacker@gmail.com"})
    assert "login_error" in r.headers["location"] and client.get("/api/auth/me").status_code == 401
    r = run_login(client, idp, {"email": "a.kovalenko@college.edu.ua"}, tamper_state=True)
    assert "login_error" in r.headers["location"]
    r = run_login(client, idp, {"email": "a.kovalenko@college.edu.ua", "email_verified": False})
    assert "login_error" in r.headers["location"]
    r = run_login(client, idp, {"email": "nobody@college.edu.ua"})          # акаунта немає, автостворення вимкнено
    assert "login_error" in r.headers["location"]
    idp["issuer"] = "https://evil.test"                                       # чужий видавець
    r = run_login(client, idp, {"email": "a.kovalenko@college.edu.ua"})
    assert "login_error" in r.headers["location"]
    idp["issuer"] = ISSUER
    idp["sign_with"] = rsa.generate_private_key(public_exponent=65537, key_size=2048)   # підроблений підпис
    r = run_login(client, idp, {"email": "a.kovalenko@college.edu.ua"})
    assert "login_error" in r.headers["location"]
    assert client.get("/api/auth/me").status_code == 401


def test_nonce_replay_rejected(client, idp, login):
    set_email(login, "student1", "a.kovalenko@college.edu.ua")
    idp["claims"] = {"email": "a.kovalenko@college.edu.ua"}
    r = client.get("/api/auth/oidc/login", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    idp["nonce"] = "some-other-nonce"
    r = client.get(f"/api/auth/oidc/callback?code=good-code&state={q['state'][0]}", follow_redirects=False)
    assert "login_error" in r.headers["location"]


def test_auto_create_student(client, idp, monkeypatch):
    from app.config import config
    monkeypatch.setattr(config, "oidc_auto_create", True)
    r = run_login(client, idp, {"email": "o.new+lab@college.edu.ua", "name": "Олег Новий"})
    assert r.headers["location"] == "/"
    me = client.get("/api/auth/me").json()
    assert me["username"] == "o.new.lab" and me["role"] == "student" and me["group"] is None
    assert me["must_change_password"] is False
    # пароля в такого акаунта немає — увійти логіном і паролем неможливо
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"username": "o.new.lab", "password": "!oidc"},
                       headers=H).status_code == 401


def test_temp_password_user_can_use_portal_via_oidc(client, idp, login):
    a = login("admin", "Admin12345")
    a.post("/api/admin/users", json={"username": "imported", "password": "Given2026x",
                                     "email": "imported@college.edu.ua"}, headers=H)
    run_login(client, idp, {"email": "imported@college.edu.ua"})
    assert client.get("/api/templates").status_code == 200   # пароль змінювати не треба


def test_username_from_email():
    from app.oidc import username_from_email
    taken = {"ivan.petrenko"}
    assert username_from_email("Ivan.Petrenko@college.edu.ua", taken.__contains__) == "ivan.petrenko2"
    assert username_from_email("_x@college.edu.ua", lambda n: False) == "user.x"
