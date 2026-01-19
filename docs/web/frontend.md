# Frontend Build

The frontend is built with Vite, Tailwind CSS v4, and page-specific bundles.

## Vite Inputs

`vite.config.js` defines the bundles:
- Core: `resources/css/app.css`, `resources/js/app.js`.
- Page bundles: `resources/js/pages/*.js` (index, leaderboard, newsfeed, statistics, tutorials, search, rank_card, convertor, lootbox, submit, game, moderator, dashboard, infos, prism).

## Tailwind Theme

`tailwind.config.js`:
- Dark mode via `class`.
- Brand palette in `theme.extend.colors.brand`.
- Custom `glow`/`soft` shadows and a `loading` animation.

## App Bootstrap

`resources/js/app.js`:
- Imports global CSS and UI modules (modals, notifications tray).
- Initializes Sentry on the client, using Vite-provided DSN + environment.
- Adds a CSRF header patch for `fetch()` on non-GET requests.
- Lazy-loads Prism when the page needs it.

## Assets And Views

- Blade templates live under `resources/views/`.
- Page-specific JS runs alongside Blade views and API endpoints.
- `public/build` is generated at build time and served by Unit with immutable cache headers.
