# Evaluation design and portable evidence

The harness uses Strands Evals with deterministic Python evaluators. No judge model, second credential, or fixed tool sequence is required. Evaluation version 3 strengthens two failures discovered while reviewing a successful run: the earlier scorers accepted a fabricated final budget despite correct tool arithmetic, and accepted a wrong geography statement when the response status was `needs_clarification`.

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

## Cases and measured coverage

`evals/cases.json` contains ten cases: underspecified input, beach budget, Tokyo without flights, family missing origin, nightly hotel limit, destination exclusion, conflicting constraints, Antarctica outside the catalog, the original $2,000 beach prompt, and the original Lisbon wedding-extension prompt.

The curated source run is **OpenAI / gpt-6.1-sol**, run ID `20261006T044810289114Z`, with **8/8 cases and 28/28 applicable checks passing**. Its original answers also pass version-3 replay. The two added original-assignment prompts have **not** been evaluated live yet. A replay is not a fresh model run and does not measure nondeterminism. OpenRouter free routing has both successful historical turns and quota/protocol failures; it is not presented as a reliable fixed-model benchmark. Anthropic and Bedrock setup is tested offline only.

## Portable replay

From the repository root after installing `.[eval]`:

```bash
python -m evals.run --replay submission/evidence/openai-20261006T044810289114Z/outputs.json
```

No API key, `.env`, `trip-agent.toml`, or `.trip-agent` directory is needed. The bundle includes original generated responses and selected original request/tool/state/prompt/error records, with session IDs and artifact IDs preserved. The embedded evidence store enforces session isolation and fails on missing references. It does not fall back to the developer's machine.

- `cases.json`: the original case inputs with current evaluation metadata, frozen at export.
- `outputs.json`: original responses plus their embedded evidence; local session paths removed.
- `manifest.json`: source run identity, source-file hashes, and bundle-file hashes.
- `replays/<run-id>/summary.json`: a version-3 rescore, labeled `replay`.

Hashes detect accidental edits; they do not prove authenticity against an attacker who can replace the manifest. Bundle hashes are verified before replay. The exporter excludes private model reasoning, SDK memory, local credential/config files, and personal manual-travel sessions. This is a portable review bundle, not a complete session backup.

## Create new results

```bash
python -m evals.run --profile openai
python -m evals.run --profile openai --only original-tight-beach-budget original-lisbon-extension
python -m evals.export --run reports/RUN_ID --output submission/evidence/NEW_BUNDLE_NAME
```

New live cases use fresh isolated sessions. Outputs, case snapshots, exports, and summaries are created without replacement. An export requires unchanged case input text; changed inputs require a new live run. Legacy output files without embedded evidence still require their original session directories. Original local reports remain preserved and ignored by Git; only the curated submission bundle is intended for publication.
