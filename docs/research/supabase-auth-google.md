# Supabase Auth + "sign in with Google" — the mechanics a UI decision hangs on

**Researched 2026-08-24.** Every claim below is from a primary source: Supabase's own
docs (`supabase.com/docs`, `supabase.com/pricing`), Supabase's own source repositories
(`github.com/supabase/auth-js`, `github.com/supabase/ssr`, `github.com/supabase/auth`,
`github.com/supabase/supabase`), Google's own Identity Services reference, and the PyJWT
documentation. No blog posts, Medium articles or Stack Overflow answers were consulted.
Anything an official page would not confirm is flagged **UNVERIFIED**.

Scope: the auth vendor is already decided (Supabase Auth). Sign-in exists only to bound
spending — a verified person gets a quota that is theirs rather than their IP's. There is
no account system, no owned history, no teams.

Two sourcing notes carried from the research session:

- Any Supabase docs or pricing URL serves raw Markdown if you append `.md`
  (e.g. `https://supabase.com/docs/guides/api/api-keys.md`). The docs source also lives
  at `raw.githubusercontent.com/supabase/supabase/master/apps/docs/content/guides/…`.
  Both were used in preference to rendered HTML, which summarising fetchers mangle.
- Where a fact exists only in package source and not in prose docs, it is labelled
  **source-only**. Source is primary, but it is a version-pinned fact, not a contract.

---

## Verdict for the UI decision

**A full-page navigation is avoidable.** `signInWithOAuth` is a full-page navigation and
there is no supported popup variant of it — but Google's own pre-built button / One Tap
(`google.accounts.id`) never navigates at all, and Supabase documents feeding its ID
token to `supabase.auth.signInWithIdToken({ provider: 'google', token, nonce })`. That
path is an in-page `fetch`; the React tree never unmounts. It is Supabase's own
documented integration, not a workaround.

**The backend verifies asymmetrically via JWKS — but only after the project opts in.**
Supabase's current recommendation is RS256/ES256 verified against
`https://<ref>.supabase.co/auth/v1/.well-known/jwks.json`. Migration off the legacy
shared HS256 secret is a **manual dashboard action**, not something Supabase has done for
existing projects. Until it is done, that JWKS endpoint returns no keys.

**The email address does land in the project's own Postgres.** `auth.users` is a real
table in the project database with an `email` column, queryable from the SQL Editor. Any
claim that PanelVerdict "holds no PII" is false once Google sign-in ships.

---

## 1. Redirect vs popup — the most important question

### 1a. `signInWithOAuth` is a full-page navigation. There is no popup mode.

`GoTrueClient.signInWithOAuth` delegates to a private `_handleProviderSignIn`, whose
entire browser behaviour is one line
(`github.com/supabase/auth-js/blob/master/src/GoTrueClient.ts`, read 2026-08-24):

```ts
// try to open on the browser
if (isBrowser() && !options.skipBrowserRedirect) {
  window.location.assign(url)
}

return { data: { provider, url }, error: null }
```

`window.location.assign` is a document-level navigation. The React tree unmounts, all
in-memory state is lost, and the app is re-entered cold at the callback URL. There is no
`ux_mode`, no `popup` option, and no `window.open` anywhere in the OAuth path — searching
the file finds `window.location.assign` at the two OAuth sites only (line 2247, the
identity-linking path, and line 2420, `_handleProviderSignIn`). **Source-only** for the
mechanism; the docs describe the same behaviour in prose ("The user will be taken to
Google's consent screen, and finally redirected to your app…",
`supabase.com/docs/guides/auth/social-login/auth-google`, read 2026-08-24).

### 1b. What `skipBrowserRedirect: true` hands you

The complete option set, verbatim JSDoc from
`github.com/supabase/auth-js/blob/master/src/lib/types.ts` (read 2026-08-24):

```ts
provider: Provider
options?: {
  /** A URL to send the user to after they are confirmed. */
  redirectTo?: string
  /** A space-separated list of scopes granted to the OAuth application. */
  scopes?: string
  /** An object of query params */
  queryParams?: { [key: string]: string }
  /** If set to true does not immediately redirect the current browser context to visit the OAuth authorization page for the provider. */
  skipBrowserRedirect?: boolean
}
```

With it set, the return value is unchanged — `{ data: { provider, url }, error: null }`
— but nothing navigates. **You get a URL string and nothing else.** The PKCE code
verifier has already been written to storage as a side effect of building that URL, so
the URL is live and must be visited by *something* that shares the same cookie jar.

This is the one genuine popup escape hatch, and it is unsupported in the sense that
Supabase documents no popup flow built on it: you would `window.open(data.url)`, let the
popup complete the round trip against your `/auth/callback` route, and have the popup
`postMessage` back to the opener before closing. The session cookie is written by the
callback route in the popup, on the same origin, so the opener sees it on its next
request. **Supabase does not document this pattern anywhere** — UNVERIFIED as a supported
path; treat it as a thing that can be made to work, not a thing that is promised to.

### 1c. Google's pre-built button / One Tap — the documented no-navigation path

Supabase documents this as a first-class option, not a workaround. The guide's own
framing (`supabase.com/docs/guides/auth/social-login/auth-google`, read 2026-08-24):

> Supabase Auth supports Sign in with Google for the web […] To support Sign in with
> Google, you need to configure the Google provider for your Supabase project. […]
> - By writing application code for the web, native applications or Chrome extensions
> - By using Google's pre-built solutions such as personalized sign-in buttons, One Tap
>   or automatic sign-in

