# Localization And Translations

The website ships with built-in localization support and a workflow for updating translation files.

## Language Configuration

- `config/gp.php` defines available languages and a default (`en`).
- Each language entry includes display name, flag, and whether it is fully translated.

## Translation Sources

- `resources/lang/` holds PHP translation files per locale.
- `resources/translations/` contains JSON assets used by the client-side pages.
- The `DetectLanguage` middleware resolves locale based on `?lang=`, cookie, or session.

## Client-Side Translation Files

- Pages like convertor and search read JSON from `public/translations/*`.
- The convertor page can compile translation JSON via `/api/compile`.

## Moderator Cache Tools

- Moderator UI includes controls for clearing translation caches.
- The API endpoint for cache clearing is `DELETE /api/mods/cache/translations`.
