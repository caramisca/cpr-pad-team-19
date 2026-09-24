CREATE TABLE players (
    id UUID PRIMARY KEY,
    discord_id VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    rank VARCHAR(255) NOT NULL,
    xp INTEGER NOT NULL,
    level INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE player_stats (
    player_id UUID PRIMARY KEY REFERENCES players (id),
    total_shifts INTEGER NOT NULL,
    correct_decisions INTEGER NOT NULL,
    incorrect_decisions INTEGER NOT NULL,
    last_shift_at TIMESTAMPTZ
);

CREATE TABLE processed_events (
    event_id UUID PRIMARY KEY,
    event_type VARCHAR(255) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL
);
