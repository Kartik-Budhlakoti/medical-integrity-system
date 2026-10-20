import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine.url import make_url

from app.core.limiter import limiter
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.audit_log import AuditLog
from app.models.user import Role, User

SAFE_HOSTS = {"localhost", "127.0.0.1"}

MODULE_ORDER = ["test_auth.py", "test_user.py"]

TEST_PASSWORD = "TestPass123!"
SUPERADMIN_EMAIL = "superadmin@example.com"


def pytest_collection_modifyitems(items):
    """
    Controls the order tests run in.

    1. Any test marked @pytest.mark.first runs before everything else
       (the login rate-limit test needs the real limiter before
       anything switches it off).
    2. Then the files in MODULE_ORDER. test_auth.py must come first:
       its bootstrap tests need an empty database and create the
       superadmin every other file logs in as. test_user.py comes next
       because its last test expects exactly two Admin accounts.
    3. Every other test file runs after those, alphabetically.

    Python's sort is stable, so tests inside one file keep the order
    they are written in.
    """
    def rank(item):
        if item.get_closest_marker("first"):
            return -1
        name = item.path.name
        if name in MODULE_ORDER:
            return MODULE_ORDER.index(name)
        return len(MODULE_ORDER)

    items.sort(key=rank)


@pytest.fixture(scope="session", autouse=True)
def fresh_test_database():
    """
    Drops and recreates the test database before anything else runs, so
    local runs start from the same empty state CI gets automatically from
    its throwaway container. Connects to the always-present `postgres`
    system database to do it, since you can't drop a database you're
    connected to. Refuses to run unless DATABASE_URL points at a *_test
    database on localhost — that's the one thing standing between a
    forgotten `export` (or a remote URL like Neon) and losing real data.
    """
    test_url = make_url(os.environ["DATABASE_URL"])
    if test_url.host not in SAFE_HOSTS or not (test_url.database or "").endswith("_test"):
        pytest.exit(
            f"Refusing to drop/recreate '{test_url.database}' on host '{test_url.host}': "
            "tests only run against a *_test database on localhost. "
            "Did you forget to export DATABASE_URL in this terminal?",
            returncode=2,
        )

    admin_url = test_url.set(database="postgres")
    conn = psycopg2.connect(admin_url.render_as_string(hide_password=False))
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{test_url.database}"')
        cur.execute(f'CREATE DATABASE "{test_url.database}"')
    conn.close()
    yield


@pytest.fixture(scope="session", autouse=True)
def create_test_tables(fresh_test_database):
    """
    Runs once, before any test in the whole session, right after
    fresh_test_database empties the database out. Creates every table
    registered on Base.metadata (SQLAlchemy already knows about all your
    models because app.main imports app.models, which conftest.py pulls
    in by importing `app` above). No teardown needed either way — in CI
    the container is destroyed when the job ends, and locally the next
    run's fresh_test_database drops it again before anything runs.
    """
    Base.metadata.create_all(bind=engine)


@pytest.fixture()
def client():
    """
    A fresh TestClient per test function. No dependency override —
    app.database.get_db already points at the test database, because
    DATABASE_URL is set before this process starts. The `with` form
    (rather than just TestClient(app)) makes sure any startup/shutdown
    events run, if you ever add any — costs nothing if you don't have
    any now.
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db_session():
    """
    Direct DB access for tests that need to set up state the API can't
    (the role-missing edge case) or verify what the HTTP response alone
    doesn't show (audit log rows).
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------
# Shared helpers for the test files that come after test_auth/test_user
# ---------------------------------------------------------------------

def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _login(client, email):
    response = client.post("/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200, f"login failed for {email}: {response.status_code} {response.text}"
    return response.json()["access_token"]


def _create_user(client, db, superadmin_headers, role_name):
    """Creates one user through the real API and logs them in."""
    role = db.query(Role).filter(Role.role_name == role_name).first()
    email = f"{role_name.lower()}-{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "full_name": f"{role_name} Test",
        "email": email,
        "password": TEST_PASSWORD,
        "role_id": role.id,
    }
    if role_name == "Doctor":
        payload["specialty"] = "General Medicine"
    response = client.post("/users/create", json=payload, headers=superadmin_headers)
    assert response.status_code == 200, f"user setup failed: {response.status_code} {response.text}"
    return {
        "id": response.json()["id"],
        "email": email,
        "headers": _headers(_login(client, email)),
    }


@pytest.fixture(scope="session")
def superadmin_ready(create_test_tables):
    """
    Makes sure the SuperAdmin account exists. In a normal full run
    test_auth.py has already created it (it always runs first), so this
    does nothing. It only matters when you run a single file on its own,
    e.g. `pytest tests/test_patient.py`: the test database starts empty
    every run, so without this the very first login would fail.

    Also switches the rate limiter off. The tests after the first one
    log in far more often than the real limits allow (see the docstring
    on the rate-limit test in test_auth.py).
    """
    limiter.enabled = False
    db = SessionLocal()
    try:
        exists = db.query(User).filter(User.email == SUPERADMIN_EMAIL).first() is not None
    finally:
        db.close()
    if not exists:
        with TestClient(app) as c:
            response = c.post("/bootstrap/superadmin", json={
                "full_name": "Test SuperAdmin",
                "email": SUPERADMIN_EMAIL,
                "password": TEST_PASSWORD,
            })
        assert response.status_code == 200, (
            f"could not create the SuperAdmin account: {response.status_code} {response.text}"
        )


