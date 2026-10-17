import os

import psycopg2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine.url import make_url

from app.database import Base, SessionLocal, engine
from app.main import app

SAFE_HOSTS = {"localhost", "127.0.0.1"}

def pytest_collection_modifyitems(items):
    """
    Runs any test marked @pytest.mark.first before everything else in
    the suite, regardless of which file it's in or what it's named.
    Needed because test_assignment.py — already on the roadmap — sorts
    alphabetically before test_auth.py, so relying on file order alone
    to put the rate-limit test first was already broken the moment that
    file gets created.
    """
    first_tests = [item for item in items if item.get_closest_marker("first")]
    other_tests = [item for item in items if not item.get_closest_marker("first")]
    items[:] = first_tests + other_tests
    
@pytest.fixture(scope="session", autouse=True)
def fresh_test_database():
    """
    Drops and recreates the test database before anything else runs, so
    local runs start from the same empty state CI gets automatically from
    its throwaway container. Connects to the always-present `postgres`
    system database to do it, since you can't drop a database you're
    connected to. Refuses to run at all if DATABASE_URL points at the
    real local dev database — that's the one thing standing between a
    forgotten `export` and losing real data.
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


@pytest.fixture()
def superadmin_token(client):
    response = client.post("/auth/login", json={
        "email": "superadmin@example.com",
        "password": "TestPass123!",
    })
    return response.json()["access_token"]


