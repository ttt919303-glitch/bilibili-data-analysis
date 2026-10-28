import pytest

from app import create_app


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setattr("app.initialize_database", lambda application: None)
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "MYSQL_PASSWORD": "test-password",
            "ENABLE_SCHEDULER": False,
        }
    )


@pytest.fixture()
def client(app):
    return app.test_client()
