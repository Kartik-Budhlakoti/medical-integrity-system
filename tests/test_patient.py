from datetime import date, timedelta

import pytest

from app.models.patient import Patient

# Setup uses the shared fixtures from conftest.py: `staff` (a standing
# cast of admin/doctor/nurse users), `make_user` (a brand-new user),
# `make_patient` (a fresh patient per test, so tests never share one),
# `assign_patient`, and `watch_audit` (checks a request wrote a NEW
# audit row).
#
# "Known limitation" comments below mark behaviour that is pinned on
# purpose but is on the Known Issues list, so a future change to it
# shows up as a deliberate decision and not a surprise.


def get_patient(client, headers, patient_id):
    return client.get(f"/patients/{patient_id}", headers=headers)


def patch_patient(client, headers, patient_id, body):
    return client.patch(f"/patients/{patient_id}", json=body, headers=headers)


def patient_ids(response):
    return [patient["id"] for patient in response.json()]


# ======================================================================
# POST /patients/create
# ======================================================================

@pytest.mark.parametrize("who", ["admin", "doctor", "nurse"])
def test_admin_doctor_and_nurse_can_create_a_patient(who, client, db_session, staff, watch_audit):
    logged = watch_audit("PATIENT_CREATION_SUCCESSFUL", user_id=staff[who]["id"])

    response = client.post("/patients/create", json={
        "full_name": f"Created by {who}",
        "dob": "1985-03-02",
        "height_cm": 171.5,
        "weight_kg": 72.25,
        "chief_complaint": "Back pain",
    }, headers=staff[who]["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == f"Created by {who}"
    assert body["dob"] == "1985-03-02"
    assert body["height_cm"] == 171.5
    assert body["weight_kg"] == 72.25
    assert body["chief_complaint"] == "Back pain"
    assert body["is_emergency"] is False
    assert body["is_admitted"] is False
    assert "id" in body
    assert "created_at" in body

    db_session.expire_all()
    assert db_session.query(Patient).filter(Patient.id == body["id"]).first() is not None
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_id == body["id"]


def test_is_emergency_can_be_set_at_creation(client, staff):
    response = client.post("/patients/create", json={
        "full_name": "Emergency Case",
        "dob": "1985-03-02",
        "height_cm": 171.5,
        "weight_kg": 72.25,
        "chief_complaint": "Chest pain",
        "is_emergency": True,
    }, headers=staff["admin"]["headers"])

    assert response.status_code == 200
    assert response.json()["is_emergency"] is True


def test_superadmin_cannot_create_a_patient(client, db_session, superadmin, watch_audit):
    logged = watch_audit("PATIENT_CREATION_FAILED", user_id=superadmin["id"])

    response = client.post("/patients/create", json={
        "full_name": "Should Not Exist",
        "dob": "1985-03-02",
        "height_cm": 171.5,
        "weight_kg": 72.25,
        "chief_complaint": "Back pain",
    }, headers=superadmin["headers"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert db_session.query(Patient).filter(Patient.full_name == "Should Not Exist").first() is None
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"


def test_create_requires_login(client):
    response = client.post("/patients/create", json={
        "full_name": "No Token",
        "dob": "1985-03-02",
        "height_cm": 171.5,
        "weight_kg": 72.25,
        "chief_complaint": "Back pain",
    })

    assert response.status_code == 401


def test_values_exactly_on_the_limits_are_accepted(client, staff):
    # The smallest/largest allowed height and weight, and the oldest
    # allowed and newest (today) dates of birth.
    for height, weight, dob in [
        (30, 5, "1900-01-01"),
        (250, 300, date.today().isoformat()),
    ]:
        response = client.post("/patients/create", json={
            "full_name": f"Limit {height}",
            "dob": dob,
            "height_cm": height,
            "weight_kg": weight,
            "chief_complaint": "Edge case",
        }, headers=staff["admin"]["headers"])
        assert response.status_code == 200, (height, weight, dob, response.text)


VALID_PATIENT = {
    "full_name": "Validation Probe",
    "dob": "1985-03-02",
    "height_cm": 171.5,
    "weight_kg": 72.25,
    "chief_complaint": "Back pain",
}


@pytest.mark.parametrize("field, value, message", [
    pytest.param("height_cm", 29.9, "Height must be between 30 and 250 cm", id="height-too-low"),
    pytest.param("height_cm", 250.1, "Height must be between 30 and 250 cm", id="height-too-high"),
    pytest.param("weight_kg", 4.9, "Weight must be between 5.0 and 300 kg", id="weight-too-low"),
    pytest.param("weight_kg", 300.1, "Weight must be between 5.0 and 300 kg", id="weight-too-high"),
    pytest.param("dob", (date.today() + timedelta(days=1)).isoformat(), "Date of birth cannot be in the future", id="dob-in-future"),
    pytest.param("dob", "1899-12-31", "Date of birth is not realistic", id="dob-before-1900"),
    pytest.param("height_cm", "tall", "valid number", id="height-not-a-number"),
    pytest.param("dob", "not-a-date", "valid date", id="dob-not-a-date"),
])
def test_create_rejects_invalid_values_and_saves_nothing(field, value, message, client, db_session, staff):
    response = client.post(
        "/patients/create",
        json={**VALID_PATIENT, field: value},
        headers=staff["admin"]["headers"],
    )

    assert response.status_code == 422
    assert message in response.text
    assert db_session.query(Patient).filter(Patient.full_name == "Validation Probe").first() is None


@pytest.mark.parametrize("missing", ["full_name", "dob", "height_cm", "weight_kg", "chief_complaint"])
def test_create_requires_every_core_field(missing, client, db_session, staff):
    body = {**VALID_PATIENT}
    del body[missing]

    response = client.post("/patients/create", json=body, headers=staff["admin"]["headers"])

    assert response.status_code == 422
    assert db_session.query(Patient).filter(Patient.full_name == "Validation Probe").first() is None


# ======================================================================
# GET /patients/  (the list)
# ======================================================================

def test_admin_sees_every_patient_newest_first(client, staff, make_patient, watch_audit):
    older = make_patient()
    newer = make_patient()
    logged = watch_audit("PATIENTS_ACCESSED", user_id=staff["admin"]["id"])

    response = client.get("/patients/", headers=staff["admin"]["headers"])

    assert response.status_code == 200
    ids = patient_ids(response)
    assert older["id"] in ids and newer["id"] in ids
    assert ids.index(newer["id"]) < ids.index(older["id"])
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"


@pytest.mark.parametrize("role_name", ["Doctor", "Nurse"])
def test_doctor_or_nurse_sees_only_their_assigned_patients(role_name, client, make_user, make_patient, assign_patient, watch_audit):
    user = make_user(role_name)
    first = make_patient()
    second = make_patient()
    not_mine = make_patient()
    assign_patient(first, user)
    assert patient_ids(client.get("/patients/", headers=user["headers"])) == [first["id"]]

    assign_patient(second, user)
    logged = watch_audit("PATIENTS_ACCESSED", user_id=user["id"])
    response = client.get("/patients/", headers=user["headers"])

    assert response.status_code == 200
    # newest first, and never the patient they are not assigned to
    assert patient_ids(response) == [second["id"], first["id"]]
    assert not_mine["id"] not in patient_ids(response)
    assert logged() is not None


@pytest.mark.parametrize("role_name", ["Doctor", "Nurse"])
def test_doctor_or_nurse_with_no_patients_gets_a_403(role_name, client, make_user, watch_audit):
    # Known limitation: a doctor or nurse with no active assignments gets
    # a 403 (and an access-denied audit row) instead of an empty list,
    # even though nothing was really denied. Kept on purpose for now (see
    # Known Issues); if it is ever changed to return [], this test changes
    # with it.
    user = make_user(role_name)
    logged = watch_audit("PATIENTS_ACCESS_DENIED", user_id=user["id"])

    response = client.get("/patients/", headers=user["headers"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not assigned to this patient"
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_id == 0


def test_unassigned_patients_disappear_from_the_list(client, staff, make_user, make_patient, assign_patient):
    doctor = make_user("Doctor")
    kept = make_patient()
    removed = make_patient()
    assign_patient(kept, doctor)
    assignment = assign_patient(removed, doctor)
    assert patient_ids(client.get("/patients/", headers=doctor["headers"])) == [removed["id"], kept["id"]]

    client.post(f"/assignments/{assignment['id']}/unassign", headers=staff["admin"]["headers"])

    assert patient_ids(client.get("/patients/", headers=doctor["headers"])) == [kept["id"]]


def test_superadmin_cannot_list_patients(client, superadmin, watch_audit):
    logged = watch_audit("PATIENTS_ACCESS_DENIED", user_id=superadmin["id"])

    response = client.get("/patients/", headers=superadmin["headers"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"


def test_list_requires_login(client):
    assert client.get("/patients/").status_code == 401


# ======================================================================
# GET /patients/{id}
# ======================================================================

def test_admin_can_read_any_patient(client, staff, make_patient, watch_audit):
    patient = make_patient()
    logged = watch_audit("PATIENT_ACCESSED", user_id=staff["admin"]["id"])

    response = get_patient(client, staff["admin"]["headers"], patient["id"])

    assert response.status_code == 200
    assert response.json() == patient
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_id == patient["id"]


@pytest.mark.parametrize("who", ["doctor", "nurse"])
def test_assigned_doctor_or_nurse_can_read_the_patient(who, client, staff, make_patient, assign_patient, watch_audit):
    patient = make_patient()
    assign_patient(patient, staff[who])
    logged = watch_audit("PATIENT_ACCESSED", user_id=staff[who]["id"])

    response = get_patient(client, staff[who]["headers"], patient["id"])

    assert response.status_code == 200
    assert response.json() == patient
    row = logged()
    assert row is not None
    assert row.entity_id == patient["id"]


@pytest.mark.parametrize("who", ["doctor2", "nurse2"])
def test_unassigned_doctor_or_nurse_cannot_read_the_patient(who, client, staff, make_patient, watch_audit):
    patient = make_patient()
    logged = watch_audit("PATIENT_ACCESS_DENIED", user_id=staff[who]["id"])

    response = get_patient(client, staff[who]["headers"], patient["id"])

    assert response.status_code == 403
    assert response.json() == {"detail": "Not assigned to this patient"}
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_id == patient["id"]


def test_superadmin_cannot_read_a_patient(client, superadmin, make_patient, watch_audit):
    patient = make_patient()
    logged = watch_audit("PATIENT_ACCESS_DENIED", user_id=superadmin["id"])

    response = get_patient(client, superadmin["headers"], patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert logged() is not None


def test_read_requires_login(client, make_patient):
    patient = make_patient()

    assert client.get(f"/patients/{patient['id']}").status_code == 401


def test_read_rejects_a_non_numeric_id(client, staff):
    assert get_patient(client, staff["admin"]["headers"], "abc").status_code == 422


@pytest.mark.parametrize("who", ["admin", "doctor", "nurse"])
def test_reading_a_nonexistent_patient_gives_404(who, client, staff):
    # Known limitation: a doctor/nurse gets 404 for a patient number that
    # does not exist but 403 for one that exists and is not theirs, so the
    # difference reveals which patient numbers exist. Kept on purpose for
    # now (see Known Issues); if it is ever changed, this test and
    # test_unassigned_doctor_or_nurse_cannot_read_the_patient change together.
    response = get_patient(client, staff[who]["headers"], 999999999)

    assert response.status_code == 404
    assert response.json()["detail"] == "Patient not found"


def test_a_doctor_who_creates_a_patient_cannot_read_it_until_assigned(client, staff, assign_patient):
    # Known limitation: creating a patient does not assign the creator to
    # it; only an admin can do that. Kept on purpose (see Known Issues).
    created = client.post("/patients/create", json={
        "full_name": "Created by a doctor",
        "dob": "1985-03-02",
        "height_cm": 171.5,
        "weight_kg": 72.25,
        "chief_complaint": "Back pain",
    }, headers=staff["doctor2"]["headers"])
    assert created.status_code == 200
    patient = created.json()

    before = get_patient(client, staff["doctor2"]["headers"], patient["id"])
    assign_patient(patient, staff["doctor2"])
    after = get_patient(client, staff["doctor2"]["headers"], patient["id"])

    assert before.status_code == 403
    assert after.status_code == 200


# ======================================================================
# PATCH /patients/{id}  (field-level permissions)
# ======================================================================
#
# Who may change which field:
#   Admin  -> is_admitted, is_emergency, chief_complaint
#   Doctor -> is_emergency, chief_complaint
#   Nurse  -> height_cm, weight_kg
# Doctors and nurses additionally need an active assignment.

ALLOWED_UPDATES = [
    pytest.param("admin", "is_admitted", True, id="admin-is_admitted"),
    pytest.param("admin", "is_emergency", True, id="admin-is_emergency"),
    pytest.param("admin", "chief_complaint", "Chest pain", id="admin-chief_complaint"),
    pytest.param("doctor", "is_emergency", True, id="doctor-is_emergency"),
    pytest.param("doctor", "chief_complaint", "Chest pain", id="doctor-chief_complaint"),
    pytest.param("nurse", "height_cm", 172.5, id="nurse-height_cm"),
    pytest.param("nurse", "weight_kg", 70.5, id="nurse-weight_kg"),
]

FORBIDDEN_UPDATES = [
    pytest.param("admin", "height_cm", 180.0, id="admin-height_cm"),
    pytest.param("admin", "weight_kg", 80.0, id="admin-weight_kg"),
    pytest.param("doctor", "is_admitted", True, id="doctor-is_admitted"),
    pytest.param("doctor", "height_cm", 180.0, id="doctor-height_cm"),
    pytest.param("doctor", "weight_kg", 80.0, id="doctor-weight_kg"),
    pytest.param("nurse", "is_admitted", True, id="nurse-is_admitted"),
    pytest.param("nurse", "is_emergency", True, id="nurse-is_emergency"),
    pytest.param("nurse", "chief_complaint", "Chest pain", id="nurse-chief_complaint"),
]


def setup_patient_for(who, make_patient, assign_patient, staff):
    """A fresh patient; doctors and nurses are assigned so that the
    field rule is the ONLY thing that can stop them."""
    patient = make_patient()
    if who != "admin":
        assign_patient(patient, staff[who])
    return patient


@pytest.mark.parametrize("who, field, value", ALLOWED_UPDATES)
def test_each_role_can_change_the_fields_it_owns(who, field, value, client, staff, make_patient, assign_patient, watch_audit):
    patient = setup_patient_for(who, make_patient, assign_patient, staff)
    logged = watch_audit("PATIENT_UPDATED", user_id=staff[who]["id"])

    response = patch_patient(client, staff[who]["headers"], patient["id"], {field: value})

    assert response.status_code == 200
    assert response.json()[field] == value
    # ...and it really was saved, not just echoed back.
    assert get_patient(client, staff["admin"]["headers"], patient["id"]).json()[field] == value
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_id == patient["id"]


@pytest.mark.parametrize("who, field, value", FORBIDDEN_UPDATES)
def test_each_role_is_blocked_from_fields_it_does_not_own(who, field, value, client, staff, make_patient, assign_patient, watch_audit):
    patient = setup_patient_for(who, make_patient, assign_patient, staff)
    logged = watch_audit("PATIENT_UPDATE_FAILED", user_id=staff[who]["id"])

    response = patch_patient(client, staff[who]["headers"], patient["id"], {field: value})

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail.startswith("Not authorized to update:")
    assert field in detail
    # nothing was changed
    assert get_patient(client, staff["admin"]["headers"], patient["id"]).json()[field] == patient[field]
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_id == patient["id"]


def test_one_forbidden_field_blocks_the_whole_update(client, staff, make_patient, assign_patient):
    # All-or-nothing: the allowed part is not applied either.
    patient = setup_patient_for("doctor", make_patient, assign_patient, staff)

    response = patch_patient(client, staff["doctor"]["headers"], patient["id"], {
        "chief_complaint": "Changed by doctor",
        "is_admitted": True,
    })

    assert response.status_code == 403
    after = get_patient(client, staff["admin"]["headers"], patient["id"]).json()
    assert after["chief_complaint"] == patient["chief_complaint"]
    assert after["is_admitted"] is False


@pytest.mark.parametrize("who, field, value", [
    pytest.param("doctor2", "chief_complaint", "Changed", id="unassigned-doctor"),
    pytest.param("nurse2", "height_cm", 175.0, id="unassigned-nurse"),
])
def test_unassigned_doctor_or_nurse_cannot_update(who, field, value, client, staff, make_patient, watch_audit):
    patient = make_patient()
    logged = watch_audit("PATIENT_UPDATE_FAILED", user_id=staff[who]["id"])

    response = patch_patient(client, staff[who]["headers"], patient["id"], {field: value})

    assert response.status_code == 403
    assert response.json()["detail"] == "Not assigned to this patient"
    assert get_patient(client, staff["admin"]["headers"], patient["id"]).json()[field] == patient[field]
    assert logged() is not None


def test_superadmin_cannot_update(client, superadmin, make_patient, watch_audit):
    patient = make_patient()
    logged = watch_audit("PATIENT_UPDATE_FAILED", user_id=superadmin["id"])

    response = patch_patient(client, superadmin["headers"], patient["id"], {"chief_complaint": "Changed"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert logged() is not None


def test_update_requires_login(client, make_patient):
    patient = make_patient()

    response = client.patch(f"/patients/{patient['id']}", json={"chief_complaint": "Changed"})

    assert response.status_code == 401


@pytest.mark.parametrize("who, field, value", [
    pytest.param("admin", "chief_complaint", "Changed", id="admin"),
    pytest.param("doctor", "chief_complaint", "Changed", id="doctor"),
    pytest.param("nurse", "height_cm", 175.0, id="nurse"),
])
def test_updating_a_nonexistent_patient_gives_404(who, field, value, client, staff):
    # Known limitation, same as reading a nonexistent patient (see above).
    response = patch_patient(client, staff[who]["headers"], 999999999, {field: value})

    assert response.status_code == 404
    assert response.json()["detail"] == "Patient not found"


@pytest.mark.parametrize("field, value", [
    pytest.param("height_cm", 29.9, id="height-too-low"),
    pytest.param("height_cm", 250.1, id="height-too-high"),
    pytest.param("weight_kg", 4.9, id="weight-too-low"),
    pytest.param("weight_kg", 300.1, id="weight-too-high"),
    pytest.param("height_cm", "tall", id="height-not-a-number"),
])
def test_update_rejects_invalid_values(field, value, client, staff, make_patient, assign_patient):
    patient = setup_patient_for("nurse", make_patient, assign_patient, staff)

    response = patch_patient(client, staff["nurse"]["headers"], patient["id"], {field: value})

    assert response.status_code == 422
    assert get_patient(client, staff["admin"]["headers"], patient["id"]).json()[field] == patient[field]


@pytest.mark.parametrize("who", ["admin", "doctor"])
def test_name_and_date_of_birth_cannot_be_changed_through_update(who, client, staff, make_patient, assign_patient):
    # Mass-assignment guard: extra fields in the request body are ignored,
    # they never reach the database.
    patient = setup_patient_for(who, make_patient, assign_patient, staff)

    response = patch_patient(client, staff[who]["headers"], patient["id"], {
        "chief_complaint": "Legitimate change",
        "full_name": "Hacked Name",
        "dob": "1900-01-01",
        "id": 1,
        "created_at": "2000-01-01T00:00:00Z",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["chief_complaint"] == "Legitimate change"
    assert body["full_name"] == patient["full_name"]
    assert body["dob"] == patient["dob"]
    assert body["id"] == patient["id"]
    assert body["created_at"] == patient["created_at"]


def test_empty_update_changes_nothing(client, staff, make_patient):
    patient = make_patient()

    response = patch_patient(client, staff["admin"]["headers"], patient["id"], {})

    assert response.status_code == 200
    assert response.json() == patient


# KNOWN BUG, pinned as "expected to fail" so CI stays green. Sending an
# explicit null for a field makes the update set that column to NULL; the
# columns are NOT NULL, so the database refuses and the request crashes
# with a 500 instead of a clean 422. When it is fixed (reject null in
# PatientUpdate), these start passing, pytest then reports XPASS(strict) as a
# failure, and the xfail marker below should simply be deleted.
@pytest.mark.xfail(strict=True, reason="PATCH with an explicit null crashes with a 500 (NOT NULL violation)")
@pytest.mark.parametrize("who, field", [
    pytest.param("admin", "is_admitted", id="admin-is_admitted"),
    pytest.param("admin", "is_emergency", id="admin-is_emergency"),
    pytest.param("admin", "chief_complaint", id="admin-chief_complaint"),
    pytest.param("doctor", "chief_complaint", id="doctor-chief_complaint"),
    pytest.param("nurse", "height_cm", id="nurse-height_cm"),
    pytest.param("nurse", "weight_kg", id="nurse-weight_kg"),
])
def test_update_with_explicit_null_is_rejected_cleanly(who, field, client, staff, make_patient, assign_patient):
    patient = setup_patient_for(who, make_patient, assign_patient, staff)

    response = patch_patient(client, staff[who]["headers"], patient["id"], {field: None})

    assert response.status_code == 422
    assert get_patient(client, staff["admin"]["headers"], patient["id"]).json()[field] == patient[field]