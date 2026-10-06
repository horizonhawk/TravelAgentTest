# Evaluation design and portable evidence

The harness uses Strands Evals with deterministic Python evaluators. No judge model, second credential, or fixed tool sequence is required. Evaluation version 4 adds an explicit missing-detail contract and accurate status-mismatch diagnostics; the valid-final-response count now requires a passing contract check. Version 3 introduced the earlier budget/geography checks described below. Original reports retain their original evaluator versions.

## Dimensions

| Dimension | What it checks | What it does not establish |
| --- | --- | --- |
| Contract | Pydantic output types and status coherence | That well-formed prose is correct |
| Constraints | Case-specific facts, exclusions, flight scope, nightly versus total limits, and conflict resolution | General understanding of every possible request |
| Evidence | Original request/tool provenance, matching destination/hotel/budget, arithmetic, final USD claims, and partial-cost scope | Comprehensive semantic truth or real-world prices |
| Tools | Required attempts, required successful results, forbidden calls | Optimal order, efficiency, or subjective usefulness |

`required_tools` checks attempted calls. `required_successful_tools` additionally requires an SDK-success result with business status `ok` or `no_match`; invalid inputs do not qualify. Checks allow extra tools and any order. A valid no-match lookup is successful execution, not a successful trip recommendation. Cases without tool requirements show N/A.

Quota, rate-limit, access, and connection failures are provider-blocked cases. Their quality checks show N/A, and the run exits nonzero. Agent/protocol failures remain failures. The raw SDK aggregate fields are retained for compatibility, but case counts in `counts`/`case_outcomes` are the primary summary.

## Stronger answer checks

For each priced suggestion, the evidence evaluator requires the final rough budget to contain the calculated whole-party range. Explicit USD amounts must come from cited totals, line items, hotel/flight unit prices, the user's budget, or a calculated budget remainder. It rejects unqualified all-in coverage when tool evidence lists exclusions or unknown costs. This catches changing the answer to `USD 1 all-in` even if all referenced tool calculations are valid.

The Tokyo/Japan conflict case must retain the Tokyo requirement as conflicting, retain the Japan exclusion, acknowledge the incompatibility, avoid recommending a trip, and ask about resolving the conflict when clarification is chosen. It rejects the false statement that Tokyo is outside Japan and rejects an unrelated budget question as conflict resolution.

These are intentionally narrow English/numeric checks. They can reject unusual but correct phrasing, and they cannot prove arbitrary prose correct. They do not constitute a general geography engine or semantic judge. Mutation tests demonstrate rejection of the observed false claims; the original correct responses still pass. More varied language would justify a reviewed labeled dataset and/or a calibrated judge later.

## Missing details and judge scope

A repeated clean-clone run exposed a representation mismatch: the user explicitly left origin and duration undecided, and the model stored `value: "Undecided", status: "user_stated"`. The original evaluator reported "Invented user-stated" fields even though no city or duration was fabricated. Live and replay failed identically; exporting evidence was not the cause.

Prompt version 5 and the schema specify `value: null, status: "unknown"` for entirely missing details. Original request citations and an explanation in `open_questions` retain the user's explicit uncertainty. A small guard rejects exact standalone English placeholders (for example, "Undecided", "Not yet decided", and "TBD") in the six core trip fields, allowing the existing tool loop to request correction. It does not silently rewrite artifacts or implement general language understanding. Partial facts, explicit flexibility and separately labeled proposals remain supported. The constraint evaluator still rejects invented user-stated values; its message now accurately identifies a status mismatch.

An LLM judge is unnecessary for this concrete contract. A future judge could score subjective usefulness or clarification quality against a human-reviewed rubric and labeled examples, with separate scores, recorded model/prompt versions, and calibration for disagreement. It would supplement the deterministic checks. No judge or new dependency was added for this fix.

## Cases and measured coverage

The ten inputs and their requirements are defined in [`evals/cases.json`](../evals/cases.json). Every case receives the common contract/evidence checks; the table describes additional case-specific assertions.

| Case | Input scenario | Additional checks |
| --- | --- | --- |
| `underspecified` | “Cheap.” | Clarification status; missing origin, destination, dates and travelers must not be marked user-stated. |
| `beach-budget` | Two adults from JFK, $3,000 including flights | Retain JFK; require successful destination, accommodation, flight and budget tools; allow suggestions or no match. |
| `tokyo-excluding-flights` | Tokyo, $6,000 excluding flights | Retain Tokyo and flight exclusion; require successful accommodation/budget tools; forbid flight search and flight costs in the total. |
| `family-missing-origin` | Family of four, warm spring break, pool, no origin | Clarification status; retain pool preference; do not invent a user-stated origin. |
| `nightly-hotel-limit` | Porto hotel under $300 per room/night, no total budget | Retain nightly limit; selected hotel must fit it; require accommodation/budget tools; an unspecified total budget stays unknown. |
| `explicit-exclusion` | Romantic trip excluding Santorini, origin/duration undecided | Retain exclusion, avoid Santorini suggestions, ask questions, and keep preliminary suggestions unpriced. |
| `contradiction` | Tokyo required, Japan forbidden | Preserve the conflict, acknowledge incompatibility, avoid trip suggestions, and address the conflict in clarification. |
| `unsupported-catalog` | Antarctica required | Require a successful destination lookup and `no_match`; a catalog gap does not make Antarctica invalid. |
| `original-tight-beach-budget` | Original $2,000 beach request from JFK | Retain JFK; accept clarification, evidence-supported suggestions or no match. |
| `original-lisbon-extension` | Five-day extension after a Lisbon wedding; flight already booked | Retain the booked Lisbon flight; any flight search must originate in Lisbon instead of an invented long-haul departure city. |