And, on the pre-built path:

> Most web apps and websites can use Google's personalized sign-in buttons, One Tap or
> automatic sign-in for the best user experience.

The mechanism: load `https://accounts.google.com/gsi/client`, render the button or call
`google.accounts.id.initialize(...)` + `.prompt()`, and receive a `CredentialResponse` in
a JavaScript callback. Nothing navigates — Google renders its UI in an iframe or via
FedCM. You then hand the credential to Supabase:

```ts
async function handleSignInWithGoogle(response) {
  const { data, error } = await supabase.auth.signInWithIdToken({
    provider: 'google',
    token: response.credential,
    nonce: '<NONCE>',
  })
}
```

`signInWithIdToken` is an ordinary `fetch` to `/auth/v1/token?grant_type=id_token`. **The
React tree never unmounts.** This is the answer to the design question.

Supported providers and parameter semantics, verbatim from `auth-js` `types.ts`
(read 2026-08-24):

```ts
export type SignInWithIdTokenCredentials = {
  /** Provider name or OIDC `iss` value identifying which provider should be used to verify the provided token. Supported names: `google`, `apple`, `azure`, `facebook`, `kakao`, `keycloak` (deprecated). */
  provider: 'google' | 'apple' | 'azure' | 'facebook' | 'kakao' | (string & {})
  /** OIDC ID token issued by the specified provider. The `iss` claim in the ID token must match the supplied provider. Some ID tokens contain an `at_hash` which require that you provide an `access_token` value to be accepted properly. If the token contains a `nonce` claim you must supply the nonce used to obtain the ID token. */
  token: string
  /** If the ID token contains an `at_hash` claim, then the hash of this value is compared to the value in the ID token. */
  access_token?: string
  /** If the ID token contains a `nonce` claim, then the hash of this value is compared to the value in the ID token. */
  nonce?: string
  options?: { captchaToken?: string }
}
```

### 1d. The nonce rule — the one thing that trips this path up

Supabase's guide, verbatim (read 2026-08-24):

> *(Optional)* Configure a nonce. The use of a nonce is recommended for extra security,
> but optional. The nonce should be generated randomly each time, and it must be provided
> in both the `data-nonce` attribute of the HTML code and the options of the callback
> function.

> Note that the nonce should be the same in both places, but because Supabase Auth
> expects the provider to hash it (SHA-256, hexadecimal representation), you need to
> provide a hashed version to Google and a non-hashed version to `signInWithIdToken`.

So: **hashed to Google, unhashed to Supabase.** Getting this backwards is the failure
mode. Supabase ships the generator in the guide:

```js
const nonce = btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))
const encodedNonce = new TextEncoder().encode(nonce)
const hashBuffer = await crypto.subtle.digest('SHA-256', encodedNonce)
const hashArray = Array.from(new Uint8Array(hashBuffer))
const hashedNonce = hashArray.map((b) => b.toString(16).padStart(2, '0')).join('')
```

The nonce is **optional**, so a first cut can skip it and add it later. There is also a
per-provider escape hatch — `auth.external.<provider>.skip_nonce_check`, described in the
CLI config reference as "Disables nonce validation during OIDC authentication flow for
the specified provider. Enable only when client libraries cannot properly handle nonce
verification. Be aware that this reduces security by allowing potential replay attacks
with stolen ID tokens."
(`supabase.com/docs/guides/local-development/cli/config`, read 2026-08-24). Don't.

### 1e. Third-party cookies / FedCM

Supabase's guide, verbatim (read 2026-08-24):

> To make your app compatible with Chrome's third-party-cookie phase-out, make sure to
> set `data-use_fedcm_for_prompt` to `true`.

and in the JS sample, `use_fedcm_for_prompt: true` with the comment "with chrome's
removal of third-party cookies, we need to use FedCM instead". This is not optional in
practice on current Chrome.

### 1f. Setup cost of the pre-built path

Both paths need the same Google Cloud client. From the guide (read 2026-08-24):

- "Under **Authorized JavaScript origins** add your application's URL. These should also
  be configured as the Site URL or redirect configuration in your project." — this is the
  origin that matters for the pre-built button.
- "Under **Authorized redirect URIs** add your Supabase project's callback URL." — needed
  for the `signInWithOAuth` path.
- "Register the Client ID in the Google provider page on the Dashboard."

Note that Google's own reference gives `ux_mode` a default of `"popup"` for the GSI
button, with `"redirect"` as the alternative
(`developers.google.com/identity/gsi/web/reference/js-reference`, read 2026-08-24) — but
in the Supabase integration the JavaScript-callback mode is used, so `ux_mode` is not the
lever; the credential arrives in the callback with no top-level navigation either way.

---

## 2. What survives the round trip (if a redirect is used after all)

### 2a. `redirectTo` query parameters survive

The Auth server appends `code` to whatever URL you gave it, preserving existing query
parameters. From `github.com/supabase/auth/blob/master/internal/api/verify.go`
(read 2026-08-24):

```go
func (a *API) prepPKCERedirectURL(rurl, code string) (string, error) {
	u, err := url.Parse(rurl)
	if err != nil {
		return "", err
	}
	q := u.Query()
	q.Set("code", code)
	u.RawQuery = q.Encode()
	return u.String(), nil
}
```

`u.Query()` parses the existing query and `q.Set("code", …)` adds to it — existing
parameters are re-encoded and returned intact. **Source-only**; the docs do not state
this in prose.

