import builtins
import importlib

import pymysql
import pytest
from flask import Flask
from werkzeug.security import check_password_hash


class FakeCursor:
    def __init__(self, statements):
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement, parameters=None):
        self.statements.append((" ".join(statement.split()), parameters))


class FakeConnection:
    def __init__(self, statements):
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def cursor(self):
        return FakeCursor(self.statements)


def load_initializer():
    return importlib.import_module("services.database_initializer")


def make_app(database="bigdata_course"):
    app = Flask(__name__)
    app.config.update(
        MYSQL_HOST="127.0.0.1",
        MYSQL_PORT=3306,
        MYSQL_USER="root",
        MYSQL_PASSWORD="",
        MYSQL_DATABASE=database,
        ADMIN_USERNAME="course-admin",
        ADMIN_PASSWORD="admin-config-test-passphrase",
        USER_USERNAME="course-user",
        USER_PASSWORD="user-config-test-passphrase",
    )
    return app


def install_fake_connections(monkeypatch, initializer):
    calls = []
    statements = []

    def connect(**options):
        calls.append(options)
        return FakeConnection(statements)

    monkeypatch.setattr(initializer.pymysql, "connect", connect)
    return calls, statements


def test_initialize_database_creates_schema_tables_and_configured_users(monkeypatch):
    initializer = load_initializer()
    calls, statements = install_fake_connections(monkeypatch, initializer)

    initializer.initialize_database(make_app())

    assert calls == [
        {
            "host": "127.0.0.1",
            "port": 3306,
            "user": "root",
            "password": "",
            "autocommit": True,
        },
        {
            "host": "127.0.0.1",
            "port": 3306,
            "user": "root",
            "password": "",
            "database": "bigdata_course",
            "autocommit": True,
        },
    ]
    sql = "\n".join(statement for statement, _ in statements)
    assert "CREATE DATABASE IF NOT EXISTS `bigdata_course` DEFAULT CHARACTER SET utf8mb4" in sql
    assert "CREATE TABLE IF NOT EXISTS users" in sql
    assert "username VARCHAR(50) NOT NULL UNIQUE" in sql
    assert "role ENUM('admin', 'user') NOT NULL" in sql
    assert "CREATE TABLE IF NOT EXISTS collection_tasks" in sql
    assert "status ENUM('waiting', 'running', 'success', 'failed') NOT NULL" in sql
    assert "ON DUPLICATE KEY UPDATE password = VALUES(password), role = VALUES(role)" in sql

    users = [parameters for _, parameters in statements if parameters]
    assert [user[0] for user in users] == ["course-admin", "course-user"]
    assert check_password_hash(users[0][1], "admin-config-test-passphrase")
    assert check_password_hash(users[1][1], "user-config-test-passphrase")


def test_initialize_database_is_repeatable_and_does_not_read_sql_file(monkeypatch):
    initializer = load_initializer()
    calls, statements = install_fake_connections(monkeypatch, initializer)
    original_open = builtins.open

    def reject_sql_file(path, *args, **kwargs):
        if str(path).replace("\\", "/").endswith("sql/init.sql"):
            raise AssertionError("database initialization must not read sql/init.sql")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", reject_sql_file)

    initializer.initialize_database(make_app())
    initializer.initialize_database(make_app())

    assert len(calls) == 4
    assert sum("CREATE TABLE IF NOT EXISTS" in statement for statement, _ in statements) == 4
    assert sum("ON DUPLICATE KEY UPDATE" in statement for statement, _ in statements) == 4


def test_initialize_database_rejects_unsafe_database_name(monkeypatch):
    initializer = load_initializer()
    calls, _ = install_fake_connections(monkeypatch, initializer)

    with pytest.raises(ValueError, match="数据库名只能包含字母、数字和下划线"):
        initializer.initialize_database(make_app("course-name;DROP"))

    assert calls == []


def test_initialize_database_reports_mysql_connection_failure(monkeypatch, caplog):
    initializer = load_initializer()
    error = pymysql.MySQLError("server offline")
    monkeypatch.setattr(
        initializer.pymysql,
        "connect",
        lambda **options: (_ for _ in ()).throw(error),
    )

    with pytest.raises(RuntimeError, match="MySQL初始化失败") as raised:
        initializer.initialize_database(make_app())

    assert raised.value.__cause__ is error
    assert "server offline" in caplog.text


def test_create_app_initializes_database(monkeypatch):
    app_module = importlib.import_module("app")
    initialized_apps = []
    monkeypatch.setattr(
        app_module,
        "initialize_database",
        lambda application: initialized_apps.append(application),
        raising=False,
    )

    application = app_module.create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "MYSQL_PASSWORD": "",
            "ENABLE_SCHEDULER": False,
        }
    )

    assert initialized_apps == [application]
