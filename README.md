# Trip Idea Agent

A Python + Strands CLI that turns a travel request into typed suggestions with reasoning, mock budgets, and caveats. The **LLM chooses the tools and clarification questions**; there is no fixed travel workflow. LLM calls are real. Travel data is deliberately small and mocked.

**Inspect every step:** readable replies, optional indented debug JSON, and a portable HTML logbook backed by append-only session evidence. [See debug mode and logbooks](#debug-mode-and-session-logbooks).

## Run an example

Requires Python 3.11+, internet access, and your own API key. The verified starter is OpenAI `gpt-6.1-sol` through Responses.

**Using another provider?** Follow [Choose a provider](#choose-a-provider) after cloning and creating the virtual environment. Install that provider's extra and configure its model; an OpenAI account is not required.

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

An [actual GitHub-clone acceptance run](submission/validation/20261006T162608763233Z-clean-clone/summary.json), on commit `97b8245`, passed with a fresh venv and pip's cache disabled: runtime/configuration ready in **12.64 seconds**, first successful travel response in **46.53 seconds after cloning** (**47.275 seconds including cloning**). All ten live evaluation cases and all 70 offline tests in that revision passed; the complete acceptance suite took **242.293 seconds**. These are measured OpenAI results with Python, Git and credentials already available. Earlier [slow-setup/connection-failure evidence](submission/validation/20261006T053840817424Z-github-clone/check.json) and its [successful continuation](submission/validation/20261006T054836705601Z-github-clone/check.json) remain preserved.

A [later repeat on `e17bd3e`](submission/validation/20261006T170738499600Z-clean-clone/summary.json) also met both timing targets (49.569 seconds after cloning; 50.441 including cloning), but passed **9/10 live cases**: the model represented undecided details as user-stated values. The current prompt/schema clarify that contract and add correction tests. Fresh live acceptance of this correction is still pending; historical passing runs do not guarantee every new model response passes.

## Check the submission from a fresh GitHub clone

With Python 3.11+, Git, internet access and your chosen provider's credentials available, run from this folder. The default is OpenAI:

```bash
python3 scripts/verify_submission.py --env-file .env

# Other providers: replace model placeholders with IDs you have access to.
python3 scripts/verify_submission.py --provider anthropic --model YOUR_CLAUDE_MODEL_ID --env-file .env
python3 scripts/verify_submission.py --provider openrouter --model YOUR_ROUTER_MODEL_ID --env-file .env
python3 scripts/verify_submission.py --provider bedrock --model YOUR_BEDROCK_MODEL_ID \
  --aws-region us-west-2 --aws-profile YOUR_AWS_PROFILE
```

Choose **one** command for the provider you want to test. It tests **remote `main`**, records its exact commit, creates a new clone and virtual environment, and installs only `.[PROVIDER]` initially. The configuration probe, example and all live evaluations use that same provider/model. It loads only the selected provider's key or AWS settings from your existing file (shell values take precedence); it never copies the file or publishes anything. Bedrock can use an existing AWS profile/role without a `.env`; select the region where your model is available and omit `--aws-profile` to use the default credential chain. There is no provider fallback. Pip's download cache is disabled by default. `--use-pip-cache` opts into a cached comparison, labeled in its report. OS/network caches may still exist.

The two timing checks use a conservative definition of “running”: a successful structured Porto suggestion, after the README's live configuration probe. **Under 120 seconds** is measured from clone completion through that response; **under 300 seconds** includes cloning too. A separate runtime-ready duration shows installation/configuration time. These automated timings include downloads and LLM latency, but assume Python, Git and a valid API key are available; they do not measure a human reading the README or acquiring a key.

After timing stops, the command checks logbook/artifact preservation, installs optional test dependencies, runs every offline test, replays the included evidence, runs **all ten live evaluation cases**, exports their evidence and replays that export. Live calls consume API quota; the full suite can take several minutes beyond the setup limits. Keep your terminal open until it finishes.

Each attempt creates `reports/acceptance/<timestamp>-clean-clone/check.json`, detailed evaluation reports, portable evidence and a sample logbook. Previous attempts are preserved, and the new clone is retained at the path printed at the end. Exit `0` means all automated checks and both timing targets passed; exit `1` means a failed, blocked or incomplete attempt—inspect the separate timing, step and evaluation results. A slow install does not become an agent-quality failure. Process authenticity, clarity of the instructions and visual readability still require human review.

## Evaluations and offline tests

```bash
# Evaluation dependencies are optional for running the CLI.
pip install -e '.[eval]'

# Portable ten-case OpenAI evidence: no key or local session directory required.
python -m evals.run --replay submission/evidence/openai-20261006T162713800251Z/outputs.json

# Real calls, fresh isolated sessions; API charges/quotas apply.
python -m evals.run  # Uses your configured default provider; no OpenAI requirement.
# Just two cases:
python -m evals.run --only beach-budget contradiction

# Offline implementation and evaluator regression tests:
pip install -e '.[test]'
pytest -q
```

Four deterministic dimensions check **output schema**, **user constraints**, **evidence and budget claims**, and **tool use**. Tool checks distinguish required attempts, successful results and forbidden calls; they do not impose tool order on the agent.

The **ten live cases** cover:

| Coverage | Cases and checked behavior |
| --- | --- |
| Missing information | “Cheap.” and a family trip without an origin: request clarification, retain stated preferences, and avoid marking missing details as user-provided facts. |
| Budget scope | A $3,000 beach trip including flights, Tokyo excluding flights, and Porto under $300 per room/night: use relevant pricing tools, respect excluded flights, and distinguish nightly limits from an unknown total budget. |
| Destination constraints | An explicit Santorini exclusion and “Tokyo required, Japan forbidden”: retain exclusions and address contradictory requirements. |
| Catalog limitations | Antarctica: perform a lookup and report the mock catalog's lack of coverage. The destination itself is valid. |
| Original assignment examples | The $2,000 beach request and Lisbon wedding extension: preserve JFK or the already-booked Lisbon flight while allowing clarification, evidenced suggestions or no match. These cases have narrower assertions than a complete itinerary-quality assessment. |

The [case-by-case checks](docs/EVALUATIONS.md#cases-and-measured-coverage) map to [the input definitions](evals/cases.json). Separately, **89 offline regression tests** cover tools, sessions, append-only artifacts/logbooks, provider protocols, replay, acceptance checks, missing-detail correction, and deliberately corrupted answers that the evaluators must reject. Offline tests use fixtures and do not establish live model quality. Subjective usefulness, general semantic correctness, multilingual requests and multi-turn planning quality remain outside the live suite's coverage.

Included evidence preserves both the **10/10 OpenAI run (34/34 applicable checks)** and the [later 9/10 run](submission/evidence/openai-20261006T170847905864Z/manifest.json). The latter's original live/replay scores were 33/34; its failed output remains failed under the stricter version-4 contract. Earlier eight-case and two-case runs remain preserved. Regression tests reject incorrect final dollar amounts, false all-in claims, and the claim that Tokyo lies outside Japan, even when the response has valid structure and citations. These are deliberately narrow English checks, not a complete semantic judge.

Entirely missing or undecided trip details use `status: "unknown"` and `value: null`, retaining request citations and explanatory open questions. Partial information (such as May without a year) and a flexible budget remain meaningful facts. Standalone uncertainty placeholders trigger a correction request through the existing model/tool loop; original attempts remain in the logbook. No LLM judge or extra API dependency is needed for this contract check.

Reports are saved under `reports/<run-id>/`. Provider failures are **BLOCKED**, not quality passes; blocked or failed runs exit nonzero. The terminal shows one row per case, with PASS/FAIL/N/A. Replaying creates a new report and never modifies the original outputs. See [evaluation design and evidence](docs/EVALUATIONS.md).

## Choose a provider

Reviewers need only the credential for their chosen backend. After cloning, creating the venv and activating it, choose **one row** below. Run `pip install -e '.[EXTRA]'` using its extra, then its initialization command. Replace `MODEL_ID` with a tool-capable model available to your account.

| Backend | Extra | Initial configuration | Credential |
| --- | --- | --- | --- |
| OpenAI | `openai` | `trip-agent config init --provider openai --model gpt-6.1-sol` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `trip-agent config init --provider anthropic --model MODEL_ID` | `ANTHROPIC_API_KEY` |
| Bedrock | `bedrock` | `trip-agent config init --provider bedrock --model MODEL_ID` | AWS credential chain and region |
| OpenRouter | `openrouter` | `trip-agent config init --provider openrouter --model MODEL_ID` | `OPENROUTER_API_KEY` |

For example, a Claude reviewer installs `pip install -e '.[anthropic]'`, initializes with the Anthropic command, and puts only `ANTHROPIC_API_KEY=...` in `.env`. A Bedrock reviewer sets `region` and, if needed, `aws_profile` in the generated `trip-agent.toml`; it initially uses `us-west-2`. Then **every provider follows the same steps**:

```bash
trip-agent config show                 # Confirm provider, model and region before spending quota.
trip-agent config check                # Local dependencies and configuration.
trip-agent config check --live         # Real model, tool and structured-response check.
trip-agent session create --name "Provider review"
trip-agent run --session "Provider review" \
  "Two adults from SFO to Porto in May 2027, 3 nights and 4 days. Boutique hotel under USD 300 per room per night. No total trip budget. Give a mock estimate."
trip-agent session create --name "Missing information"
trip-agent run --session "Missing information" "Cheap."
pip install -e '.[eval]'
python -m evals.run                    # All ten live cases using your default profile.
trip-agent logbook --session "Provider review" --open
```

The first request should return an evidenced suggestion; `Cheap.` should ask for clarification. Investigate a failed live configuration check before starting the full suite. To review implementation tests too, install `.[test]` and run `pytest -q`; this installs SDKs for multiple providers but uses offline fixtures, so additional provider credentials are unnecessary. The evaluation scorers are deterministic and need no separate LLM judge/key. The included OpenAI evidence can also be replayed without an OpenAI key; replay does not test your chosen model.

`.[openai]` includes the SDK OpenRouter also uses; it does not install Anthropic's SDK. Bedrock's dependencies are already included by the base Strands package. `.[providers]` optionally installs all integrations. Installing an extra never selects a backend or changes existing configuration. A non-default profile can be selected with `--profile` when creating sessions, checking configuration or running evaluations. Existing sessions retain their saved model configuration; in-session switching is deferred. See the [operating guide](docs/OPERATIONS.md#configure-another-backend) to add profiles to an existing config instead of running `config init` again.

When accessing Claude **through OpenRouter**, choose `--provider openrouter`, use the OpenRouter model ID, and supply `OPENROUTER_API_KEY`. Direct Anthropic access uses `--provider anthropic` and `ANTHROPIC_API_KEY`. For independent comparisons in fresh clones, initialize each clone once; the configuration initializer never overwrites an existing file.

OpenAI is the verified live path. Anthropic/Bedrock configuration is tested offline, not with live accounts. OpenRouter has made successful live tool calls and completed some cases; its free router also showed formatting failures and quota exhaustion. Free routing is not a fixed-model quality benchmark. No automatic paid fallback or provider switching occurs.

Separate [fresh runtime-install checks](submission/validation/20261006T162608763233Z-clean-clone/provider-installations.json) passed for Anthropic, Bedrock and OpenRouter using cached wheels and fake credentials: configuration, session creation, agent imports and SDK construction all worked. Anthropic and Bedrock environments contained no OpenAI SDK. These checks establish dependency isolation, not live model quality or online setup speed.

The [deeper dependency audit](submission/validation/20261006T164247Z-provider-dependencies/summary.json) also passed for all three: `pip check` before/after installing `.[eval]`, ten-case evidence replay with no credentials, and real provider SDK/Strands tool-call, structured-output and saved-session-resume tests with simulated transport responses. Anthropic/Bedrock still had no OpenAI SDK after adding evaluations. Exact package versions are recorded. The local regression suite passed **81 tests**; the timed published revision had 70. This audit used Python 3.14.6 on macOS and cached wheels; other platforms, live Anthropic/Bedrock accounts and arbitrary model compatibility remain unverified.

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
- [PROCESS.md](PROCESS.md#design-choices-i-drove): candidate-led design choices, ten annotated prompts, personal review, scope reflection, and time disclosure.
- [transcripts/](transcripts/README.md): source-derived coding conversation export.

The original brief asks for a single-turn agent. Session persistence and logbooks were explicit candidate-requested extensions; they are not needed to evaluate one request. Real travel APIs, a UI, deployment, production infrastructure, and model switching are deferred. Mock coverage is limited to Cancun, Algarve, Porto, Seville, Lyon, and Tokyo; an absent destination is a catalog limitation, not an invalid travel request.

[Submission status](submission/README.md) · [Detailed operating guide](docs/OPERATIONS.md) · [Evaluation rationale and limitations](docs/EVALUATIONS.md)
