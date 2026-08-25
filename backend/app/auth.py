"""Who is spending, proved rather than asserted (063/#158).

Every quota in this service counts a `caller`, and a quota is only as honest as
the identity it counts. Until now that identity was a header our own proxy
stamped: trustworthy only because the shared secret proved the request came
from the proxy, and worth nothing about *which person* was on the other side of
it. A verified session JWT answers the question the ledger is actually asking.

The rules this module exists to keep:

- **Verify, never trust.** The subject id comes out of a signature check, never
  out of the request body or a header a caller can write. A `curl` with a
  hand-written user id must buy nothing.
- **Asymmetric only.** Supabase's own guidance is blunt about the legacy shared
  secret — "a shared secret that is in the hands of a malicious actor can be
  used to impersonate your users" (`supabase.com/docs/guides/auth/jwts`, read
  2026-08-24) — so HS256 is left out of `ALGORITHMS` rather than merely
  discouraged. A backend that accepts it would verify tokens it also knows how
  to mint.
- **The subject id, and nothing else.** The token carries the address
  (`email` is a documented claim), and it stops here: `subject()` returns a
  string, so nothing downstream can persist what it never receives.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx
import jwt

from app.config import settings

logger = logging.getLogger(__name__)

# ES256 is Supabase's recommended signing key type and RS256 its other
# asymmetric option (`supabase.com/docs/guides/auth/signing-keys`, read
# 2026-08-24). Named explicitly because `algorithms` left open is the classic
# JWT vulnerability: a token declaring `alg: none` verifies against nothing.
ALGORITHMS = ("ES256", "RS256")

# Supabase issues session tokens for a signed-in person with this audience;
# `anon` is the other one, and it is precisely not a person
# (`supabase.com/docs/guides/auth/jwt-fields`, read 2026-08-24).
AUDIENCE = "authenticated"


class InvalidSession(Exception):
    """The token did not prove anything. Never carries the library's reason.

    The caller learns that their session was not accepted and nothing more: a
    verifier that reports *why* a forged token failed is a signature oracle,
    and this codebase's refusals are its own sentences anyway (013). The
    operator gets the reason instead, in the log — the two audiences want
    opposite things here.
    """


class SessionUnverifiable(Exception):
    """The token could not be checked at all — the key server was unreachable.

    A different outcome from `InvalidSession` because it has a different
    remedy. Telling a signed-in person their session is invalid sends them back
    through Google, which cannot possibly help when the thing that is down is
    the endpoint their new token would also be checked against; they would loop
    until they gave up, and the logs would read as a wave of forged tokens.
    """


class SigningKeys(Protocol):
    """The published half of the project's signing keys, resolved per token."""

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK: ...


@dataclass(frozen=True)
class SupabaseVerifier:
    """Turns a Supabase session JWT into the subject id the ledger counts."""

    keys: SigningKeys
    issuer: str
    audience: str = AUDIENCE
    algorithms: tuple[str, ...] = ALGORITHMS

    def subject(self, token: str) -> str:
        try:
            key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
            )
        except jwt.exceptions.PyJWKClientConnectionError as exc:
            # Not a verdict on the token — we never got to look at it.
            logger.warning("session key set unreachable: %s", exc)
            raise SessionUnverifiable from exc
        except Exception as exc:
            # Deliberately broad after that: `get_signing_key_from_jwt` raises
            # its own error type, `decode` raises another, and a malformed
            # header raises from neither. Every one of them means the same
            # thing to the caller, and a class this module forgot to name must
            # not become a 500 that lets a request past the gate.
            #
            # Logged because refusals have two indistinguishable causes with
            # opposite remedies: forged tokens, and a project whose signing
            # keys were never migrated — which returns an empty key set, so
            # every honest session fails exactly like an attack. The reason
            # goes here; the token never does, since a rejected credential is
            # still a credential (it may be a real one aimed at the wrong
            # project).
            logger.warning("session rejected: %s", type(exc).__name__)
            raise InvalidSession from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            # A token with no subject authenticates nobody: there would be
            # nothing to charge, so there is no one to admit.
            logger.warning("session rejected: no subject claim")
            raise InvalidSession
        return subject


