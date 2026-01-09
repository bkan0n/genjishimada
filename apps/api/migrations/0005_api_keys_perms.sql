-- Add scope columns to api_tokens table
ALTER TABLE public.api_tokens
    ADD COLUMN is_superuser boolean DEFAULT FALSE,
    ADD COLUMN scopes       text[]  DEFAULT '{}';
