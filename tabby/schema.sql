CREATE DATABASE tabby;

CREATE TABLE tabby.levels (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    total_xp BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE VIEW tabby.leaderboard AS
SELECT
    guild_id,
    user_id,
    rank() OVER most_xp AS position,
    total_xp
FROM tabby.levels
WINDOW most_xp AS (PARTITION BY guild_id ORDER BY total_xp DESC)
ORDER BY guild_id, user_id DESC;

CREATE TABLE tabby.autoroles (
    guild_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    granted_at INT NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);
