# Deploying Tunnelgate

A reference deployment for a homelab: Tunnelgate runs as a single container on an internal host, behind an
internal reverse proxy, and signs users in through an OIDC provider. The examples use
[SWAG](https://docs.linuxserver.io/general/swag/) and [Authelia](https://www.authelia.com/); any reverse
proxy and any OIDC provider that meets the [requirements](#oidc-provider) work the same way.

```text
phone / laptop (LAN or VPN)
        │ https://tunnelgate.int.example.com
        ▼
internal reverse proxy (SWAG) ──── "tunnelgate" Docker network ────► tunnelgate:8000
                                                                       │        │
                                       OIDC login (internal DNS) ◄─────┘        └────► api.cloudflare.com
                                       https://auth.example.com
```

Tunnelgate must **not** be reachable from the internet: it holds a Cloudflare token that can expose or
block every route. Keep it internal, and do not publish it through one of the tunnels it manages.

| File                                                               | Goes to                                                   |
| ------------------------------------------------------------------ | --------------------------------------------------------- |
| [`compose.yaml`](compose.yaml)                                     | Your compose stack on the internal host.                  |
| [`swag/tunnelgate.subdomain.conf`](swag/tunnelgate.subdomain.conf) | The internal SWAG instance, `/config/nginx/proxy-confs/`. |
| [`authelia/oidc-client.yml`](authelia/oidc-client.yml)             | Merged into Authelia's `configuration.yml`.               |
| [`../.env.example`](../.env.example)                               | Copied to `tunnelgate.env` next to `compose.yaml`.        |

## 1. Cloudflare API token

Create an account API token with the permissions listed in the main
[README](../README.md#requirements), scoped to the zones Tunnelgate should manage. Tunnels must be
remotely managed (created in the dashboard and run with a token); locally managed tunnels are shown
read-only.

## 2. OIDC provider

Skip this step to use [password mode](../README.md#password-mode) instead: set `BASIC_AUTH_USERNAME`
and `BASIC_AUTH_PASSWORD_HASH` (from `tunnelgate hash-password`) and leave the `OIDC_*` variables and
`ALLOWED_GROUPS` unset.

### Requirements

- Authorization code flow with **PKCE (S256)** and a confidential client (`client_secret_basic`).
- Redirect URI: `<APP_URL>/auth/callback`.
- Scopes `openid profile email groups`, with the user's groups in the `groups` claim (ID token or userinfo).
- The `amr` claim, when `OIDC_REQUIRE_MFA=true` (the default), so Tunnelgate can check for MFA.

Group membership is enforced by Tunnelgate (`ALLOWED_GROUPS`), so the provider only needs a generic
"two factor" policy for the client; there is no group list to keep in sync in two places.

### Authelia

1. Generate the client secret:

   ```sh
   docker run --rm ghcr.io/authelia/authelia:latest \
     authelia crypto hash generate pbkdf2 --variant sha512 --random --random.length 128
   ```

   The **random password** goes into `OIDC_CLIENT_SECRET`; the **digest** goes into the client definition.

2. Merge [`authelia/oidc-client.yml`](authelia/oidc-client.yml) into `configuration.yml`, replacing the
   digest and the redirect URI, and restart Authelia.
3. With Active Directory and nested groups, use the matching-rule-in-chain group filter shown at the end
   of that file.

## 3. Environment

Copy [`../.env.example`](../.env.example) to `tunnelgate.env` next to `compose.yaml` and fill it in
(`chmod 600`). At minimum: `CF_API_TOKEN`, `CF_ACCOUNT_ID`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`,
`OIDC_CLIENT_SECRET`, `APP_URL` and `ALLOWED_GROUPS` (or, in password mode, `BASIC_AUTH_USERNAME` and
`BASIC_AUTH_PASSWORD_HASH` instead of the OIDC variables). Setting `SERVICE_ALLOWLIST` is strongly
recommended, so cloned routes can only point at services you expect. Leave `SESSION_SECRET` unset.

## 4. Container

[`compose.yaml`](compose.yaml) runs the image read-only, without capabilities, as UID 10001, with no
published ports, and keeps an SQLite file (audit log and config snapshots) in the `tunnelgate-data` volume.

```sh
docker compose up -d
docker compose exec tunnelgate tunnelgate status   # lists tunnels and routes using the token
```

- Set `dns:` to a resolver that answers the OIDC issuer's **internal** address (split DNS).
- Allow outbound HTTPS to the issuer and to `api.cloudflare.com` in your firewall.
- `pids_limit`, `mem_limit` and `cpus` need cgroup delegation. In an unprivileged Proxmox LXC without it,
  the container fails to start with `pids.max: no such file or directory`; remove those three lines there.

To verify a published image before running it, see the main [README](../README.md).

## 5. Reverse proxy

1. Attach the proxy container to the `tunnelgate` network (as an external network in its own compose
   file), so it can reach `tunnelgate:8000` by name.
2. Copy [`swag/tunnelgate.subdomain.conf`](swag/tunnelgate.subdomain.conf) to
   `/config/nginx/proxy-confs/` and reload SWAG. It serves `tunnelgate.int.*` with SWAG's certificate.
3. Optional: uncomment the two `authelia-*.conf` includes to add Authelia forward auth in front of the
   app's own login (defense in depth). The Authelia session cookie must then cover both hostnames.

## 6. First run

1. Open `APP_URL`, sign in, and check that a user outside `ALLOWED_GROUPS` (or without MFA) gets the
   _Access denied_ page.
2. Block a **non-critical** route, then open it from outside your network (mobile data): Cloudflare must
   answer with its block page. Try a mixed-case host too (`https://Some.Example.com`).
3. Unblock it, clone a route (it is created blocked), remove the clone, and try _Undo_ on that tunnel.
4. Install the PWA on your phone (browser menu → _Add to home screen_).

## Break-glass

If the identity provider or DNS is down, block everything from the host:

```sh
docker compose exec tunnelgate tunnelgate block-all
docker compose exec tunnelgate tunnelgate unblock-all   # CLI only; the UI has no "unblock all"
```

## Updating

The image is rebuilt monthly and on every release. Pull and restart:

```sh
docker compose pull && docker compose up -d
```

A restart signs everyone out (the session key is generated at every start).