@pytest.fixture()
def superadmin_token(client, superadmin_ready):
    response = client.post("/auth/login", json={
        "email": SUPERADMIN_EMAIL,
        "password": TEST_PASSWORD,
    })
    assert response.status_code == 200, (
        f"SuperAdmin login failed ({response.status_code}): {response.text}"
    )
    return response.json()["access_token"]


@pytest.fixture()
def superadmin(superadmin_token, db_session):
    """The SuperAdmin as {"id", "headers"} — same shape as one entry of `staff`."""
    user = db_session.query(User).filter(User.email == SUPERADMIN_EMAIL).first()
    return {"id": user.id, "headers": _headers(superadmin_token)}


@pytest.fixture(scope="session")
def staff(superadmin_ready):
    """
    A standing cast of users, created once per run and shared by every
    test file after test_user.py: staff["admin"], ["doctor"], ["doctor2"],
    ["nurse"], ["nurse2"]. Each entry is {"id", "email", "headers"}.

    Creating a user costs a password hash plus a login (about half a
    second), so we pay that once here instead of in every test. Tests
    stay independent anyway because each one creates its own fresh
    patient — see `make_patient`.
    """
    cast = {}
    with TestClient(app) as c:
        superadmin_headers = _headers(_login(c, SUPERADMIN_EMAIL))
        db = SessionLocal()
        try:
            for key, role_name in [
                ("admin", "Admin"),
                ("doctor", "Doctor"),
                ("doctor2", "Doctor"),
                ("nurse", "Nurse"),
                ("nurse2", "Nurse"),
            ]:
                cast[key] = _create_user(c, db, superadmin_headers, role_name)
        finally:
            db.close()
    return cast


@pytest.fixture()
def make_user(client, db_session, superadmin_headers):
    """
    Factory for a brand-new user: make_user("Doctor"). Use this when a
    test needs someone with no history (an empty patient list) or
    someone it is going to change (deactivate). Everyone else should
    use the shared `staff` cast.
    """
    def _make(role_name="Doctor"):
        return _create_user(client, db_session, superadmin_headers, role_name)
    return _make


@pytest.fixture()
def superadmin_headers(superadmin_token):
    return _headers(superadmin_token)


@pytest.fixture()
def make_patient(client, staff):
    """
    Factory for a fresh patient, created through the API as the shared
    admin: make_patient() or make_patient(chief_complaint="Fever").
    Returns the response body, so patient["id"] etc. work.
    """
    def _make(**overrides):
        payload = {
            "full_name": f"Patient {uuid.uuid4().hex[:8]}",
            "dob": "1990-05-17",
            "height_cm": 170.0,
            "weight_kg": 65.0,
            "chief_complaint": "Headache",
            **overrides,
        }
        response = client.post("/patients/create", json=payload, headers=staff["admin"]["headers"])
        assert response.status_code == 200, f"patient setup failed: {response.status_code} {response.text}"
        return response.json()
    return _make


@pytest.fixture()
def assign_patient(client, staff):
    """
    Setup helper: assign_patient(patient, user) gives that user access
    to that patient (done as the shared admin). Fails loudly if the
    assignment did not work, so a broken setup never looks like a
    broken test.
    """
    def _assign(patient, user):
        response = client.post(
            "/assignments/assign",
            json={"patient_id": patient["id"], "user_id": user["id"]},
            headers=staff["admin"]["headers"],
        )
        assert response.status_code == 200, f"assignment setup failed: {response.status_code} {response.text}"
        return response.json()
    return _assign


@pytest.fixture()
def watch_audit(db_session):
    """
    Checks that a request wrote a NEW audit-log row.

        logged = watch_audit("PATIENT_ASSIGNED", user_id=admin_id)
        client.post(...)               # the request being tested
        row = logged()                 # the new row, or None

    The row only counts if it appeared after watch_audit() was called,
    so an old row with the same action can never make a test pass by
    accident.
    """
    def _query(action, user_id):
        db_session.expire_all()
        query = db_session.query(AuditLog).filter(AuditLog.action == action)
        if user_id is not None:
            query = query.filter(AuditLog.user_id == user_id)
        return query.order_by(AuditLog.id.desc()).first()

    def _watch(action, user_id=None):
        before = _query(action, user_id)
        before_id = before.id if before else 0

        def _check():
            row = _query(action, user_id)
            return row if row is not None and row.id > before_id else None
        return _check
    return _watch