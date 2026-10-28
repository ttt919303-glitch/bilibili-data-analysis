from werkzeug.security import generate_password_hash


def test_admin_login_writes_role(client, monkeypatch):
    monkeypatch.setattr(
        "app.find_user",
        lambda username: {
            "id": 1,
            "username": "admin",
            "password": generate_password_hash("admin-test-passphrase"),
            "role": "admin",
        },
    )
    response = client.post(
        "/login", data={"username": "admin", "password": "admin-test-passphrase"}
    )
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["username"] == "admin"
        assert session["role"] == "admin"


def test_invalid_password_is_rejected(client, monkeypatch):
    monkeypatch.setattr(
        "app.find_user",
        lambda username: {
            "id": 2,
            "username": "student",
            "password": generate_password_hash("user-test-passphrase"),
            "role": "user",
        },
    )
    response = client.post(
        "/login", data={"username": "student", "password": "wrong"}
    )
    assert response.status_code == 200
    assert "用户名或密码错误" in response.get_data(as_text=True)


def test_login_required_redirects_anonymous_user(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
