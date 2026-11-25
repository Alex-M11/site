from conftest import H


def test_cli_reset_password_and_create_admin(client, capsys):
    from app.cli import main
    assert main(["reset-password", "admin"]) == 0
    pw = capsys.readouterr().out.split("Тимчасовий пароль: ")[1].split()[0]
    r = client.post("/api/auth/login", json={"username": "admin", "password": pw}, headers=H)
    assert r.status_code == 200 and client.get("/api/auth/me").json()["must_change_password"] is True
    assert main(["create-admin", "second.admin"]) == 0
    assert main(["create-admin", "second.admin"]) == 1
    assert main(["reset-password", "nobody"]) == 1
