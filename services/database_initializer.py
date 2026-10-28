import re

import pymysql
from werkzeug.security import generate_password_hash


DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role ENUM('admin', 'user') NOT NULL
)
"""

COLLECTION_TASKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS collection_tasks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    keyword VARCHAR(100) NOT NULL,
    target_count INT NOT NULL,
    success_count INT NOT NULL DEFAULT 0,
    status ENUM('waiting', 'running', 'success', 'failed') NOT NULL,
    collect_date DATE NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME NULL,
    message VARCHAR(500) NOT NULL DEFAULT ''
)
"""

UPSERT_USER_SQL = """
INSERT INTO users (username, password, role)
VALUES (%s, %s, %s)
ON DUPLICATE KEY UPDATE password = VALUES(password), role = VALUES(role)
"""

def connection_options(app):
    return {
        "host": app.config["MYSQL_HOST"],
        "port": app.config["MYSQL_PORT"],
        "user": app.config["MYSQL_USER"],
        "password": app.config["MYSQL_PASSWORD"],
        "autocommit": True,
    }


def configured_users(app):
    credentials = (
        ("ADMIN_USERNAME", "ADMIN_PASSWORD", "admin"),
        ("USER_USERNAME", "USER_PASSWORD", "user"),
    )
    missing = [
        name
        for username_key, password_key, _role in credentials
        for name in (username_key, password_key)
        if not app.config.get(name) or not app.config[name].strip()
    ]
    if missing:
        raise ValueError(f"必须设置初始用户配置：{', '.join(missing)}")

    usernames = [
        app.config[username_key].strip()
        for username_key, _password_key, _role in credentials
    ]
    if len({username.casefold() for username in usernames}) != len(usernames):
        raise ValueError("管理员和普通用户必须使用不同的用户名")

    return tuple(
        (
            app.config[username_key].strip(),
            generate_password_hash(app.config[password_key]),
            role,
        )
        for username_key, password_key, role in credentials
    )


def initialize_database(app):
    database_name = app.config["MYSQL_DATABASE"]
    if not DATABASE_NAME_PATTERN.fullmatch(database_name):
        raise ValueError("数据库名只能包含字母、数字和下划线")

    users = configured_users(app)
    options = connection_options(app)
    try:
        with pymysql.connect(**options) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                    "DEFAULT CHARACTER SET utf8mb4"
                )

        with pymysql.connect(**options, database=database_name) as connection:
            with connection.cursor() as cursor:
                cursor.execute(USERS_TABLE_SQL)
                cursor.execute(COLLECTION_TASKS_TABLE_SQL)
                for user in users:
                    cursor.execute(UPSERT_USER_SQL, user)
    except pymysql.MySQLError as exc:
        app.logger.exception("MySQL database initialization failed")
        raise RuntimeError(
            "MySQL初始化失败，请检查MySQL服务及config.py数据库配置。"
        ) from exc
