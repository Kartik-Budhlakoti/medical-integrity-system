import pytest

from app.models.nursing_note import NursingNote

# Nursing notes are written by nurses and hold vital signs plus free text.
# Who may do what:
#   create: Nurse only, and only for a patient they are assigned to
#   read:   Admin (any patient), Doctor/Nurse (only assigned patients)
# Notes can never be edited or deleted: there are no such routes.
#
# Setup uses the shared fixtures from conftest.py (`staff`, `make_patient`,
# `assign_patient`, `watch_audit`, `superadmin`).


def note_body(patient_id, **overrides):
    return {
        "patient_id": patient_id,
        "blood_pressure": "120/80",
        "heart_rate": 72,
        "respiratory_rate": 16,
        "pain_level": 3,
        "temperature_celsius": 36.6,
        "oxygen_saturation": 98,
        "care_notes": "Patient resting, no complaints",
        **overrides,
    }


def create_note(client, headers, patient_id, **overrides):
    return client.post("/nursing-notes/create", json=note_body(patient_id, **overrides), headers=headers)


def list_notes(client, headers, patient_id):
    return client.get(f"/nursing-notes/{patient_id}", headers=headers)


def stored_notes(db_session, patient_id):
    db_session.expire_all()
    return db_session.query(NursingNote).filter(NursingNote.patient_id == patient_id).all()


@pytest.fixture
def nursed_patient(staff, make_patient, assign_patient):
    # A fresh patient with the main nurse already assigned.
    patient = make_patient()
    assign_patient(patient, staff["nurse"])
    return patient


# ======================================================================
# POST /nursing-notes/create
# ======================================================================

