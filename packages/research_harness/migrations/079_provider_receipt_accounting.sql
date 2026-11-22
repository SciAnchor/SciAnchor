-- Bind exact provider receipts to existing token-ledger idempotency rows.
ALTER TABLE token_ledger ADD COLUMN provider_receipt_sha256 TEXT;
