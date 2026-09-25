# Assistant research and implementation decisions

Research date: 24 September 2026. The implementation uses the published Python
`deepagents==0.7.19` package, inspected locally after installation, rather than
assuming older examples still describe its API. `requirements-assistant.txt`
pins the harness, graph, checkpoint adapter, provider adapters and compatibility
sensitive SDKs. A combined installation with the existing application and test
requirements was verified on Python 3.13.

## Harness and skill routing

Deep Agents supplies planning, virtual files, skills, summarization and subagent
delegation through `create_deep_agent`. Skills expose only their metadata at
startup; detailed instructions load through a file read. Our application adds
middleware that hides domain tools until the corresponding skill file has been
successfully read. More than one domain can be active. Loading resets on the
next user turn, so a general follow-up does not keep unrelated application tools
in the model's tool schema. Tool execution checks activation independently of
schema filtering. This is application policy layered on the documented
[Deep Agents skills mechanism](https://docs.langchain.com/oss/python/deepagents/skills)
and [LangChain model/tool middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom).

General questions can finish after one model response. No extra classifier model
or broad data search runs before the answer. Planning is enabled by default in this app through explicit
`TodoListMiddleware` (the 0.7 harness makes it optional) and can be disabled independently. A domain specialist for every app area and a
general-purpose subagent remain available. Each has its own safety middleware,
skill loading and permitted tools; specialists do not inherit a larger toolset.
The explicit general-purpose declaration avoids relying on implicit middleware
inheritance. See the official
[subagent configuration and isolation documentation](https://docs.langchain.com/oss/python/deepagents/subagents).

## Authorization and actions

Application operations use a reviewed route catalog and the existing ASGI app,
so existing validation and authorization are reused. HTTP method alone is not a
sufficient read/write classification: an endpoint that refreshes provider state
can mutate even when invoked with GET. The catalog explicitly records these
exceptions and supplies a read-only tier-map operation that forces refresh off.

Mutation authorization has separate layers: root authentication, enabled
assistant/skill/tool settings, the mutation switch and human approval of the
specific operation. The executor rechecks live policy when an action actually
runs. A model can neither switch permissions nor make a direct SQL/HTTP request.
Mutation tools pause using Deep Agents `interrupt_on`; only approve/reject are
accepted, avoiding an unreviewed action replacement. The same policy applies to
subagents. [Deep Agents human-in-the-loop reference](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop).

`ask_user` uses a LangGraph interrupt for missing targets or choices. Interrupt
identifiers and values are persisted, including parallel subagent interrupts.
The client provides an answer or explicit decisions, and a new graph instance
can resume the same checkpoint. No tool work precedes the interrupt inside the
question tool. These decisions follow the documented replay semantics of
[LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts).

## Backend execution and persistence

The job owner is the backend, not a browser connection. It persists messages,
runs, events, usage and human decisions; WebSocket consumers replay ordered
events from their last sequence. Both application state and graph checkpoints
use the application's existing configured MySQL database. `MySQLCheckpointSaver`
implements the installed LangGraph `BaseCheckpointSaver` protocol using the
project connection pool, with blocking database work dispatched off the event
loop. SQLite remains an explicitly selected test backend and a read-only source
for importing earlier local state; production does not fall back to it.
Streaming uses graph message/update channels with subgraph
namespaces. Main-answer text is separated from specialist output; tools, plans
and specialist progress are structured events. A model callback aggregates
usage across parent and child calls. Provider reasoning blocks and arbitrary
provider metadata are not sent to the browser.
[LangGraph streaming documentation](https://docs.langchain.com/oss/python/langgraph/streaming).

Checkpoints and the application event log serve different purposes: checkpoints
resume computation; the event log restores what the user sees. Losing a socket
does not cancel work. Cancellation is a backend job action. An interrupted or
failed mutation is not automatically retried: a new checkpoint generation and
completed conversation messages avoid replaying an uncertain action. The
runtime accepts an explicit checkpoint identity and completed-message history
for this recovery boundary.

Checkpoint values, metadata and intermediate writes retain their LangGraph
serializer type tags. Parent checkpoint links and nested namespaces survive a
new graph instance. Repeated ordinary task writes keep the original result;
reserved interrupt/error/resume writes replace their own index. These follow the
[official checkpoint interface and default delta-history traversal](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint/langgraph/checkpoint/base/__init__.py)
and the [official SQLite reference implementation](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/aio.py).
Full namespace text is retained alongside a SHA-256 index key, so nested
subagents do not exceed [InnoDB index-size limits](https://dev.mysql.com/doc/refman/8.4/en/innodb-limits.html).
Schema creation belongs to the application's canonical migration; the saver
only validates its tables and never silently creates another database. Each
operation finishes one transaction and returns its pooled connection. A
cancelled coroutine waits for its in-flight database operation to finish before
checkpoint cleanup can begin.

One API worker is the supported, recommended assistant deployment (and matches
the supplied Docker entrypoint). Transaction-based claims and status checks
protect job ownership, three-second polling propagates cancellation, and
ninety-second stale-job detection marks interrupted work. Multiple API processes
additionally require sticky routing to the worker executing the user's runs so
refreshed session credentials reach it; credentials are intentionally kept in
process memory. Multi-host execution still needs job coordination and secure
credential handoff, in addition to the shared MySQL state. Checkpoints can
contain conversation data and tool arguments, so restrict database access,
protect backups, and apply the deployment's retention/encryption policy.
Provider keys are separate from graph state and never inserted into the model
prompt.

## Provider and execution boundaries

Profiles construct `ChatOllama`, `ChatOpenAI` or `ChatAnthropic`; they do not pass
credentials through chat messages. Ollama defaults to a local connection and
requires an installed model with tool calling support for agentic tasks. An
OpenAI-compatible endpoint can be selected in a separately named profile.
Ollama profiles explicitly configure the context window (`num_ctx`), defaulting
to 32,768 tokens so its small server default does not silently crowd out domain
tool schemas. The administrator can tune this to the installed model/hardware.
At most 96 application tools are exposed per model call, leaving room for the
harness tools. If several loaded skills exceed that budget, the latest selected
domains have priority and the model is told to delegate omitted operations to
the always-available domain specialists. No tool authorization is widened.
Provider/model choice is made per conversation/run; changing profiles does not
silently fall back to a different connection. API timeouts and bounded retries
prevent an unavailable provider from waiting forever.

`StateBackend` confines files to the graph's virtual conversation state. It has
no host shell, host filesystem or unrestricted network capability. Skill files
are seeded by trusted application code and cannot be rewritten by the model.
Model-visible file mutation tools are hidden and denied; framework context
offloading still writes its own virtual state. This respects the distinction
between a virtual backend and an OS sandbox in the
[backend documentation](https://docs.langchain.com/oss/python/deepagents/backends).
File rules use the installed `FilesystemPermission` type, and deny writes
through the harness. [Filesystem permission semantics](https://docs.langchain.com/oss/python/deepagents/permissions).

## Verification scope

Runtime tests execute real `create_deep_agent` graphs against a deterministic
local chat model. They test progressive activation, direct tool-call denial,
FAQ behavior, on-disk interrupt/resume with a reconstructed graph, approved and
rejected mutations, subagent execution and aggregated token usage. This proves
the framework integration without sending application data to a model service.

Final runtime verification: 21 tests passed, and `pip check` reported no broken
requirements in the combined test environment.

## Follow-up live deployment verification

The first running development server used the project's older `.venv`, while
initial automated validation used a separate environment. That active `.venv`
was missing both Deep Agents and a Uvicorn WebSocket protocol package. Uvicorn
therefore treated the upgrade as HTTP GET and returned 404. Installing the
already-declared `requirements.txt` into the actual serving interpreter and
reloading the worker corrected the failure. A real TCP WebSocket regression now
covers successful upgrade/RPC, origin rejection, and the missing-protocol 404;
startup diagnostics identify the serving interpreter when transport is missing.
The dashboard displays connection repair guidance instead of indefinite loading.

Live verification then used the user-specified existing Ollama server at
`http://192.168.1.90:11434` and its existing
`srchmnmichael/qwen3.5-9B-uncensored:Q8_0` model. The real Deep Agents runtime,
ChatOllama adapter and SQLite checkpointer completed both cases:

- General FAQ: 19.95 seconds, 47 text deltas, 4,384 total tokens, no skill reads
  or application tools.
- Synthetic skill: 10.05 seconds, 14 text deltas, three model calls and 13,456
  total tokens; loaded the skill and called its read-only fixture exactly once,
  returning the expected fictional count of 17.

Streamed text matched the final answer in both cases. Only synthetic prompts and
fixture data were sent; no application records or secrets were used. No Ollama
server or models were installed locally or downloaded remotely. The actual root
dashboard successfully connected, saved the remote provider profile and restored
it after refresh. The assistant activation switch and application writes remained
off for the user to enable deliberately.