### 2b. The `next` convention is documented, but it is your convention, not a feature

Supabase's own PKCE flow partial
(`apps/docs/content/_partials/oauth_pkce_flow.mdx`, read 2026-08-24) has the Next.js
callback route read a `next` parameter out of the URL itself:

```ts
const { searchParams, origin } = new URL(request.url)
const code = searchParams.get('code')
// if "next" is in param, use it as the redirect URL
let next = searchParams.get('next') ?? '/'
if (!next.startsWith('/')) {
  // if "next" is not a relative URL, use the default
  next = '/'
}
```

So `next` is a convention Supabase's sample code establishes and your route handler
implements. There is no `state` parameter exposed by the client library — Supabase
manages OAuth `state` internally. The carrying capacity of the round trip is therefore
"whatever you put in the `redirectTo` query string and read back yourself", bounded by
URL length and by the redirect allow-list.

Note the guard in the sample: `next` is rejected unless it starts with `/`. Any state you
carry must be treated as attacker-controlled.

### 2c. The redirect allow-list constrains what URLs are legal

From `supabase.com/docs/guides/auth/redirect-urls` (read 2026-08-24):

> When using passwordless sign-ins or third-party providers, the Supabase client library
> provides a `redirectTo` parameter to specify where to redirect the user after
> authentication. The URL in `redirectTo` should match the Redirect URLs list
> configuration.

> The Site URL in URL Configuration defines the **default redirect URL** when no
> `redirectTo` is specified in the code.

Wildcards are supported for preview deployments — `http://localhost:3000/**` matches
nested paths, `/*` matches one segment only. "The separator characters in a URL are
defined as `.` and `/`." And: "While the 'globstar' (`**`) is useful for local development
and preview URLs, we recommend setting the exact redirect URL path for your site URL in
production." Vercel-specific guidance is on the same page.

**Whether the allow-list matches against the query string at all is not stated** —
UNVERIFIED. The wildcard examples are all path-shaped. Assume path matching and put state
in the query string, which is the shape Supabase's own `next` sample uses.

### 2d. Does PKCE require a route handler? Yes.

From the same partial (read 2026-08-24): the PKCE flow requires a callback route that
calls `supabase.auth.exchangeCodeForSession(code)` server-side, because the code verifier
lives in a cookie the server client can read. The documented Next.js App Router shape is
`app/auth/callback/route.ts`:

```ts
if (code) {
  const supabase = await createClient()
  const { error } = await supabase.auth.exchangeCodeForSession(code)
  if (!error) {
    // …redirect to `${origin}${next}`, honouring x-forwarded-host behind a proxy
  }
}
```

`@supabase/ssr` sets `flowType: "pkce"` unconditionally in **both**
`createBrowserClient` and `createServerClient`
(`github.com/supabase/ssr/blob/main/src/createBrowserClient.ts` and
`createServerClient.ts`, read 2026-08-24) — **source-only**. So if you use
`@supabase/ssr` at all, you are on PKCE and you need the route handler. The implicit
flow (tokens in the URL fragment, no callback route) is only reachable via plain
`@supabase/supabase-js`.

---

## 3. Where the session lives

### 3a. Cookies, unconditionally

`@supabase/ssr`'s own README, verbatim
(`github.com/supabase/ssr/blob/main/README.md`, read 2026-08-24):

> ### The `auth.storage` option is ignored
>
> `createBrowserClient` and `createServerClient` always store the session in cookies —
> this is the entire point of the package, since it lets a server-rendered request read
> the same session the browser wrote. Passing `auth.storage` has no effect; a one-time
> console warning is logged if you do. […] If you don't need server-side access to the
> session, use `@supabase/supabase-js`'s `createClient` directly with your own `storage`
> (e.g. `localStorage`) — there's no reason to use `@supabase/ssr` in that case.

That last sentence is a live design fork for PanelVerdict: **if the backend calls do not
need the session server-side, `@supabase/ssr` earns nothing** and plain
`@supabase/supabase-js` with `localStorage` is simpler. It stops being true the moment an
`app/api/*` route handler needs to read the user.

### 3b. Cookie name, chunking, and flags — all source-only

From `github.com/supabase/ssr/blob/main/src/constants.ts` (read 2026-08-24):

```ts
export const DEFAULT_COOKIE_OPTIONS: CookieOptions = {
  path: "/",
  sameSite: "lax",
  httpOnly: false,
  maxAge: 400 * 24 * 60 * 60, // 400 days
};
```

Three things follow, and none of them are in the prose docs — **all source-only**:

- **`httpOnly: false`.** The session cookie is readable by page JavaScript by design,
  because the browser client has to refresh the token. Do not describe this cookie as
  HttpOnly-protected anywhere.
- **`secure` is not set by default.** UNVERIFIED whether the hosting platform or a
  documented option sets it in production; nothing in `constants.ts` does.
- **`sameSite: "lax"`**, which is what makes the OAuth redirect land with the cookie
  attached.

The cookie name is `sb-<project-ref>-auth-token`, derived from the first hostname label
of the Supabase URL. Values exceeding `MAX_CHUNK_SIZE = 3180` are split across
`` `${key}.${i}` `` (`github.com/supabase/ssr/blob/main/src/utils/chunker.ts`, read
2026-08-24) — so expect `sb-<ref>-auth-token.0`, `.1`, … in practice, plus PKCE
scratch keys of the form `<storageKey>-code-verifier`. **Source-only**; the chunk naming
is not documented, so don't build anything that parses it.

### 3c. Route handlers see the session; no middleware is strictly required

