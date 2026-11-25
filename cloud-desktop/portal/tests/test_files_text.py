"""Текстові файли й переміщення (для робочого столу в демо-режимі)."""
from conftest import H


def test_text_read_write_move(login):
    c = login("student1", "Student123")
    assert c.put("/api/files/content", json={"path": "notes.txt", "content": "Привіт\n"}, headers=H).status_code == 200
    assert c.get("/api/files/content?path=notes.txt").json()["content"] == "Привіт\n"
    c.put("/api/files/content", json={"path": "notes.txt", "content": "v2"}, headers=H)      # перезапис
    assert c.get("/api/files/content?path=notes.txt").json()["content"] == "v2"
    c.post("/api/files/mkdir", json={"path": "", "name": "lab"}, headers=H)
    r = c.post("/api/files/move", json={"path": "notes.txt", "to": "lab/readme.md"}, headers=H)
    assert r.json()["path"] == "lab/readme.md"
    assert [i["name"] for i in c.get("/api/files?path=lab").json()["items"]] == ["readme.md"]
    # помилки
    assert c.post("/api/files/move", json={"path": "lab", "to": "lab/inner"}, headers=H).status_code == 400
    assert c.post("/api/files/move", json={"path": "lab/readme.md", "to": "../x"}, headers=H).status_code == 400
    assert c.put("/api/files/content", json={"path": "../evil.txt", "content": "x"}, headers=H).status_code in (200, 400)
    assert all(i["name"] != "evil.txt" for i in login("student2", "Student123").get("/api/files").json()["items"])
    c.post("/api/files/upload", data={"path": ""}, files={"file": ("img.bin", b"\xff\xfe\x00\x01")}, headers=H)
    assert c.get("/api/files/content?path=img.bin").status_code == 400
