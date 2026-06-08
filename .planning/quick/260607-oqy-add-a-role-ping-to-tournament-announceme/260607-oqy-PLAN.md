---
phase: quick-260607-oqy
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - apps/bot/configs/dev.toml
  - apps/bot/configs/prod.toml
  - apps/bot/utilities/config.py
  - apps/bot/extensions/tournaments.py
  - apps/bot/extensions/information_pages.py
autonomous: true
requirements:
  - QUICK-260607-oqy

must_haves:
  truths:
    - "Both tournament announcements (edition rollover card AND deferred results card) ping the tournament announcement role"
    - "The role ping actually fires (the role mention is delivered, not suppressed by allowed_mentions)"
    - "The tournament announcement role ID is configured in dev.toml and prod.toml and decoded by the msgspec config struct"
    - "The mod-only Accept/Reject verification card is NOT changed (it is not a public announcement)"
    - "Users can self-assign/remove the tournament announcement role from the #role-react view (ServerRoleSelectView) using the same toggle-button mechanism as the other announcement-ping roles"
    - "The role-react entry references the SAME tournament_announcements config field (single source of truth, no duplicated snowflake)"
    - "When tournament_announcements is the 0 sentinel (unconfigured), the role-react toggle button is NOT registered (avoids the _set_guild_and_role assert on get_role(0))"
  artifacts:
    - path: "apps/bot/utilities/config.py"
      provides: "tournament_announcements role field on the msgspec config struct"
      contains: "tournament_announcements"
    - path: "apps/bot/configs/dev.toml"
      provides: "tournament announcement role ID (dev)"
      contains: "tournament_announcements"
    - path: "apps/bot/configs/prod.toml"
      provides: "tournament announcement role ID (prod)"
      contains: "tournament_announcements"
    - path: "apps/bot/extensions/tournaments.py"
      provides: "role-ping content + allowed_mentions on both announcement sends"
    - path: "apps/bot/extensions/information_pages.py"
      provides: "self-assignable Tournament Announcements toggle button in ServerRoleSelectView (#role-react view)"
      contains: "tournament_announcements"
  key_links:
    - from: "apps/bot/extensions/tournaments.py"
      to: "bot.config.roles.mentionable.tournament_announcements"
      via: "ui.TextDisplay role mention + AllowedMentions roles allow-list"
      pattern: "tournament_announcements"
    - from: "apps/bot/extensions/information_pages.py"
      to: "bot.config.roles.mentionable.tournament_announcements"
      via: "ServerRoleToggleButton in ServerRoleSelectView 'Announcement Pings' ActionRow"
      pattern: "tournament_announcements"
---

<objective>
Add a pingable tournament announcement role to ALL tournament announcement
messages posted by the bot.

A new config value `tournament_announcements` is added under `[roles.mentionable]`
in both `dev.toml` and `prod.toml` and to the `Mentionable` msgspec struct, mirroring
the existing `general_announcements` pingable announcement role. Both tournament
announcement send sites (the edition-rollover card and the deferred-results card)
include the role mention in their content and configure `allowed_mentions` so the
ping fires.

The SAME `tournament_announcements` role is also made self-assignable from the
`#role-react` view (`ServerRoleSelectView` in apps/bot/extensions/information_pages.py)
by adding a `ServerRoleToggleButton` to the existing "Announcement Pings" ActionRow,
mirroring the General Announcements / Patch Notes toggle buttons. This lets users
opt in/out of the ping themselves.

Purpose: Notify the tournament announcement role whenever a tournament rotation
starts, ends, or its deferred results are published, and let members self-assign
that role from the role-react picker.
Output: Updated TOML configs, config struct, the tournaments bot extension, and the
role-react view (ServerRoleSelectView).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@CLAUDE.md

<interfaces>
<!-- Config struct — apps/bot/utilities/config.py -->
<!-- `Mentionable` holds pingable role IDs; `Roles.mentionable` exposes it as
     bot.config.roles.mentionable.<field>. forbid_unknown_fields=True means the TOML
     keys and struct fields MUST match exactly. -->

class Mentionable(Base):  # apps/bot/utilities/config.py
    general_announcements: int
    website_patch_notes: int
    framework_patch_notes: int
    modmail: int

class Roles(Base):
    mentionable: Mentionable
    ...

