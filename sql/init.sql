CREATE DATABASE IF NOT EXISTS bigdata_course DEFAULT CHARACTER SET utf8mb4;
USE bigdata_course;

CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role ENUM('admin', 'user') NOT NULL
);

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
);
