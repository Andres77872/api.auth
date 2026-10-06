"""
OpenAPI document contract

Guards the generated /openapi.json against documentation drift: every operation
is described and carries exactly one declared, grouped tag; every security
requirement names a defined scheme; routes that read credentials or bodies
themselves still document them.
"""

from collections import Counter


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _schema(app):
    app.openapi_schema = None
    return app.openapi()


def _operations(schema):
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                yield method.upper(), path, operation


def test_every_operation_has_one_declared_and_grouped_tag(app):
    schema = _schema(app)
    declared = [tag["name"] for tag in schema["tags"]]
    grouped = Counter(tag for group in schema["x-tagGroups"] for tag in group["tags"])

    assert len(declared) == len(set(declared))
    assert set(grouped) == set(declared)
    assert all(count == 1 for count in grouped.values())
    assert all(tag.get("description") for tag in schema["tags"])

    used = set()
    for method, path, operation in _operations(schema):
        tags = operation.get("tags", [])
        assert len(tags) == 1, f"{method} {path} has tags {tags}"
        used.update(tags)
    assert used == set(declared)


def test_every_operation_has_a_description(app):
    missing = [
        f"{method} {path}"
        for method, path, operation in _operations(_schema(app))
        if not operation.get("description", "").strip()
    ]
    assert missing == []


def test_security_requirements_reference_defined_schemes(app):
    schema = _schema(app)
    schemes = schema["components"]["securitySchemes"]
    assert {"HTTPBearerOrCookie", "ProjectApiKey", "BillingS2SBearer", "PatreonS2SBearer"} <= set(schemes)
    assert all(scheme.get("description") for scheme in schemes.values())

    for method, path, operation in _operations(schema):
        for requirement in operation.get("security", []):
            for name in requirement:
                assert name in schemes, f"{method} {path} references undefined scheme {name}"


def test_validation_failures_are_documented_as_the_400_error_envelope(app):
    schema = _schema(app)
    assert "ErrorResponse" in schema["components"]["schemas"]
    assert "HTTPValidationError" not in schema["components"]["schemas"]

    login = schema["paths"]["/auth/login"]["post"]["responses"]
    assert "422" not in login
    assert login["400"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }


def test_injected_log_context_is_not_a_request_input(app):
    schema = _schema(app)
    for method, path, operation in _operations(schema):
        names = [parameter["name"] for parameter in operation.get("parameters", [])]
        assert "log_context" not in names, f"{method} {path}"
        assert "LogContext" not in str(operation.get("requestBody", {})), f"{method} {path}"
        if method == "GET":
            assert "requestBody" not in operation, f"{method} {path}"
    for name, component in schema["components"]["schemas"].items():
        assert "log_context" not in component.get("properties", {}), name


def test_manually_authenticated_routes_document_their_credentials(app):
    schema = _schema(app)

    def security_names(method, path):
        operation = schema["paths"][path][method]
        return {name for requirement in operation.get("security", []) for name in requirement}

    assert security_names("post", "/auth/validate-api-key") == {"ProjectApiKey"}
    for method, path, _ in _operations(schema):
        if path.startswith("/internal/") and "/billing" in path:
            assert security_names(method.lower(), path) == {"BillingS2SBearer"}, path
        if path.startswith("/internal/users/") and "/entitlements" in path:
            assert security_names(method.lower(), path) == {"PatreonS2SBearer"}, path


def test_webhooks_and_manual_body_routes_document_a_request_body(app):
    schema = _schema(app)
    for path in (
        "/webhooks/stripe/{billing_group_hash}",
        "/webhooks/patreon",
        "/webhooks/email/resend",
        "/auth/oauth/init",
        "/auth/oauth/start",
    ):
        assert "requestBody" in schema["paths"][path]["post"], path


def test_retired_routes_are_absent(app):
    schema = _schema(app)
    assert "/webhooks/stripe" not in schema["paths"]
    assert not any(path.startswith("/auth/google/") for path in schema["paths"])