The documented server client
(`supabase.com/docs/guides/auth/server-side/creating-a-client`, read 2026-08-24) is:

```ts
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

export async function createClient() {
  const cookieStore = await cookies()
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll() { return cookieStore.getAll() },
        setAll(cookiesToSet, _headers) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options))
          } catch {
            // The `setAll` method was called from a Server Component.
            // This can be ignored if you have middleware refreshing user sessions.
          }
        },
      },
    }
  )
}
```

A Route Handler *can* write cookies, so the `catch` never fires there and a route handler
reads and refreshes the session with no extra wiring beyond this helper.

### 3d. What middleware actually buys, and note the file-name change

Middleware is **not required for correctness in route handlers**. It exists because
Server Components cannot write cookies, so without it a token refreshed during a page
render is lost. `@supabase/ssr`'s README also names a second reason (read 2026-08-24):

> Supabase refresh tokens are single-use. If two requests arrive simultaneously with the
> same expired session cookie […] The second request will receive `session: null` until
> the browser syncs the updated cookie from the first response.
>
> The **middleware pattern** mitigates this for the common case: middleware runs once per
> navigation and refreshes the session before the page renders […] For parallel requests
> (e.g. parallel `fetch()` calls from the client), handle `null` sessions gracefully and
> retry or re-authenticate as needed.

**This matters for PanelVerdict specifically**, since every backend call is proxied
through `app/api/*` route handlers and a page may fire several in parallel. Adding
middleware does not fully solve it; the README says to handle `null` and retry.

Two cautions on the middleware sample itself:

- Supabase's current Next.js example uses **`proxy.ts`**, not `middleware.ts`, following
  Next.js's own file-convention change
  (`github.com/supabase/supabase/blob/master/examples/auth/nextjs/proxy.ts`, read
  2026-08-24). **The mapping back to `middleware.ts` for a given Next.js version is
  inferred, not documented by Supabase** — UNVERIFIED; check against Next.js 15's own
  conventions before copying.
- The sample carries a hard instruction: "Do not run code between `createServerClient`
  and `supabase.auth.getClaims()`", and the response object must be returned unchanged.

### 3e. Refresh defaults differ between the two clients — source-only

| Client | `flowType` | `autoRefreshToken` | `detectSessionInUrl` |
| --- | --- | --- | --- |
| `createBrowserClient` | `"pkce"` | `?? isBrowser()` → **true** | `?? isBrowser()` → **true** |
| `createServerClient` | `"pkce"` | **`false`** | `false` |
| `supabase-js` `createClient` | (implicit) | **`true`** | `true` |

From `github.com/supabase/ssr/blob/main/src/createBrowserClient.ts`,
`createServerClient.ts`, and `github.com/supabase/auth-js/blob/master/src/GoTrueClient.ts`
(read 2026-08-24). All **source-only** — the reference docs do not state these defaults.

---

## 4. Verifying the JWT on a separate backend

### 4a. Supabase's recommendation is asymmetric JWKS verification

From `supabase.com/docs/guides/auth/jwts` (read 2026-08-24):

> ```
> GET https://project-id.supabase.co/auth/v1/.well-known/jwks.json
> ```
>
> Which responds with JWKS object containing one or more asymmetric JWT signing keys
> (only their public keys). **Be aware that this endpoint does not return any keys if you
> are not using asymmetric JWT signing keys.**

That last sentence is the trap. See 4c.

On the legacy shared secret, the same page is blunt (read 2026-08-24):

> If you are using a shared secret (HS256) signing key, you may wish to verify using the
> shared secret. **We strongly recommend against this approach.**

> There is almost no benefit from using a JWT signed with a shared secret. […] A shared
> secret that is in the hands of a malicious actor can be used to impersonate your users
> […] It can be very easy to accidentally leak the shared secret in publicly available
> source code […] This is especially true if you accidentally add the secret in
> environment variables prefixed with `NEXT_PUBLIC_`, `VITE_`, `PUBLIC_` […]

And the fallback if you are still on HS256 (read 2026-08-24):

> If your project is using a shared secret (HS256) signing key, we recommend always
> verifying a user access token directly with the Auth server […]

i.e. a network call per request. That is the cost of not migrating.

### 4b. The JWKS cache rule

From `supabase.com/docs/guides/auth/jwts` (read 2026-08-24):

> This endpoint is served directly from the Auth server, but is also additionally cached
> by the Supabase Edge for 10 minutes […] We recommend waiting at least 20 minutes when
> creating a standby signing key, or revoking a previously used key.

> Make sure that you do not cache this data for longer in your application, as it might
> make revocation difficult. If you do, make sure to provide a way to purge this cache
> when rotating signing keys […]

**10 minutes edge cache; do not cache longer in the backend without a purge path.**

### 4c. Supabase has NOT migrated existing projects — it is a manual opt-in

From `supabase.com/docs/guides/auth/signing-keys` (read 2026-08-24):

> Supabase provides two systems for dealing with signing keys: the Legacy system based on
> the JWT secret, and the new Signing keys system.

> | Legacy | JWT secret | Initially Supabase was designed to use a single shared secret
> key to sign all JWTs. This includes the `anon` and `service_role` keys, all user access
> tokens […] **No longer recommended.** Available for backward compatibility. |

The migration is a sequence of dashboard actions, verbatim:

