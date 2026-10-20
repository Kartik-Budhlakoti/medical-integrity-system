import pytest

from app.core.validators import height_validator, password_validator, weight_validator

# These are plain-function tests: no HTTP, no database. They pin the exact
# rules, including the edge values, so a rule can't drift without a test
# going red.


# ---------- password_validator ----------

def test_valid_password_is_returned_unchanged():
    assert password_validator("Abcdef1!") == "Abcdef1!"


@pytest.mark.parametrize("password, message", [
    pytest.param("Ab1!xyz", "at least 8 characters", id="too-short"),
    pytest.param("abcdefg1!", "uppercase letter", id="no-uppercase"),
    pytest.param("Abcdefgh!", "at least one number", id="no-number"),
    pytest.param("Abcdefg12", "special character", id="no-special-character"),
])
def test_password_rules_reject_weak_passwords(password, message):
    with pytest.raises(ValueError, match=message):
        password_validator(password)


def test_password_length_limit_is_72_bytes_not_72_characters():
    # bcrypt silently ignores or rejects anything past 72 BYTES. "é" is
    # 2 bytes, so this password is only 39 characters long but 74 bytes.
    multibyte_password = "Aa1!" + "é" * 35
    assert len(multibyte_password) == 39
    assert len(multibyte_password.encode("utf-8")) == 74
    with pytest.raises(ValueError, match="maximum size"):
        password_validator(multibyte_password)


def test_password_of_exactly_72_bytes_is_accepted():
    password = "Aa1!" + "x" * 68
    assert len(password.encode("utf-8")) == 72
    assert password_validator(password) == password


def test_password_of_73_bytes_is_rejected():
    password = "Aa1!" + "x" * 69
    assert len(password.encode("utf-8")) == 73
    with pytest.raises(ValueError, match="maximum size"):
        password_validator(password)


# ---------- height_validator ----------

@pytest.mark.parametrize("height", [30, 30.0, 170.5, 250, 250.0])
def test_height_inside_range_is_accepted(height):
    assert height_validator(height) == height


@pytest.mark.parametrize("height", [29.9, 0, -5, 250.1, 1000])
def test_height_outside_range_is_rejected(height):
    with pytest.raises(ValueError, match="between 30 and 250 cm"):
        height_validator(height)


def test_height_none_passes_through():
    # The update schema allows a field to be left out; the validator
    # lets None through and leaves "is it required?" to the schema.
    assert height_validator(None) is None


# ---------- weight_validator ----------

@pytest.mark.parametrize("weight", [5, 5.0, 65.5, 300, 300.0])
def test_weight_inside_range_is_accepted(weight):
    assert weight_validator(weight) == weight


@pytest.mark.parametrize("weight", [4.9, 0, -1, 300.1, 1000])
def test_weight_outside_range_is_rejected(weight):
    with pytest.raises(ValueError, match="between 5.0 and 300 kg"):
        weight_validator(weight)


def test_weight_none_passes_through():
    assert weight_validator(None) is None