# Access in the bot: self.bot.config.roles.mentionable.general_announcements

<!-- Tournament announcement send sites — apps/bot/extensions/tournaments.py -->
<!-- Both are CV2 LayoutView sends. A LayoutView send overload accepts NO `content`
     kwarg (MEMORY.md cv2-layoutview-no-content), so the role ping text must live
     INSIDE a ui.TextDisplay added to the container, and the role must be on the
     AllowedMentions allow-list for the ping to fire. -->

# Site 1 — _on_edition_rollover (around line 460):
await self.announcement_channel.send(
    view=view,
    allowed_mentions=discord.AllowedMentions(users=allowed_users, everyone=False, roles=False),
)

# Site 2 — _on_edition_results (around line 575):
await self.announcement_channel.send(
    view=view,
    allowed_mentions=discord.AllowedMentions(users=allowed_users, everyone=False, roles=False),
)

<!-- A Discord role mention is the literal string "<@&ROLE_ID>". To make it ping, the
     role must be permitted by AllowedMentions, e.g. roles=[discord.Object(id=ROLE_ID)]. -->
<!-- DO NOT change the mod Accept/Reject card send (_on_completion_created, ~line 606):
     it is a mod-only verification card, NOT a public announcement. -->

<!-- Role-react view — apps/bot/extensions/information_pages.py -->
<!-- The #role-react picker is `ServerRoleSelectView` (apps/bot/extensions/information_pages.py,
     class at line 429). Its `rebuild_components()` (line 436) builds `container = ui.Container(...)`
     containing several `ui.ActionRow(...)` of self-assignable role buttons.
     Each self-assignable role is one `ServerRoleToggleButton` (class at line 385):
         ServerRoleToggleButton(bot=self.bot, label="...", role_id=<config int>, emoji="...")
     - role_id ALWAYS comes from `self.bot.config.roles.mentionable.<field>` /
       `...roles.location.<field>` / `...roles.platform.<field>` — never a hardcoded snowflake.
     - emoji is OPTIONAL (Announcement Pings + Regions omit it; Platform uses 🎮/⌨️).
     - Toggle mechanism is `ServerRoleToggleButton.add_remove_roles` (line 411): adds the role if
       absent, removes it if present.
     - The "Announcement Pings" section is the FIRST ActionRow (lines 442-459) and already holds:
         General Announcements -> mentionable.general_announcements
         Framework Patch Notes -> mentionable.framework_patch_notes
         Website/Bot Patch Notes -> mentionable.website_patch_notes
       The tournament toggle belongs in THIS section.

     SENTINEL GUARD (important): `ServerRoleToggleButton._set_guild_and_role` (line 402) does
     `_role = _guild.get_role(self.role_id); assert _role`. With the `0` placeholder,
     `get_role(0)` returns None and the assert fails on click. The buttons in this section are
     declared inline inside the `ui.ActionRow(...)` literal, which cannot conditionally drop a
     child. So when `tournament_announcements == 0` the Tournament Announcements button must NOT
     be added — build the "Announcement Pings" ActionRow's children as a list, append the
     Tournament Announcements button only if the role id is truthy, then splat into ui.ActionRow.
     A button row may hold up to 5 buttons, so adding a 4th is fine. -->

<!-- ServerRoleSelectView is a persistent view registered in setup() (line 544):
     `bot.add_view(ServerRoleSelectView(bot))`. Building children conditionally in
     rebuild_components keeps the persistent-view registration unchanged. -->
</interfaces>

<dev.toml current — apps/bot/configs/dev.toml>
[roles.mentionable]
general_announcements = 1377808368978235404
website_patch_notes = 1377808368978235405
framework_patch_notes = 1377808368978235406
modmail = 1377808368978235402
</dev.toml>

<prod.toml current — apps/bot/configs/prod.toml>
[roles.mentionable]
general_announcements = 1073292414271356938
website_patch_notes = 1328055776358563990
framework_patch_notes = 1073292274877878314
modmail = 1120076555293569081
</prod.toml>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add tournament_announcements role to config struct and TOML files</name>
  <files>apps/bot/utilities/config.py, apps/bot/configs/dev.toml, apps/bot/configs/prod.toml</files>
  <action>
