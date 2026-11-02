import pytest

from app.models.user import Role, User
from app.models.audit_log import AuditLog

TEST_PASSWORD = "TestPass123!"
TEST_BOOTSTRAP_TOKEN = "test-bootstrap-token"

@pytest.fixture()
def bootstrap_headers(monkeypatch):
    """Configures the setup token for one test and returns the header that matches it."""
    monkeypatch.setenv("BOOTSTRAP_TOKEN", TEST_BOOTSTRAP_TOKEN)
    return {"X-Bootstrap-Token": TEST_BOOTSTRAP_TOKEN}


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

def test_bootstrap_rejects_missing_token(client, db_session, bootstrap_headers):
    # The token is configured, but this request doesn't send the header.
    response = client.post("/bootstrap/superadmin", json={
        "full_name": "No Token",
        "email": "no-token@example.com",
        "password": TEST_PASSWORD,
    })

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid setup token"
    assert db_session.query(User).filter(User.email == "no-token@example.com").first() is None


def test_bootstrap_rejects_wrong_token(client, db_session, bootstrap_headers):
    response = client.post("/bootstrap/superadmin", json={
        "full_name": "Wrong Token",
        "email": "wrong-token@example.com",
        "password": TEST_PASSWORD,
    }, headers={"X-Bootstrap-Token": "not-the-token"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid setup token"
    assert db_session.query(User).filter(User.email == "wrong-token@example.com").first() is None


@pytest.mark.parametrize("configured", [None, ""], ids=["unset", "empty"])
def test_bootstrap_refuses_everyone_when_token_not_configured(client, db_session, monkeypatch, configured):
    # Fails closed: an unset OR empty setting must never match an empty header.
    if configured is None:
        monkeypatch.delenv("BOOTSTRAP_TOKEN", raising=False)
    else:
        monkeypatch.setenv("BOOTSTRAP_TOKEN", configured)

    response = client.post("/bootstrap/superadmin", json={
        "full_name": "Unconfigured",
        "email": "unconfigured@example.com",
        "password": TEST_PASSWORD,
    }, headers={"X-Bootstrap-Token": ""})

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid setup token"
    assert db_session.query(User).filter(User.email == "unconfigured@example.com").first() is None
    

def test_bootstrap_fails_when_superadmin_role_missing(client, db_session, bootstrap_headers):
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
    }, headers=bootstrap_headers)

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


def test_bootstrap_creates_first_superadmin(client, db_session, bootstrap_headers):
    response = client.post("/bootstrap/superadmin", json={
        "full_name": "Test SuperAdmin",
        "email": "superadmin@example.com",
        "password": TEST_PASSWORD,
    }, headers=bootstrap_headers)

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


def test_bootstrap_rejects_second_call(client, db_session, bootstrap_headers):
    response = client.post("/bootstrap/superadmin", json={
        "full_name": "Second Admin",
        "email": "second-admin@example.com",
        "password": TEST_PASSWORD,
    }, headers=bootstrap_headers)

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

