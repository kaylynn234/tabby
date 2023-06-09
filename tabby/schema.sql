CREATE SCHEMA IF NOT EXISTS tabby;

CREATE TABLE IF NOT EXISTS tabby.levels (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    total_xp BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE OR REPLACE VIEW tabby.leaderboard AS
SELECT
    guild_id,
    user_id,
    row_number() OVER most_xp AS leaderboard_position,
    total_xp
FROM tabby.levels
WINDOW most_xp AS (PARTITION BY guild_id ORDER BY total_xp DESC)
ORDER BY guild_id, total_xp DESC;

CREATE OR REPLACE VIEW tabby.user_count AS
SELECT guild_id, COUNT(*) AS total_users
FROM tabby.levels
GROUP BY guild_id;

CREATE TABLE IF NOT EXISTS tabby.autoroles (
    guild_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    granted_at INT NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS tabby.guild_options (
    guild_id BIGINT PRIMARY KEY,
    stack_autoroles BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS tabby.user_accounts (
    user_id BIGINT PRIMARY KEY,
    -- `account_info` is the encrypted JSON payload, containing an access token and refresh token.
    account_info BYTEA NOT NULL
);
