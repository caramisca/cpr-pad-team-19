-- Lab 5, Grade 8: a shift closed through the two-phase commit (CPR contracts/two-phase.md) remembers
-- the transaction that closed it. Its commit (any instance, any time after the prepare) finds the
-- shift by this ID to announce the close, and a repeated commit sees it was already applied.
-- Null for a shift closed without it (SHIFT_CLOSE_MODE=event) or still open.
ALTER TABLE sessions ADD COLUMN close_transaction_id UUID;
CREATE UNIQUE INDEX uq_sessions_close_transaction_id ON sessions (close_transaction_id);