> You can start migrating away from the legacy JWT secret through the Supabase dashboard.
> This process does not cause downtime for your application.
>
> 1. Start off by clicking the *Migrate JWT secret* button on the JWT signing keys page.
>    This step will import the existing legacy JWT secret into the new JWT signing keys
>    system.
> 2. Simultaneously, we're creating a new asymmetric JWT signing key for you to rotate
>    to. This key starts off as standby key […]
> 4. If you do wish to start using the standby key for all new JWT use the *Rotate keys*
>    button. […]
> 6. Plan for revocation of the legacy JWT secret. If your access token expiry time is
>    configured to be 1 hour, wait at least 1 hour and 15 minutes before revoking […]

Supported algorithms are ES256 (recommended), RS256, and HS256
(same page, read 2026-08-24).

**Action item for PanelVerdict: the existing Supabase project is almost certainly still
on the legacy JWT secret, so `.well-known/jwks.json` will return nothing until *Migrate
JWT secret* → *Rotate keys* is run.** Whether a *brand-new* 2026 project defaults to
asymmetric keys is **not stated on the signing-keys page** — UNVERIFIED. Check the
project's JWT signing keys page before writing the backend verifier.

### 4d. The stable user id is `sub`

From `supabase.com/docs/guides/auth/jwt-fields` (read 2026-08-24):

| Claim | Type | Meaning | Example |
| --- | --- | --- | --- |
| `iss` | `string` | Issuer | `"https://project-ref.supabase.co/auth/v1"` |
| `aud` | `string \| string[]` | Audience | `"authenticated"` or `"anon"` |
| `exp` | `number` | Unix timestamp when the token expires | `1640995200` |
| `sub` | `string` | **The user ID (UUID)** | `"123e4567-e89b-12d3-a456-426614174000"` |
| `role` | `string` | User's role | `"authenticated"`, `"anon"`, `"service_role"` |
| `email` | `string` | User's email address | `"user@example.com"` |
| `is_anonymous` | `boolean` | Whether the user is anonymous | `false` |

**`sub` is the quota key.** Note that `email` is *in the token* — see question 8. Also
note `aud: "authenticated"` and `iss` as the two claims a verifier must check beyond the
signature; the `iss` doc line says "If you append `/.well-known/jwks.json` to this URL
you'll get access to the public keys with which you can verify the token."

### 4e. Supabase names no Python library

Searching `auth/jwts`, `auth/signing-keys`, and `auth/third-party/overview` for
`pyjwt`, `python-jose`, `PyJWKClient`, or `python` returns **zero hits** (read
2026-08-24). The only verification sample Supabase ships is TypeScript, using `jose`:

```ts
import { createRemoteJWKSet, jwtVerify } from 'jose'

const PROJECT_JWKS = createRemoteJWKSet(
  new URL('https://project-id.supabase.co/auth/v1/.well-known/jwks.json')
)

async function verifyProjectJWT(jwt: string) {
  return jwtVerify(jwt, PROJECT_JWKS)
}
```

The docs' only language-agnostic instruction is "avoid implementing the algorithms
yourself and instead rely on `supabase.auth.getClaims()`, or other high-quality JWT
verification libraries for your language" (`supabase.com/docs/guides/auth/jwts`, read
2026-08-24). **Supabase does not name a Python library** — UNVERIFIED / gap.

The closest primary-source Python equivalent is PyJWT's `PyJWKClient`, which does exactly
what `createRemoteJWKSet` does. From `pyjwt.readthedocs.io/en/stable/usage.html`
(read 2026-08-24):

> `PyJWKClient` fetches and manages JSON Web Key Sets (JWKS) from a remote endpoint.
> Identity providers such as Auth0, Okta, and any OpenID Connect server publish a JWKS
> endpoint containing the public keys used to sign JWTs. Instead of hard-coding public
> keys, you can point `PyJWKClient` at that URL and let it resolve the correct key for
> each token automatically.

```python
import jwt
from jwt import PyJWKClient

jwks_client = PyJWKClient(url, headers=optional_custom_headers)
signing_key = jwks_client.get_signing_key_from_jwt(token)
jwt.decode(
    token,
    signing_key,
    audience="https://expenses-api",
    options={"verify_exp": False},
    algorithms=["RS256"],
)
```

> If the `kid` is not found in the current key set, `PyJWKClient` automatically refreshes
> the JWKS from the endpoint and retries before raising an error.
>
> `PyJWKClient` also includes built-in caching to avoid unnecessary network requests. See
> `PyJWKClient` in the API reference for details on the caching parameters.

Two notes for a FastAPI implementation: pass `algorithms=["ES256"]` or `["RS256"]` to
match the project's chosen key (never leave it open), keep `verify_exp` on (the sample
above disables it only to decode a long-expired demo token), and set `audience`
to `"authenticated"` and `issuer` to `https://<ref>.supabase.co/auth/v1`. That
`PyJWKClient` is the right choice for Supabase specifically is **an inference from
matching capabilities, not a Supabase recommendation** — flagged.

---

## 5. Token lifetime and expiry

All from `supabase.com/docs/guides/auth/sessions` unless noted, read 2026-08-24.

- **Default access-token TTL is 1 hour.** "Most applications should use the default
  expiration time of 1 hour. You can customize this value in the Auth settings >
  Sessions." Corroborated by the CLI config reference, `auth.jwt_expiry`, **Default:
  `3600`** — "How long tokens are valid for, in seconds. Defaults to 3600 (1 hour),
  maximum 604,800 seconds (one week)."
  (`supabase.com/docs/guides/local-development/cli/config`, read 2026-08-24.)
