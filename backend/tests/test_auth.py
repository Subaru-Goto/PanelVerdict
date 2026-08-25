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

from app.auth import InvalidSession, SupabaseVerifier

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
def signed():
    private, jwk = _keypair("live")
    verifier = SupabaseVerifier(keys=_PublishedKeys(jwk), issuer=ISSUER)
    return private, verifier


def test_a_token_signed_by_the_project_yields_its_subject(signed):
    private, verifier = signed
    subject = str(uuid.uuid4())

    assert verifier.subject(_token(private, "live", sub=subject)) == subject


def test_a_token_signed_by_another_key_is_refused(signed):
    _, verifier = signed
    # The attack the whole dependency exists to stop: a well-formed token whose
    # claims are perfect and whose signature is somebody else's.
    forged, _ = _keypair("live")

    with pytest.raises(InvalidSession):
        verifier.subject(_token(forged, "live"))


def test_a_token_from_an_unknown_key_is_refused(signed):
    private, verifier = signed
    stranger, _ = _keypair("not-published")

    with pytest.raises(InvalidSession):
        verifier.subject(_token(stranger, "not-published"))


def test_an_expired_token_is_refused(signed):
    private, verifier = signed

    with pytest.raises(InvalidSession):
        verifier.subject(_token(private, "live", exp=int(time.time()) - 1))


def test_a_token_for_another_audience_is_refused(signed):
    private, verifier = signed
    # `anon` is a real Supabase audience and is precisely not a signed-in person.
    with pytest.raises(InvalidSession):
        verifier.subject(_token(private, "live", aud="anon"))


def test_a_token_from_another_issuer_is_refused(signed):
    private, verifier = signed
    # Same algorithm, same shape, another project's URL.
    with pytest.raises(InvalidSession):
        verifier.subject(
            _token(private, "live", iss="https://evil.supabase.co/auth/v1")
        )


def test_an_unsigned_token_is_refused(signed):
    _, verifier = signed
    unsigned = jwt.encode(
        {"sub": "anyone", "aud": "authenticated", "iss": ISSUER},
        key="",
        algorithm="none",
    )

    with pytest.raises(InvalidSession):
        verifier.subject(unsigned)


def test_a_token_carrying_no_subject_is_refused(signed):
    private, verifier = signed
    # There is nothing to charge, so there is no one to let in.
    with pytest.raises(InvalidSession):
        verifier.subject(_token(private, "live", sub=None))


def test_the_verifier_never_returns_the_email_it_was_handed(signed):
    private, verifier = signed
    # The address rides in the token (research: jwt-fields) and stops here:
    # what the application keeps is the subject id and nothing else.
    subject = str(uuid.uuid4())
    token = _token(private, "live", sub=subject, email="someone@example.com")

    assert verifier.subject(token) == subject
