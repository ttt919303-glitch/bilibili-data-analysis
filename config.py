import os

from dotenv import load_dotenv


load_dotenv()


class Config:
    SECRET_KEY = os.environ["SECRET_KEY"]
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
    USER_USERNAME = os.getenv("USER_USERNAME")
    USER_PASSWORD = os.getenv("USER_PASSWORD")
    MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    # 本机 MySQL 密码非空时，可修改默认值或设置 MYSQL_PASSWORD 环境变量。
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "bigdata_course")
    BILIBILI_PROXY = os.getenv("BILIBILI_PROXY")
    HDFS_WEB_URL = os.getenv("HDFS_WEB_URL", "http://127.0.0.1:9870")
    HDFS_NAMENODE_URI = os.getenv("HDFS_NAMENODE_URI", "hdfs://127.0.0.1:9000")
    HDFS_USER = os.getenv("HDFS_USER", "hadoop")
    SPARK_MASTER = os.getenv("SPARK_MASTER", "local[*]")
    DEFAULT_KEYWORD = os.getenv("DEFAULT_KEYWORD", "大数据技术")
    DEFAULT_TARGET_COUNT = int(os.getenv("DEFAULT_TARGET_COUNT", "20"))
    COURSE_DATASET_TARGET = int(os.getenv("COURSE_DATASET_TARGET", "10000"))
    ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "1") == "1"
