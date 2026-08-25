"""The edge proves who is spending (063/#158).

Every test here mints a real ES256 token against a real key and verifies it
through the real library — the only thing stubbed is the network fetch of the
key set, because the point under test is the verification, not the transport.
"""

import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from app.auth import InvalidSession, SessionUnverifiable, SupabaseVerifier

ISSUER = "https://project-ref.supabase.co/auth/v1"


def _keypair(kid: str):
    """A signing key and the public JWK the project would publish for it."""
    private = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(ECAlgorithm.to_jwk(private.public_key()))
    jwk |= {"kid": kid, "alg": "ES256", "use": "sig"}
    return private, jwk


class _PublishedKeys:
    """Stands in for the project's .well-known/jwks.json, resolved by `kid`."""

    def __init__(self, *jwks: dict):
        self._by_kid = {key["kid"]: jwt.PyJWK(key, algorithm="ES256") for key in jwks}

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        kid = jwt.get_unverified_header(token).get("kid")
        if kid not in self._by_kid:
            # What PyJWKClient raises once a refresh still cannot find the kid.
            raise jwt.exceptions.PyJWKClientError(f"unknown kid {kid!r}")
        return self._by_kid[kid]


def _token(private, kid, **claims) -> str:
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
        "role": "authenticated",
    } | claims
    return jwt.encode(payload, private, algorithm="ES256", headers={"kid": kid})


@pytest.fixture
def signing():
    private, jwk = _keypair("live")
    verifier = SupabaseVerifier(keys=_PublishedKeys(jwk), issuer=ISSUER)
    return private, verifier


def test_a_token_signed_by_the_project_yields_its_subject(signing):
    private, verifier = signing
    subject = str(uuid.uuid4())

    assert verifier.subject(_token(private, "live", sub=subject)) == subject


def test_a_token_signed_by_another_key_is_refused(signing):
    _, verifier = signing
    # The attack the whole dependency exists to stop: a well-formed token whose
    # claims are perfect and whose signature is somebody else's.
    forged, _ = _keypair("live")

    with pytest.raises(InvalidSession):
        verifier.subject(_token(forged, "live"))


def test_a_token_from_an_unknown_key_is_refused(signing):
    private, verifier = signing
    stranger, _ = _keypair("not-published")

    with pytest.raises(InvalidSession):
        verifier.subject(_token(stranger, "not-published"))


def test_an_expired_token_is_refused(signing):
    private, verifier = signing

    with pytest.raises(InvalidSession):
        verifier.subject(_token(private, "live", exp=int(time.time()) - 1))


def test_a_token_for_another_audience_is_refused(signing):
    private, verifier = signing
    # `anon` is a real Supabase audience and is precisely not a signed-in person.
    with pytest.raises(InvalidSession):
        verifier.subject(_token(private, "live", aud="anon"))


def test_a_token_from_another_issuer_is_refused(signing):
    private, verifier = signing
    # Same algorithm, same shape, another project's URL.
    with pytest.raises(InvalidSession):
        verifier.subject(
            _token(private, "live", iss="https://evil.supabase.co/auth/v1")
        )


def test_an_unsigned_token_is_refused(signing):
    _, verifier = signing
    unsigned = jwt.encode(
        {"sub": "anyone", "aud": "authenticated", "iss": ISSUER},
        key="",
        algorithm="none",
    )

    with pytest.raises(InvalidSession):
        verifier.subject(unsigned)


def test_a_token_carrying_no_subject_is_refused(signing):
    private, verifier = signing
    # There is nothing to charge, so there is no one to let in.
    with pytest.raises(InvalidSession):
        verifier.subject(_token(private, "live", sub=None))


def test_the_verifier_never_returns_the_email_it_was_handed(signing):
    private, verifier = signing
    # The address rides in the token (research: jwt-fields) and stops here:
    # what the application keeps is the subject id and nothing else.
    subject = str(uuid.uuid4())
    token = _token(private, "live", sub=subject, email="someone@example.com")

    assert verifier.subject(token) == subject


def test_an_unreachable_key_server_is_not_the_visitor_s_fault(signing):
    """ "Your session is invalid" and "I cannot reach the key server" have
    opposite remedies, and telling a signed-in person to sign in again when the
    provider is down sends them round a loop that cannot end."""
    private, verifier = signing

    class Unreachable:
        def get_signing_key_from_jwt(self, token):
            raise jwt.exceptions.PyJWKClientConnectionError("no route")

    offline = SupabaseVerifier(keys=Unreachable(), issuer=ISSUER)

    with pytest.raises(SessionUnverifiable):
        offline.subject(_token(private, "live"))


def test_a_refusal_leaves_the_operator_something_to_read(signing, caplog):
    """The caller is told nothing beyond "not accepted" — but a wave of
    refusals caused by a misconfigured project and one caused by a forged token
    look identical in the logs otherwise, and only one of them is fixable."""
    private, verifier = signing
    forged, _ = _keypair("live")

    with caplog.at_level("WARNING"), pytest.raises(InvalidSession):
        verifier.subject(_token(forged, "live"))

    assert caplog.records, "a rejected session must leave a log line"


def test_the_log_line_never_repeats_the_token(signing, caplog):
    """A rejected token is still a credential — it may be a real one sent to
    the wrong project."""
    private, verifier = signing
    token = _token(private, "live", iss="https://elsewhere.supabase.co/auth/v1")

    with caplog.at_level("WARNING"), pytest.raises(InvalidSession):
        verifier.subject(token)

    assert token not in caplog.text
