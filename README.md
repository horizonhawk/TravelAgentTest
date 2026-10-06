# Trip Idea Agent

A Python + Strands CLI that turns a travel request into typed suggestions with reasoning, mock budgets, and caveats. The **LLM chooses the tools and clarification questions**; there is no fixed travel workflow. LLM calls are real. Travel data is deliberately small and mocked.

**Inspect every step:** readable replies, optional indented debug JSON, and a portable HTML logbook backed by append-only session evidence. [See debug mode and logbooks](#debug-mode-and-session-logbooks).

## Run an example

Requires Python 3.11+, internet access, and your own API key. The verified starter is OpenAI `gpt-6.1-sol` through Responses.

```bash
git clone https://github.com/horizonhawk/TravelAgentTest.git
cd TravelAgentTest
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[openai]'
trip-agent config init
cp .env.example .env
# Edit .env and set OPENAI_API_KEY. Never overwrite an existing credential file.
trip-agent config check --live
trip-agent session create --name "Reviewer demo"
trip-agent run --session "Reviewer demo" \
  "Two adults from SFO to Porto in May 2027, 3 nights and 4 days. Boutique hotel under USD 300 per room per night. No total trip budget. Give a mock estimate."
```

The result should explain a **USD 2,140–3,130** mock estimate, with hotel rates **USD 140–190/night**. Wording and tool order vary. The estimate excludes activities, insurance, visas, baggage, and intercity transfers. It is not a live quote.

Try missing information independently:

```bash
trip-agent session create --name "Vague request"
trip-agent run --session "Vague request" "Cheap."
```

A clarification is a valid single-turn answer. `run` exits after one response. For a conversation, use `trip-agent session resume "Reviewer demo"`; `/exit` leaves it saved. To repeat a test, resume the existing name or create a different one.

On Windows use `.venv\Scripts\Activate.ps1` to activate. Existing installations should skip `config init` and inspect `trip-agent config show`. Shell environment variables take precedence over `.env`. Keys, local configuration, and personal sessions are ignored by Git.

The [actual GitHub-clone check](submission/validation/20261006T053840817424Z-github-clone/check.json) passed all 70 tests, the eight-case replay, and a live model/tool/structured-output probe. The [continuation on the same unchanged commit](submission/validation/20261006T054836705601Z-github-clone/check.json) passed the Porto example in 23.26 seconds and both added cases. The earlier example attempt had a connection failure, which remains recorded. Setup took **146 seconds** including evaluation dependencies and download timeouts, missing the two-minute target. The quickstart now installs runtime dependencies only; its online timing is not yet measured.

## Evaluate or inspect without API calls

```bash
# Evaluation dependencies are optional for running the CLI.
pip install -e '.[eval]'

# Portable original OpenAI evidence: no key or local session directory required.
python -m evals.run --replay submission/evidence/openai-20261006T044810289114Z/outputs.json

# Real calls, fresh isolated sessions; API charges/quotas apply.
python -m evals.run --profile openai
# Just two cases:
python -m evals.run --profile openai --only beach-budget contradiction

# Offline implementation and evaluator regression tests:
pip install -e '.[test]'
pytest -q
```

Four deterministic dimensions check schema, constraints, evidence/budget claims, and tool use. **Ten cases** include vague input, exclusions, conflicting requirements, unknown budgets, catalog gaps, and two original assignment examples. They do not impose tool order on the agent.

The included original **eight-case OpenAI run passed 8/8**; it also passes the stronger version-3 scorers on replay. The two added assignment cases passed a separate live run from the GitHub clone (**2/2, 6/6 applicable checks**). This covers ten cases across two live runs, not one ten-case run. Regression tests reject incorrect final dollar amounts, false all-in claims, and the claim that Tokyo lies outside Japan, even when the response has valid structure and citations. These are deliberately narrow English checks, not a complete semantic judge.

Reports are saved under `reports/<run-id>/`. Provider failures are **BLOCKED**, not quality passes; blocked or failed runs exit nonzero. The terminal shows one row per case, with PASS/FAIL/N/A. Replaying creates a new report and never modifies the original outputs. See [evaluation design and evidence](docs/EVALUATIONS.md).

## Choose a provider

Reviewers need only the credential for their chosen backend. Install its extra and initialize a fresh configuration:

| Backend | Extra | Initial configuration | Credential |
| --- | --- | --- | --- |
| OpenAI | `openai` | `trip-agent config init --provider openai --model gpt-6.1-sol` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `trip-agent config init --provider anthropic --model MODEL_ID` | `ANTHROPIC_API_KEY` |
| Bedrock | `bedrock` | `trip-agent config init --provider bedrock --model MODEL_ID` | AWS credential chain and region |
| OpenRouter | `openrouter` | `trip-agent config init --provider openrouter --model openrouter/free` | `OPENROUTER_API_KEY` |

For example, install `pip install -e '.[openrouter]'`, initialize once, add the key to `.env`, then run `trip-agent config check --live`. Add `.[eval]` to run evaluations. A non-default profile can be selected when creating sessions or running evaluations. Existing sessions retain their saved model configuration. In-session model switching is deferred.

OpenAI is the verified live path. Anthropic/Bedrock configuration is tested offline, not with live accounts. OpenRouter has made successful live tool calls and completed some cases; its free router also showed formatting failures and quota exhaustion. Free routing is not a fixed-model quality benchmark. No automatic paid fallback or provider switching occurs.

Missing keys fail local validation; invalid credentials/model access, quota limits, and connectivity failures produce actionable errors and retain evidence. Strands' OpenAI-compatible adapter is also used for OpenRouter; diagnostic labels identify OpenRouter correctly. See [provider setup and troubleshooting](docs/OPERATIONS.md#configure-another-backend).

## Debug mode and session logbooks

The normal display emphasizes the agent's answer and announces tool calls before execution with muted `[Debug]` notices. **`--debug` expands the tool arguments, returned JSON, and evidence IDs**, including JSON nested inside SDK text blocks. Assumptions and caveats remain visible in both modes. Terminal colors are optional (`NO_COLOR=1` disables them); diagnostics go to stderr, and `run --json` keeps the final structured result on stdout.

```bash
# Continue the existing session with detailed diagnostics.
trip-agent session resume "Reviewer demo" --debug

# Or inspect one new turn and exit.
trip-agent run --session "Reviewer demo" --debug "What assumptions are in this estimate?"

# Open the entire saved history; this command makes no LLM calls.
trip-agent logbook --session "Reviewer demo" --open
```

**The logbook is one self-contained HTML file for the whole session.** It combines the conversation, intermediate responses, tool calls/results, extracted trip facts and state changes, failures, and event timeline. Expand technical records to inspect indented JSON and source artifact IDs. Each completed, failed, or interrupted turn produces a new edition; older editions remain unchanged. The command above also creates a fresh edition. An existing edition is a snapshot, so reopen a new edition after more turns.

Open the included [logbook from the successful live Porto example](submission/examples/porto-live-logbook-20261006T054836.html) in a browser after cloning, without an API key or internet connection. Its [provenance manifest](submission/examples/porto-live-logbook-20261006T054836.manifest.json) identifies the original session and checked revision. Logbooks include the saved conversation, so review their contents before sharing personal travel sessions.

**The underlying evidence stays separate from agent memory.** Default storage is `.trip-agent/sessions/<session-uuid>/`: `artifacts/` holds original requests, prompt/model records, tool inputs/results, trip-state snapshots, final responses, errors, and compatibility adjustments; `events.jsonl` records the timeline; `logbooks/` holds HTML editions; `memory/` is Strands' conversation state. Resuming reuses that session's evidence; creating a new session isolates it.

```bash
trip-agent session show "Reviewer demo"  # Prints the absolute storage path.
trip-agent artifacts --session "Reviewer demo" --kind tool_results
trip-agent artifacts --session "Reviewer demo" --read ARTIFACT_UUID
```

Replace `ARTIFACT_UUID` with an ID from the artifact list. Facts retain their source references, so a later correction creates new evidence without erasing the earlier interpretation. Source artifacts, events, and HTML editions are append-only; indexes, current-state pointers, session metadata, and Strands memory are mutable. This is an inspectable history, not tamper-proof storage.

[Full artifact layout and inspection guide](docs/OPERATIONS.md#evidence-and-json-output) · [Session lifecycle commands](docs/OPERATIONS.md#continue-and-manage-sessions)

## Design and scope

- `src/trip_agent/tools/`: destination, flight, accommodation, budget, and session-evidence tools.
- `agent.py`, `prompts.py`, `schemas.py`: Strands invocation, model instructions, typed response and provenance.
- `models.py`: provider selection; small compatibility shims preserve SDK orchestration.
- `evals/`, `tests/`: live/replay evaluations and offline regressions.
- [PROCESS.md](PROCESS.md): genuine development decisions, reflection, and time disclosure.
- [transcripts/](transcripts/README.md): source-derived coding conversation export.

The original brief asks for a single-turn agent. Session persistence and logbooks were explicit candidate-requested extensions; they are not needed to evaluate one request. Real travel APIs, a UI, deployment, production infrastructure, and model switching are deferred. Mock coverage is limited to Cancun, Algarve, Porto, Seville, Lyon, and Tokyo; an absent destination is a catalog limitation, not an invalid travel request.

[Submission status](submission/README.md) · [Detailed operating guide](docs/OPERATIONS.md) · [Evaluation rationale and limitations](docs/EVALUATIONS.md)
