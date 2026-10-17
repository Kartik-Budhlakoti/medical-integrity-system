import pytest

from app.models.user import Role, User
from app.models.audit_log import AuditLog

TEST_PASSWORD = "TestPass123!"

@pytest.mark.first
def test_login_rate_limit_blocks_after_five_attempts(client):
    """
    Needs the real rate limiter active, so it's marked to run before
    everything else in the suite (conftest.py's
    pytest_collection_modifyitems enforces this). Disables rate limiting
    at the end for every test that runs after it — the rest of the
    suite calls /auth/login and /bootstrap/superadmin far more times
    than the real limits allow, since they share one in-memory bucket
    with no reset between tests.
    """
    from app.core.limiter import limiter
    try:
        for _ in range(5):
            response = client.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever"})
            assert response.status_code == 401

        response = client.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever"})
        assert response.status_code == 429
    finally:
        limiter.enabled = False

def test_bootstrap_fails_when_superadmin_role_missing(client, db_session):
# Precondition: some role exists, but not "SuperAdmin"— the endpoint's
# seeding logic only runs when NO role exists at all, so one unrelated
# role is enough to skip seeding and hit the 500 branch.
    fake_role = Role(role_name="Nurse", dept_name="Medical")
    db_session.add(fake_role)
    db_session.commit()

    response = client.post("/bootstrap/superadmin", json={
        "full_name": "Test Admin",
        "email": "first-admin@example.com",
        "password": TEST_PASSWORD,
    })

    assert response.status_code == 500
    assert response.json()["detail"] == "SuperAdmin role not found"

    log_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "SYSTEM_INITIALIZATION_FAILED", AuditLog.entity_type == "roles")
        .first()
    )
    assert log_entry is not None
    assert log_entry.result == "FAILURE"

    # Clean up — the next test expects a genuinely empty roles table.
    db_session.delete(fake_role)
    db_session.commit()


def test_bootstrap_creates_first_superadmin(client, db_session):
    response = client.post("/bootstrap/superadmin", json={
        "full_name": "Test SuperAdmin",
        "email": "superadmin@example.com",
        "password": TEST_PASSWORD,
    })

    assert response.status_code == 200
    assert response.json()["message"] == "System initialized successfully"

    superadmin = db_session.query(User).filter(User.email == "superadmin@example.com").first()
    log_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "SYSTEM_INITIALIZED", AuditLog.user_id == superadmin.id)
        .first()
    )
    assert log_entry is not None
    assert log_entry.result == "SUCCESS"


def test_bootstrap_rejects_second_call(client, db_session):
    response = client.post("/bootstrap/superadmin", json={
        "full_name": "Second Admin",
        "email": "second-admin@example.com",
        "password": TEST_PASSWORD,
    })

    assert response.status_code == 403
    assert response.json()["detail"] == "System already initialized"

    log_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "SYSTEM_INITIALIZATION_FAILED", AuditLog.entity_type == "users")
        .first()
    )
    assert log_entry is not None
    assert log_entry.result == "FAILURE"

def test_bootstrap_rate_limit_blocks_after_three_attempts(client):
    from app.core.limiter import limiter
    body = {"full_name": "Rate Limit Probe", "email": "ratelimit-probe@example.com", "password": TEST_PASSWORD}
    limiter.reset()
    limiter.enabled = True
    try:
        for _ in range(3):
            assert client.post("/bootstrap/superadmin", json=body).status_code == 403
        assert client.post("/bootstrap/superadmin", json=body).status_code == 429
    finally:
        limiter.enabled = False


def test_login_success(client, db_session):
    response = client.post("/auth/login", json={
        "email": "superadmin@example.com",
        "password": TEST_PASSWORD,
    })

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"

    superadmin = db_session.query(User).filter(User.email == "superadmin@example.com").first()
    log_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "LOGIN_SUCCESS", AuditLog.user_id == superadmin.id)
        .first()
    )
    assert log_entry is not None
    assert log_entry.result == "SUCCESS"


def test_login_nonexistent_email(client):
    response = client.post("/auth/login", json={
        "email": "nobody@example.com",
        "password": "whatever",
    })

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_login_wrong_password(client):
    # Deliberately asserting the exact same detail string as the
    # nonexistent-email case above — confirms no user-enumeration leak
    # via the error message.
    response = client.post("/auth/login", json={
        "email": "superadmin@example.com",
        "password": "WrongPassword123!",
    })

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_login_oversized_password(client):
    response = client.post("/auth/login", json={
        "email": "superadmin@example.com",
        "password": "a" * 73,
    })

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"

