import bcrypt
import pytest

from app.core.dependencies import get_current_user
from app.core.limiter import limiter
from app.main import app
from app.models.user import User
from app.schemas.token import TokenData

# POST /auth/change-password: any logged-in user changes their own
# password by giving the current one plus a new one.
#
# Each test makes its own brand-new user (`make_user`) because a
# password change must never touch the shared accounts in `staff` or
# the SuperAdmin that every other test file logs in as.

TEST_PASSWORD = "TestPass123!"
NEW_PASSWORD = "NewPass456!"


def change(client, headers, old=TEST_PASSWORD, new=NEW_PASSWORD):
    return client.post(
        "/auth/change-password",
        json={"old_password": old, "new_password": new},
        headers=headers,
    )


def login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def stored_hash(db_session, user_id):
    db_session.expire_all()
    return db_session.query(User).filter(User.id == user_id).first().pass_hash


def matches(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())


@pytest.mark.parametrize("role", ["Doctor", "Nurse", "Admin"])
def test_a_user_changes_their_own_password(role, client, db_session, make_user, watch_audit):
    user = make_user(role)
    old_hash = stored_hash(db_session, user["id"])
    logged = watch_audit("PASSWORD_CHANGE_SUCCESSFUL", user_id=user["id"])

    response = change(client, user["headers"])

    assert response.status_code == 200
    assert response.json() == {"message": "Password changed successfully"}

    new_hash = stored_hash(db_session, user["id"])
    assert new_hash != old_hash
    assert new_hash.startswith("$2b$")
    assert matches(NEW_PASSWORD, new_hash)
    assert not matches(TEST_PASSWORD, new_hash)

    assert login(client, user["email"], NEW_PASSWORD).status_code == 200
    assert login(client, user["email"], TEST_PASSWORD).status_code == 401

    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_type == "users"
    assert row.entity_id == user["id"]


def test_a_wrong_current_password_is_refused(client, db_session, make_user, watch_audit):
    user = make_user("Nurse")
    old_hash = stored_hash(db_session, user["id"])
    logged = watch_audit("PASSWORD_CHANGE_FAILED", user_id=user["id"])

    response = change(client, user["headers"], old="WrongPass123!")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"
    assert stored_hash(db_session, user["id"]) == old_hash
    assert login(client, user["email"], TEST_PASSWORD).status_code == 200
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_type == "users"
    assert row.entity_id == user["id"]


@pytest.mark.parametrize("old", ["A" * 72, "A" * 73, "é" * 37], ids=["72 bytes", "73 bytes", "74 bytes (37 letters)"])
def test_a_wrong_current_password_of_any_length_is_a_plain_401(old, client, db_session, make_user, watch_audit):
    # bcrypt only reads 72 bytes, so anything longer is refused before it
    # gets near the hashing step. The answer is the same either way.
    user = make_user("Nurse")
    old_hash = stored_hash(db_session, user["id"])
    logged = watch_audit("PASSWORD_CHANGE_FAILED", user_id=user["id"])

    response = change(client, user["headers"], old=old)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"
    assert stored_hash(db_session, user["id"]) == old_hash
    assert logged() is not None


@pytest.mark.parametrize(
    "new",
    [
        "Ab1!xyz",            # 7 characters
        "newpass456!",        # no capital letter
        "NewPass!!!!",        # no number
        "NewPass4567",        # no special character
        "Aa1!" + "x" * 69,    # 73 bytes
        TEST_PASSWORD,        # same as the current one
    ],
    ids=["too short", "no capital", "no number", "no special", "73 bytes", "same as current"],
)
def test_a_weak_or_unchanged_new_password_is_refused(new, client, db_session, make_user):
    user = make_user("Nurse")
    old_hash = stored_hash(db_session, user["id"])

    response = change(client, user["headers"], new=new)

    assert response.status_code == 422
    assert stored_hash(db_session, user["id"]) == old_hash
    assert login(client, user["email"], TEST_PASSWORD).status_code == 200


def test_the_new_password_must_differ_from_the_current_one(client, make_user):
    user = make_user("Nurse")

    response = change(client, user["headers"], new=TEST_PASSWORD)

    assert "must be different" in response.text


@pytest.mark.parametrize("new", ["Abcdef1!", "Aa1!" + "x" * 68], ids=["8 characters", "72 bytes"])
def test_new_passwords_at_the_length_limits_are_accepted(new, client, make_user):
    user = make_user("Nurse")

    assert change(client, user["headers"], new=new).status_code == 200
    assert login(client, user["email"], new).status_code == 200


@pytest.mark.parametrize(
    "body",
    [{"old_password": TEST_PASSWORD}, {"new_password": NEW_PASSWORD}, {}],
    ids=["no new password", "no old password", "empty body"],
)
def test_both_passwords_are_required(body, client, make_user):
    user = make_user("Nurse")

    response = client.post("/auth/change-password", json=body, headers=user["headers"])

    assert response.status_code == 422


def test_change_password_requires_login(client):
    response = client.post(
        "/auth/change-password",
        json={"old_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 401


def test_a_garbage_token_cannot_change_a_password(client):
    assert change(client, {"Authorization": "Bearer not.a.token"}).status_code == 401


def test_a_deactivated_user_cannot_change_their_password(client, db_session, make_user, superadmin):
    user = make_user("Nurse")
    old_hash = stored_hash(db_session, user["id"])
    client.post(f"/users/{user['id']}/deactivate", headers=superadmin["headers"])

    response = change(client, user["headers"])

    assert response.status_code == 401
    assert stored_hash(db_session, user["id"]) == old_hash


def test_changing_one_password_does_not_affect_other_users(client, make_user):
    first = make_user("Nurse")
    second = make_user("Nurse")

    change(client, first["headers"])

    assert login(client, second["email"], TEST_PASSWORD).status_code == 200
    assert login(client, first["email"], TEST_PASSWORD).status_code == 401


def test_a_user_that_no_longer_exists_gets_404(client):
    # Defensive branch: the login check normally stops this first, so it
    # is reached here by swapping the login check for one that always
    # says "user 999999999". (No audit row is checked on purpose: the row
    # would name a user that does not exist, the database refuses it, and
    # log_action swallows the error. See the known-issues queue.)
    app.dependency_overrides[get_current_user] = lambda: TokenData(user_id=999999999, role="Nurse")
    try:
        response = change(client, headers={})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 404
    assert response.json()["detail"] == "Invalid credentials"


def test_tokens_issued_before_a_password_change_keep_working(client, make_user):
    # KNOWN LIMITATION (stateless tokens): changing the password does not
    # end sessions that already exist. The old token works until it
    # expires on its own (30 minutes). This pins that behaviour; if
    # token revocation is ever added, this is the test to change.
    admin = make_user("Admin")

    change(client, admin["headers"])

    assert client.get("/users/doctors", headers=admin["headers"]).status_code == 200


def test_change_password_is_limited_to_five_attempts_per_minute(client, make_user):
    user = make_user("Nurse")
    limiter.reset()
    limiter.enabled = True
    try:
        for _ in range(5):
            assert change(client, user["headers"], old="WrongPass123!").status_code == 401
        assert change(client, user["headers"], old="WrongPass123!").status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()