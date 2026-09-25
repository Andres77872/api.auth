# Root assistant

The dashboard's floating assistant runs Deep Agents on the FastAPI backend. It
can answer general questions, load domain skills progressively, plan tasks,
delegate to specialists, ask questions, and use the application's management
APIs. Only a currently authenticated **root user** can configure, view or run it.
Administrators and API keys cannot access it. Each root user's conversations,
profiles and settings are isolated from other roots.

## Install and configure

Install `requirements.txt` (which includes `requirements-assistant.txt`) using
Python 3.12 or newer. The Deep Agents harness and provider adapters are pinned
together. The Docker and E2E images install the same dependency set.

Install into the **same interpreter that starts Uvicorn**, then restart that
server. Installing into a separate test environment does not update a running
development server. For the local project virtual environment:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

The requirements include `websockets`, which Uvicorn needs for this endpoint.
If the server logs `No supported WebSocket library detected` and
`GET /admin/assistant/ws` returns 404, the HTTP upgrade failed before the
assistant route ran. Install the requirements into the running interpreter and
restart Uvicorn. A plain HTTP GET to this WebSocket-only URL is not a valid
readiness check.

Set these environment variables on the backend:

- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_MYSQL_PASSWORD` (or `DB_PASSWORD`) and
  `DB_NAME`: the application's existing MySQL connection. This deployment uses
  `DB_HOST=192.168.1.90`, `DB_PORT=3306` and `DB_NAME=magic_auth`. Assistant
  configuration, conversations, events, usage and LangGraph checkpoints all use
  the same database and connection pool as the application. Apply
  `schemas/tables/14_assistant.sql` before starting the API.
- `ASSISTANT_SECRET_KEY`: a Fernet key, required before saving provider API keys.
  Generate with `python -c 'from cryptography.fernet import Fernet;
  print(Fernet.generate_key().decode())'` and store it in your deployment's
  secret manager. It is never returned to the browser or placed in model state.
  Keep it backed up separately; replacing it without re-encrypting profiles
  makes existing credentials unreadable.
- `ASSISTANT_PROVIDER_HOSTS`: comma-separated additional trusted provider hosts,
  for example `host.docker.internal,ollama.internal`. Defaults already permit
  `localhost`, `127.0.0.1`, `::1`, `api.openai.com`, and `api.anthropic.com`.
  Do not include schemes, ports, wildcards, paths, or credentials. Public OpenAI
  and Anthropic endpoints require HTTPS. Private HTTP endpoints are useful for
  explicitly trusted local Ollama/OpenAI-compatible services.
- `ASSISTANT_RUN_TIMEOUT_SECONDS`: maximum run segment duration, default `1800`.
- `ALLOWED_ORIGINS`: must include the dashboard's exact browser origin, including
  its port. WebSocket Origin checks use the same list as HTTP CORS.

Configure your reverse proxy to forward WebSocket upgrade headers for
`/admin/assistant/ws` and allow idle connections for longer than 90 seconds.
The browser sends an application ping every 20 seconds. Browser-owned HttpOnly
session cookies authenticate the socket; tokens never appear in URLs or browser
storage. The existing coordinated HTTP refresh flow renews expired sessions.

In the dashboard, sign in as root, open **Assistant**, and open its settings.
A disabled assistant and a local Ollama profile are created initially. Set the
model to an installed model that supports tool calling (the initial suggestion
is `qwen3:8b`), adjust the backend-reachable URL, and activate the assistant.
Ollama is a separate service; no model is downloaded automatically. Within a
container, `localhost` refers to that container, not the Docker host.

Create additional profiles for OpenAI-compatible and Anthropic APIs as needed.
Several profiles may remain enabled; choose a default and a profile for each
conversation. Profiles have independent model, URL, temperature and token
limits. Ollama also exposes a context-window size (default 32768); allow enough
context for the loaded tool schemas and the conversation. API keys are encrypted at rest and write-only: omitted keys preserve the
existing secret, and an explicit empty key removes it. A stored presence flag
is returned instead of the secret. The server fails closed if no encryption key
is configured.

### Dashboard provider setup

