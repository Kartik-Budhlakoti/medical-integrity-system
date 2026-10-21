import pytest

from app.models.treatment_note import TreatmentNote

# Treatment notes are written by doctors. Who may do what:
#   create: Doctor only, and only for a patient they are assigned to
#   read:   Admin (any patient), Doctor/Nurse (only assigned patients)
# Notes can never be edited or deleted: there are no such routes.
#
# Setup uses the shared fixtures from conftest.py (`staff`, `make_patient`,
# `assign_patient`, `watch_audit`, `superadmin`).


def note_body(patient_id, **overrides):
    return {
        "patient_id": patient_id,
        "condition_update": "Stable, improving",
        "medications": "Paracetamol 500 mg",
        "orders": "Repeat bloods in 6 hours",
        **overrides,
    }


def create_note(client, headers, patient_id, **overrides):
    return client.post("/notes/create", json=note_body(patient_id, **overrides), headers=headers)


def list_notes(client, headers, patient_id):
    return client.get(f"/notes/{patient_id}", headers=headers)


def stored_notes(db_session, patient_id):
    db_session.expire_all()
    return db_session.query(TreatmentNote).filter(TreatmentNote.patient_id == patient_id).all()


# ======================================================================
# POST /notes/create
# ======================================================================

def test_assigned_doctor_creates_a_note(client, db_session, staff, make_patient, assign_patient, watch_audit):
    patient = make_patient()
    assign_patient(patient, staff["doctor"])
    logged = watch_audit("NOTE_CREATED", user_id=staff["doctor"]["id"])

    response = create_note(client, staff["doctor"]["headers"], patient["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == patient["id"]
    assert body["treatment_by_id"] == staff["doctor"]["id"]
    assert body["condition_update"] == "Stable, improving"
    assert body["medications"] == "Paracetamol 500 mg"
    assert body["orders"] == "Repeat bloods in 6 hours"
    assert body["completed_procedures"] is None
    assert body["ongoing_treatments"] is None
    assert body["observations"] is None
    assert "created_at" in body

    assert [note.id for note in stored_notes(db_session, patient["id"])] == [body["id"]]
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_type == "treatment_notes"
    assert row.entity_id == body["id"]


def test_optional_fields_are_stored_when_given(client, staff, make_patient, assign_patient):
    patient = make_patient()
    assign_patient(patient, staff["doctor"])

    response = create_note(
        client, staff["doctor"]["headers"], patient["id"],
        completed_procedures="Wound dressing",
        ongoing_treatments="IV fluids",
        observations="Patient comfortable",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["completed_procedures"] == "Wound dressing"
    assert body["ongoing_treatments"] == "IV fluids"
    assert body["observations"] == "Patient comfortable"


def test_note_author_comes_from_the_login_not_the_request(client, staff, make_patient, assign_patient):
    # Anyone could type another doctor's id into the request body. It must
    # be ignored: the author is always whoever is logged in.
    patient = make_patient()
    assign_patient(patient, staff["doctor"])

    response = create_note(
        client, staff["doctor"]["headers"], patient["id"],
        treatment_by_id=staff["doctor2"]["id"],
    )

    assert response.status_code == 200
    assert response.json()["treatment_by_id"] == staff["doctor"]["id"]


def test_unassigned_doctor_cannot_create_a_note(client, db_session, staff, make_patient, watch_audit):
    patient = make_patient()
    logged = watch_audit("NOTE_CREATION_FAILED", user_id=staff["doctor2"]["id"])

    response = create_note(client, staff["doctor2"]["headers"], patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not assigned to this patient"
    assert stored_notes(db_session, patient["id"]) == []
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_type == "treatment_notes"
    assert row.entity_id == patient["id"]


@pytest.mark.parametrize("who", ["admin", "nurse"])
def test_only_doctors_can_create_treatment_notes(who, client, db_session, staff, make_patient, assign_patient, watch_audit):
    # The nurse is assigned to the patient, so the role rule is the only
    # thing that can stop them.
    patient = make_patient()
    if who == "nurse":
        assign_patient(patient, staff["nurse"])
    logged = watch_audit("NOTE_CREATION_FAILED", user_id=staff[who]["id"])

    response = create_note(client, staff[who]["headers"], patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert stored_notes(db_session, patient["id"]) == []
    row = logged()
    assert row is not None
    assert row.entity_type == "treatment_notes"


def test_superadmin_cannot_create_a_treatment_note(client, db_session, superadmin, make_patient):
    patient = make_patient()

    response = create_note(client, superadmin["headers"], patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert stored_notes(db_session, patient["id"]) == []


def test_create_requires_login(client, make_patient):
    patient = make_patient()

    response = client.post("/notes/create", json=note_body(patient["id"]))

    assert response.status_code == 401


def test_create_for_a_nonexistent_patient(client, staff):
    response = create_note(client, staff["doctor"]["headers"], 999999999)

    assert response.status_code == 404
    assert response.json()["detail"] == "Patient not found"


@pytest.mark.parametrize("missing", ["patient_id", "condition_update", "medications", "orders"])
def test_create_requires_the_core_fields(missing, client, db_session, staff, make_patient, assign_patient):
    patient = make_patient()
    assign_patient(patient, staff["doctor"])
    body = note_body(patient["id"])
    del body[missing]

    response = client.post("/notes/create", json=body, headers=staff["doctor"]["headers"])

    assert response.status_code == 422
    assert stored_notes(db_session, patient["id"]) == []


def test_create_rejects_a_non_numeric_patient_id(client, staff):
    response = client.post(
        "/notes/create",
        json=note_body("abc"),
        headers=staff["doctor"]["headers"],
    )

    assert response.status_code == 422


# KNOWN INCONSISTENCY, pinned as "expected to fail" so CI stays green.
# Nursing notes refuse blank care notes, but treatment notes accept blank
# or whitespace-only condition, medications and orders. If blank text is
# meant to be allowed here, delete this test and replace it with one that
# says so; if it is not, reject blank text in TreatmentNoteCreate and just
# delete the xfail marker.
@pytest.mark.xfail(strict=True, reason="blank required text is accepted (nursing notes reject it)")
@pytest.mark.parametrize("field", ["condition_update", "medications", "orders"])
def test_blank_required_text_is_rejected(field, client, staff, make_patient, assign_patient):
    patient = make_patient()
    assign_patient(patient, staff["doctor"])

    response = create_note(client, staff["doctor"]["headers"], patient["id"], **{field: "   "})

    assert response.status_code == 422


# ======================================================================
# GET /notes/{patient_id}
# ======================================================================

def test_admin_reads_every_note_newest_first(client, staff, make_patient, assign_patient, watch_audit):
    patient = make_patient()
    assign_patient(patient, staff["doctor"])
    first = create_note(client, staff["doctor"]["headers"], patient["id"], condition_update="First").json()
    second = create_note(client, staff["doctor"]["headers"], patient["id"], condition_update="Second").json()
    logged = watch_audit("NOTE_ACCESSED", user_id=staff["admin"]["id"])

    response = list_notes(client, staff["admin"]["headers"], patient["id"])

    assert response.status_code == 200
    assert [note["id"] for note in response.json()] == [second["id"], first["id"]]
    assert response.json()[0] == second
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_type == "treatment_notes"
    assert row.entity_id == patient["id"]


@pytest.mark.parametrize("who", ["doctor", "nurse"])
def test_assigned_doctor_or_nurse_can_read_the_notes(who, client, staff, make_patient, assign_patient):
    patient = make_patient()
    assign_patient(patient, staff["doctor"])
    assign_patient(patient, staff["nurse"])
    note = create_note(client, staff["doctor"]["headers"], patient["id"]).json()

    response = list_notes(client, staff[who]["headers"], patient["id"])

    assert response.status_code == 200
    assert response.json() == [note]


@pytest.mark.parametrize("who", ["doctor2", "nurse2"])
def test_unassigned_doctor_or_nurse_cannot_read_the_notes(who, client, staff, make_patient, assign_patient, watch_audit):
    patient = make_patient()
    assign_patient(patient, staff["doctor"])
    create_note(client, staff["doctor"]["headers"], patient["id"])
    logged = watch_audit("NOTE_ACCESS_FAILED", user_id=staff[who]["id"])

    response = list_notes(client, staff[who]["headers"], patient["id"])

    assert response.status_code == 403
    assert response.json() == {"detail": "Not assigned to this patient"}
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_type == "treatment_notes"
    assert row.entity_id == patient["id"]


def test_superadmin_cannot_read_notes(client, superadmin, make_patient):
    patient = make_patient()

    response = list_notes(client, superadmin["headers"], patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"


def test_read_requires_login(client, make_patient):
    patient = make_patient()

    assert client.get(f"/notes/{patient['id']}").status_code == 401


def test_patient_with_no_notes_gives_an_empty_list(client, staff, make_patient):
    patient = make_patient()

    response = list_notes(client, staff["admin"]["headers"], patient["id"])

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("who", ["admin", "doctor", "nurse"])
def test_reading_notes_of_a_nonexistent_patient_gives_404(who, client, staff):
    # Known limitation: see the matching test in test_patient.py. A doctor
    # or nurse learns which patient numbers exist from 404 vs 403.
    response = list_notes(client, staff[who]["headers"], 999999999)

    assert response.status_code == 404
    assert response.json()["detail"] == "Patient not found"


def test_notes_never_leak_between_patients(client, staff, make_patient, assign_patient):
    patient_a = make_patient()
    patient_b = make_patient()
    assign_patient(patient_a, staff["doctor"])
    assign_patient(patient_b, staff["doctor"])
    note_a = create_note(client, staff["doctor"]["headers"], patient_a["id"], condition_update="Only A").json()
    note_b = create_note(client, staff["doctor"]["headers"], patient_b["id"], condition_update="Only B").json()

    assert list_notes(client, staff["admin"]["headers"], patient_a["id"]).json() == [note_a]
    assert list_notes(client, staff["admin"]["headers"], patient_b["id"]).json() == [note_b]


def test_unassigning_cuts_off_notes_access(client, staff, make_patient, assign_patient):
    patient = make_patient()
    assignment = assign_patient(patient, staff["doctor"])
    create_note(client, staff["doctor"]["headers"], patient["id"])
    assert list_notes(client, staff["doctor"]["headers"], patient["id"]).status_code == 200

    client.post(f"/assignments/{assignment['id']}/unassign", headers=staff["admin"]["headers"])

    assert list_notes(client, staff["doctor"]["headers"], patient["id"]).status_code == 403
    assert create_note(client, staff["doctor"]["headers"], patient["id"]).status_code == 403


# ======================================================================
# Notes are append-only
# ======================================================================

@pytest.mark.parametrize("method", ["delete", "patch", "put", "post"])
def test_a_note_cannot_be_edited_or_deleted(method, client, staff, make_patient, assign_patient):
    # No route exists to change or remove a note, for anyone, so every
    # such attempt is "405 Method Not Allowed" and the note is untouched.
    patient = make_patient()
    assign_patient(patient, staff["doctor"])
    note = create_note(client, staff["doctor"]["headers"], patient["id"]).json()

    for who in ("doctor", "admin"):
        response = client.request(
            method.upper(),
            f"/notes/{note['id']}",
            json={"condition_update": "Rewritten"},
            headers=staff[who]["headers"],
        )
        assert response.status_code == 405

    assert list_notes(client, staff["admin"]["headers"], patient["id"]).json() == [note]