- "Setting a value over 1 hour is generally discouraged for security reasons […] The
  shorter the expiration time, the more frequently refresh tokens are used, which
  increases the load on the Auth server." And elsewhere: "We do not recommend going below
  5 minutes for the JWT expiration time."
- **Refresh tokens never expire but are single-use.** "Access tokens are designed to be
  short lived, usually between 5 minutes and 1 hour while refresh tokens never expire but
  can only be used once. You can exchange a refresh token only once to get a new access
  and refresh token pair."
- **Reuse interval is 10 seconds.** "A refresh token can be used more than once within a
  defined reuse interval. By default this is 10 seconds and we do not recommend changing
  this value." It exists precisely for "using server-side rendering where the same
  refresh token needs to be reused on the server and soon after on the client."
- **Reuse outside that window kills the whole session.** "Should the reuse attempt not
  fall under these two exceptions, the whole session is regarded as terminated and all
  refresh tokens belonging to it are marked as revoked."
- **Inactivity timeout is off by default and Pro-plan-only.** "This feature is only
  available on Pro Plans and up." Note the gotcha: "the actual duration of a session is
  the configured timeout plus the JWT expiration time." Not reachable on a $0 budget.
- Sessions live in a real table: "The session is stored in the `auth.sessions` table."

**What a client sees on expiry.** Two distinct surfaces:

- Against PostgREST / the Data API: `PGRST301`, HTTP 401, "Provided JWT couldn't be
  decoded or it is invalid." (`supabase.com/docs/guides/troubleshooting/postgrest-error-codes`,
  read 2026-08-24.) Note the message says *invalid*, not *expired* — **the docs do not
  give a distinct expired-token code** on this surface.
- Against the Auth server: `bad_jwt` — "JWT sent in the Authorization header is not
  valid."; `refresh_token_already_used` — "Refresh token has been revoked and falls
  outside the refresh token reuse interval."; `session_expired` — "Session to which the
  API request relates has expired. This can occur if an inactivity timeout is configured,
  or the session entry has exceeded the configured timebox value."; `session_not_found` —
  "Session to which the API request relates no longer exists."
  (`supabase.com/docs/guides/auth/debugging/error-codes`, read 2026-08-24.)

**`autoRefreshToken` is on by default in the browser** — `true` in `auth-js`'s defaults
and `?? isBrowser()` in `createBrowserClient`, but explicitly **`false` in
`createServerClient`**, which has no background timer. The refresh timer ticks every 30s
(`AUTO_REFRESH_TICK_DURATION_MS = 30 * 1000`) and refreshes when the token is within 3
ticks (~90s) of expiry (`AUTO_REFRESH_TICK_THRESHOLD = 3`). All **source-only**, from
`GoTrueClient.ts` and `createServerClient.ts` (read 2026-08-24) — the reference docs do
not state the default.

For the FastAPI backend this means: a 1-hour token, refreshed client-side ~90s early, so
a *mid-request* expiry is rare but not impossible. The backend should return 401 and let
the frontend refresh and retry rather than try to be clever.

---

## 6. Public env vars

### 6a. Yes, "anon key" has been renamed to "publishable key"

The four key types, verbatim from `supabase.com/docs/guides/api/api-keys`
(read 2026-08-24):

| Type | Format | Privileges | Use |
| --- | --- | --- | --- |
| Publishable key | `sb_publishable_...` | Low | Safe to expose online: web page, mobile or desktop app, GitHub actions, CLIs, source code. |
| Secret keys | `sb_secret_...` | Elevated | Only use in backend components of your app […] They provide *full access* to your project's data, bypassing Row Level Security. |
| `anon` | JWT (long lived) | Low | Legacy version of publishable keys. |
| `service_role` | JWT (long lived) | Elevated | Legacy version of secret keys. |

> **They will be deprecated by the end of 2026, and you should now use the publishable
> (`sb_publishable_xxx`) and secret (`sb_secret_xxx`) keys instead.**

> Both key types work simultaneously. Creating publishable and secret keys adds them
> *alongside* your existing `anon` and `service_role` keys without affecting them — your
> legacy keys keep working.

Supabase's own announcement timetable
(`github.com/orgs/supabase/discussions/29260`, created 2024-09-12, last edited
2025-07-14, read 2026-08-24) adds: from **1 November 2025**, "New projects no longer have
`anon` and `service_role` available for use", and "Projects restored from 1st November
2025 will no longer be restored with the legacy API keys." **That discussion body is a
forward-looking plan last edited in 2025, not a 2026 confirmation** — UNVERIFIED that it
shipped as written; check the project's dashboard.

The restore clause matters here: **a Free-plan project pauses after a week of inactivity,
and a paused project restored after that date comes back without its legacy keys.** If
anything in PanelVerdict still depends on `anon`/`service_role`, a pause/restore cycle
breaks it.

### 6b. What must reach the browser

Exactly two values. Supabase's Next.js quickstart, verbatim `.env.local`
(`supabase.com/docs/guides/getting-started/quickstarts/nextjs`, read 2026-08-24):

```text
NEXT_PUBLIC_SUPABASE_URL=<SUBSTITUTE_SUPABASE_URL>
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<SUBSTITUTE_SUPABASE_PUBLISHABLE_KEY>
```

