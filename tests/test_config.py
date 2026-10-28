import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


CONFIG_ENV_NAMES = (
    "SECRET_KEY",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "USER_USERNAME",
    "USER_PASSWORD",
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
    "BILIBILI_PROXY",
    "HDFS_WEB_URL",
    "HDFS_NAMENODE_URI",
    "HDFS_USER",
    "SPARK_MASTER",
    "DEFAULT_KEYWORD",
    "DEFAULT_TARGET_COUNT",
    "COURSE_DATASET_TARGET",
    "ENABLE_SCHEDULER",
)


def run_config(tmp_path, overrides=None):
    shutil.copy(Path("config.py"), tmp_path / "config.py")
    environment = os.environ.copy()
    for name in CONFIG_ENV_NAMES:
        environment.pop(name, None)
    environment.update(overrides or {})

    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; from config import Config; "
                "print(json.dumps({"
                "'SECRET_KEY': Config.SECRET_KEY, "
                "'ADMIN_USERNAME': Config.ADMIN_USERNAME, "
                "'ADMIN_PASSWORD': Config.ADMIN_PASSWORD, "
                "'USER_USERNAME': Config.USER_USERNAME, "
                "'USER_PASSWORD': Config.USER_PASSWORD, "
                "'MYSQL_HOST': Config.MYSQL_HOST, "
                "'MYSQL_PORT': Config.MYSQL_PORT, "
                "'MYSQL_USER': Config.MYSQL_USER, "
                "'MYSQL_PASSWORD': Config.MYSQL_PASSWORD, "
                "'MYSQL_DATABASE': Config.MYSQL_DATABASE, "
                "'BILIBILI_PROXY': Config.BILIBILI_PROXY, "
                "'HDFS_WEB_URL': Config.HDFS_WEB_URL, "
                "'HDFS_NAMENODE_URI': Config.HDFS_NAMENODE_URI, "
                "'HDFS_USER': Config.HDFS_USER, "
                "'SPARK_MASTER': Config.SPARK_MASTER, "
                "'DEFAULT_KEYWORD': Config.DEFAULT_KEYWORD, "
                "'DEFAULT_TARGET_COUNT': Config.DEFAULT_TARGET_COUNT, "
                "'COURSE_DATASET_TARGET': Config.COURSE_DATASET_TARGET, "
                "'ENABLE_SCHEDULER': Config.ENABLE_SCHEDULER"
                "}, ensure_ascii=False))"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def load_config_values(tmp_path, overrides=None):
    completed = run_config(tmp_path, overrides)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_secret_key_is_required_without_env_file(tmp_path):
    completed = run_config(tmp_path)

    assert completed.returncode != 0
    assert "SECRET_KEY" in completed.stderr


def test_environment_variables_override_classroom_defaults(tmp_path):
    values = load_config_values(
        tmp_path,
        {
            "SECRET_KEY": "teacher-secret",
            "ADMIN_USERNAME": "course-admin",
            "ADMIN_PASSWORD": "admin-config-test-passphrase",
            "USER_USERNAME": "course-user",
            "USER_PASSWORD": "user-config-test-passphrase",
            "MYSQL_PASSWORD": "teacher-password",
            "MYSQL_DATABASE": "teacher_course",
            "BILIBILI_PROXY": "http://127.0.0.1:8899",
            "DEFAULT_TARGET_COUNT": "35",
            "COURSE_DATASET_TARGET": "12000",
            "ENABLE_SCHEDULER": "0",
        },
    )

    assert values["SECRET_KEY"] == "teacher-secret"
    assert values["ADMIN_USERNAME"] == "course-admin"
    assert values["ADMIN_PASSWORD"] == "admin-config-test-passphrase"
    assert values["USER_USERNAME"] == "course-user"
    assert values["USER_PASSWORD"] == "user-config-test-passphrase"
    assert values["MYSQL_HOST"] == "127.0.0.1"
    assert values["MYSQL_PORT"] == 3306
    assert values["MYSQL_USER"] == "root"
    assert values["MYSQL_PASSWORD"] == "teacher-password"
    assert values["MYSQL_DATABASE"] == "teacher_course"
    assert values["HDFS_WEB_URL"] == "http://127.0.0.1:9870"
    assert values["HDFS_NAMENODE_URI"] == "hdfs://127.0.0.1:9000"
    assert values["HDFS_USER"] == "hadoop"
    assert values["SPARK_MASTER"] == "local[*]"
    assert values["DEFAULT_KEYWORD"] == "大数据技术"
    assert values["BILIBILI_PROXY"] == "http://127.0.0.1:8899"
    assert values["DEFAULT_TARGET_COUNT"] == 35
    assert values["COURSE_DATASET_TARGET"] == 12000
    assert values["ENABLE_SCHEDULER"] is False


def test_dotenv_is_loaded_before_config_reads_environment(tmp_path):
    shutil.copy(Path("config.py"), tmp_path / "config.py")
    (tmp_path / ".env").write_text(
        "SECRET_KEY=dotenv-secret\n"
        "MYSQL_PASSWORD=dotenv-password\n"
        "BILIBILI_PROXY=http://127.0.0.1:7890\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    for name in ("SECRET_KEY", "MYSQL_PASSWORD", "BILIBILI_PROXY"):
        environment.pop(name, None)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from config import Config; "
                "print(Config.SECRET_KEY); "
                "print(Config.MYSQL_PASSWORD); "
                "print(Config.BILIBILI_PROXY)"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == [
        "dotenv-secret",
        "dotenv-password",
        "http://127.0.0.1:7890",
    ]


def test_course_dataset_target_defaults_to_10000(monkeypatch):
    monkeypatch.delenv("COURSE_DATASET_TARGET", raising=False)

    from config import Config

    assert Config.COURSE_DATASET_TARGET == 10000
