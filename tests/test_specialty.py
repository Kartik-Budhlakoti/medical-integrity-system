import uuid

import pytest

from app.models.user import Role, User

# Doctor specialties:
#   PATCH /users/{id}/specialty   Admin only, Doctor accounts only
#   GET   /users/doctors          Admin or SuperAdmin; active doctors only,
#                                 optionally filtered by ?specialty=, sorted
#                                 by full name
#
# The shared database holds every doctor ever created in the run, so the
# list tests look for their own doctors by id instead of counting.

TEST_PASSWORD = "TestPass123!"

SPECIALTIES = ["General Medicine", "Cardiology", "Orthopedics", "Neurology", "Pediatrics", "Emergency Medicine"]


def create_doctor(client, db_session, superadmin, full_name="Specialty Test Doctor", specialty="General Medicine"):
    role = db_session.query(Role).filter(Role.role_name == "Doctor").first()
    payload = {
        "full_name": full_name,
        "email": f"doctor-{uuid.uuid4().hex[:8]}@example.com",
        "password": TEST_PASSWORD,
        "role_id": role.id,
    }
    if specialty is not None:
        payload["specialty"] = specialty
    response = client.post("/users/create", json=payload, headers=superadmin["headers"])
    assert response.status_code == 200, f"doctor setup failed: {response.status_code} {response.text}"
    return response.json()


def set_specialty(client, headers, user_id, specialty):
    return client.patch(f"/users/{user_id}/specialty", json={"updated_specialty": specialty}, headers=headers)


def list_doctors(client, headers, specialty=None):
    params = {"specialty": specialty} if specialty else {}
    return client.get("/users/doctors", params=params, headers=headers)


def stored_specialty(db_session, user_id):
    db_session.expire_all()
    return db_session.query(User).filter(User.id == user_id).first().specialty


# ======================================================================
# PATCH /users/{id}/specialty
# ======================================================================

@pytest.mark.parametrize("specialty", SPECIALTIES)
def test_admin_can_set_every_valid_specialty(specialty, client, db_session, staff, superadmin, watch_audit):
    doctor = create_doctor(client, db_session, superadmin, specialty=None)
    logged = watch_audit("SPECIALTY_UPDATED", user_id=staff["admin"]["id"])

    response = set_specialty(client, staff["admin"]["headers"], doctor["id"], specialty)

    assert response.status_code == 200
    body = response.json()
    assert body["specialty"] == specialty
    assert body["id"] == doctor["id"]
    assert body["email"] == doctor["email"]
    assert body["full_name"] == doctor["full_name"]
    assert stored_specialty(db_session, doctor["id"]) == specialty
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_type == "users"
    assert row.entity_id == doctor["id"]


def test_a_doctor_created_without_a_specialty_can_be_given_one_later(client, db_session, staff, superadmin):
    doctor = create_doctor(client, db_session, superadmin, specialty=None)
    assert doctor["specialty"] is None

    response = set_specialty(client, staff["admin"]["headers"], doctor["id"], "Cardiology")

    assert response.status_code == 200
    assert stored_specialty(db_session, doctor["id"]) == "Cardiology"


def test_superadmin_cannot_change_a_specialty(client, db_session, staff, superadmin, watch_audit):
    doctor = create_doctor(client, db_session, superadmin, specialty="Neurology")
    logged = watch_audit("SPECIALTY_UPDATE_FAILED", user_id=superadmin["id"])

    response = set_specialty(client, superadmin["headers"], doctor["id"], "Cardiology")

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert stored_specialty(db_session, doctor["id"]) == "Neurology"
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_id == doctor["id"]


@pytest.mark.parametrize("who", ["doctor", "nurse"])
def test_doctors_and_nurses_cannot_change_a_specialty(who, client, db_session, staff, superadmin, watch_audit):
    doctor = create_doctor(client, db_session, superadmin, specialty="Neurology")
    logged = watch_audit("SPECIALTY_UPDATE_FAILED", user_id=staff[who]["id"])

    response = set_specialty(client, staff[who]["headers"], doctor["id"], "Cardiology")

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert stored_specialty(db_session, doctor["id"]) == "Neurology"
    assert logged() is not None


