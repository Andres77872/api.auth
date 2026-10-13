# Request body protection

Every HTTP method and webhook has an 8 MiB (8,388,608-byte) limit. The outer
ASGI receive guard rejects a declared oversized body before authentication or
audit work, and counts actual bytes when a parser or handler reads a body.
Missing, inaccurate, or chunked `Content-Length` framing cannot disable this
count. The guard stops at the first offending chunk; it does not drain the rest.
WebSocket messages and application lifespan events are outside this HTTP limit.

The HTTP response is `413` with the existing JSON error envelope:

```json
{"status":"error","error":{"code":"VAL_3010","category":"validation","message":"Request payload is too large"}}
```

Debug mode can add existing diagnostic fields. Allowed browser origins keep
credentialed CORS headers and `Vary: Origin`. Rejected HTTP/1.x connections close;
normal client connection pools can reconnect. A handler that starts its response
before reading oversized input must abort that connection rather than send a
second status. Early 401/404/405 responses need not read or drain a lengthless body.

## Client compatibility

LAN clients, local development, and `https://auth-ui.arz.ai/` need no request
format, credential, URL, or header changes for bodies within 8 MiB. Chunked
requests still work, and clients do not need to start supplying `Content-Length`.
The limit measures encoded body bytes, including JSON escaping, form encoding,
and multipart overhead. No automatic decompression is introduced.

Clients that previously bypassed the limit with PUT/PATCH/DELETE, webhooks, or
lengthless POSTs must reduce oversized inputs or use an endpoint's supported
batching. Show a request-size error on 413 and do not automatically retry the
unchanged payload. Do not split a single operation unless the API supports it.

API audit JSON bodies are retained only up to 64 KiB. Larger/incomplete inputs
have an omission `_note`, and provider raw bodies remain excluded. Audit viewers
must allow null bodies on in-progress rows and render omission notes. Request
rows are created before processing; bounded capture is filled in the response
transaction without replacing request timestamps. There is no schema migration.

## Deployment checks

1. Test login/authentication, normal admin/import operations, signed webhooks,
   and streamed audit exports in staging from the LAN clients, local development,
   and public auth UI. Check the largest legitimate encoded request bodies.
2. Identify whether the public UI forwards API requests through a reverse proxy.
   Apply an equivalent 8 MiB limit there, covering webhooks as well as other
   routes. For Nginx the size setting is `client_max_body_size 8m;`; also configure
   its 413 error response to use the JSON envelope above and the same explicit
   allowed-origin CORS policy. Do not use wildcard origins with credentials.
3. Verify browser-readable 413s through the real UI/proxy path. A proxy's HTML
   error or missing CORS headers can hide the API error from the UI. The application
   guard also protects direct LAN and development access without a proxy.
4. Verify the API database account can update the existing `api_audit_log`
   columns `request_body`, `request_size_bytes`, and `metadata`, and read `id`
   for the update's row filter. An account with the usual database-wide access
   already supports this. A custom procedure-only account needs these column
   privileges for deferred capture; no table or stored-procedure migration is needed.
5. Restart/deploy the API using the normal release procedure. No coordinated
   client release, dependency upgrade, or database migration is required.
6. Watch 413 counts, API memory, and provider delivery failures. The structured
   `Rejected oversized HTTP request` warning includes `request_method`,
   `request_path`, `received_bytes`, `body_limit_bytes`,
   `declared_content_length`, and `rejection_reason`, without body contents.
   Pre-rejected requests do not enter database-backed audit middleware. Investigate
   legitimate oversized workflows before changing the bounded limit.

Uvicorn's flow-control and incomplete-header limits are not total body limits;
the application guard is authoritative. The production proxy and client sources
are maintained outside this repository.

## Verification

Run the request-body unit, audit-capture, webhook, and real Uvicorn network tests
serially with the repository's normal memory/time rails. Boundary tests cover
8 MiB minus one byte, exactly 8 MiB, and one byte over. Network tests cover ordinary
chunked framing, early rejection, concurrent requests, and connection lifecycle.
