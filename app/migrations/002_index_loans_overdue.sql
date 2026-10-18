-- Partial index for fast lookup and ordering of overdue open loans.
CREATE INDEX idx_loans_overdue ON loans (due_on) WHERE returned_at IS NULL;
