CREATE USER hendawi WITH PASSWORD '';
CREATE DATABASE telegram_bot OWNER hendawi ENCODING 'UTF8';


\c telegram_bot


DROP TABLE IF EXISTS user_keywords;
DROP TABLE IF EXISTS keywords;
DROP TABLE IF EXISTS user_channels;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS channels;
DROP TABLE IF EXISTS users;


CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    expiry_date TIMESTAMP
);

CREATE TABLE channels (
    channel_id BIGINT PRIMARY KEY,
    channel_username VARCHAR(255) UNIQUE NOT NULL,
    channel_name VARCHAR(255) NOT NULL
);

CREATE TABLE user_channels (
    user_id BIGINT REFERENCES users(user_id),
    channel_id BIGINT REFERENCES channels(channel_id),
    priority INTEGER NOT NULL DEFAULT 1,
    add_date TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, channel_id)
);

CREATE TABLE keywords (
    keyword_id SERIAL PRIMARY KEY,
    channel_id BIGINT REFERENCES channels(channel_id),
    keyword_text VARCHAR(255) NOT NULL,
    UNIQUE (channel_id, keyword_text)
);

CREATE TABLE user_keywords (
    user_id BIGINT REFERENCES users(user_id),
    keyword_id INTEGER REFERENCES keywords(keyword_id),
    target_channel VARCHAR(255) NOT NULL,
    PRIMARY KEY (user_id, keyword_id)
);

CREATE TABLE payments (
    payment_id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    amount INTEGER NOT NULL,
    currency VARCHAR(3) NOT NULL, 
    payment_date TIMESTAMP NOT NULL DEFAULT NOW(),
    payer_username VARCHAR(255) NOT NULL
);


CREATE INDEX idx_user_channels ON user_channels(user_id);
CREATE INDEX idx_keywords_search ON keywords USING gin(keyword_text gin_trgm_ops);
CREATE INDEX idx_user_keywords ON user_keywords(user_id);
CREATE INDEX idx_payments_date ON payments(payment_date);
CREATE INDEX CONCURRENTLY idx_users_expiry ON users(expiry_date);
CREATE INDEX CONCURRENTLY idx_users_username ON users(username);
CREATE INDEX CONCURRENTLY idx_channels_username ON channels USING HASH (channel_username);
CREATE INDEX CONCURRENTLY idx_user_channels_composite ON user_channels(user_id, channel_id);
CREATE INDEX CONCURRENTLY idx_keywords_channel_text ON keywords(channel_id, keyword_text);
CREATE INDEX CONCURRENTLY idx_user_keywords_composite ON user_keywords(user_id, keyword_id);
CREATE INDEX CONCURRENTLY idx_payments_user_date ON payments(user_id, payment_date);
ALTER TABLE users 
ADD COLUMN invited INTEGER DEFAULT 0 NOT NULL;



GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO hendawi;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hendawi;
ALTER TABLE users OWNER TO hendawi;
ALTER TABLE channels OWNER TO hendawi;
ALTER TABLE user_channels OWNER TO hendawi;
ALTER TABLE keywords OWNER TO hendawi;
ALTER TABLE user_keywords OWNER TO hendawi;
ALTER TABLE payments OWNER TO hendawi;
