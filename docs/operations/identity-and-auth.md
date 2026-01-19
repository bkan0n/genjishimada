# Identity & Auth (Keycloak + OAuth2 Proxy)

Genji Shimada uses Keycloak for identity management and oauth2-proxy to protect
internal services (Grafana, Prometheus, etc.) behind the reverse proxy. The
Keycloak stack lives in [`bkan0n/genjishimada-oidc`](https://github.com/bkan0n/genjishimada-oidc), and the reverse proxy routes
Keycloak through `portal.bkan0n.com` and oauth2-proxy through `auth.bkan0n.com`.

This page documents the deployed configuration and how it is wired to the
reverse proxy and monitoring stack.

## How It Fits Together

- **Keycloak** provides OIDC issuer at
  `https://portal.bkan0n.com/realms/master`.
- **oauth2-proxy** uses Keycloak OIDC to gate monitoring endpoints.
- **Caddy** routes `portal.bkan0n.com` -> `keycloak:8080` and
  `auth.bkan0n.com` -> `oauth2-proxy:4180`.
- **Grafana** is configured to use Keycloak (see monitoring docs).

## Deployment (from [genjishimada-oidc](https://github.com/bkan0n/genjishimada-oidc))

Keycloak and oauth2-proxy run in Docker with the following key settings:

**Keycloak**

- `KC_HOSTNAME=portal.bkan0n.com`
- `KC_PROXY_HEADERS=xforwarded`
- `KC_HTTP_ENABLED=true`

**oauth2-proxy**

- `--provider=keycloak-oidc`
- `--client-id=oauth2-proxy`
- `--oidc-issuer-url=https://portal.bkan0n.com/realms/master`
- `--redirect-url=https://auth.bkan0n.com/oauth2/callback`
- `--allowed-group=monitoring`

Secrets are supplied via environment variables and should not be stored in docs:

- `OAUTH2_PROXY_CLIENT_SECRET`
- `OAUTH2_PROXY_COOKIE_SECRET`

## Admin Console Configuration Summary

The current Keycloak realm export (redacted) shows:

- **Realm:** `master`
- **Registration:** disabled
- **Email login:** enabled
- **Required credentials:** password
- **OTP:** TOTP enabled with 30s period and 6 digits
- **Auth flows:** browser, direct grant, and conditional OTP flows enabled

Clients in the realm include built-in admin/account clients and service clients
used by Keycloak itself. The oauth2-proxy client is defined in Keycloak and
relies on OIDC standard scopes.

## Roles and Groups

From the export (master realm):

- **Realm roles**:
    - Built-ins: `offline_access`, `uma_authorization`, `default-roles-master`, `admin`, `create-realm`.
    - Grafana roles: `grafana-admin`, `grafana-editor`, `grafana-viewer` (used by Grafana role mapping).
    - RabbitMQ roles:
        - `rabbitmq.tag:administrator`, `rabbitmq.tag:management`
        - `rabbitmq.configure:*/*/*`, `rabbitmq.write:*/*/*`, `rabbitmq.read:*/*/*`
- **Client roles**: standard roles for `master-realm`, `account`, and `broker`.
- **Groups**:
    - `monitoring` (for Grafana/Prometheus/Loki/cAdvisor access)
    - `RabbitMQ` (grants RabbitMQ tag roles)

If you are using oauth2-proxy group gating (for example `--allowed-group=monitoring`),
make sure a `monitoring` group exists in the realm and that users are assigned to it.

## Clients

The realm includes built-in Keycloak clients plus service clients for internal
apps. The notable custom clients are below:

- **oauth2-proxy**
    - Redirect: `https://auth.bkan0n.com/oauth2/callback`
    - Standard flow enabled, confidential client
    - Default scopes include `groups` so oauth2-proxy can enforce group gating
- **grafana-oauth**
    - Root/Admin URL: `https://grafana.bkan0n.com`
    - Redirect: `https://grafana.bkan0n.com/login/generic_oauth`
    - Protocol mappers: realm roles + hardcoded `aud=grafana-oauth`
- **rabbitmq-prod**
    - Root/Admin URL: `https://rabbitmq.genji.pk`
    - Redirect: `https://rabbitmq.genji.pk/*`
    - Protocol mapper: hardcoded `aud=rabbitmq`
- **rabbitmq-dev**
    - Root/Admin URL: `https://dev-rabbitmq.genji.pk`
    - Redirect: `https://dev-rabbitmq.genji.pk/*`
    - Protocol mapper: hardcoded `aud=rabbitmq`

Built-in clients also exist: `account`, `account-console`, `admin-cli`,
`broker`, `master-realm`, `security-admin-console`.

## Client Scopes and Mappers

- **groups** client scope adds a `groups` claim via
  `oidc-group-membership-mapper` (used by oauth2-proxy).
- **grafana-oauth** uses realm-role mapping and a hardcoded audience claim.
- **rabbitmq** clients include a hardcoded `aud` claim of `rabbitmq`.

## Related Docs

- [Reverse Proxy](reverse-proxy.md) - Caddy routes and auth wiring
- [Monitoring](monitoring.md) - Grafana OAuth config
