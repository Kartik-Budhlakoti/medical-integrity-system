import hashlib
import io
import uuid

import pytest

import app.routers.file as file_router
from app.core import storage
from app.core.integrity import compute_sha256
from app.core.limiter import limiter
from app.models.file import File as FileModel
from app.models.file import FileHash

# Medical files (scans, reports). Who may do what:
#   upload:      Admin (any patient), Doctor/Nurse (only assigned patients)
#   download:    same people, and only while the file is still active
#   list:        same people, per patient
#   invalidate:  Admin only (one-way: there is no way to undo it)
#
# Every download re-checks the file's SHA-256 against the hash saved at
# upload. A mismatch means someone changed the stored file: the file is
# switched off and TAMPER_DETECTED is logged.
#
# Storage is always the local disk here. conftest.py's `upload_dir`
# fixture points it at a throwaway folder for every test, so real
# Backblaze B2 is never touched.

CONTENT = b"%PDF-1.4 pretend scan data"


def upload(client, headers, patient_id, name="scan.pdf", data=CONTENT, file_type="X-ray"):
    return client.post(
        "/files/upload",
        data={"patient_id": str(patient_id), "file_type": file_type},
        files={"file": (name, data, "application/octet-stream")},
        headers=headers,
    )


def download(client, headers, file_id):
    return client.get(f"/files/{file_id}", headers=headers)


def list_files(client, headers, patient_id):
    return client.get(f"/files/patient/{patient_id}", headers=headers)


def invalidate(client, headers, file_id, reason="Uploaded to the wrong patient"):
    return client.post(f"/files/{file_id}/invalidate", json={"invalidation_reason": reason}, headers=headers)


def file_row(db_session, file_id):
    db_session.expire_all()
    return db_session.query(FileModel).filter(FileModel.id == file_id).first()


def file_count(db_session, patient_id):
    db_session.expire_all()
    return db_session.query(FileModel).filter(FileModel.patient_id == patient_id).count()


@pytest.fixture
def scan_patient(make_patient, assign_patient, staff):
    # A fresh patient with the main doctor and the main nurse assigned.
    patient = make_patient()
    assign_patient(patient, staff["doctor"])
    assign_patient(patient, staff["nurse"])
    return patient


@pytest.fixture
def uploaded(client, staff, scan_patient):
    # One file uploaded by the main doctor; returns the upload response body.
    response = upload(client, staff["doctor"]["headers"], scan_patient["id"])
    assert response.status_code == 200
    return response.json()


# ======================================================================
# POST /files/upload
# ======================================================================

@pytest.mark.parametrize("who", ["doctor", "nurse"])
def test_assigned_doctor_or_nurse_uploads_a_file(who, client, db_session, staff, scan_patient, upload_dir, watch_audit):
    logged = watch_audit("FILE_UPLOADED", user_id=staff[who]["id"])

    response = upload(client, staff[who]["headers"], scan_patient["id"], name="chest.pdf", file_type="X-ray")

    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == scan_patient["id"]
    assert body["file_type"] == "X-ray"
    assert body["file_name"] == "chest.pdf"
    assert body["uploaded_by_id"] == staff[who]["id"]
    assert body["is_active"] is True
    assert "created_at" in body

    # The bytes really are in storage, unchanged...
    assert (upload_dir / body["file_path"]).read_bytes() == CONTENT
    # ...and the hash saved in the database is the real SHA-256 of them.
    record = file_row(db_session, body["id"])
    assert record.file_hash.hash_value == hashlib.sha256(CONTENT).hexdigest()
    assert record.file_hash.verified_at is None

    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_type == "files"
    assert row.entity_id == body["id"]


def test_admin_can_upload_for_any_patient(client, staff, make_patient):
    patient = make_patient()  # nobody is assigned to this patient

    response = upload(client, staff["admin"]["headers"], patient["id"])

    assert response.status_code == 200
    assert response.json()["uploaded_by_id"] == staff["admin"]["id"]


