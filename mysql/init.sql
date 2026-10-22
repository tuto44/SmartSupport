ALTER DATABASE smartsupport CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

USE smartsupport;

CREATE TABLE IF NOT EXISTS conversations (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    user_name VARCHAR(255) NOT NULL,
    title VARCHAR(255) DEFAULT 'Nueva conversación',
    root_issue TEXT NULL,
    last_context MEDIUMTEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS chat_history (
    id BIGINT AUTO_INCREMENT NOT NULL,
    conversation_id VARCHAR(64) NOT NULL,
    user_name VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_conversation (conversation_id),
    CONSTRAINT fk_chat_history_conversation
        FOREIGN KEY (conversation_id)
        REFERENCES conversations(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;