Add a `tournament_announcements: int` field to the `Mentionable` struct in
apps/bot/utilities/config.py, immediately after `general_announcements` (keep it
grouped with the other pingable announcement roles; field order is cosmetic but match
the TOML order). The struct uses `forbid_unknown_fields=True`, so the TOML key name
MUST be exactly `tournament_announcements`.

In apps/bot/configs/dev.toml under `[roles.mentionable]`, add a `tournament_announcements`
key. Use a placeholder value of `0` (the real dev role ID is supplied by the maintainer
later — do NOT invent a snowflake; `0` is the explicit "needs configuring" sentinel and
will simply not resolve to a real role until set). Add it immediately after
`general_announcements`.

In apps/bot/configs/prod.toml under `[roles.mentionable]`, add the same
`tournament_announcements` key with placeholder value `0`, immediately after
`general_announcements`.

Leave a brief inline comment on each TOML line noting it must be replaced with the real
tournament announcement role ID before deploy (mirror existing TOML style — no comment
clutter; a short `# TODO: real tournament announcement role ID` is sufficient).
  </action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && uv run python -c "from pathlib import Path; import sys; sys.path.insert(0, 'apps/bot'); from utilities.config import decode; c=decode(Path('apps/bot/configs/dev.toml').read_text()); assert hasattr(c.roles.mentionable, 'tournament_announcements'), 'dev missing field'; c2=decode(Path('apps/bot/configs/prod.toml').read_text()); assert hasattr(c2.roles.mentionable, 'tournament_announcements'), 'prod missing field'; print('OK both configs decode with tournament_announcements')"</automated>
  </verify>
  <done>Both dev.toml and prod.toml decode cleanly via `config.decode` (forbid_unknown_fields passes) and expose `roles.mentionable.tournament_announcements`.</done>
</task>

<task type="auto">
  <name>Task 2: Ping the tournament role on both announcement sends</name>
  <files>apps/bot/extensions/tournaments.py</files>
  <action>
Add the tournament announcement role ping to BOTH public announcement send sites:
`_on_edition_rollover` (the combined rollover card) and `_on_edition_results` (the
deferred results card). Do NOT touch `_on_completion_created` (mod-only verification
card) or the `TournamentVerificationView` send.

For each of the two sites:

1. Read the role id once into a local from `self.bot.config.roles.mentionable.tournament_announcements`.
   Because a CV2 LayoutView `send` accepts no `content` kwarg, the role mention must be
   rendered INSIDE the card: add a `ui.TextDisplay` containing the literal role mention
   string `<@&{role_id}>` to the container. Place it as the FIRST item in the container
   (before the title TextDisplay) so the ping line reads at the top of the announcement —
   match the existing container-building style (use `container.add_item(...)` if the
   container is built incrementally, or include it in the initial `ui.Container(...)`
   construction; both sites build `container = ui.Container(...)` then `add_item` more,
   so prepend by constructing the ping TextDisplay first). Guard against an unconfigured
   role: if `role_id` is falsy (0, the placeholder sentinel), skip adding the ping line
   and skip allowing the role mention, so an unconfigured role never renders a broken
   `<@&0>` mention.

2. Update the `allowed_mentions` on that send so the role ping actually fires: change
   `roles=False` to `roles=[discord.Object(id=role_id)]` when the role is configured,
   keeping the existing `users=allowed_users` winner allow-list and `everyone=False`.
   When the role is unconfigured (falsy), leave `roles=False`. The cleanest form is to
   build a `roles=` value (`[discord.Object(id=role_id)]` if role_id else `False`) into
   a local and pass it to `discord.AllowedMentions(...)`.

Keep the existing winner-mention security behavior intact: `users=allowed_users`,
`everyone=False`, numeric-id-only winner pings. Only the role allow-list is added.
  </action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && grep -v '^\s*#' apps/bot/extensions/tournaments.py | grep -c 'tournament_announcements' | { read n; test "$n" -ge 2 && echo "OK: $n role-ping references (both sends)"; } && just lint-bot</automated>
  </verify>
  <done>Both `_on_edition_rollover` and `_on_edition_results` add a `<@&{role_id}>` TextDisplay to the card and pass `roles=[discord.Object(id=role_id)]` in `allowed_mentions` (falling back to `roles=False` when the role id is 0). `just lint-bot` passes (Ruff + BasedPyright). `_on_completion_created` is unchanged.</done>
