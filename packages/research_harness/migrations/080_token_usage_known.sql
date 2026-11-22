-- Distinguish provider-reported zero tokens from unavailable token counts.
ALTER TABLE token_ledger ADD COLUMN prompt_tokens_known INTEGER NOT NULL DEFAULT 1
    CHECK (prompt_tokens_known IN (0, 1));
ALTER TABLE token_ledger ADD COLUMN completion_tokens_known INTEGER NOT NULL DEFAULT 1
    CHECK (completion_tokens_known IN (0, 1));
