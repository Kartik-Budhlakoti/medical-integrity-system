from app.models.user import Role, User
from app.models.audit_log import AuditLog

TEST_PASSWORD = "TestPass123!"


def get_role_id(db_session, role_name):
    return db_session.query(Role).filter(Role.role_name == role_name).first().id


def get_user_id(db_session, email):
    return db_session.query(User).filter(User.email == email).first().id


# ---------- /users/create ----------

def test_create_nurse_as_superadmin(client, db_session, superadmin_token):
    response = client.post(
        "/users/create",
        json={
            "full_name": "Nina Nurse",
            "email": "nurse1@example.com",
            "password": TEST_PASSWORD,
            "role_id": get_role_id(db_session, "Nurse"),
        },
        headers={"Authorization": f"Bearer {superadmin_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "nurse1@example.com"
    assert body["is_active"] is True
    assert body["specialty"] is None

    log_entry = db_session.query(AuditLog).filter(
        AuditLog.action == "USER_CREATION_SUCCESSFUL", AuditLog.entity_id == body["id"]
    ).first()
    assert log_entry is not None
    assert log_entry.result == "SUCCESS"


def test_create_doctor_with_specialty_persists(client, db_session, superadmin_token):
    response = client.post(
        "/users/create",
        json={
            "full_name": "Dana Doctor",
            "email": "doctor1@example.com",
            "password": TEST_PASSWORD,
            "role_id": get_role_id(db_session, "Doctor"),
            "specialty": "Cardiology",
        },
        headers={"Authorization": f"Bearer {superadmin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["specialty"] == "Cardiology"


def test_non_admin_cannot_create_user(client, db_session):
    login = client.post("/auth/login", json={"email": "nurse1@example.com", "password": TEST_PASSWORD})
    nurse_token = login.json()["access_token"]

    response = client.post(
        "/users/create",
        json={
            "full_name": "Another Nurse",
            "email": "nurse-attempt@example.com",
            "password": TEST_PASSWORD,
            "role_id": get_role_id(db_session, "Nurse"),
        },
        headers={"Authorization": f"Bearer {nurse_token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"


def test_admin_cannot_create_admin(client, db_session, superadmin_token):
    # setup: SuperAdmin creates the Admin account this test needs as caller
    client.post(
        "/users/create",
        json={
            "full_name": "Alan Admin",
            "email": "admin1@example.com",
            "password": TEST_PASSWORD,
            "role_id": get_role_id(db_session, "Admin"),
        },
        headers={"Authorization": f"Bearer {superadmin_token}"},
    )
    login = client.post("/auth/login", json={"email": "admin1@example.com", "password": TEST_PASSWORD})
    admin_token = login.json()["access_token"]

    response = client.post(
        "/users/create",
        json={
            "full_name": "Would-be Admin",
            "email": "wouldbe-admin@example.com",
            "password": TEST_PASSWORD,
            "role_id": get_role_id(db_session, "Admin"),
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin can only create Doctor or Nurse accounts"


def test_superadmin_cannot_create_superadmin_via_route(client, db_session, superadmin_token):
    response = client.post(
        "/users/create",
        json={
            "full_name": "Second SuperAdmin",
            "email": "second-superadmin@example.com",
            "password": TEST_PASSWORD,
            "role_id": get_role_id(db_session, "SuperAdmin"),
        },
        headers={"Authorization": f"Bearer {superadmin_token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "SuperAdmin accounts can only be created via bootstrap"


def test_create_duplicate_email(client, db_session, superadmin_token):
    response = client.post(
        "/users/create",
        json={
            "full_name": "Duplicate Nurse",
            "email": "nurse1@example.com",
            "password": TEST_PASSWORD,
            "role_id": get_role_id(db_session, "Nurse"),
        },
        headers={"Authorization": f"Bearer {superadmin_token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


def test_create_specialty_on_non_doctor(client, db_session, superadmin_token):
    response = client.post(
        "/users/create",
        json={
            "full_name": "Confused Nurse",
            "email": "confused-nurse@example.com",
            "password": TEST_PASSWORD,
            "role_id": get_role_id(db_session, "Nurse"),
            "specialty": "Cardiology",
        },
        headers={"Authorization": f"Bearer {superadmin_token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Specialty can only be set for Doctors"


# ---------- /users/{id}/deactivate ----------

def test_admin_deactivates_nurse(client, db_session):
    login = client.post("/auth/login", json={"email": "admin1@example.com", "password": TEST_PASSWORD})
    admin_token = login.json()["access_token"]
    nurse_id = get_user_id(db_session, "nurse1@example.com")

    response = client.post(
        f"/users/{nurse_id}/deactivate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    log_entry = db_session.query(AuditLog).filter(
        AuditLog.action == "USER_DEACTIVATED", AuditLog.entity_id == nurse_id
    ).first()
    assert log_entry is not None
    assert log_entry.result == "SUCCESS"


def test_self_deactivation_forbidden(client, db_session):
    login = client.post("/auth/login", json={"email": "admin1@example.com", "password": TEST_PASSWORD})
    admin_token = login.json()["access_token"]
    admin_id = get_user_id(db_session, "admin1@example.com")

    response = client.post(
        f"/users/{admin_id}/deactivate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Self-deactivation not allowed"


def test_cannot_deactivate_superadmin(client, db_session):
    login = client.post("/auth/login", json={"email": "admin1@example.com", "password": TEST_PASSWORD})
    admin_token = login.json()["access_token"]
    superadmin_id = get_user_id(db_session, "superadmin@example.com")

    response = client.post(
        f"/users/{superadmin_id}/deactivate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "SuperAdmin cannot be deactivated"


def test_admin_cannot_deactivate_another_admin(client, db_session, superadmin_token):
    # setup: a second Admin account to be the deactivation target
    client.post(
        "/users/create",
        json={
            "full_name": "Second Admin",
            "email": "admin2@example.com",
            "password": TEST_PASSWORD,
            "role_id": get_role_id(db_session, "Admin"),
        },
        headers={"Authorization": f"Bearer {superadmin_token}"},
    )
    login = client.post("/auth/login", json={"email": "admin1@example.com", "password": TEST_PASSWORD})
    admin_token = login.json()["access_token"]
    admin2_id = get_user_id(db_session, "admin2@example.com")

    response = client.post(
        f"/users/{admin2_id}/deactivate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin cannot deactivate another Admin"


def test_deactivated_user_token_rejected(client, db_session, superadmin_token):
    # the headline test: a token issued before deactivation must stop working immediately after
    client.post(
        "/users/create",
        json={
            "full_name": "Nurse To Deactivate",
            "email": "nurse2@example.com",
            "password": TEST_PASSWORD,
            "role_id": get_role_id(db_session, "Nurse"),
        },
        headers={"Authorization": f"Bearer {superadmin_token}"},
    )
    login = client.post("/auth/login", json={"email": "nurse2@example.com", "password": TEST_PASSWORD})
    nurse_token = login.json()["access_token"]
    nurse_id = get_user_id(db_session, "nurse2@example.com")

    deactivate_response = client.post(
        f"/users/{nurse_id}/deactivate",
        headers={"Authorization": f"Bearer {superadmin_token}"},
    )
    assert deactivate_response.status_code == 200

    response = client.get(
        "/users/doctors",
        headers={"Authorization": f"Bearer {nurse_token}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"

    log_entry = db_session.query(AuditLog).filter(
        AuditLog.action == "DEACTIVATED_ACCOUNT_ACCESS_ATTEMPT", AuditLog.user_id == nurse_id
    ).first()
    assert log_entry is not None
    assert log_entry.result == "FAILURE"


# ---------- /users/{id}/specialty ----------

def test_admin_updates_doctor_specialty(client, db_session):
    login = client.post("/auth/login", json={"email": "admin1@example.com", "password": TEST_PASSWORD})
    admin_token = login.json()["access_token"]
    doctor_id = get_user_id(db_session, "doctor1@example.com")

    response = client.patch(
        f"/users/{doctor_id}/specialty",
        json={"updated_specialty": "Neurology"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["specialty"] == "Neurology"

    log_entry = db_session.query(AuditLog).filter(
        AuditLog.action == "SPECIALTY_UPDATED", AuditLog.entity_id == doctor_id
    ).first()
    assert log_entry is not None
    assert log_entry.result == "SUCCESS"


# ---------- /users/doctors ----------

def test_non_admin_cannot_list_doctors(client):
    login = client.post("/auth/login", json={"email": "doctor1@example.com", "password": TEST_PASSWORD})
    doctor_token = login.json()["access_token"]

    response = client.get(
        "/users/doctors",
        headers={"Authorization": f"Bearer {doctor_token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"

def test_cannot_deactivate_last_active_admin(client, db_session, superadmin_token):
    superadmin_id = get_user_id(db_session, "superadmin@example.com")
    admin1_id = get_user_id(db_session, "admin1@example.com")
    admin2_id = get_user_id(db_session, "admin2@example.com")
    auth = {"Authorization": f"Bearer {superadmin_token}"}

    first = client.post(f"/users/{admin2_id}/deactivate", headers=auth)
    assert first.status_code == 200
    assert first.json()["is_active"] is False

    response = client.post(f"/users/{admin1_id}/deactivate", headers=auth)
    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot deactivate the last active Admin"

    # user_id filter is required: test_self_deactivation_forbidden already logged
    # a USER_DEACTIVATION_FAILED row with entity_id == admin1_id
    log_entry = db_session.query(AuditLog).filter(
        AuditLog.action == "USER_DEACTIVATION_FAILED",
        AuditLog.user_id == superadmin_id,
        AuditLog.entity_id == admin1_id,
    ).first()
    assert log_entry is not None
    assert log_entry.result == "FAILURE"

    assert db_session.query(User.is_active).filter(User.id == admin1_id).scalar() is True