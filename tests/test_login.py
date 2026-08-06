from __future__ import annotations

from pathlib import Path

try:
    from app import create_app
except ImportError:
    create_app = None


def create_client(tmp_path: Path):
    assert callable(create_app), "create_app 尚未实现"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "DATABASE": tmp_path / "users.db",
        }
    )
    return app.test_client()


def login(client, username: str, password: str):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def test_anonymous_home_redirects_to_login(tmp_path):
    client = create_client(tmp_path)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_admin_can_log_in_and_see_admin_navigation(tmp_path):
    client = create_client(tmp_path)

    response = login(client, "admin", "admin123")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    page = client.get("/").get_data(as_text=True)
    assert "管理员" in page
    assert 'href="/data">数据管理</a>' in page
    assert "数据管理（后续阶段）" not in page


def test_regular_user_can_log_in_but_cannot_see_admin_navigation(tmp_path):
    client = create_client(tmp_path)
    login(client, "user", "user123")

    page = client.get("/").get_data(as_text=True)

    assert "普通用户" in page
    assert "数据管理（后续阶段）" not in page


def test_logout_returns_to_login_and_clears_session(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    assert client.get("/", follow_redirects=False).headers["Location"].endswith("/login")


def test_default_local_port_is_available_for_this_project(tmp_path):
    assert callable(create_app), "create_app 尚未实现"

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "DATABASE": tmp_path / "users.db",
        }
    )

    assert app.config["PORT"] == 5052