The two original-assignment cases allow several valid strategies and have relatively narrow assertions. For example, the Lisbon case does not comprehensively score geographic proximity or itinerary quality. Case names describe scenarios, not a claim that every preference in the prompt has an automated assertion.

Separate offline tests cover session isolation, corrections, append-only artifacts and logbooks, budget units, secret redaction, provider setup/protocols, execution limits, portable replay and acceptance-runner failure handling. Adversarial tests verify that altered budget/geography claims and missing or cross-session evidence fail. The local suite has 89 passing tests, including missing-detail rejection/correction and preservation of the actual failed output; the earlier timed published revision had 70 tests. These fixture-based tests are distinct from live model evaluations. Subjective usefulness, multilingual behavior and multi-turn planning quality are not measured by the ten-case live suite.

An earlier curated **OpenAI / gpt-6.1-sol** run, `20261006T162713800251Z`, passed **10/10 cases and 34/34 applicable checks**, with no provider blockers. It ran from actual GitHub commit `97b8245049409bfd788502804d60eb15fe86f9b9`; [acceptance timings and checks](../submission/validation/20261006T162608763233Z-clean-clone/summary.json) and [portable evidence](../submission/evidence/openai-20261006T162713800251Z/manifest.json) are included. Its exported evidence also passes all ten cases under version 4.

The later [candidate-run repeat](../submission/validation/20261006T170738499600Z-clean-clone/summary.json), on `e17bd3e`, passed both timing targets but scored 9/10 cases and 33/34 checks under version 3. Its [unchanged portable evidence](../submission/evidence/openai-20261006T170847905864Z/manifest.json) preserves the undecided-field failure. Version-4 replay still fails that case; it now fails schema-dependent dimensions too (31/34, nine valid final responses). The offline correction-loop regression passes. An attempted fresh live check from the assistant environment was provider-connection blocked, so a live post-fix acceptance result remains pending.

Earlier evidence remains preserved: the original eight-case run `20261006T044810289114Z` passed 8/8 cases and 28/28 applicable checks, including version-3 replay; the two added assignment cases passed a [separate run](../submission/validation/20261006T054836705601Z-github-clone/check.json), 2/2 cases and 6/6 checks. A replay is not a fresh model run and does not measure nondeterminism. OpenRouter free routing has both successful historical turns and quota/protocol failures; it is not presented as a reliable fixed-model benchmark. Anthropic and Bedrock setup is tested offline only.

## Portable replay

From the repository root after installing `.[eval]`:

```bash
# Latest complete ten-case run:
python -m evals.run --replay submission/evidence/openai-20261006T162713800251Z/outputs.json
# Earlier eight-case run:
python -m evals.run --replay submission/evidence/openai-20261006T044810289114Z/outputs.json
# The two original-assignment examples generated from the actual GitHub clone:
python -m evals.run --replay submission/validation/20261006T054836705601Z-github-clone/additional-evidence/outputs.json
# Preserved later failure: intentionally exits 1; replay must not turn it into a pass.
python -m evals.run --replay submission/evidence/openai-20261006T170847905864Z/outputs.json
```

No API key, `.env`, `trip-agent.toml`, or `.trip-agent` directory is needed. The bundle includes original generated responses and selected original request/tool/state/prompt/error records, with session IDs and artifact IDs preserved. The embedded evidence store enforces session isolation and fails on missing references. It does not fall back to the developer's machine.

- `cases.json`: the original case inputs with current evaluation metadata, frozen at export.
- `outputs.json`: original responses plus their embedded evidence; local session paths removed.
- `manifest.json`: source run identity, source-file hashes, and bundle-file hashes.
- `replays/<run-id>/summary.json`: a rescore labeled `replay`, with its evaluator version recorded.

Hashes detect accidental edits; they do not prove authenticity against an attacker who can replace the manifest. Bundle hashes are verified before replay. The exporter excludes private model reasoning, SDK memory, local credential/config files, and personal manual-travel sessions. This is a portable review bundle, not a complete session backup.

## Create new results

```bash
python -m evals.run  # Uses the configured default provider.
python -m evals.run --only original-tight-beach-budget original-lisbon-extension
python -m evals.export --run reports/RUN_ID --output submission/evidence/NEW_BUNDLE_NAME
```

New live cases use fresh isolated sessions. Outputs, case snapshots, exports, and summaries are created without replacement. An export requires unchanged case input text; changed inputs require a new live run. Legacy output files without embedded evidence still require their original session directories. Original local reports remain preserved and ignored by Git; only the curated submission bundle is intended for publication.
