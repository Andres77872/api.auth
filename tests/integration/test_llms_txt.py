"""GET /llms.txt serves docs/llms.txt with absolute links and the running version."""

import re
from pathlib import Path

import pytest
from starlette.routing import Route


LLMS_TXT = Path(__file__).resolve().parents[2] / "docs" / "llms.txt"
CURL_TARGET = re.compile(r'"\$BASE(/[^"?]*)(?:\?[^"]*)?"')
CURL_METHOD = re.compile(r"-X\s+(GET|POST|PUT|PATCH|DELETE)\b")


def _curl_operations() -> list[tuple[str, str]]:
    """(METHOD, path) of every curl command in the bash blocks of docs/llms.txt."""

    operations = []
    text = LLMS_TXT.read_text(encoding="utf-8")
    for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL):
        # Join continuation lines so -X and the URL of one command sit on one line.
        for command in block.replace("\\\n", " ").splitlines():
            if not command.lstrip().startswith("curl"):
                continue
            target = CURL_TARGET.search(command)
            if target is None or target.group(1) == "/openapi.json":
                continue
            method = CURL_METHOD.search(command)
            operations.append((method.group(1) if method else "GET", target.group(1)))
    return operations


def _matches(path: str, template: str) -> bool:
    """Example segments like `usr-...` or `<public_id>` only match `{param}` segments."""

    segments, expected = path.rstrip("/").split("/"), template.rstrip("/").split("/")
    if len(segments) != len(expected):
        return False
    return all(
        want.startswith("{") or ("..." not in got and "<" not in got and got == want)
        for got, want in zip(segments, expected)
    )


def test_every_curl_example_calls_a_registered_operation(app):
    routes = [
        (method, route.path)
        for route in app.routes
        if isinstance(route, Route)
        for method in route.methods or ()
    ]
    examples = _curl_operations()
    unknown = [
        f"{method} {path}"
        for method, path in examples
        if not any(m == method and _matches(path, template) for m, template in routes)
    ]

    assert len(examples) >= 30
    assert unknown == []


@pytest.mark.asyncio
async def test_llms_txt_uses_the_request_base_url(client, app, monkeypatch):
    monkeypatch.delenv("PUBLIC_API_BASE_URL", raising=False)

    response = await client.get("/llms.txt")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    body = response.text
    assert body.startswith("# api.auth\n")
    assert "{{" not in body
    assert f"API version {app.version}" in body
    assert "(http://test/openapi.json)" in body
    assert 'BASE="http://test"' in body


@pytest.mark.asyncio
async def test_llms_txt_prefers_the_configured_public_base_url(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://auth.example.com/")

    response = await client.get("/llms.txt")

    assert response.status_code == 200
    assert "(https://auth.example.com/openapi.json)" in response.text
    assert "http://test" not in response.text


@pytest.mark.asyncio
async def test_llms_txt_is_gzipped_when_accepted(client):
    response = await client.get("/llms.txt", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.text.startswith("# api.auth\n")
