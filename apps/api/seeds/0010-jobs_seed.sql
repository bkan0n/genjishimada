-- Jobs seed data for testing internal job endpoints

-- =============================================================================
-- JOB STATUS RECORDS
-- =============================================================================

-- Queued job
INSERT INTO public.jobs (id, action, status, error_code, error_msg)
VALUES
  ('550e8400-e29b-41d4-a716-446655440001', 'test_action', 'queued', NULL, NULL);

-- Succeeded job
INSERT INTO public.jobs (id, action, status, error_code, error_msg, started_at, finished_at)
VALUES
  ('550e8400-e29b-41d4-a716-446655440002', 'completion_verification', 'succeeded', NULL, NULL, now() - interval '5 minutes', now() - interval '4 minutes');

-- Failed job with error
INSERT INTO public.jobs (id, action, status, error_code, error_msg, started_at, finished_at, attempts)
VALUES
  ('550e8400-e29b-41d4-a716-446655440003', 'notification_delivery', 'failed', 'DELIVERY_ERROR', 'Something went wrong during processing', now() - interval '10 minutes', now() - interval '9 minutes', 3);

-- =============================================================================
-- IDEMPOTENCY CLAIMS
-- =============================================================================

-- Pre-existing claim (for duplicate claim tests)
INSERT INTO public.processed_messages (idempotency_key)
VALUES
  ('existing-claim-key-123'),
  ('another-existing-key-456');
