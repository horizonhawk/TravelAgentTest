# Detailed operating guide

A Python CLI in which a Strands agent decides what to clarify, which mock travel tools to use, and when to return a structured suggestion. One session retains its conversation, extracted trip state, and inspectable evidence across process restarts. A different session starts with independent storage.

The starter profile uses **OpenAI `gpt-6.1-sol` through the Responses API**. Tool calling for this model requires Responses, not Chat Completions ([official model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol)). OpenAI, Anthropic, Bedrock, and OpenRouter profiles are supported. A provider's individual model must support function calling. No travel APIs, web server, database, or deployment are needed.

Jump to [setup](#quick-start), [manual conversation testing](#try-a-real-conversation), [session management](#continue-and-manage-sessions), [provider configuration](#configure-another-backend), [tools and mock data](#agent-behavior-and-tools), [logbooks and artifacts](#evidence-and-json-output), or [tests and evaluations](#tests-and-evaluations).

## Quick start

Prerequisites: Python 3.11+, internet access for installation/API calls, and a credential with access to your chosen model. Commands below run from the project root.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[openai]'

trip-agent config init
cp .env.example .env
# Edit .env: set OPENAI_API_KEY to your own key.

trip-agent config check
trip-agent session create --name "My beach trip"
trip-agent run --session "My beach trip" "Relaxing beach week in February under USD 2000 for two, leaving JFK. Want a nice hotel."
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell. The remaining CLI commands are the same. The config initializer does not overwrite existing files. If this working directory already has `trip-agent.toml`, use `trip-agent config show` instead of initializing again. Do not overwrite an existing `.env` that contains your credentials.

`.gitignore` excludes `.env`, `.env.*` (including `.env.local` and `.env.production`), local `trip-agent.toml`, and `.trip-agent/` runtime storage. The credential-free `.env.example` template is intentionally allowed. Keep your real key in `.env`; do not put it in source code or model configuration. Once this folder is a Git repository, `git check-ignore -v .env` shows the matching rule. Ignore rules do not remove a file that was already committed or tracked.

The install/setup target is under two minutes once prerequisites and credentials are available; network/download speed and model access can affect this. This is a target, not a measured clean-clone guarantee. Model response time and the live evaluation suite are separate from installation time.

`config check` checks local configuration, dependencies, and API-key presence. For Bedrock it checks settings; AWS credential resolution and model access occur on a live call. `config check --live` runs a small model/tool/structured-output check and saves its own clearly named session. It makes billable API calls.

## Try a real conversation

Open your own terminal in the project directory. After completing setup, run:

```bash
source .venv/bin/activate
trip-agent config check
trip-agent session create --name "Manual test"
trip-agent session resume "Manual test"
```

If `Manual test` already exists, skip the create command and resume it. At `You>`, enter a request such as:

> I want to go somewhere warm for a relaxing vacation, but haven't decided where.

Answer the agent's questions naturally. Each reply invokes the real configured model and may incur API charges. The LLM decides whether to clarify or call tools; the CLI does not enforce a travel-tool sequence. Type `/exit` (or `/quit`) to leave, then use the same resume command later. Your session ID, memory, and artifacts persist. To test independently, create a differently named session.

The normal display emphasizes the agent reply, with muted `[Debug]` tool notices and quieter assumptions/caveats. To inspect indented tool inputs and results, exit and resume with debugging enabled:

```bash
trip-agent session resume "Manual test" --debug
```

After code updates, exit and restart a running CLI so it loads the new behavior, including automatic logbook editions. The editable installation uses the updated source; reinstall only if dependencies change. Restarting does not create a new session. If API calls fail only inside a restricted coding environment, use your own terminal with normal network access; inspect the saved error artifacts for details.

## Continue and manage sessions

```bash
trip-agent session list
trip-agent session show "My beach trip"
trip-agent session resume "My beach trip"
# Enter successive replies; /exit or Ctrl-D leaves the conversation saved.

trip-agent run --session "My beach trip" "Make that March 2027, seven nights."
trip-agent session rename "My beach trip" "March getaway"
trip-agent session create --name "Japan November"

trip-agent session delete "March getaway"
trip-agent session list --deleted
trip-agent session restore "March getaway"
```

Names are case-insensitively unique among active sessions. Each session also has a permanent UUID accepted by all commands. Renaming does not change that UUID or move its evidence. New sessions are explicit; an unknown reference is an error. Exiting does not delete a session. Deletion moves the complete directory into local trash; restoration preserves its ID, memory, and artifacts. Concurrent operations on the same session are rejected. OS file locks release on process exit.

The original assignment calls for single-turn behavior and excludes persistence. `run` still accepts one request and returns one response; clarification is a valid response. Interactive resumption and local persistence are explicit user-requested extensions. There is no authentication, cross-session memory, or hosted service.

## Configure another backend

Install the required extra: `.[anthropic]`, `.[bedrock]`, or `.[openrouter]`. `pip install -e '.[providers]'` installs all four integrations. Reviewers need credentials only for the backend they select.

`trip-agent config init --provider anthropic --model <model-id>` creates a new config for that provider. To keep several profiles together, edit `trip-agent.toml`:

```toml
default_profile = "openai"

[profiles.openai]
provider = "openai"
model_id = "gpt-6.1-sol"
api_key_env = "OPENAI_API_KEY"
max_model_calls = 12
timeout_seconds = 60

[profiles.claude]
provider = "anthropic"
model_id = "<your-Claude-model-id>"
api_key_env = "ANTHROPIC_API_KEY"

[profiles.bedrock]
provider = "bedrock"
model_id = "<your-Bedrock-model-or-inference-profile-id>"
region = "us-west-2"
# aws_profile = "your-existing-AWS-profile"

[profiles.router]
provider = "openrouter"
model_id = "<provider/model-id>"
api_key_env = "OPENROUTER_API_KEY"
```

Replace placeholders before loading this example; all profiles are validated. `.env` is loaded from the configuration file's directory without overriding existing environment variables. Bedrock uses the AWS credential chain and requires model access in the selected region. OpenRouter uses its OpenAI-compatible Chat Completions endpoint, so select a tool-capable model compatible with that endpoint.

```bash
trip-agent config check --profile claude
trip-agent session create --name "Claude trip" --profile claude
```

A session snapshots its selected configuration. Editing global defaults will not silently change existing sessions. In-session provider/model switching is reserved for a later implementation: `session set-model` currently reports that limitation and leaves the session untouched. Session identity is independent of provider choice.

Strands supplies the provider adapters. Our [`models.py`](../src/trip_agent/models.py) factory selects and configures a small `OpenAIResponsesModel` subclass (OpenAI), `AnthropicModel`, `BedrockModel`, or the OpenRouter endpoint through a small `OpenAIModel` subclass. That subclass projects outbound history without reasoning blocks the installed Strands Chat Completions formatter already discards, avoiding repeated warnings while preserving original memory and audit evidence. The Responses subclass explicitly preserves non-strict optional-field semantics. The OpenRouter subclass also records provider-returned model/response IDs through a narrow SDK client wrapper. No separate orchestration loop is implemented. Model capability and live account access still require verification; provider support does not mean every model supports our tool and structured-response requirements.

Missing keys, inaccessible models, invalid responses, API failures, and execution-limit failures return a nonzero exit code with an actionable message. The session and available evidence remain inspectable. Transport retries are disabled. Strands can request corrected tool arguments or force final formatting within the per-turn model-call limit, which bounds orchestration, and each provider request has a timeout.

### Test OpenRouter with a free model

Use an **OpenRouter API key**, distinct from your OpenAI key. Create one in [OpenRouter settings](https://openrouter.ai/settings/keys), then add `OPENROUTER_API_KEY=...` to your existing ignored `.env` without replacing other entries. `pip install -e '.[openrouter]'` installs the integration; an environment already installed with `.[openai]` has the same required SDK dependency.

For a fresh checkout, open a terminal in the project directory and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[openrouter]'
trip-agent config init --provider openrouter --model openrouter/free
cp .env.example .env
# Edit .env and add OPENROUTER_API_KEY=your-own-key before continuing.
trip-agent config check
trip-agent config check --live
trip-agent session create --name "OpenRouter test"
trip-agent session resume "OpenRouter test"
```

This fresh initializer creates a profile named `openrouter` and makes it the default (60-second request timeout). The added-profile example below instead uses the name `openrouter_free` and a 90-second timeout. Both target the same route. Do not copy `.env.example` over an existing credential file. If the named session already exists, skip `session create` and use `session resume`; there is no need to delete it.

If you already have `trip-agent.toml`, keep your existing default and add this profile once instead of rerunning `config init`:

```toml
[profiles.openrouter_free]
provider = "openrouter"
model_id = "openrouter/free"
api_key_env = "OPENROUTER_API_KEY"
max_model_calls = 12
timeout_seconds = 90
```

Then select it explicitly:

```bash
trip-agent config check --profile openrouter_free
trip-agent config check --profile openrouter_free --live
trip-agent session create --name "OpenRouter test" --profile openrouter_free
trip-agent session resume "OpenRouter test"
trip-agent logbook --session "OpenRouter test" --open
python -m evals.run --profile openrouter_free
```

The repository's local working configuration has this profile prepared; `config show` lists configured profiles. New clones need to create their own configuration. An existing OpenAI session retains its original model; create a separate OpenRouter test session to test the selected profile.

The initial `qwen/qwen3.8-27b:free` candidate appeared in the public catalog but returned HTTP 404 during the user's live check: its free variant was unavailable. Catalog presence is not proof that a live request will succeed. The setup recipe now uses `openrouter/free` for connectivity and integration testing. [OpenRouter documents](https://openrouter.ai/docs/guides/routing/routers/free-router) that this route selects among compatible free models, potentially choosing a different underlying model between calls. Availability and limits still apply. For final per-model quality comparisons, configure an explicit model ID that has passed a live check; label results from the free router as router-level results, not results for one fixed model. The profile records the requested route; new model-response artifacts also record returned model IDs when the provider supplies them.

If you see **HTTP 404 / unavailable for free**, do not simply remove `:free`: that selects the paid model. Check `trip-agent config show`, update the profile to a working free route, and rerun `config check --profile openrouter_free --live`. That check creates a new session using the updated configuration. An already-created `OpenRouter test` session keeps its old model snapshot; create a differently named session such as `OpenRouter router test` after changing the model. Historical failed sessions and their artifacts remain available for audit.

Run the small live check before the full evaluation suite. Free models have availability and rate-limit constraints, and one agent turn can make several API requests. A 429 or unavailable endpoint should be recorded as an operational failure, not interpreted as a travel-reasoning score. No automatic switch to paid models is configured. If the free model is unavailable, select another tool-capable free model explicitly in the profile and create a new test session; existing session snapshots do not change. See [OpenRouter limits](https://openrouter.ai/docs/api_reference/limits).

To exercise configuration and SDK integration **offline**:

```bash
pytest tests/test_provider_setup.py -q
```

These checks cover all four providers' initial configuration/session creation, missing credentials, OpenAI/OpenRouter credential separation, `.env` versus shell precedence, named-profile selection, and preserving the OpenAI default. The OpenRouter protocol test goes through our CLI, model factory, real Strands adapter, and OpenAI SDK with mocked HTTP responses, checking the endpoint, authentication header, tool schema, streamed tool call, tool-result round trip, structured final output, and saved evidence. It is not a live-model evaluation and makes no network calls.

### OpenRouter tool formatting and reasoning warnings

Some models emit a JSON array/object as a string inside tool arguments: for example, `"questions": "[\"When?\"]"` instead of `"questions": ["When?"]`. For OpenRouter calls, a schema-directed compatibility step decodes valid JSON only where the tool requires an array or object, including nested trip state. It does not alter string-valued prose, infer missing values, invent evidence IDs, or accept malformed JSON. Normal schema and evidence validation still run; other errors are returned to the model for correction within the existing call limit.

The original model response and tool-call input remain immutable. Every decoding adjustment creates a separate `normalizations/` artifact linked to the original call, with field paths and effective arguments; the logbook includes both. Thus a successful normalized response does not imply the model originally produced perfectly typed arguments.

The installed Strands Chat Completions adapter omits `reasoningContent` when formatting subsequent requests. Previously, it warned once per historical block per call, producing repeated console messages. Our OpenRouter formatter now omits those blocks from an outbound copy before calling the SDK formatter and shows one diagnostic notice per turn when applicable. Normal conversation/tool messages and the original saved reasoning blocks are preserved. This does not add replay support for provider-specific reasoning signatures/details; models requiring those across tool calls are not verified with this adapter. OpenRouter itself has [reasoning support](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens); the limitation described here is our installed SDK integration.

After updating the code, exit the running CLI and resume the same session to load the fix:

```bash
trip-agent session resume "OpenRouter router test" --debug
```

No new session is required for this compatibility fix. Historical failed turns remain in the audit trail. To view adjustments, use `trip-agent artifacts --session "OpenRouter router test" --kind normalizations` or generate a new logbook edition.

### Printed tool markup / StructuredOutputException

Output such as `<tool_call>TripResponse` or `<arg_key>status</arg_key>` in ordinary assistant text is not a native API tool call. A partial response ending inside `<arg_value>` cannot safely be reconstructed: required facts and evidence may be missing. This is different from a complete native tool call containing a JSON-encoded list, which the narrow normalization step above can decode.

The application preserves this raw response, records an `UnstructuredToolMarkup` diagnostic, and keeps the markup out of the normal agent progress display (it remains available with `--debug`). Strands' existing forced-finalization attempt now uses explicit instructions to invoke the native `TripResponse` function with complete JSON arguments. That remains within the configured model-call limit. If the model ignores this request, the turn fails with an actionable model/tool-protocol error; there is no fabricated final response, extra unbounded retry loop, or automatic paid/provider fallback. Tools and intermediate state saved before the failure remain in the session.

Exit and resume to load updated code, then send a short follow-up such as “Please continue using my saved trip details and return a valid response”:

```bash
trip-agent session resume "OpenRouter router test"
```

Repeated failures mean the selected model/route has not demonstrated reliable native tool calling for this application. `openrouter/free` can select a different model on each request, so one successful smoke check is not a reliability guarantee. For final evaluation, use an explicitly selected model that passes the live smoke check **and** the evaluation cases. After changing a profile's model, use a new test session because existing sessions retain their snapshots. The profile setup above works with an explicit model ID as well as a router ID; testers supply their own credential. A different model's success remains unverified until tested.

For a fresh default OpenRouter setup, install evaluation dependencies and run:

```bash
pip install -e '.[openrouter,test,eval]'
pytest -q
python -m evals.run
```

For the added `openrouter_free` profile, use `python -m evals.run --profile openrouter_free`. The evaluations make real API calls. Offline test success checks our implementation, not whether a free model will reliably follow the protocol.

## Agent behavior and tools

The LLM receives the original user request, latest trip state, and references to recent evidence. It may clarify immediately, explore options using tools, save an updated interpretation, or produce suggestions. There is no application-coded order for travel tools. Tools selected in a single model response execute sequentially so terminal activity and evidence ordering are easy to inspect.

| Tool | Role |
| --- | --- |
| `search_destinations` | Explore a small catalog; filter preferences, month, region, proximity, and exclusions |
| `search_flights` | Mock round-trip airfare per person; missing origin stays missing |
| `search_accommodations` | Mock per-room nightly ranges, capacity, and amenities |
| `calculate_trip_budget` | Calculate party costs from saved lookup results, separating days, nights, rooms, and excluded/unknown flights |
| `update_trip_state` | Save the model's complete interpretation with original user evidence references |
| `list_artifacts`, `read_artifact` | Retrieve evidence from the active session only |

Pydantic validates the final response. Evidence validation rejects unsupported destination/hotel IDs and mismatched budget references. Facts are marked `user_stated`, `inferred`, `proposed`, `unknown`, or `conflicting`; only original user request artifacts can support `user_stated` facts. This checks provenance structure, not semantic truth: a model can still misinterpret a cited sentence, which is why evaluations and review matter.

Mock data supports Cancun, Algarve, Porto, Seville, Lyon, and Tokyo, with a deliberately small route/stay catalog. Rates do not vary by date. Seasonal labels are illustrative, not forecasts. Missing routes are catalog limitations. Budget totals cover only their explicit line items; excluded activities, insurance, visas, baggage, and intercity transfers mean they are not complete all-in quotes. Adults and children use the same mock airfare/daily allowance.

The LLM calls are real, travel lookups use local mock fixtures, budget arithmetic is actually executed against those fixture prices, and session/artifact tools really read and write local evidence. A destination such as NYC or Antarctica is valid even though it is absent from this catalog. The current `no_match` response can describe a catalog limitation; it must not be interpreted as evidence that the destination cannot be visited. The agent should preserve the requested destination, explain its coverage limitation, and avoid fabricated quotes or unwanted alternatives. Separate statuses for missing coverage versus unmet constraints are not implemented yet.

## Evidence and JSON output

For human review, generate and open one integrated **agent logbook**:

```bash
trip-agent logbook --session "Manual test" --open
```

Omit `--open` to generate the edition and print its file path without launching a browser. This command works on an existing session without making an LLM call. Exit or wait for any running turn in that session first; concurrent access is rejected by the session lock.

Each self-contained HTML edition includes the entire saved conversation in turn order, the latest trip state, intermediate agent responses, tool arguments/results, state changes, errors, and the full event timeline. Technical records are expandable, with indented JSON and source IDs. Everything needed to read that edition is embedded: copy the HTML file to review elsewhere without the artifact directory or internet access. It contains the conversation's personal information, so share it deliberately.

New immutable editions are saved under the session's `logbooks/` folder after each completed, failed, or interrupted turn and session lifecycle change. The command also creates a fresh edition for existing sessions. An opened edition is a snapshot: rerun the command to view newer turns. No LLM summarizes or rewrites the history.

The interactive CLI highlights the agent's reply and shows assumptions/caveats underneath in a quieter style. Repeated questions already present in the main reply are omitted from the follow-up list. Compact, muted `[Debug]` notices announce every tool before execution, including Strands' final-formatting tool. Full inputs and results are always saved as evidence.

Add `--debug` to display tool inputs, results, and artifact IDs. JSON is indented, including JSON nested inside SDK text blocks. Debug diagnostics go to stderr; `--json` keeps stdout as plain, parseable JSON. Colors are enabled only on terminals; set `NO_COLOR=1` to disable them. Assumptions and caveats remain visible with or without debugging because they can affect travel decisions.

```bash
trip-agent session resume "Japan November" --debug
trip-agent run --session "Japan November" --debug "What do you still need to know?"
```

Final JSON can be captured on stdout:

```bash
trip-agent run --session "Japan November" --json "Two adults, Tokyo, 8 days and 7 nights in November 2027, USD 6000 excluding flights" > result.json
trip-agent artifacts --session "Japan November"
trip-agent artifacts --session "Japan November" --kind requests
trip-agent artifacts --session "Japan November" --read <artifact-uuid>
```

Replace `<artifact-uuid>` with an ID from the artifact list. To inspect your manual conversation specifically:

```bash
trip-agent session show "Manual test"
trip-agent artifacts --session "Manual test"
trip-agent artifacts --session "Manual test" --kind tool_results
```

`session show` prints the absolute session `path`, permanent UUID, current trip state, and artifact count. Default storage is `.trip-agent/sessions/<session-uuid>/` under the project directory. `.trip-agent` is a hidden folder; on macOS, press Command–Shift–Period in Finder to show hidden files, or run `open .trip-agent/sessions` from the project directory. Open individual JSON files in an editor, or use the logbook for an integrated view.

```text
.trip-agent/
  sessions/<session-uuid>/
    session.json            # Identity, saved profile, lifecycle status
    events.jsonl            # Ordered lifecycle/artifact events
    artifact_index.json     # Rebuildable evidence index
    current_trip.json       # Pointer and latest derived trip interpretation
    memory/                 # Strands-managed local snapshots
    logbooks/               # Timestamped immutable HTML editions of the complete history
    artifacts/
      requests/             # Original user text per turn
      prompt_configs/       # Prompt, schemas, tools, provider settings/version
      model_inputs/         # Application-visible model context per call
      model_responses/      # Initial and subsequent model messages
      tool_calls/           # Inputs saved before execution
      tool_results/         # Full results, including failures
      normalizations/       # Original-call references and schema-directed decoding adjustments
      trip_states/          # Immutable extracted-state versions
      final_responses/      # Validated final response per successful turn
      errors/               # Failure evidence
  trash/                    # Recoverable deleted sessions
  locks/                    # Process locks outside movable session directories
```

All artifacts include session/turn IDs, timestamps, schema versions, and source references. A correction adds new evidence; it does not overwrite earlier records. Retrieval accepts artifact UUIDs, not filesystem paths. The capture is at Strands' application boundary, not a raw HTTP packet trace. Known credential values are redacted from evidence; credentials are not included in saved model configuration. Runtime data and `.env` are git-ignored.

Audit records in `artifacts/` and logbook editions use atomic, exclusive creation: an existing filename causes failure instead of replacement. `events.jsonl` only appends. The application never edits an earlier source record or logbook edition. `session.json`, `current_trip.json`, and `artifact_index.json` remain mutable operational metadata/derived views; their updates do not overwrite the historical evidence. Strands manages its memory separately. This is an application-level append-only policy, not storage-level tamper protection against someone manually modifying local files. Session deletion moves the entire history into recoverable trash.

`--config PATH` and `--data-dir PATH` are global options and go **before** the subcommand. Environment alternatives are `TRIP_AGENT_CONFIG` and `TRIP_AGENT_DATA_DIR`.

## Tests and evaluations

```bash
pip install -e '.[openai,test,eval]'
pytest -q
python -m evals.run
# Or select another configured profile:
python -m evals.run --profile claude
```

Pytest runs offline. The `test` extra installs the optional provider and evaluation libraries exercised by these tests. A scripted model drives the actual Strands loop to check hooks, structured output, memory restoration, and failures. These tests are not measurements of LLM quality. Provider construction tests do not prove live account/model access.

The optional Strands Evals harness runs ten real-model cases in isolated sessions and scores four dimensions: contract validity, case-specific constraint preservation, evidence/budget consistency, and tool usage. Scorers are Python code, with no additional judge model. It saves each completed case once in `reports/<run-id>/cases/<session-id>.json`, then creates `outputs.json` and `summary.json` once the run completes. Case snapshots remain available if a run is interrupted. Failures remain in the report. The terminal summary shows one row per case with dimension-level PASS/FAIL/N/A labels and exits without an interactive prompt; full tool trajectories remain in the JSON report. A saved run can be rescored without API calls:

```bash
python -m evals.run --replay reports/<run-id>/outputs.json
```

Portable replay uses the embedded original artifacts. Legacy outputs without embedded evidence require the original session directories. It is a re-score, not a fresh model evaluation. Inspect dimension-level failures rather than relying only on the aggregate. The checks do not measure every qualitative aspect of helpfulness.

Reports now include `case_outcomes` and `counts`. Cases are `passed`, `failed`, or `provider_blocked`; quota, rate-limit, access, and connection failures are operational failures, not travel-reasoning verdicts. Their quality dimensions are marked N/A and excluded from quality scores. A blocked run still exits with code 1 and does **not** count as passing. The terminal shows separate case counts, applicable check counts, and failure reasons. Raw SDK fields remain in the JSON for compatibility; their row pass rate includes N/A rows and is not the percentage of successful requests. A missing final response after a model/protocol error remains an agent failure.

Run selected cases after a fix without paying for the whole suite:

```bash
python -m evals.run --profile openai --only nightly-hotel-limit explicit-exclusion
python -m evals.run --profile openrouter_free --only beach-budget contradiction unsupported-catalog
# Rescore an older run using today's evaluation rules, without API calls:
python -m evals.run --replay submission/evidence/openai-20261006T044810289114Z/outputs.json
```

Live runs always create fresh isolated sessions; replays preserve the original outputs and create a new report with `evaluation_version` and `source_outputs`. Replaying cannot prove a runtime fix worked. After targeted live checks pass, run the full suite again. If OpenRouter's daily quota is exhausted, wait for its reset before rerunning; the agent does not silently change models or buy credits.

New OpenRouter model-response artifacts record provider-returned response IDs and model IDs when supplied. Evaluation outputs also collect these as `provider_responses`, alongside the configured profile. These may differ from `openrouter/free`, and may differ between calls in the same session. Missing identity metadata stays unknown; historical runs cannot be retroactively attributed to a specific routed model.

OpenRouter uses Strands’ OpenAI-compatible adapter, whose upstream log messages hardcode the name OpenAI. Our request-scoped logging filter labels its rate-limit and context-window errors as OpenRouter; it preserves the actual exception and other providers’ logs. This message does not mean an OpenAI credential or endpoint was used.

### Schema consistency and invalid-call recovery

The integration preserves Python argument types in tool JSON schemas, including nullable optional prices. OpenAI Responses function definitions explicitly use `strict: false` to preserve omission/default semantics; Pydantic and evidence validation still enforce the final response. Before each model call, the dynamic `TripResponse` tool advertises the original Pydantic schema, so defaulted lists accept `[]` and reject `null`. This corrects two schema transformations in pinned Strands 1.57.2; it does not introduce a separate orchestration loop.

When no whole-trip budget or nightly hotel limit was supplied, the model should omit that optional argument or pass `null`, never zero. Invalid price arguments return explicit correction guidance. After two identical failed tool executions in a turn, a third identical attempt stops with `repeated_invalid_tool_input`; the attempted call and prior results remain in the audit history. The model can correct its arguments after either error, and a failed session can be resumed. There is still a separate overall model-call limit.

### Require specific tools without prescribing a workflow

The separate `ToolUsageEvaluator` delegates presence checks to Strands' built-in deterministic [`ToolCalled`](https://strandsagents.com/docs/user-guide/evals-sdk/evaluators/deterministic_evaluators/). Edit a case's `metadata` in `evals/cases.json` to declare requirements:

```json
{
  "required_tools": ["search_accommodations", "calculate_trip_budget"],
  "required_successful_tools": ["search_accommodations", "calculate_trip_budget"],
  "forbidden_tools": ["search_flights"]
}
```

This example applies to the Tokyo case, whose prompt explicitly says not to search flights. Checks are order-independent and allow extra tools and repeated attempts. The LLM still chooses its own execution path; evaluation requirements are not injected into the runtime prompt.

- `required_tools`: each named tool must appear in the recorded call trajectory. This checks an attempt; a failed or canceled call can satisfy presence alone.
- `required_successful_tools`: each named travel tool must also have an SDK-success result with a business status of `ok` or `no_match`. A valid catalog lookup returning no match counts as successful execution; it does not mean a matching trip exists. Errors, missing inputs, and invalid inputs do not count.
- `forbidden_tools`: none of the named tools may be attempted. Use this only when justified by the actual user request.

Raw model prose or XML-like tool markup never counts as a tool call. Missing trajectory evidence fails a configured tool check. Cases with no tool requirements are marked not applicable for this dimension, so a valid clarification is not penalized for skipping tools. The dimension's score is the fraction of its configured checks passed; its pass flag requires all checks to pass. Failure reasons name the missing, forbidden, or unsuccessful tools.

The beach-budget, nightly-hotel-limit, Tokyo, and Antarctica cases require successful execution as well as attempted calls. The nightly case also checks that the model does not invent a total budget and that selected returned hotels satisfy the nightly ceiling. The destination-exclusion case accepts either clarification or grounded preliminary suggestions, requires clarifying questions, preserves exclusions and unknown facts, and disallows a calculated budget before the missing details are supplied. This matches the agent's permitted discovery behavior instead of prescribing one response-status label.

New runs save full tool-call/result records and pass a tool-name trajectory to Strands Experiment. Replay of older outputs containing only `tool_results` derives a trajectory from those results; attempts without a saved result cannot be recovered from that older format. Replay writes a new report and leaves the original output file intact.

Strands also offers an LLM-judged `TrajectoryEvaluator` for qualitative path assessment. It is not needed for these exact inclusion checks, so no judge-model credentials or calls are added.

The initial cases are defined in [evals/cases.json](../evals/cases.json):

| Case | Intended behavior checked |
| --- | --- |
| Underspecified: “Cheap.” | Ask for clarification without treating missing details as user-stated facts |
| Beach trip with an overall budget | Preserve origin and gather destination, stay, flight, and budget evidence |
| Tokyo with flights excluded | Preserve the destination and exclude flights from the calculated scope |
| Family trip missing origin | Ask for clarification and retain the pool preference |
| Nightly hotel limit | Distinguish the nightly limit from a whole-trip budget |
| Explicit destination exclusion | Retain the exclusion and avoid recommending that destination |
| Contradictory requirements | Clarify or report no match rather than claim both requirements are satisfied |
| Antarctica outside the mock catalog | Report the current catalog limitation using lookup evidence |

These evaluations test travel-agent behavior. The 5–10 annotated development prompts required for the submission belong in `PROCESS.md` and describe work with the coding assistant; they are a separate deliverable. The current scorers check selected constraints and evidence structure/arithmetic, not comprehensive semantic correctness, subjective helpfulness, or multi-turn LLM quality. Offline tests cover session continuity and isolation, lifecycle commands, history preservation/redaction, tool arithmetic, the Strands loop, failure recovery, provider construction, and the evaluation harness. Run `pytest -q` without making API calls; run `python -m evals.run` with working credentials for billable real-model evaluations.

## Current submission evidence

See [submission status](../submission/README.md) for the latest results, portable evidence, and remaining author-provided materials. Older local reports remain available in the development workspace but are not the reviewer entry point.