1. Open **AI assistant → Assistant settings → Connections**.
2. Choose **Edit** beside Local Ollama, or **Add connection** for another profile.
3. Set **API format**, **Base URL**, and the exact **Model** identifier supported
   by that provider. The URL is reached by the backend, not the browser.
   - Ollama: use the existing server URL, for example `http://192.168.1.90:11434`,
     and the name of an installed model that supports tool calling. Add
     `192.168.1.90` to `ASSISTANT_PROVIDER_HOSTS` and restart the API when using
     that host. No local Ollama server or model is needed for a remote connection.
   - OpenAI compatible: the API base URL, usually ending in `/v1` (for example
     `https://api.openai.com/v1`), a supported model ID, and its API key.
   - Anthropic compatible: the API base URL (for example
     `https://api.anthropic.com`), a supported model ID, and its API key.
4. Keep **Connection enabled** on, choose **Save connection**, and select the
   profile under **Default connection**.
5. Turn on **Enable AI assistant**, return to chat, and start a conversation.
   Leave write access off for an initial question.

A saved profile does not install an Ollama server or download a model. See the
[Ollama quickstart](https://docs.ollama.com/quickstart) for the separate provider
service. An API-key profile needs `ASSISTANT_SECRET_KEY` configured before saving.

## MySQL deployment

The canonical schema is [14_assistant.sql](../schemas/tables/14_assistant.sql).
It creates the `assistant_*` InnoDB tables, including `assistant_checkpoints`
and `assistant_checkpoint_writes`, in the existing `magic_auth` database.
Fresh-database provisioning and `scripts/schema_sync.py` include this file.
Application startup does not create tables or fall back to local storage.

For an existing database, apply only this additive assistant schema with your
configured database administrator account. The example uses the current host
and database; replace `YOUR_DB_USER` with the appropriate `DB_USER`. The client
prompts for the password so it does not appear in shell history:

```sh
mysql --host=192.168.1.90 --port=3306 --user=YOUR_DB_USER --password \
  --database=magic_auth < schemas/tables/14_assistant.sql
```

Start the API after the schema exists. Include the assistant tables in the
application's MySQL backup and restore procedures.

## Capabilities and safety

All reviewed application read tools and ten skills are enabled by default:
users, groups, projects, security, audit, analytics, billing, Patreon, email and
system operations. The model initially sees skill descriptions. Reading the
relevant `SKILL.md` activates its toolset for that turn; multiple skills can be
loaded. Generic questions do not require application tools. A general-purpose
subagent and domain specialists are always available; disabling a domain still
disables its application tools in delegated work.

Application writes are off by default. To permit one, enable **application
changes** and that individual tool. The dashboard displays a persistent warning
while the switch is active, including when the chat is closed. Every enabled
write also requires explicit approval of its proposed action. Approval gates
apply to subagents too. Disabling the switch or a tool takes effect at execution,
including after an approval was requested. The assistant never receives a
blanket SQL, shell, arbitrary HTTP, or host-filesystem tool. Its skill filesystem
is isolated checkpoint state and is read-only. Planning, conversation context,
and asking questions are configurable; write approvals cannot be disabled.

Each operation is explicitly registered and invokes the existing FastAPI route
in-process, retaining the current root credential and the route's authorization,
validation, business logic, audit logging and permission checks. The executor
revalidates current root status and current tool policy on every invocation.
Adding a new API route does **not** automatically expose a new assistant tool.
Secret fields and credential-like values are redacted before results reach the
model. Output sizes, pagination, run concurrency and command sizes are bounded.
API errors remain failures; the model must not claim unsupported actions work.

The Patreon tier-map endpoint has a backwards-compatible `refresh_catalog`
query parameter. Normal clients retain its existing `true` default. The
assistant's read tool pins it to `false`; catalog refresh is a separate write
tool requiring activation and approval.

## Background execution and recovery

A WebSocket starts a server-owned `asyncio` task and then subscribes to persisted
events. Closing, hiding, resizing, refreshing or reconnecting the client does
not cancel that task. Several conversations can execute concurrently, with a
global bound of eight queued/running runs. Only one active run is permitted per
conversation. Client request IDs deduplicate accepted starts and resumes;
mutations are never silently retried by the transport.

Events have monotonically increasing database sequence numbers. A transactional
snapshot contains the transcript, current run, complete unfinished text,
activity and an event cursor. Reconnecting subscribes after that cursor, so
long generations are restored even if they exceed one replay page. Clients
ignore duplicate events. Questions and approvals persist as LangGraph
interrupts and can be answered after reconnecting, including multiple delegated
interrupts.

Every new turn has its own checkpoint thread and receives completed conversation
history when context is enabled. Resume uses the same run checkpoint. Failed or
cancelled tool calls are never carried into a new turn to be accidentally
replayed. A server process crash is detected by an expired heartbeat and marks
the run interrupted. **It is not automatically replayed:** a change might have
committed before the process died. Inspect its activity and start a new turn or
conversation. Browser restart recovery is automatic; process failure is visibly
reported. Graceful shutdown cancels current runs and persists that status.

Run the assistant with **one API worker**, as the default Docker entrypoint does.
MySQL transactions, row locks and cancellation checks protect run ownership and
concurrency, while current root credentials deliberately stay in worker memory.
A refreshed browser connection routed to another worker cannot refresh the
original worker's credential. Multi-worker deployments therefore require strict
affinity to the executing worker; transparent horizontal deployment still needs
an authenticated job service that coordinates execution and credential refresh.
The shared MySQL storage alone does not provide a distributed job queue. No live
application credential is persisted in job records, and no assistant filesystem
volume is required.

## Persistence, logs and usage

The store keeps settings, provider profiles, conversations, messages, run
statuses, user questions, approvals, task/subagent/tool activity, replay events
and model token usage. Token counts include delegated model calls when the
provider supplies usage metadata; no monetary cost is invented for custom
providers. Usage survives reconnects and human-input pauses. No cloud tracing
service is enabled by this feature.

The assistant panel can delete completed/cancelled conversations. Deletion
removes their messages, events, runs, request IDs and checkpoint namespaces.
Active conversations must first be cancelled. There is no automatic retention
expiry; operators should set a data-retention policy appropriate for their
installation. Include all `assistant_*` tables in the application's consistent
MySQL backups and restore them together. Back up `ASSISTANT_SECRET_KEY` separately
in the secret manager; database backups alone cannot recover encrypted provider
credentials.

## WebSocket contract

All assistant configuration, sessions, runs and streaming use
`/admin/assistant/ws`. Commands are JSON `{id, method, params}`. Responses are
`{id, result}` or `{id, error: {code, message}}`. Timestamps are Unix seconds.
Durable events are `{type: "event", session_id, seq, kind, data, created_at}`.
Credentials are accepted only in the cookie or explicit Bearer header.

Methods: `bootstrap`, `settings.get`, `settings.update`, `profiles.save`, `profiles.delete`,
`sessions.list`, `sessions.create`, `sessions.get`, `sessions.delete`,
`sessions.subscribe`, `sessions.unsubscribe`, `messages.list`, `runs.start`, `runs.resume`,
`runs.cancel`, `usage.get`, `ping`.

- `runs.start`: `session_id`, `message`, `request_id`, optional `profile_id`.
- `runs.resume`: `session_id`, `run_id`, `request_id`, and either `answer`,
  `decisions`, or `responses` mapping interrupt IDs to answers/decision objects.
- `runs.cancel`: `session_id`, `run_id`.
- `sessions.subscribe`: `session_id`, `after_seq` (snapshot's `last_seq`).
  Events written by the serving process arrive within 250 ms. Otherwise the
  subscription polls MySQL, backing off to one read every 2 s while the
  conversation is idle.
- `sessions.list`: optional `limit` (1–100), `before` Unix timestamp.
- `messages.list`: `session_id`, optional `before_id` and `limit` (1–200), for
  paging older transcript messages. Returns `messages` and `has_more`.
- `sessions.get`: returns `session`, `messages`, `events`, `run`,
  `partial_content`, `last_seq`, `has_older_messages`. Older messages are retained in storage; the
  initial display is bounded to the latest 500 messages and 500 activity events.

See `src/assistant/models.py` and the dashboard's `assistant.types.ts` for the
complete typed payloads. The implementation's security and durability tests
are `tests/unit/test_assistant_*.py`; deterministic runtime tests use real Deep
Agents with scripted local models. MySQL persistence, concurrency, replay and
checkpoint recovery are also covered by
`tests/integration/test_assistant_mysql_real_db.py` in an explicitly isolated
`assistant_verify_*` database. Transport tests use an in-memory store double;
runtime tests inject an in-memory checkpoint saver. Durable persistence is
verified against MySQL.
A live provider smoke requires an independently running Ollama or configured
cloud profile.

Research and limitations: [research](ASSISTANT_RESEARCH.md),
[project review](ASSISTANT_PROJECT_REVIEW.md).