def test_assigned_nurse_creates_a_note(client, db_session, staff, nursed_patient, watch_audit):
    logged = watch_audit("NOTE_CREATED", user_id=staff["nurse"]["id"])

    response = create_note(client, staff["nurse"]["headers"], nursed_patient["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == nursed_patient["id"]
    assert body["nursing_by_id"] == staff["nurse"]["id"]
    assert body["blood_pressure"] == "120/80"
    assert body["heart_rate"] == 72
    assert body["respiratory_rate"] == 16
    assert body["pain_level"] == 3
    assert body["temperature_celsius"] == 36.6
    assert body["oxygen_saturation"] == 98
    assert body["care_notes"] == "Patient resting, no complaints"
    assert "created_at" in body

    assert [note.id for note in stored_notes(db_session, nursed_patient["id"])] == [body["id"]]
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_type == "nursing_notes"
    assert row.entity_id == body["id"]


def test_only_care_notes_is_needed_the_vitals_are_optional(client, staff, nursed_patient):
    response = client.post(
        "/nursing-notes/create",
        json={"patient_id": nursed_patient["id"], "care_notes": "Slept well"},
        headers=staff["nurse"]["headers"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["care_notes"] == "Slept well"
    for vital in (
        "blood_pressure", "heart_rate", "respiratory_rate",
        "pain_level", "temperature_celsius", "oxygen_saturation",
    ):
        assert body[vital] is None


def test_vitals_sent_as_null_are_stored_as_empty(client, staff, nursed_patient):
    response = create_note(
        client, staff["nurse"]["headers"], nursed_patient["id"],
        blood_pressure=None, heart_rate=None, respiratory_rate=None,
        pain_level=None, temperature_celsius=None, oxygen_saturation=None,
    )

    assert response.status_code == 200
    assert response.json()["heart_rate"] is None


def test_note_author_comes_from_the_login_not_the_request(client, staff, nursed_patient):
    # Anyone could type another nurse's id into the request body. It must
    # be ignored: the author is always whoever is logged in.
    response = create_note(
        client, staff["nurse"]["headers"], nursed_patient["id"],
        nursing_by_id=staff["nurse2"]["id"],
    )

    assert response.status_code == 200
    assert response.json()["nursing_by_id"] == staff["nurse"]["id"]


def test_unassigned_nurse_cannot_create_a_note(client, db_session, staff, make_patient, watch_audit):
    patient = make_patient()
    logged = watch_audit("NOTE_CREATION_FAILED", user_id=staff["nurse2"]["id"])

    response = create_note(client, staff["nurse2"]["headers"], patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not assigned to this patient"
    assert stored_notes(db_session, patient["id"]) == []
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_type == "nursing_notes"
    assert row.entity_id == patient["id"]


@pytest.mark.parametrize("who", ["admin", "doctor"])
def test_only_nurses_can_create_nursing_notes(who, client, db_session, staff, make_patient, assign_patient, watch_audit):
    # The doctor is assigned to the patient, so the role rule is the only
    # thing that can stop them.
    patient = make_patient()
    if who == "doctor":
        assign_patient(patient, staff["doctor"])
    logged = watch_audit("NOTE_CREATION_FAILED", user_id=staff[who]["id"])

    response = create_note(client, staff[who]["headers"], patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Only nurse can create nursing note"
    assert stored_notes(db_session, patient["id"]) == []
    row = logged()
    assert row is not None
    assert row.entity_type == "nursing_notes"


def test_superadmin_cannot_create_a_nursing_note(client, db_session, superadmin, make_patient):
    patient = make_patient()

    response = create_note(client, superadmin["headers"], patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Only nurse can create nursing note"
    assert stored_notes(db_session, patient["id"]) == []


def test_create_requires_login(client, make_patient):
    patient = make_patient()

    response = client.post("/nursing-notes/create", json=note_body(patient["id"]))

    assert response.status_code == 401


def test_create_for_a_nonexistent_patient(client, staff):
    response = create_note(client, staff["nurse"]["headers"], 999999999)

    assert response.status_code == 404
    assert response.json()["detail"] == "Patient not found"


@pytest.mark.parametrize("missing", ["patient_id", "care_notes"])
def test_create_requires_patient_and_care_notes(missing, client, db_session, staff, nursed_patient):
    body = note_body(nursed_patient["id"])
    del body[missing]

    response = client.post("/nursing-notes/create", json=body, headers=staff["nurse"]["headers"])

    assert response.status_code == 422
    assert stored_notes(db_session, nursed_patient["id"]) == []


@pytest.mark.parametrize("blank", ["", " ", "   ", "\n\t"])
def test_blank_care_notes_are_rejected(blank, client, db_session, staff, nursed_patient):
    response = create_note(client, staff["nurse"]["headers"], nursed_patient["id"], care_notes=blank)

    assert response.status_code == 422
    assert stored_notes(db_session, nursed_patient["id"]) == []


# ----------------------------------------------------------------------
# Vital sign limits. Each pair is (lowest allowed, highest allowed) and
# the values just outside them. The database repeats the same limits as
# CHECK constraints, so a value the API accepts can never be refused by
# the database later.
# ----------------------------------------------------------------------

LIMITS = [
    ("pain_level", 0, 10),
    ("heart_rate", 0, 300),
    ("respiratory_rate", 0, 60),
    ("oxygen_saturation", 0, 100),
    ("temperature_celsius", 25, 45),
]


@pytest.mark.parametrize(
    "field, value",
    [(field, edge) for field, low, high in LIMITS for edge in (low, high)],
)
def test_vital_at_its_limit_is_accepted(field, value, client, staff, nursed_patient):
    response = create_note(client, staff["nurse"]["headers"], nursed_patient["id"], **{field: value})

    assert response.status_code == 200
    assert response.json()[field] == value


@pytest.mark.parametrize(
    "field, value",
    [
        (field, bad)
        for field, low, high in LIMITS
        for bad in (low - 1, high + 1)
    ]
    + [("temperature_celsius", 24.9), ("temperature_celsius", 45.1)],
)
def test_vital_outside_its_limit_is_rejected(field, value, client, db_session, staff, nursed_patient):
    response = create_note(client, staff["nurse"]["headers"], nursed_patient["id"], **{field: value})

    assert response.status_code == 422
    assert stored_notes(db_session, nursed_patient["id"]) == []


@pytest.mark.parametrize(
    "field, value",
    [
        ("pain_level", "high"),
        ("pain_level", 5.5),
        ("heart_rate", "fast"),
        ("heart_rate", 72.5),
        ("respiratory_rate", "slow"),
        ("oxygen_saturation", "full"),
        ("temperature_celsius", "warm"),
    ],
)
def test_vital_of_the_wrong_type_is_rejected(field, value, client, staff, nursed_patient):
    response = create_note(client, staff["nurse"]["headers"], nursed_patient["id"], **{field: value})

    assert response.status_code == 422


# ======================================================================
# GET /nursing-notes/{patient_id}
# ======================================================================

def test_admin_reads_every_note_newest_first(client, staff, nursed_patient, watch_audit):
    first = create_note(client, staff["nurse"]["headers"], nursed_patient["id"], care_notes="First").json()
    second = create_note(client, staff["nurse"]["headers"], nursed_patient["id"], care_notes="Second").json()
    logged = watch_audit("NOTE_ACCESSED", user_id=staff["admin"]["id"])

    response = list_notes(client, staff["admin"]["headers"], nursed_patient["id"])

    assert response.status_code == 200
    assert [note["id"] for note in response.json()] == [second["id"], first["id"]]
    assert response.json()[0] == second
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_type == "nursing_notes"
    assert row.entity_id == nursed_patient["id"]


@pytest.mark.parametrize("who", ["doctor", "nurse"])
def test_assigned_doctor_or_nurse_can_read_the_notes(who, client, staff, nursed_patient, assign_patient):
    assign_patient(nursed_patient, staff["doctor"])
    note = create_note(client, staff["nurse"]["headers"], nursed_patient["id"]).json()

    response = list_notes(client, staff[who]["headers"], nursed_patient["id"])

    assert response.status_code == 200
    assert response.json() == [note]


@pytest.mark.parametrize("who", ["doctor2", "nurse2"])
def test_unassigned_doctor_or_nurse_cannot_read_the_notes(who, client, staff, nursed_patient, watch_audit):
    create_note(client, staff["nurse"]["headers"], nursed_patient["id"])
    logged = watch_audit("NOTE_ACCESS_FAILED", user_id=staff[who]["id"])

    response = list_notes(client, staff[who]["headers"], nursed_patient["id"])

    assert response.status_code == 403
    assert response.json() == {"detail": "Not assigned to this patient"}
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_type == "nursing_notes"
    assert row.entity_id == nursed_patient["id"]


def test_superadmin_cannot_read_notes(client, superadmin, nursed_patient):
    response = list_notes(client, superadmin["headers"], nursed_patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"


def test_read_requires_login(client, nursed_patient):
    assert client.get(f"/nursing-notes/{nursed_patient['id']}").status_code == 401


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
    assign_patient(patient_a, staff["nurse"])
    assign_patient(patient_b, staff["nurse"])
    note_a = create_note(client, staff["nurse"]["headers"], patient_a["id"], care_notes="Only A").json()
    note_b = create_note(client, staff["nurse"]["headers"], patient_b["id"], care_notes="Only B").json()

    assert list_notes(client, staff["admin"]["headers"], patient_a["id"]).json() == [note_a]
    assert list_notes(client, staff["admin"]["headers"], patient_b["id"]).json() == [note_b]


def test_nursing_and_treatment_notes_are_kept_apart(client, staff, make_patient, assign_patient):
    # A patient with both kinds of note: each list shows only its own kind.
    patient = make_patient()
    assign_patient(patient, staff["doctor"])
    assign_patient(patient, staff["nurse"])
    nursing = create_note(client, staff["nurse"]["headers"], patient["id"]).json()
    treatment = client.post(
        "/notes/create",
        json={
            "patient_id": patient["id"],
            "condition_update": "Stable",
            "medications": "None",
            "orders": "Observe",
        },
        headers=staff["doctor"]["headers"],
    ).json()

    nursing_list = list_notes(client, staff["admin"]["headers"], patient["id"]).json()
    treatment_list = client.get(f"/notes/{patient['id']}", headers=staff["admin"]["headers"]).json()

    assert nursing_list == [nursing]
    assert treatment_list == [treatment]


def test_unassigning_cuts_off_nursing_notes_access(client, staff, make_patient, assign_patient):
    patient = make_patient()
    assignment = assign_patient(patient, staff["nurse"])
    create_note(client, staff["nurse"]["headers"], patient["id"])
    assert list_notes(client, staff["nurse"]["headers"], patient["id"]).status_code == 200

    client.post(f"/assignments/{assignment['id']}/unassign", headers=staff["admin"]["headers"])

    assert list_notes(client, staff["nurse"]["headers"], patient["id"]).status_code == 403
    assert create_note(client, staff["nurse"]["headers"], patient["id"]).status_code == 403


# ======================================================================
# Notes are append-only
# ======================================================================

@pytest.mark.parametrize("method", ["delete", "patch", "put", "post"])
def test_a_note_cannot_be_edited_or_deleted(method, client, staff, nursed_patient):
    # No route exists to change or remove a note, for anyone, so every
    # such attempt is "405 Method Not Allowed" and the note is untouched.
    note = create_note(client, staff["nurse"]["headers"], nursed_patient["id"]).json()

    for who in ("nurse", "admin"):
        response = client.request(
            method.upper(),
            f"/nursing-notes/{note['id']}",
            json={"care_notes": "Rewritten"},
            headers=staff[who]["headers"],
        )
        assert response.status_code == 405

    assert list_notes(client, staff["admin"]["headers"], nursed_patient["id"]).json() == [note]