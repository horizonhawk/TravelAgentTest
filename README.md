# Trip Idea Agent

A Python + Strands CLI that turns a travel request into typed suggestions with reasoning, mock budgets, and caveats. The **LLM chooses the tools and clarification questions**; there is no fixed travel workflow. LLM calls are real. Travel data is deliberately small and mocked.

## Run an example

Requires Python 3.11+, internet access, and your own API key. The verified starter is OpenAI `gpt-6.1-sol` through Responses.

```bash
git clone https://github.com/horizonhawk/TravelAgentTest.git
cd TravelAgentTest
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[openai,eval]'
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

Setup targets two minutes after prerequisites and credentials are available. A [fresh source-copy check](submission/validation/20261006T051625Z/clean-source-check.json) installed dependencies in 14.3 seconds using cached wheels and passed all 70 tests. Internet timing and an actual remote-clone live check are still pending. The complete evaluation suite is separate from setup time.

## Evaluate or inspect without API calls

```bash
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

The included original **eight-case OpenAI run passed 8/8**; it also passes the stronger version-3 scorers on replay. The two newly added assignment cases have not yet been evaluated live. Regression tests reject incorrect final dollar amounts, false all-in claims, and the claim that Tokyo lies outside Japan, even when the response has valid structure and citations. These are deliberately narrow English checks, not a complete semantic judge.

Reports are saved under `reports/<run-id>/`. Provider failures are **BLOCKED**, not quality passes; blocked or failed runs exit nonzero. The terminal shows one row per case, with PASS/FAIL/N/A. Replaying creates a new report and never modifies the original outputs. See [evaluation design and evidence](docs/EVALUATIONS.md).

## Choose a provider

Reviewers need only the credential for their chosen backend. Install its extra and initialize a fresh configuration:

| Backend | Extra | Initial configuration | Credential |
| --- | --- | --- | --- |
| OpenAI | `openai` | `trip-agent config init --provider openai --model gpt-6.1-sol` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `trip-agent config init --provider anthropic --model MODEL_ID` | `ANTHROPIC_API_KEY` |
| Bedrock | `bedrock` | `trip-agent config init --provider bedrock --model MODEL_ID` | AWS credential chain and region |
| OpenRouter | `openrouter` | `trip-agent config init --provider openrouter --model openrouter/free` | `OPENROUTER_API_KEY` |

For example, install `pip install -e '.[openrouter,eval]'`, initialize once, add the key to `.env`, then run `trip-agent config check --live`. A non-default profile can be selected when creating sessions or running evaluations. Existing sessions retain their saved model configuration. In-session model switching is deferred.

OpenAI is the verified live path. Anthropic/Bedrock configuration is tested offline, not with live accounts. OpenRouter has made successful live tool calls and completed some cases; its free router also showed formatting failures and quota exhaustion. Free routing is not a fixed-model quality benchmark. No automatic paid fallback or provider switching occurs.

Missing keys fail local validation; invalid credentials/model access, quota limits, and connectivity failures produce actionable errors and retain evidence. Strands' OpenAI-compatible adapter is also used for OpenRouter; diagnostic labels identify OpenRouter correctly. See [provider setup and troubleshooting](docs/OPERATIONS.md#configure-another-backend).

## Inspect a session

```bash
trip-agent session list
trip-agent session resume "Reviewer demo" --debug
trip-agent logbook --session "Reviewer demo" --open
```

The normal output highlights the reply and keeps tool notices muted. `--debug` prints indented tool JSON. `--json` on `run` puts the final structured result on stdout, with diagnostics on stderr.

Every request, tool call/result, response, and extracted state is saved as a separate immutable artifact. Each session has a UUID and its own memory. HTML logbook editions integrate the whole history. Source artifacts and editions are append-only; indexes/current-state files are mutable, and this is not tamper-proof storage. [Full session and artifact instructions](docs/OPERATIONS.md#continue-and-manage-sessions).

## Design and scope

- `src/trip_agent/tools/`: destination, flight, accommodation, budget, and session-evidence tools.
- `agent.py`, `prompts.py`, `schemas.py`: Strands invocation, model instructions, typed response and provenance.
- `models.py`: provider selection; small compatibility shims preserve SDK orchestration.
- `evals/`, `tests/`: live/replay evaluations and offline regressions.
- [PROCESS.md](PROCESS.md): genuine development decisions, reflection, and time disclosure.
- [transcripts/](transcripts/README.md): source-derived coding conversation export.

The original brief asks for a single-turn agent. Session persistence and logbooks were explicit candidate-requested extensions; they are not needed to evaluate one request. Real travel APIs, a UI, deployment, production infrastructure, and model switching are deferred. Mock coverage is limited to Cancun, Algarve, Porto, Seville, Lyon, and Tokyo; an absent destination is a catalog limitation, not an invalid travel request.

[Submission status](submission/README.md) · [Detailed operating guide](docs/OPERATIONS.md) · [Evaluation rationale and limitations](docs/EVALUATIONS.md)
