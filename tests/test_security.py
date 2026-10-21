import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest

from app.core import jwt as app_jwt
from app.core.security import hash_password, verify_password
from app.models.user import Role, User
from app.schemas.token import TokenData

# The security building blocks: login tokens (core/jwt.py), password
# hashing (core/security.py) and a few account rules at the door.
#
# Token tests forge their own tokens with the app's real secret key, so
# a "wrong" token can be wrong in exactly one way. A sanity test first
# proves a hand-made token is accepted when it is right.

TEST_PASSWORD = "TestPass123!"


def sign(payload, key=None, algorithm=None):
    return pyjwt.encode(payload, key or app_jwt.SECRET_KEY, algorithm or app_jwt.ALGORITHM)


def soon(minutes=5):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def call(client, token):
    # Any route that needs a login will do. This one answers 200 for an Admin.
    return client.get("/users/doctors", headers={"Authorization": f"Bearer {token}"})


# ======================================================================
# Login tokens
# ======================================================================

def test_a_token_carries_the_user_and_role_and_expires_after_the_configured_time():
    token = app_jwt.create_access_token(user_id=42, role="Doctor")

    data = app_jwt.verify_token(token)
    assert data == TokenData(user_id=42, role="Doctor")

    claims = pyjwt.decode(token, app_jwt.SECRET_KEY, algorithms=[app_jwt.ALGORITHM])
    expected = datetime.now(timezone.utc) + timedelta(minutes=app_jwt.ACCESS_TOKEN_EXPIRE_MINUTES)
    assert abs(datetime.fromtimestamp(claims["exp"], timezone.utc) - expected) < timedelta(seconds=60)


def test_a_correctly_signed_token_is_accepted(client, staff):
    # Sanity check for every rejection test below: if this fails, the
    # forging helper is wrong and the other results mean nothing.
    token = sign({"user_id": staff["admin"]["id"], "role": "Admin", "exp": soon()})

    assert call(client, token).status_code == 200


def test_an_expired_token_is_rejected(client, staff, watch_audit):
    token = sign({"user_id": staff["admin"]["id"], "role": "Admin", "exp": soon(minutes=-5)})
    logged = watch_audit("TOKEN_VERIFICATION_FAILED")

    response = call(client, token)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.user_id is None


def test_a_token_signed_with_the_wrong_key_is_rejected(client, staff):
    token = sign({"user_id": staff["admin"]["id"], "role": "Admin", "exp": soon()}, key="x" * 40)

    assert call(client, token).status_code == 401


def test_a_token_with_an_edited_role_is_rejected(client, staff):
    # A nurse takes their own valid token, rewrites the role to Admin and
    # keeps the old signature. The signature no longer matches.
    nurse_token = sign({"user_id": staff["nurse"]["id"], "role": "Nurse", "exp": soon()})
    header, payload, signature = nurse_token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["role"] = "Admin"
    edited = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()

    response = call(client, f"{header}.{edited}.{signature}")

    assert response.status_code == 401


def test_a_token_with_no_signature_algorithm_is_rejected(client, staff):
    # The classic "alg: none" attack: a token that claims it needs no signature.
    token = pyjwt.encode({"user_id": staff["admin"]["id"], "role": "Admin", "exp": soon()}, None, algorithm="none")

    assert call(client, token).status_code == 401


@pytest.mark.filterwarnings("ignore:The HMAC key is")
def test_a_token_signed_with_a_different_algorithm_is_rejected(client, staff):
    # Same key, but HS512 instead of the configured algorithm.
    token = sign({"user_id": staff["admin"]["id"], "role": "Admin", "exp": soon()}, algorithm="HS512")

    assert call(client, token).status_code == 401


@pytest.mark.parametrize("token", ["not.a.token", "abc", "a.b.c", "eyJhbGciOiJIUzI1NiJ9.e30."])
def test_garbage_tokens_are_rejected(token, client, watch_audit):
    logged = watch_audit("TOKEN_VERIFICATION_FAILED")

    response = call(client, token)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"
    assert logged() is not None


def test_a_request_with_no_token_is_rejected(client):
    response = client.get("/users/doctors")

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_a_non_bearer_authorization_header_is_rejected(client):
    response = client.get("/users/doctors", headers={"Authorization": "Basic YWRtaW46cGFzc3dvcmQ="})

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_a_signed_token_for_a_user_that_does_not_exist_is_rejected(client):
    token = sign({"user_id": 999999999, "role": "Admin", "exp": soon()})

    response = call(client, token)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