`NEXT_PUBLIC_SUPABASE_ANON_KEY` appears **zero times** on the current server-side auth
guide, against 10 occurrences each of `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (`supabase.com/docs/guides/auth/server-side/nextjs`,
read 2026-08-24). Adding the Google sign-in also means the Google **Client ID** must
reach the browser for the pre-built-button path — that is public by design in Google's
model.

### 6c. Is the publishable key safe to ship in a client bundle? Yes, explicitly — with a condition

From `supabase.com/docs/guides/api/api-keys` (read 2026-08-24):

> Publishable keys identify the public components of your application. Public components
> run in environments where it is impossible to secure any secrets. These include:
> - Web pages, where the key is bundled in source code.
> - Mobile or desktop applications […]
> - CLI, scripts, tools, or other pre-built executables. […]
>
> These environments are always considered public because anyone can retrieve the key
> from the source code or build artifacts.

The condition — quote this alongside the above, never alone:

> When using a publishable key, access to your project's data is guarded by Postgres via
> the built-in `anon` and `authenticated` roles. For full protection make sure:
> - You have enabled Row Level Security on all tables.
> - You regularly review your Row Level Security policies for permissions granted to the
>   `anon` and `authenticated` roles.
> - You do not modify the role's attributes without understanding the changes you are
>   making.

And, on the same page: "Danger: Tables and views exposed through the Data API without RLS
can be accessed by any role with matching grants." — from
`supabase.com/docs/guides/api/securing-your-api`, read 2026-08-24, which adds that
Dashboard-created tables have RLS on by default but SQL-Editor-created ones do not.

**PanelVerdict's tables were created by migrations, not the Dashboard.** Shipping a
publishable key to the browser makes the Data API a live surface onto whatever those
tables grant. If PanelVerdict does not intend to expose the Data API at all, that is a
deliberate decision to record and enforce with RLS, not something the publishable key's
"safe to expose" label covers on its own.

The counterpart, verbatim: "Never expose your secret keys publicly. Your data is at risk.
[…] **Never use in a browser, even on `localhost`.**" and "You cannot use a secret key in
the browser (matches on the `User-Agent` header) and it will always reply with HTTP 401
Unauthorized."

---

## 7. Google-only, and cost

### 7a. Providers are individually toggled; email is on by default, Google is off

- "Email authentication is enabled by default." (`supabase.com/docs/guides/auth/passwords`,
  read 2026-08-24.)
- `auth.external.<provider>.enabled` — **Default: `false`** — "Use an external OAuth
  provider. The full list of providers are: `apple`, `azure`, … `google`, …"
  (`supabase.com/docs/guides/local-development/cli/config`, read 2026-08-24.)
- `auth.enable_anonymous_sign_ins` — **Default: `false`**.
- `auth.email.enable_signup` — **Default: `true`** — "Allow/disallow new user signups via
  email to your project."

Every provider has an independent flag; the Auth server's settings endpoint returns one
boolean per provider including `Email` and `Phone`
(`github.com/supabase/auth/blob/master/internal/api/settings.go`, read 2026-08-24).

### 7b. Google as the sole provider — yes, via the dashboard / Management API

The Management API's `UpdateAuthConfigBody` exposes `external_email_enabled`,
`external_google_enabled`, `external_anonymous_users_enabled` and `disable_signup` as
nullable booleans, written via `PATCH /v1/projects/{ref}/config/auth`
(`api.supabase.com/api/v1-json` and
`supabase.com/docs/reference/api/v1-update-auth-service-config`, read 2026-08-24). The
docs also treat "social login only" as a supported configuration in passing: "Disable
email-based sign ups for the event and use social login only."
(`supabase.com/docs/guides/auth/auth-smtp`, read 2026-08-24.)

**Caveat, flagged:** there is no prose sentence in the guides saying "you can disable the
email provider" — the capability is confirmed *structurally* from the API spec field.
Locally, `config.toml` has no `auth.email.enabled` key at all; it can disable email
*signups* (`enable_signup = false`), not the provider. Verify the dashboard toggle
exists before designing around it.

### 7c. Free tier: 50,000 MAU, $0

Docs quota table (`supabase.com/docs/guides/platform/manage-your-usage/monthly-active-users`,
read 2026-08-24):

| Plan | Quota | Over-Usage |
| --- | --- | --- |
| Free | 50,000 | – |
| Pro | 100,000 | $0.00325 per MAU |
| Team | 100,000 | $0.00325 per MAU |

Corroborated on `supabase.com/pricing` (read 2026-08-24): Free plan, "$0/month",
"50,000 monthly active users"; comparison table "| MAUs | 50,000 included | …".

Google sign-ins are ordinary MAUs, not a surcharged category:

> You are charged for the number of distinct users who log in or refresh their token
> during the billing cycle (**including Social Login with e.g. Google, Facebook,
> GitHub**). Each unique user is counted only once per billing cycle, regardless of how
> many times they authenticate.

and on the pricing page: "| Social OAuth providers | Included | Included | Included |
Included |". "Third-Party MAUs" is a *different* meter, for Clerk/Firebase/Auth0/Cognito
(`…/monthly-active-users-third-party`, read 2026-08-24), and SAML SSO is "Not included"
on Free.

On overage: "When you are exceeding your quotas while being on a Free Plan or having
Spend Cap enabled, you will get a notification to your billing email address and put
under a grace period." The concrete consequence lives in the Fair Use Policy, **not
fetched** — UNVERIFIED.

**Auth is free at PanelVerdict's scale by four orders of magnitude.** The relevant $0
risk is not MAU but the Free plan's "Free projects are paused after 1 week of inactivity.
Limit of 2 active projects." (`supabase.com/pricing`, read 2026-08-24) — already a known
constraint for the database, and see 6a on what a restore does to legacy keys.

---

## 8. PII — the email IS stored in the project's own Postgres

**State it plainly: yes.** Three independent confirmations, all read 2026-08-24.

**1. The user record lives in the project's database.** From
`supabase.com/docs/guides/auth/users`:

> A **user** in Supabase Auth is someone with a user ID, stored in the Auth schema.

**2. That record has an `email` column.** From the user-object attribute table on the
same page:

| Attribute | Type | Description |
| --- | --- | --- |
| `email` | `string` | The user's email address. |
| `email_confirmed_at` | `string` | The timestamp that the user's email was confirmed. […] |
| `identities` | `UserIdentity[]` | Contains an object array of identities linked to the user. |

The same page classifies exactly this as PII:

> **Permanent users** are tied to a piece of Personally Identifiable Information (PII),
> such as an email address, a phone number, or a third-party identity.

**3. It is a queryable Postgres table, not vendor-side storage.** From
`supabase.com/docs/guides/auth/managing-user-data`:

> As Supabase is built on top of Postgres, you can query the `auth.users` and
> `auth.identities` table via the `SQL Editor` tab to extract all users:
>
> ```sql
> select * from auth.users;
> ```

and "You can also view the contents of the Auth schema in the Table Editor."

Corroborating: `email` is a documented JWT claim
(`supabase.com/docs/guides/auth/jwt-fields`), so the address is also present in every
access token the browser holds and every token the FastAPI backend receives.

### What this means for the docs

Any statement that PanelVerdict "holds no PII" becomes **false** the moment Google
sign-in ships. The accurate replacement is narrower and still worth saying: *the only
personal data stored is what Supabase Auth records for a Google sign-in — an email
address, a Google identity, and timestamps, in the `auth.users` and `auth.identities`
tables — and PanelVerdict's own tables key off the opaque `sub` UUID, never the email.*
That is a design commitment the schema must actually honour.

Two mitigations Supabase documents, both read 2026-08-24:

- **Provider tokens are not stored.** "Provider tokens are intentionally not stored in
  your project's database. This is because provider tokens give access to potentially
  sensitive user data in third-party systems."
  (`supabase.com/docs/guides/auth/social-login`.) So Google *access* tokens are not held —
  only the identity record.
- **Deletion is real and cascading.** "With the default `shouldSoftDelete: false`, this
  removes the row from `auth.users`, which cascades to `auth.sessions` and invalidates the
  user's refresh tokens." But note the caveat on the same page: "deleting a user from the
  `auth.users` table does not automatically sign out a user […] a user's JWT will remain
  'valid' until it has expired" — up to the 1-hour TTL. A quota-enforcing backend that
  trusts `sub` from a signature alone will honour a deleted user's token for up to an
  hour.

Whether the raw Google ID-token payload is additionally retained in
`auth.identities.identity_data` — and therefore whether name and profile-picture URL are
stored too — **could not be confirmed**: the string `identity_data` appears in none of the
auth guides read. UNVERIFIED; inspect the table directly before making a claim about the
full PII surface.

---

## Questions that could NOT be fully answered from primary sources

None of the eight was a total blank, but seven carry a specific unconfirmed edge:

1. **Q1 (redirect vs popup)** — answered. The one gap: **Supabase documents no popup flow
   built on `skipBrowserRedirect`**, so the `window.open` + `postMessage` variant is
   inference from the primitive, not a supported path. The One Tap / `signInWithIdToken`
   answer is fully documented and needs no such inference.
2. **Q2 (round trip)** — answered, except **whether the redirect allow-list matches
   against the query string**. The wildcard examples are all path-shaped.
3. **Q3 (session)** — answered, but the cookie **name, chunk naming, and every flag
   (`httpOnly: false`, `sameSite: lax`, absent `secure`) are source-only**, documented
   nowhere in prose. Also unconfirmed: **the `proxy.ts` → `middleware.ts` mapping for
   Next.js 15**, and whether anything sets `secure` in production.
4. **Q4 (backend verification)** — answered, except **(a) Supabase names no Python
   library**, so `PyJWKClient` is a capability match rather than a recommendation, and
   **(b) whether a brand-new 2026 project defaults to asymmetric keys** is not stated on
   the signing-keys page.
5. **Q5 (lifetime)** — answered, except **`autoRefreshToken`'s default is source-only**,
   and **PostgREST has no distinct "expired" error code** — `PGRST301` says "invalid".
6. **Q6 (env vars)** — answered. Unconfirmed: **whether new projects really ship without
   `anon`/`service_role` today**; the only source is a plan last edited 2025-07-14.
7. **Q7 (Google-only, cost)** — answered. Unconfirmed: **no prose sentence says the
   hosted email provider can be toggled off** (confirmed only from the Management API's
   `external_email_enabled` field), and the **Fair Use Policy's concrete overage
   behaviour** was not fetched.
8. **Q8 (PII)** — answered decisively for the email. Unconfirmed: **what else
   `auth.identities.identity_data` retains** from the Google ID token (name, picture).

## Open decisions this research hands back

- **Do route handlers need the session at all?** If not, `@supabase/ssr` earns nothing
  over plain `supabase-js` + `localStorage` (3a) — and the whole cookie/middleware
  question disappears.
- **Migrate the project's JWT signing keys before writing the backend verifier** (4c),
  or the JWKS endpoint returns nothing.
- **Decide the RLS posture before shipping a publishable key to the browser** (6c).
- **Correct any "no PII" claim in the project docs** (8).
