-- noinspection SpellCheckingInspectionForFile

INSERT INTO public.auth_users (
    username, info
)
VALUES (
    'testing', 'testing'
);

INSERT INTO public.api_tokens (
    user_id, api_key, is_superuser
)
VALUES (
    1, 'testing', TRUE
);