# KNOWN BUG, pinned as "expected to fail". A token that is correctly
# signed but has the wrong contents crashes the server (500) instead of
# being refused (401): verify_token only catches the library's own errors,
# not a missing claim (KeyError) or a bad value (ValidationError). Hard to
# trigger in practice because the signing key is needed, but a 500 is
# never the right answer. Fix: catch those two in verify_token, then
# delete the marker.
@pytest.mark.xfail(strict=True, reason="a signed token with bad contents gives a 500 instead of a 401")
@pytest.mark.parametrize(
    "claims",
    [
        {"user_id": 1, "exp": 1},        # no role
        {"role": "Admin", "exp": 1},     # no user_id
        {"user_id": 1, "role": "Hacker", "exp": 1},   # role that does not exist
        {"user_id": "abc", "role": "Admin", "exp": 1},  # user_id is not a number
    ],
    ids=["no role", "no user_id", "unknown role", "user_id is text"],
)
def test_a_signed_token_with_bad_contents_is_refused_cleanly(claims, client):
    token = sign({**claims, "exp": soon()})

    response = call(client, token)

    assert response.status_code == 401


# ======================================================================
# Password hashing
# ======================================================================

def test_hashes_are_bcrypt_and_never_the_password():
    hashed = hash_password(TEST_PASSWORD)

    assert hashed.startswith("$2b$12$")
    assert len(hashed) == 60
    assert TEST_PASSWORD not in hashed


def test_the_same_password_hashes_differently_each_time():
    # A fresh random salt every time, so two users with the same
    # password do not have the same hash.
    assert hash_password(TEST_PASSWORD) != hash_password(TEST_PASSWORD)


def test_verify_password_accepts_the_right_password_and_nothing_else():
    hashed = hash_password("Correct-Horse1!")

    assert verify_password("Correct-Horse1!", hashed) is True
    assert verify_password("correct-horse1!", hashed) is False  # letter case matters
    assert verify_password("Correct-Horse1! ", hashed) is False  # so do spaces
    assert verify_password("", hashed) is False


def test_passwords_with_non_english_letters_work():
    hashed = hash_password("Pässwörd-1!")

    assert verify_password("Pässwörd-1!", hashed) is True
    assert verify_password("Passwoerd-1!", hashed) is False


def test_a_72_byte_password_works_and_a_73_byte_one_is_refused_by_the_library():
    # This is why the API rejects anything over 72 bytes before hashing.
    assert verify_password("A" * 72, hash_password("A" * 72)) is True
    with pytest.raises(ValueError):
        hash_password("A" * 73)


def test_the_database_stores_only_the_hash(client, db_session, make_user):
    user = make_user("Nurse")

    db_session.expire_all()
    stored = db_session.query(User).filter(User.id == user["id"]).first().pass_hash

    assert stored.startswith("$2b$")
    assert TEST_PASSWORD not in stored
    assert verify_password(TEST_PASSWORD, stored) is True


# ======================================================================
# Account rules at the door
# ======================================================================

# KNOWN BUG, pinned as "expected to fail". A deactivated user can still
# log in: they get a token and the audit log says LOGIN_SUCCESS. The token
# is useless afterwards (every other route refuses it, see
# test_user.py::test_deactivated_user_token_rejected), so this is a
# correctness and logging problem, not a way in. Fix: refuse login for an
# inactive user (401, same message as a wrong password), then delete the marker.
@pytest.mark.xfail(strict=True, reason="a deactivated user can still log in and get a token")
def test_a_deactivated_user_cannot_log_in(client, make_user, superadmin):
    user = make_user("Nurse")
    client.post(f"/users/{user['id']}/deactivate", headers=superadmin["headers"])

    response = client.post("/auth/login", json={"email": user["email"], "password": TEST_PASSWORD})

    assert response.status_code == 401


# KNOWN BUG, pinned as "expected to fail". Two emails that differ only in
# upper/lower case are accepted as two different accounts, and logging in
# with one never reaches the other. Fix: lowercase the email on the way in
# (and add a unique index on the lowercased value), then delete the marker.
@pytest.mark.xfail(strict=True, reason="emails that differ only in letter case count as different accounts")
def test_an_email_that_differs_only_in_letter_case_is_a_duplicate(client, db_session, superadmin):
    role = db_session.query(Role).filter(Role.role_name == "Nurse").first()
    tag = uuid.uuid4().hex[:8]

    def create(email):
        return client.post(
            "/users/create",
            json={"full_name": "Case Test", "email": email, "password": TEST_PASSWORD, "role_id": role.id},
            headers=superadmin["headers"],
        )

    assert create(f"Case.{tag}@example.com").status_code == 200

    second = create(f"case.{tag}@example.com")

    assert second.status_code == 400