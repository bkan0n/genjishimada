# Backend Application

The backend is a Laravel app with route groups split between Blade pages and JSON API endpoints.

## Web Routes

`routes/web.php` defines the public and authenticated pages:
- Public pages: home, newsfeed, leaderboard, statistics, tutorials, search, convertor, game, infos.
- Authenticated pages: rank card, submit, dashboard.
- Moderator page: guarded by the Discord moderator middleware.
- Email auth flows and Discord OAuth callbacks.

## API Routes

`routes/api.php` groups endpoints by feature:
- Community stats and leaderboards.
- Maps, playtests, guides, and map edit requests.
- Completions and rank cards.
- Lootbox actions.
- Newsfeed and translation endpoints.
- Moderator utilities and cache controls.
- Notifications and preferences.
- Sentry tunnel endpoint (`/api/_/e`).

## Controller Layout

Controllers are organized by domain:
- `Community`, `Completions`, `Maps`, `Lootbox`, `Newsfeed`, `Users`, `Utilities`, `Notifications`, and `Mods`.

## Middleware And Session Behavior

Key middleware:
- `RememberTokenAuth` - Rehydrates sessions from a remember token cookie.
- `RequireDiscordModerator` - Gates moderator routes based on Discord roles.
- `DetectLanguage` - Sets locale based on query, cookie, or session.
- `SentryUserContext` - Tags requests with user context.

Sessions use the custom `api` driver (`config/session.php`), backed by `App\Extensions\ApiSessionHandler` and the Genji API. This keeps user sessions and moderation flags in sync with other services.