</task>

<task type="auto">
  <name>Task 3: Add a self-assignable Tournament Announcements toggle to the #role-react view</name>
  <files>apps/bot/extensions/information_pages.py</files>
  <action>
Make the same `tournament_announcements` role self-assignable from the `#role-react`
picker by adding a `ServerRoleToggleButton` to `ServerRoleSelectView.rebuild_components`
(apps/bot/extensions/information_pages.py, method at line 436). The button MUST reference
the SAME config field — `self.bot.config.roles.mentionable.tournament_announcements` — so
the role id stays a single source of truth (no new/duplicate snowflake).

Place it in the existing "Announcement Pings" section (the first `ui.ActionRow` inside the
`container = ui.Container(...)`, lines 443-459, currently holding General Announcements,
Framework Patch Notes, Website/Bot Patch Notes). Mirror those entries exactly:
  ServerRoleToggleButton(
      bot=self.bot,
      label="Tournament Announcements",
      role_id=self.bot.config.roles.mentionable.tournament_announcements,
      emoji="🏆",
  )
Use label "Tournament Announcements" (matches the existing "<Topic> Announcements" /
"<Topic> Patch Notes" wording in this row) and a fitting emoji. The other Announcement
Pings buttons pass no emoji, but Platform buttons do (🎮/⌨️); a 🏆 trophy emoji is a
reasonable, consistent choice for a tournament toggle. If you prefer matching the
emoji-less Announcement Pings buttons, omit `emoji=` entirely — either is acceptable, but
keep it consistent with the section.

SENTINEL GUARD: the placeholder role id is `0`. `ServerRoleToggleButton._set_guild_and_role`
(line 402) asserts `get_role(self.role_id)` is truthy, so a button with role_id=0 would
crash on click. Because the section's buttons are declared inline inside the
`ui.ActionRow(...)` literal (which cannot conditionally drop a child), refactor the
"Announcement Pings" ActionRow to build its buttons as a list first, conditionally append
the Tournament Announcements button only when
`self.bot.config.roles.mentionable.tournament_announcements` is truthy, then splat the list
into `ui.ActionRow(*buttons)`. This keeps the button absent (not broken) while the role is
the `0` sentinel, consistent with the sentinel-guard approach used at the send sites in
Task 2. (A button row supports up to 5 buttons; 4 is fine.)

Do not alter the Regions/Platform sections, the `ServerRoleToggleButton` class, the
persistent-view registration in `setup()` (line 544), or any other view in the file.
  </action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && grep -v '^\s*#' apps/bot/extensions/information_pages.py | grep -q 'mentionable.tournament_announcements' && echo "OK: role-react references tournament_announcements config field" && just lint-bot</automated>
  </verify>
  <done>`ServerRoleSelectView.rebuild_components` registers a "Tournament Announcements" `ServerRoleToggleButton` in the "Announcement Pings" ActionRow, sourcing its id from `self.bot.config.roles.mentionable.tournament_announcements` (no duplicate snowflake), conditionally added so it is skipped when the id is the `0` sentinel. `just lint-bot` passes. No other view or section is changed.</done>
</task>

</tasks>

<verification>
- `config.decode` succeeds for both dev.toml and prod.toml with the new field.
- `just lint-bot` passes (format, lint, type-check).
- Both announcement send sites reference `tournament_announcements` and set a role allow-list.
- The role-react view (`ServerRoleSelectView`) references `mentionable.tournament_announcements` and adds a toggle button in the "Announcement Pings" section, skipping it when the id is the `0` sentinel.
- The mod verification card send is byte-for-byte unchanged.
</verification>

<success_criteria>
- A `tournament_announcements` role ID is configurable in both TOML files and decoded by the config struct.
- The edition-rollover announcement and the deferred-results announcement both render and fire a ping for the tournament announcement role.
- Members can self-assign/remove the tournament announcement role from the `#role-react` picker, using the same `tournament_announcements` config field (no duplicate snowflake).
- No change to the mod-only Accept/Reject verification card.
- Lint and type checks pass.
</success_criteria>

<output>
Create `.planning/quick/260607-oqy-add-a-role-ping-to-tournament-announceme/260607-oqy-SUMMARY.md` when done
</output>
