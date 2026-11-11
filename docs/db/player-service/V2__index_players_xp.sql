-- GET /players/{id}/rank counts the players at or below a player's XP (countByXpLessThanEqual);
-- without an index that scans the whole players table on every request.
CREATE INDEX idx_players_xp ON players (xp);