def test_a_doctor_cannot_change_their_own_specialty(client, db_session, staff):
    before = stored_specialty(db_session, staff["doctor"]["id"])

    response = set_specialty(client, staff["doctor"]["headers"], staff["doctor"]["id"], "Cardiology")

    assert response.status_code == 403
    assert stored_specialty(db_session, staff["doctor"]["id"]) == before


@pytest.mark.parametrize("target", ["nurse", "admin"])
def test_only_doctor_accounts_can_have_a_specialty(target, client, db_session, staff, watch_audit):
    logged = watch_audit("SPECIALTY_UPDATE_FAILED", user_id=staff["admin"]["id"])

    response = set_specialty(client, staff["admin"]["headers"], staff[target]["id"], "Cardiology")

    assert response.status_code == 400
    assert response.json()["detail"] == "Specialty can only be set for Doctor accounts"
    assert stored_specialty(db_session, staff[target]["id"]) is None
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_id == staff[target]["id"]


def test_specialty_of_an_unknown_user_gives_404(client, staff):
    response = set_specialty(client, staff["admin"]["headers"], 999999999, "Cardiology")

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


@pytest.mark.parametrize("bad", ["Astrology", "cardiology", "", None], ids=["unknown", "wrong letter case", "empty", "null"])
def test_an_invalid_specialty_is_rejected(bad, client, db_session, staff, superadmin):
    doctor = create_doctor(client, db_session, superadmin, specialty="Neurology")

    response = set_specialty(client, staff["admin"]["headers"], doctor["id"], bad)

    assert response.status_code == 422
    assert stored_specialty(db_session, doctor["id"]) == "Neurology"


def test_the_specialty_field_is_required(client, staff, superadmin, db_session):
    doctor = create_doctor(client, db_session, superadmin)

    response = client.patch(f"/users/{doctor['id']}/specialty", json={}, headers=staff["admin"]["headers"])

    assert response.status_code == 422


def test_changing_a_specialty_requires_login(client, db_session, superadmin):
    doctor = create_doctor(client, db_session, superadmin)

    response = client.patch(f"/users/{doctor['id']}/specialty", json={"updated_specialty": "Cardiology"})

    assert response.status_code == 401


# ======================================================================
# GET /users/doctors
# ======================================================================

@pytest.mark.parametrize("who", ["admin", "superadmin"])
def test_admin_and_superadmin_can_list_doctors(who, client, db_session, staff, superadmin, watch_audit):
    caller = staff["admin"] if who == "admin" else superadmin
    doctor = create_doctor(client, db_session, superadmin)
    logged = watch_audit("DOCTORS_LISTED", user_id=caller["id"])

    response = list_doctors(client, caller["headers"])

    assert response.status_code == 200
    assert doctor["id"] in [d["id"] for d in response.json()]
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_type == "users"
    assert row.entity_id == 0