def test_files_are_stored_under_a_random_name(client, staff, scan_patient):
    response = upload(client, staff["doctor"]["headers"], scan_patient["id"], name="John Smith MRI.pdf")

    body = response.json()
    assert body["file_name"] == "John Smith MRI.pdf"  # what people see
    assert body["file_path"].endswith(".pdf")
    uuid.UUID(body["file_path"].removesuffix(".pdf"))  # raises if it is not a UUID


def test_a_filename_cannot_change_where_the_file_is_stored(client, staff, scan_patient, upload_dir):
    # The name a client sends is only ever a label. The storage name is a
    # fresh UUID, so "../../" in it cannot write outside the storage folder.
    response = upload(client, staff["doctor"]["headers"], scan_patient["id"], name="../../evil.pdf")

    assert response.status_code == 200
    body = response.json()
    assert body["file_name"] == "../../evil.pdf"
    assert [p.name for p in upload_dir.iterdir()] == [body["file_path"]]
    assert [p.name for p in upload_dir.parent.iterdir()] == ["uploads"]
    assert not (upload_dir.parent.parent / "evil.pdf").exists()


@pytest.mark.parametrize("name", ["scan.pdf", "SCAN.PDF", "photo.jpg", "photo.JPG", "photo.jpeg", "photo.png", "image.dcm"])
def test_allowed_file_types_are_accepted_in_any_letter_case(name, client, staff, scan_patient):
    response = upload(client, staff["doctor"]["headers"], scan_patient["id"], name=name)

    assert response.status_code == 200
    assert response.json()["file_path"].endswith("." + name.rsplit(".", 1)[1].lower())


@pytest.mark.parametrize("name", ["scan", "run.exe", "page.html", "notes.txt", "archive.zip", "script.pdf.exe"])
def test_other_file_types_are_rejected(name, client, db_session, staff, scan_patient, upload_dir):
    response = upload(client, staff["doctor"]["headers"], scan_patient["id"], name=name)

    assert response.status_code == 400
    assert response.json()["detail"] == "File type not allowed"
    assert file_count(db_session, scan_patient["id"]) == 0
    assert list(upload_dir.iterdir()) == []


# KNOWN LIMITATION, already in known-issues.md ("File upload validation
# only checks the extension"). Pinned as "expected to fail" so it shows up
# in `pytest -rx` until the content check exists; delete the marker then.
@pytest.mark.xfail(strict=True, reason="only the file extension is checked, not the contents")
def test_a_file_whose_contents_do_not_match_its_extension_is_rejected(client, staff, scan_patient):
    windows_program = b"MZ\x90\x00\x03\x00\x00\x00"

    response = upload(client, staff["doctor"]["headers"], scan_patient["id"], name="invoice.pdf", data=windows_program)

    assert response.status_code == 400


def test_the_size_limit_is_50_megabytes():
    assert file_router.MAX_FILE_SIZE == 50 * 1024 * 1024


def test_a_file_exactly_at_the_size_limit_is_accepted_and_one_byte_more_is_not(
    client, db_session, staff, scan_patient, upload_dir, monkeypatch
):
    # Shrinks the limit to 100 bytes so the test does not have to push
    # 50 MB through the app.
    monkeypatch.setattr(file_router, "MAX_FILE_SIZE", 100)

    at_limit = upload(client, staff["doctor"]["headers"], scan_patient["id"], data=b"x" * 100)
    too_big = upload(client, staff["doctor"]["headers"], scan_patient["id"], data=b"x" * 101)

    assert at_limit.status_code == 200
    assert too_big.status_code == 413
    assert too_big.json()["detail"] == "File too large. Maximum 50MB."
    assert file_count(db_session, scan_patient["id"]) == 1
    assert len(list(upload_dir.iterdir())) == 1