def verifier_from_settings() -> SupabaseVerifier | None:
    """The project's verifier, or None when sign-in is not configured.

    None is the same escape hatch `api_shared_secret` already uses: local
    development and CI run without a Supabase project, and the deploy sets the
    URL. `main.caller_id` is what decides that an unconfigured service must not
    pretend to have verified anybody.

    The key set is fetched lazily and cached by PyJWT's own client. Its default
    `lifespan` of 300s is kept rather than tuned: Supabase asks that the set not
    be cached beyond the 10 minutes its edge already caches it for, "as it might
    make revocation difficult" (`guides/auth/jwts`, read 2026-08-24), and 5
    minutes is inside that without inventing a number.
    """
    base = settings.supabase_project_url
    if base is None:
        return None
    base = base.rstrip("/")
    return SupabaseVerifier(
        keys=jwt.PyJWKClient(f"{base}/auth/v1/.well-known/jwks.json"),
        issuer=f"{base}/auth/v1",
    )


def bearer_token(header: str | None) -> str | None:
    """The credential out of an `Authorization` header, or None.

    Case-insensitive on the scheme because RFC 7235 says the scheme is, and a
    client that sends `bearer` is not an attacker — it is a client.
    """
    if not header:
        return None
    scheme, _, credential = header.partition(" ")
    if scheme.lower() != "bearer" or not credential.strip():
        return None
    return credential.strip()


class AccountDeleter(Protocol):
    """Erases an account at the identity provider."""

    def delete(self, subject: str) -> None: ...


class DeletionFailed(Exception):
    """The provider did not confirm the erasure. Never carries its response."""


@dataclass(frozen=True)
class SupabaseAccountDeleter:
    """Asks Supabase to erase a user, address and all.

    The address is the personal data, and it lives in the provider's managed
    `auth.users` table — inside this project's own Postgres, which is why 063
    had to narrow its no-PII claim. So erasure *is* this call: the tables this
    application writes hold an opaque subject id and a timestamp, and nothing
    that could name a person.

    A hard delete, not a soft one: the default `shouldSoftDelete: false`
    "removes the row from `auth.users`, which cascades to `auth.sessions`"
    (`supabase.com/docs/guides/auth/managing-user-data`, read 2026-08-24). It
    does not reach backwards, though — the same page is explicit that "deleting
    the user still cannot retroactively invalidate an access token that was
    already issued", so a token in flight keeps working until it expires. What
    this codebase does about that hour is `main.forget_me`'s comment.
    """

    project_url: str
    service_key: str

    def delete(self, subject: str) -> None:
        # Route confirmed against the auth server's own router
        # (`supabase/auth`, internal/api/api.go: /admin/users/{user_id},
        # r.Delete) rather than inferred — the REST path appears in no prose
        # doc, which only ships the JavaScript admin client.
        response = httpx.request(
            "DELETE",
            f"{self.project_url}/auth/v1/admin/users/{subject}",
            headers={
                # Bearer authenticates to the auth server; `apikey` is what the
                # project's API gateway in front of it requires. Both are the
                # elevated key, which is why this object never reaches a
                # request handler that did not verify a session first.
                "Authorization": f"Bearer {self.service_key}",
                "apikey": self.service_key,
            },
        )
        if response.is_error:
            # The provider's body is not repeated: it is third-party text, and
            # this codebase's refusals are its own sentences (013).
            raise DeletionFailed


def deleter_from_settings() -> SupabaseAccountDeleter | None:
    """The project's account deleter, or None when no elevated key is set.

    None is not "deletion is off" — it is "this deployment cannot honour a
    deletion request", which the endpoint must say out loud rather than
    answering 204 to a request it did not carry out.
    """
    base = settings.supabase_project_url
    key = settings.supabase_service_key
    if base is None or key is None:
        return None
    return SupabaseAccountDeleter(
        project_url=base.rstrip("/"), service_key=key.get_secret_value()
    )