@pytest.mark.parametrize("who", ["doctor", "nurse"])
def test_doctors_and_nurses_cannot_list_doctors(who, client, staff, watch_audit):
    logged = watch_audit("DOCTORS_LIST_FAILED", user_id=staff[who]["id"])

    response = list_doctors(client, staff[who]["headers"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"


def test_listing_doctors_requires_login(client):
    assert client.get("/users/doctors").status_code == 401


def test_only_doctors_appear_in_the_list(client, db_session, staff, superadmin):
    doctor_role_id = db_session.query(Role).filter(Role.role_name == "Doctor").first().id

    response = list_doctors(client, staff["admin"]["headers"])

    ids = [d["id"] for d in response.json()]
    assert staff["doctor"]["id"] in ids
    assert staff["nurse"]["id"] not in ids
    assert staff["admin"]["id"] not in ids
    assert superadmin["id"] not in ids
    assert all(d["role_id"] == doctor_role_id for d in response.json())


def test_a_deactivated_doctor_drops_out_of_the_list(client, db_session, staff, superadmin):
    doctor = create_doctor(client, db_session, superadmin, specialty="Neurology")
    assert doctor["id"] in [d["id"] for d in list_doctors(client, staff["admin"]["headers"]).json()]

    deactivated = client.post(f"/users/{doctor['id']}/deactivate", headers=superadmin["headers"])
    assert deactivated.status_code == 200

    everyone = list_doctors(client, staff["admin"]["headers"])
    neurologists = list_doctors(client, staff["admin"]["headers"], specialty="Neurology")
    assert doctor["id"] not in [d["id"] for d in everyone.json()]
    assert doctor["id"] not in [d["id"] for d in neurologists.json()]


def test_the_list_can_be_filtered_by_specialty(client, db_session, staff, superadmin):
    child_one = create_doctor(client, db_session, superadmin, specialty="Pediatrics")
    child_two = create_doctor(client, db_session, superadmin, specialty="Pediatrics")
    heart = create_doctor(client, db_session, superadmin, specialty="Cardiology")

    filtered = list_doctors(client, staff["admin"]["headers"], specialty="Pediatrics").json()
    everyone = list_doctors(client, staff["admin"]["headers"]).json()

    filtered_ids = [d["id"] for d in filtered]
    assert child_one["id"] in filtered_ids
    assert child_two["id"] in filtered_ids
    assert heart["id"] not in filtered_ids
    assert all(d["specialty"] == "Pediatrics" for d in filtered)
    assert {child_one["id"], child_two["id"], heart["id"]} <= {d["id"] for d in everyone}


def test_a_changed_specialty_moves_the_doctor_between_filters(client, db_session, staff, superadmin):
    doctor = create_doctor(client, db_session, superadmin, specialty="Orthopedics")
    set_specialty(client, staff["admin"]["headers"], doctor["id"], "Emergency Medicine")

    old = list_doctors(client, staff["admin"]["headers"], specialty="Orthopedics").json()
    new = list_doctors(client, staff["admin"]["headers"], specialty="Emergency Medicine").json()

    assert doctor["id"] not in [d["id"] for d in old]
    assert doctor["id"] in [d["id"] for d in new]


def test_a_doctor_without_a_specialty_only_shows_in_the_unfiltered_list(client, db_session, staff, superadmin):
    doctor = create_doctor(client, db_session, superadmin, specialty=None)

    everyone = list_doctors(client, staff["admin"]["headers"]).json()
    entry = next(d for d in everyone if d["id"] == doctor["id"])
    assert entry["specialty"] is None
    for specialty in SPECIALTIES:
        filtered = list_doctors(client, staff["admin"]["headers"], specialty=specialty).json()
        assert doctor["id"] not in [d["id"] for d in filtered]


def test_an_unknown_specialty_filter_is_rejected(client, staff):
    response = list_doctors(client, staff["admin"]["headers"], specialty="Astrology")

    assert response.status_code == 422


def test_doctors_are_sorted_by_name(client, db_session, staff, superadmin):
    tag = uuid.uuid4().hex[:8]
    # Created in an order that is neither alphabetical nor its reverse, so
    # sorting by name is the only thing that can produce A, M, Z.
    middle = create_doctor(client, db_session, superadmin, full_name=f"Zzz {tag} M")
    first = create_doctor(client, db_session, superadmin, full_name=f"Zzz {tag} A")
    last = create_doctor(client, db_session, superadmin, full_name=f"Zzz {tag} Z")

    ids = [d["id"] for d in list_doctors(client, staff["admin"]["headers"]).json()]

    assert ids.index(first["id"]) < ids.index(middle["id"]) < ids.index(last["id"])


def test_the_doctor_list_exposes_only_public_fields(client, staff):
    entry = list_doctors(client, staff["admin"]["headers"]).json()[0]

    assert set(entry) == {"id", "full_name", "email", "role_id", "specialty", "is_active"}