@pytest.mark.parametrize("who", ["doctor2", "nurse2"])
def test_unassigned_doctor_or_nurse_cannot_upload(who, client, db_session, staff, scan_patient, upload_dir, watch_audit):
    logged = watch_audit("FILE_UPLOAD_FAILED", user_id=staff[who]["id"])

    response = upload(client, staff[who]["headers"], scan_patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not assigned to this patient"
    assert file_count(db_session, scan_patient["id"]) == 0
    assert list(upload_dir.iterdir()) == []
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_type == "files"
    assert row.entity_id == scan_patient["id"]


def test_superadmin_cannot_upload(client, db_session, superadmin, scan_patient, upload_dir, watch_audit):
    logged = watch_audit("FILE_UPLOAD_FAILED", user_id=superadmin["id"])

    response = upload(client, superadmin["headers"], scan_patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert file_count(db_session, scan_patient["id"]) == 0
    assert list(upload_dir.iterdir()) == []
    assert logged() is not None


def test_upload_requires_login(client, scan_patient):
    response = client.post(
        "/files/upload",
        data={"patient_id": str(scan_patient["id"]), "file_type": "X-ray"},
        files={"file": ("scan.pdf", CONTENT)},
    )

    assert response.status_code == 401


@pytest.mark.parametrize("who", ["admin", "doctor"])
def test_upload_for_a_nonexistent_patient(who, client, staff):
    # Known limitation: see the matching test in test_patient.py (404 vs 403).
    response = upload(client, staff[who]["headers"], 999999999)

    assert response.status_code == 404
    assert response.json()["detail"] == "Patient not found"


@pytest.mark.parametrize("case", ["no file", "no patient_id", "no file_type", "patient_id is not a number"])
def test_upload_with_missing_or_bad_parts_is_rejected(case, client, db_session, staff, scan_patient, upload_dir):
    pid = str(scan_patient["id"])
    parts = {
        "no file": {"data": {"patient_id": pid, "file_type": "X-ray"}},
        "no patient_id": {"data": {"file_type": "X-ray"}, "files": {"file": ("scan.pdf", CONTENT)}},
        "no file_type": {"data": {"patient_id": pid}, "files": {"file": ("scan.pdf", CONTENT)}},
        "patient_id is not a number": {
            "data": {"patient_id": "abc", "file_type": "X-ray"},
            "files": {"file": ("scan.pdf", CONTENT)},
        },
    }[case]

    response = client.post("/files/upload", headers=staff["doctor"]["headers"], **parts)

    assert response.status_code == 422
    assert file_count(db_session, scan_patient["id"]) == 0
    assert list(upload_dir.iterdir()) == []


def test_when_storage_fails_nothing_is_saved(client, db_session, staff, scan_patient, monkeypatch, watch_audit):
    def broken_storage(key, data):
        raise RuntimeError("disk full")

    monkeypatch.setattr(storage, "upload_bytes", broken_storage)
    logged = watch_audit("FILE_UPLOAD_FAILED", user_id=staff["doctor"]["id"])

    response = upload(client, staff["doctor"]["headers"], scan_patient["id"])

    assert response.status_code == 500
    assert response.json()["detail"] == "File upload failed, please try again"
    assert file_count(db_session, scan_patient["id"]) == 0
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_id == scan_patient["id"]


def test_when_the_database_fails_the_stored_file_is_removed_again(
    client, db_session, staff, scan_patient, upload_dir, monkeypatch, watch_audit
):
    # The file is written to storage first and the database rows second.
    # If the database part fails, the file must not be left behind with
    # nothing pointing at it.
    def broken_hash_row(**kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(file_router, "FileHash", broken_hash_row)
    logged = watch_audit("FILE_UPLOAD_FAILED", user_id=staff["doctor"]["id"])

    response = upload(client, staff["doctor"]["headers"], scan_patient["id"])

    assert response.status_code == 500
    assert response.json()["detail"] == "File upload failed, please try again"
    assert file_count(db_session, scan_patient["id"]) == 0
    assert list(upload_dir.iterdir()) == []
    assert logged() is not None


# ======================================================================
# GET /files/{file_id}  (download + integrity check)
# ======================================================================

@pytest.mark.parametrize("who", ["doctor", "nurse", "admin"])
def test_assigned_staff_and_admin_can_download(who, client, db_session, staff, uploaded, watch_audit):
    logged = watch_audit("FILE_ACCESSED", user_id=staff[who]["id"])

    response = download(client, staff[who]["headers"], uploaded["id"])

    assert response.status_code == 200
    assert response.content == CONTENT
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''scan.pdf"
    assert file_row(db_session, uploaded["id"]).file_hash.verified_at is not None
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_type == "files"
    assert row.entity_id == uploaded["id"]


@pytest.mark.parametrize(
    "name, expected",
    [
        ("my scan.pdf", "my%20scan.pdf"),
        ("scán é.pdf", "sc%C3%A1n%20%C3%A9.pdf"),
    ],
)
def test_download_filename_is_url_encoded(name, expected, client, staff, scan_patient):
    file_id = upload(client, staff["doctor"]["headers"], scan_patient["id"], name=name).json()["id"]

    response = download(client, staff["doctor"]["headers"], file_id)

    assert response.headers["content-disposition"] == f"attachment; filename*=UTF-8''{expected}"


@pytest.mark.parametrize("who", ["doctor2", "nurse2"])
def test_unassigned_doctor_or_nurse_cannot_download(who, client, staff, uploaded, watch_audit):
    logged = watch_audit("FILE_ACCESS_DENIED", user_id=staff[who]["id"])

    response = download(client, staff[who]["headers"], uploaded["id"])

    assert response.status_code == 403
    assert response.json() == {"detail": "Not assigned to this patient"}
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_id == uploaded["id"]


def test_superadmin_cannot_download(client, superadmin, uploaded, watch_audit):
    logged = watch_audit("FILE_ACCESS_DENIED", user_id=superadmin["id"])

    response = download(client, superadmin["headers"], uploaded["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert logged() is not None


@pytest.mark.parametrize("who", ["admin", "doctor"])
def test_download_of_an_unknown_file_gives_404(who, client, staff):
    # Known limitation: a doctor or nurse can tell which file numbers
    # exist from 404 vs 403 (same pattern as patients).
    response = download(client, staff[who]["headers"], 999999999)

    assert response.status_code == 404
    assert response.json()["detail"] == "File not found"


def test_download_with_a_non_numeric_id(client, staff):
    assert client.get("/files/abc", headers=staff["admin"]["headers"]).status_code == 422


def test_download_requires_login(client, uploaded):
    assert client.get(f"/files/{uploaded['id']}").status_code == 401


def test_unassigning_cuts_off_file_access(client, staff, make_patient, assign_patient):
    patient = make_patient()
    assignment = assign_patient(patient, staff["doctor"])
    file_id = upload(client, staff["doctor"]["headers"], patient["id"]).json()["id"]
    assert download(client, staff["doctor"]["headers"], file_id).status_code == 200

    client.post(f"/assignments/{assignment['id']}/unassign", headers=staff["admin"]["headers"])

    assert download(client, staff["doctor"]["headers"], file_id).status_code == 403
    assert upload(client, staff["doctor"]["headers"], patient["id"]).status_code == 403


# ----------------------------------------------------------------------
# Tamper detection
# ----------------------------------------------------------------------

TAMPERINGS = {
    "one byte flipped": lambda data: bytes([data[0] ^ 1]) + data[1:],
    "one byte added": lambda data: data + b"x",
    "emptied": lambda data: b"",
    "swapped for another file": lambda data: b"a completely different file",
}


@pytest.mark.parametrize("tamper", TAMPERINGS.values(), ids=TAMPERINGS.keys())
def test_a_changed_file_is_refused_and_switched_off(tamper, client, db_session, staff, uploaded, upload_dir, watch_audit):
    stored = upload_dir / uploaded["file_path"]
    stored.write_bytes(tamper(stored.read_bytes()))
    logged = watch_audit("TAMPER_DETECTED", user_id=staff["doctor"]["id"])

    response = download(client, staff["doctor"]["headers"], uploaded["id"])

    # The altered bytes are never handed out.
    assert response.status_code == 403
    assert response.json()["detail"] == "File integrity verification failed"
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_type == "files"
    assert row.entity_id == uploaded["id"]
    assert file_row(db_session, uploaded["id"]).is_active is False

    # From now on the file is blocked for everyone, admins included.
    again = download(client, staff["admin"]["headers"], uploaded["id"])
    assert again.status_code == 403
    assert again.json()["detail"] == "File is invalidated"


def test_an_untouched_file_passes_the_check_every_time(client, staff, uploaded):
    for _ in range(3):
        response = download(client, staff["doctor"]["headers"], uploaded["id"])
        assert response.status_code == 200
        assert response.content == CONTENT


def test_download_when_the_stored_file_is_missing(client, db_session, staff, uploaded, upload_dir, watch_audit):
    (upload_dir / uploaded["file_path"]).unlink()
    logged = watch_audit("FILE_RETRIEVAL_FAILED", user_id=staff["doctor"]["id"])

    response = download(client, staff["doctor"]["headers"], uploaded["id"])

    assert response.status_code == 500
    assert response.json()["detail"] == "Unable to retrieve file"
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_id == uploaded["id"]
    # A missing file is an outage, not tampering: the file is not switched off.
    assert file_row(db_session, uploaded["id"]).is_active is True


def test_download_when_the_saved_hash_is_missing(client, db_session, staff, uploaded, watch_audit):
    db_session.query(FileHash).filter(FileHash.file_id == uploaded["id"]).delete()
    db_session.commit()
    logged = watch_audit("FILE_INTEGRITY_RECORD_MISSING", user_id=staff["doctor"]["id"])

    response = download(client, staff["doctor"]["headers"], uploaded["id"])

    assert response.status_code == 500
    assert response.json()["detail"] == "File hash not found"
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_id == uploaded["id"]


# ======================================================================
# GET /files/patient/{patient_id}
# ======================================================================

def test_admin_lists_a_patients_files_newest_first(client, staff, scan_patient, watch_audit):
    first = upload(client, staff["doctor"]["headers"], scan_patient["id"], name="first.pdf").json()
    second = upload(client, staff["nurse"]["headers"], scan_patient["id"], name="second.pdf").json()
    logged = watch_audit("FILES_LISTED", user_id=staff["admin"]["id"])

    response = list_files(client, staff["admin"]["headers"], scan_patient["id"])

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [second["id"], first["id"]]
    assert body[0]["file_name"] == "second.pdf"
    assert body[0]["uploaded_by_id"] == staff["nurse"]["id"]
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_type == "files"
    assert row.entity_id == scan_patient["id"]


def test_the_list_never_shows_the_internal_storage_name(client, staff, uploaded, scan_patient):
    item = list_files(client, staff["admin"]["headers"], scan_patient["id"]).json()[0]

    assert set(item) == {
        "id", "patient_id", "file_type", "file_name", "uploaded_by_id", "is_active",
        "invalidation_reason", "invalidated_by_id", "invalidated_at", "verified_at", "created_at",
    }


def test_verified_at_is_empty_until_the_file_is_first_downloaded(client, staff, uploaded, scan_patient):
    before = list_files(client, staff["admin"]["headers"], scan_patient["id"]).json()[0]
    download(client, staff["doctor"]["headers"], uploaded["id"])
    after = list_files(client, staff["admin"]["headers"], scan_patient["id"]).json()[0]

    assert before["verified_at"] is None
    assert after["verified_at"] is not None


@pytest.mark.parametrize("who", ["doctor", "nurse"])
def test_assigned_doctor_or_nurse_can_list(who, client, staff, uploaded, scan_patient):
    response = list_files(client, staff[who]["headers"], scan_patient["id"])

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [uploaded["id"]]


@pytest.mark.parametrize("who", ["doctor2", "nurse2"])
def test_unassigned_doctor_or_nurse_cannot_list(who, client, staff, uploaded, scan_patient, watch_audit):
    logged = watch_audit("FILE_ACCESS_DENIED", user_id=staff[who]["id"])

    response = list_files(client, staff[who]["headers"], scan_patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not assigned to this patient"
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_id == scan_patient["id"]


def test_superadmin_cannot_list(client, superadmin, scan_patient):
    response = list_files(client, superadmin["headers"], scan_patient["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"


def test_list_requires_login(client, scan_patient):
    assert client.get(f"/files/patient/{scan_patient['id']}").status_code == 401


def test_list_for_a_nonexistent_patient(client, staff):
    response = list_files(client, staff["admin"]["headers"], 999999999)

    assert response.status_code == 404
    assert response.json()["detail"] == "Patient not found"


def test_patient_with_no_files_gives_an_empty_list(client, staff, make_patient):
    patient = make_patient()

    response = list_files(client, staff["admin"]["headers"], patient["id"])

    assert response.status_code == 200
    assert response.json() == []


def test_files_never_leak_between_patients(client, staff, make_patient):
    patient_a = make_patient()
    patient_b = make_patient()
    file_a = upload(client, staff["admin"]["headers"], patient_a["id"], name="a.pdf").json()
    file_b = upload(client, staff["admin"]["headers"], patient_b["id"], name="b.pdf").json()

    assert [f["id"] for f in list_files(client, staff["admin"]["headers"], patient_a["id"]).json()] == [file_a["id"]]
    assert [f["id"] for f in list_files(client, staff["admin"]["headers"], patient_b["id"]).json()] == [file_b["id"]]


# ======================================================================
# POST /files/{file_id}/invalidate
# ======================================================================

def test_admin_invalidates_a_file(client, db_session, staff, uploaded, scan_patient, watch_audit):
    logged = watch_audit("FILE_INVALIDATED", user_id=staff["admin"]["id"])

    response = invalidate(client, staff["admin"]["headers"], uploaded["id"], reason="Wrong patient")

    assert response.status_code == 200
    assert response.json() == {"message": "File invalidated successfully"}
    record = file_row(db_session, uploaded["id"])
    assert record.is_active is False
    assert record.invalidation_reason == "Wrong patient"
    assert record.invalidated_by_id == staff["admin"]["id"]
    assert record.invalidated_at is not None
    row = logged()
    assert row is not None
    assert row.result == "SUCCESS"
    assert row.entity_id == uploaded["id"]

    # The list still shows the file, now with the who/why/when.
    item = list_files(client, staff["admin"]["headers"], scan_patient["id"]).json()[0]
    assert item["is_active"] is False
    assert item["invalidation_reason"] == "Wrong patient"
    assert item["invalidated_by_id"] == staff["admin"]["id"]
    assert item["invalidated_at"] is not None


@pytest.mark.parametrize("who", ["doctor", "nurse", "admin"])
def test_an_invalidated_file_cannot_be_downloaded_by_anyone(who, client, staff, uploaded, watch_audit):
    invalidate(client, staff["admin"]["headers"], uploaded["id"])
    logged = watch_audit("FILE_ACCESS_DENIED", user_id=staff[who]["id"])

    response = download(client, staff[who]["headers"], uploaded["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "File is invalidated"
    assert logged() is not None


def test_a_file_cannot_be_invalidated_twice(client, db_session, staff, uploaded, watch_audit):
    invalidate(client, staff["admin"]["headers"], uploaded["id"], reason="First reason")
    logged = watch_audit("FILE_INVALIDATION_FAILED", user_id=staff["admin"]["id"])

    response = invalidate(client, staff["admin"]["headers"], uploaded["id"], reason="Second reason")

    assert response.status_code == 400
    assert response.json()["detail"] == "File is already invalidated"
    assert file_row(db_session, uploaded["id"]).invalidation_reason == "First reason"
    assert logged() is not None


@pytest.mark.parametrize("who", ["doctor", "nurse"])
def test_only_admins_can_invalidate(who, client, db_session, staff, uploaded, watch_audit):
    logged = watch_audit("FILE_INVALIDATION_FAILED", user_id=staff[who]["id"])

    response = invalidate(client, staff[who]["headers"], uploaded["id"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized"
    assert file_row(db_session, uploaded["id"]).is_active is True
    row = logged()
    assert row is not None
    assert row.result == "FAILURE"
    assert row.entity_id == uploaded["id"]


def test_superadmin_cannot_invalidate(client, db_session, superadmin, uploaded):
    response = invalidate(client, superadmin["headers"], uploaded["id"])

    assert response.status_code == 403
    assert file_row(db_session, uploaded["id"]).is_active is True


def test_a_non_admin_gets_403_even_for_a_file_that_does_not_exist(client, staff):
    # The role check comes first, so a doctor cannot use this route to
    # find out which file numbers exist.
    response = invalidate(client, staff["doctor"]["headers"], 999999999)

    assert response.status_code == 403


def test_invalidating_an_unknown_file_gives_404(client, staff):
    response = invalidate(client, staff["admin"]["headers"], 999999999)

    assert response.status_code == 404
    assert response.json()["detail"] == "File not found"


@pytest.mark.parametrize("body", [{"invalidation_reason": ""}, {"invalidation_reason": "   "}, {"invalidation_reason": "\n\t"}, {}])
def test_a_reason_is_required_to_invalidate(body, client, db_session, staff, uploaded):
    response = client.post(f"/files/{uploaded['id']}/invalidate", json=body, headers=staff["admin"]["headers"])

    assert response.status_code == 422
    assert file_row(db_session, uploaded["id"]).is_active is True


def test_invalidate_requires_login(client, uploaded):
    response = client.post(f"/files/{uploaded['id']}/invalidate", json={"invalidation_reason": "x"})

    assert response.status_code == 401


# ======================================================================
# Rate limits (the limiter is off for the rest of the suite, so these
# switch it on for one test and always switch it off again)
# ======================================================================

def test_upload_is_limited_to_ten_per_minute(client, staff, scan_patient):
    limiter.reset()
    limiter.enabled = True
    try:
        for _ in range(10):
            assert upload(client, staff["doctor"]["headers"], scan_patient["id"]).status_code == 200
        assert upload(client, staff["doctor"]["headers"], scan_patient["id"]).status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()


def test_download_is_limited_to_twenty_per_minute(client, staff, uploaded):
    limiter.reset()
    limiter.enabled = True
    try:
        for _ in range(20):
            assert download(client, staff["doctor"]["headers"], uploaded["id"]).status_code == 200
        assert download(client, staff["doctor"]["headers"], uploaded["id"]).status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()


# ======================================================================
# Storage layer and hashing, tested directly
# ======================================================================

def test_local_storage_round_trip(upload_dir):
    storage.upload_bytes("a.bin", b"data")

    assert (upload_dir / "a.bin").read_bytes() == b"data"
    assert storage.download_bytes("a.bin") == b"data"

    storage.delete_bytes("a.bin")

    assert not (upload_dir / "a.bin").exists()


def test_local_storage_deleting_a_missing_file_is_not_an_error(upload_dir):
    storage.delete_bytes("never-existed.bin")


def test_local_storage_reading_a_missing_file_fails(upload_dir):
    with pytest.raises(FileNotFoundError):
        storage.download_bytes("never-existed.bin")


def test_local_storage_creates_its_folder_when_missing(monkeypatch, tmp_path):
    folder = tmp_path / "not" / "there" / "yet"
    monkeypatch.setattr(storage, "UPLOAD_DIR", str(folder))

    storage.upload_bytes("a.bin", b"data")

    assert (folder / "a.bin").read_bytes() == b"data"


class FakeS3:
    # Stands in for the boto3 client, so the B2 code path runs with no network.
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


def test_b2_storage_uses_the_bucket_and_never_the_local_disk(upload_dir, monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(storage, "STORAGE_BACKEND", "b2")
    monkeypatch.setattr(storage, "s3_client", fake, raising=False)
    monkeypatch.setattr(storage, "BUCKET_NAME", "test-bucket", raising=False)

    storage.upload_bytes("k.pdf", b"data")
    assert fake.objects == {("test-bucket", "k.pdf"): b"data"}
    assert storage.download_bytes("k.pdf") == b"data"
    storage.delete_bytes("k.pdf")

    assert fake.objects == {}
    assert list(upload_dir.iterdir()) == []


@pytest.mark.parametrize(
    "data, expected",
    [
        (b"", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
        (b"abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
    ],
)
def test_sha256_matches_the_published_test_values(data, expected):
    assert compute_sha256(data) == expected


def test_sha256_changes_when_one_byte_changes():
    assert compute_sha256(b"scan-1") != compute_sha256(b"scan-2")