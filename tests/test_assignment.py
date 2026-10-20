import pytest

from app.models.patient_assignment import PatientAssignment
from app.models.user import Role, User

# Setup uses the shared fixtures from conftest.py: `staff` (a standing
# cast of admin/doctor/nurse users), `make_patient` (a fresh patient per
# test), `watch_audit` (checks a request wrote a NEW audit row).


def assign(client, headers, patient_id, user_id):
    return client.post(
        "/assignments/assign",
        json={"patient_id": patient_id, "user_id": user_id},
        headers=headers,
    )


def unassign(client, headers, assignment_id):
    return client.post(f"/assignments/{assignment_id}/unassign", headers=headers)


def active_assignments(db_session, patient_id, user_id):
    db_session.expire_all()
    return db_session.query(PatientAssignment).filter(
        PatientAssignment.patient_id == patient_id,
        PatientAssignment.user_id == user_id,
        PatientAssignment.is_active.is_(True),
    ).all()


# ---------- /assignments/assign: success ----------

@pytest.mark.parametrize("who", ["doctor", "nurse"])
def test_admin_assigns_doctor_or_nurse_to_patient(who, client, db_session, staff, make_patient, watch_audit):
    patient = make_patient()
    logged = watch_audit("PATIENT_ASSIGNED", user_id=staff["admin"]["id"])

    response = assign(client, staff["admin"]["headers"], patient["id"], staff[who]["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == patient["id"]
    assert body["user_id"] == staff[who]["id"]
    assert body["assigned_by_id"] == staff["admin"]["id"]
    assert body["is_active"] is True
    assert "created_at" in body

    rows = active_assignments(db_session, patient["id"], staff[who]["id"])
    assert [row.id for row in rows] == [body["id"]]

    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_id == body["id"]


# ---------- /assignments/assign: who is allowed ----------

@pytest.mark.parametrize("who", ["doctor", "nurse"])
def test_doctor_and_nurse_cannot_assign(who, client, db_session, staff, make_patient, watch_audit):
    patient = make_patient()
    logged = watch_audit("PATIENT_ASSIGNMENT_FAILED", user_id=staff[who]["id"])

    response = assign(client, staff[who]["headers"], patient["id"], staff["doctor2"]["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert active_assignments(db_session, patient["id"], staff["doctor2"]["id"]) == []
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"


def test_superadmin_cannot_assign(client, db_session, superadmin, staff, make_patient, watch_audit):
    # SuperAdmin is a bootstrap/safety-net account, not a day-to-day one
    # (decisions-log.md), so it has no patient-assignment powers either.
    patient = make_patient()
    logged = watch_audit("PATIENT_ASSIGNMENT_FAILED", user_id=superadmin["id"])

    response = assign(client, superadmin["headers"], patient["id"], staff["doctor"]["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert active_assignments(db_session, patient["id"], staff["doctor"]["id"]) == []
    assert logged() is not None


def test_assign_requires_login(client, staff, make_patient):
    patient = make_patient()

    response = client.post(
        "/assignments/assign",
        json={"patient_id": patient["id"], "user_id": staff["doctor"]["id"]},
    )

    assert response.status_code == 401


# ---------- /assignments/assign: bad input ----------

def test_assign_unknown_patient(client, staff):
    response = assign(client, staff["admin"]["headers"], 999999999, staff["doctor"]["id"])

    assert response.status_code == 404
    assert response.json()["detail"] == "Patient not found"


def test_assign_unknown_user(client, staff, make_patient):
    patient = make_patient()

    response = assign(client, staff["admin"]["headers"], patient["id"], 999999999)

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


@pytest.mark.parametrize("body", [
    pytest.param({"patient_id": "abc", "user_id": 1}, id="patient-id-not-a-number"),
    pytest.param({"patient_id": 1, "user_id": "abc"}, id="user-id-not-a-number"),
    pytest.param({"patient_id": 1}, id="user-id-missing"),
    pytest.param({"user_id": 1}, id="patient-id-missing"),
    pytest.param({}, id="empty-body"),
])
def test_assign_rejects_malformed_body(body, client, staff):
    response = client.post("/assignments/assign", json=body, headers=staff["admin"]["headers"])

    assert response.status_code == 422


@pytest.mark.parametrize("role_name", ["Admin", "SuperAdmin"])
def test_cannot_assign_admin_or_superadmin_to_a_patient(role_name, client, db_session, staff, make_patient, watch_audit):
    patient = make_patient()
    target = db_session.query(User).join(Role).filter(Role.role_name == role_name).first()
    logged = watch_audit("PATIENT_ASSIGNMENT_FAILED", user_id=staff["admin"]["id"])

    response = assign(client, staff["admin"]["headers"], patient["id"], target.id)

    assert response.status_code == 400
    assert response.json()["detail"] == "Can only assign Doctors or Nurses"
    assert active_assignments(db_session, patient["id"], target.id) == []
    assert logged() is not None


def test_cannot_assign_same_person_twice(client, db_session, staff, make_patient, assign_patient, watch_audit):
    patient = make_patient()
    assign_patient(patient, staff["doctor"])
    logged = watch_audit("PATIENT_ASSIGNMENT_FAILED", user_id=staff["admin"]["id"])

    response = assign(client, staff["admin"]["headers"], patient["id"], staff["doctor"]["id"])

    assert response.status_code == 400
    assert response.json()["detail"] == "User already assigned to this patient"
    assert len(active_assignments(db_session, patient["id"], staff["doctor"]["id"])) == 1
    assert logged() is not None


def test_cannot_assign_deactivated_user(client, staff, make_user, make_patient, watch_audit):
    doctor = make_user("Doctor")
    patient = make_patient()
    deactivated = client.post(f"/users/{doctor['id']}/deactivate", headers=staff["admin"]["headers"])
    assert deactivated.status_code == 200
    logged = watch_audit("PATIENT_ASSIGNMENT_FAILED", user_id=staff["admin"]["id"])

    response = assign(client, staff["admin"]["headers"], patient["id"], doctor["id"])

    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot assign a deactivated user"
    assert logged() is not None


# ---------- /assignments/{id}/unassign----------

def test_admin_unassigns_and_the_row_is_kept_as_history(client, db_session, staff, make_patient, assign_patient, watch_audit):
    patient = make_patient()
    assignment = assign_patient(patient, staff["doctor"])
    logged = watch_audit("PATIENT_UNASSIGNED", user_id=staff["admin"]["id"])

    response = unassign(client, staff["admin"]["headers"], assignment["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == assignment["id"]
    assert body["is_active"] is False

    # Soft delete: the row still exists,it is just switched off.
    db_session.expire_all()
    row = db_session.query(PatientAssignment).filter(PatientAssignment.id == assignment["id"]).first()
    assert row is not None
    assert row.is_active is False

    audit = logged()
    assert audit is not None
    assert audit.result == "SUCCESS"
    assert audit.entity_id == assignment["id"]


def test_cannot_unassign_twice(client, staff, make_patient, assign_patient, watch_audit):
    patient = make_patient()
    assignment = assign_patient(patient, staff["doctor"])
    assert unassign(client, staff["admin"]["headers"], assignment["id"]).status_code == 200
    logged = watch_audit("PATIENT_UNASSIGNMENT_FAILED", user_id=staff["admin"]["id"])

    response = unassign(client, staff["admin"]["headers"], assignment["id"])

    assert response.status_code == 400
    assert response.json()["detail"] == "Assignment is already inactive"
    assert logged() is not None


def test_unassign_unknown_assignment(client, staff):
    response = unassign(client, staff["admin"]["headers"], 999999999)

    assert response.status_code == 404
    assert response.json()["detail"] == "Assignment not found"


@pytest.mark.parametrize("who", ["doctor", "nurse"])
def test_doctor_and_nurse_cannot_unassign(who, client, db_session, staff, make_patient, assign_patient, watch_audit):
    patient = make_patient()
    assignment = assign_patient(patient, staff[who])
    logged = watch_audit("PATIENT_UNASSIGNMENT_FAILED", user_id=staff[who]["id"])

    response = unassign(client, staff[who]["headers"], assignment["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert len(active_assignments(db_session, patient["id"], staff[who]["id"])) == 1
    assert logged() is not None


def test_superadmin_cannot_unassign(client, db_session, superadmin, staff, make_patient, assign_patient):
    patient = make_patient()
    assignment = assign_patient(patient, staff["doctor"])

    response = unassign(client, superadmin["headers"], assignment["id"])

    assert response.status_code == 403
    assert len(active_assignments(db_session, patient["id"], staff["doctor"]["id"])) == 1


def test_unassign_requires_login(client, staff, make_patient, assign_patient):
    patient = make_patient()
    assignment = assign_patient(patient, staff["doctor"])

    response = client.post(f"/assignments/{assignment['id']}/unassign")

    assert response.status_code == 401


def test_reassigning_after_unassign_creates_a_new_row(client, db_session, staff, make_patient, assign_patient):
    patient = make_patient()
    first = assign_patient(patient, staff["doctor"])
    assert unassign(client, staff["admin"]["headers"], first["id"]).status_code == 200

    second = assign_patient(patient, staff["doctor"])

    assert second["id"] != first["id"]
    assert second["is_active"] is True
    db_session.expire_all()
    rows = db_session.query(PatientAssignment).filter(
        PatientAssignment.patient_id == patient["id"],
        PatientAssignment.user_id == staff["doctor"]["id"],
    ).order_by(PatientAssignment.id).all()
    assert [(row.id, row.is_active) for row in rows] == [(first["id"], False), (second["id"], True)]


# ----------assignment controls ----------

def test_unassigning_cuts_off_access_to_the_patient(client, staff, make_patient, assign_patient):
    patient = make_patient()
    assignment = assign_patient(patient, staff["doctor"])
    doctor_headers = staff["doctor"]["headers"]
    assert client.get(f"/patients/{patient['id']}", headers=doctor_headers).status_code == 200
    update = client.patch(f"/patients/{patient['id']}", json={"chief_complaint": "Fever"}, headers=doctor_headers)
    assert update.status_code == 200

    assert unassign(client, staff["admin"]["headers"], assignment["id"]).status_code == 200

    read = client.get(f"/patients/{patient['id']}", headers=doctor_headers)
    assert read.status_code == 403
    assert read.json()["detail"] == "Not assigned to this patient"
    update = client.patch(f"/patients/{patient['id']}", json={"chief_complaint": "Cough"}, headers=doctor_headers)
    assert update.status_code == 403
    assert update.json()["detail"] == "Not assigned to this patient"


def test_assignment_only_covers_that_one_patient(client, staff, make_patient, assign_patient):
    assigned_patient = make_patient()
    other_patient = make_patient()
    assign_patient(assigned_patient, staff["nurse"])

    ok = client.get(f"/patients/{assigned_patient['id']}", headers=staff["nurse"]["headers"])
    denied = client.get(f"/patients/{other_patient['id']}", headers=staff["nurse"]["headers"])

    assert ok.status_code == 200
    assert denied.status_code == 403