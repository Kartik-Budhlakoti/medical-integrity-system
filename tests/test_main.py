# The six security headers the middleware in app/main.py adds to every
# response. Spelled out here in full on purpose: if one is changed on
# purpose, this test is the place that records the new policy.
EXPECTED_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def test_health_check(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_security_headers_are_on_successful_responses(client):
    response = client.get("/health")

    for name, value in EXPECTED_SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, name


def test_security_headers_are_also_on_error_responses(client):
    # A 401 (no token) and a 404 (no such route) both still carry them.
    unauthorized = client.get("/patients/")
    not_found = client.get("/this-route-does-not-exist")

    assert unauthorized.status_code == 401
    assert not_found.status_code == 404
    for response in (unauthorized, not_found):
        for name, value in EXPECTED_SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, name