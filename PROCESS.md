# Development process

This records decisions from the genuine development conversation. The annotated quotations are excerpts; [the transcript export](transcripts/README.md) preserves the conversation and tool records in source order. The candidate supplied the personal reflection and time disclosure below.

## Design choices I drove

My main design question was how a person could inspect an agent's behavior: what it understood from the request, which tools it chose, what those tools returned, and how that evidence supported its answer. I directed these choices through prompts, reviewed the implementation areas listed below, and gave feedback from manual testing. Codex assisted with implementation and with drafting this account from the recorded conversation.

**Separate working memory from preserved evidence.** I asked for user requests, extracted trip facts, initial responses, and tool results to be stored as distinct artifacts alongside agent memory. My concern was that a current conversation state alone would make earlier interpretations difficult to inspect. Preserving the underlying records gives both the agent and a reviewer something concrete to revisit when a user clarifies or corrects a request.

**Make that evidence usable by humans.** When the artifact layout became too scattered, I asked for an integrated agent logbook containing the whole history. That led to one self-contained HTML edition with the conversation, state changes, tool results, errors, and expandable technical details. I also asked for the terminal to emphasize the real agent response, with quieter diagnostics and properly indented JSON. These requests came from trying to use and audit the agent, and shaped how the evidence is presented. The [actual Porto logbook](submission/examples/porto-live-logbook-20261006T054836.html) makes the result inspectable without another model call.

**Preserve the path through corrections and failures.** I explicitly requested append-only artifacts so that a later result would not erase an earlier one. The implementation retains source records and creates new state snapshots and logbook editions, while mutable indexes and working memory are kept separate. During validation, the failed connection attempt remained recorded beside the successful continuation. That is useful evaluation evidence: a later success should not conceal what failed earlier. This is a local audit history, not a claim of tamper-proof storage.

**Give the LLM responsibility for orchestration, with observable checks.** I wanted the model to interpret intent, ask useful clarification questions, and choose tools as needed. I also wanted users to see tool invocations and evaluations to check relevant tool use. Those requirements fit together: tests can check necessary evidence and respected constraints without prescribing one execution order. My proposed comparison against a deterministic workflow remains future work, rather than an untested claim that the agentic approach is better.

**Keep a session's identity independent of its model provider.** I challenged the initial suggestion that switching models should automatically create a new session. The user's conversation and its evidence should retain their identity. I subsequently agreed to defer in-session switching and prioritize smooth configuration and testing. The delivered version preserves a model snapshot per session; full switching is not implemented.

These choices reflect my emphasis on inspectability and human review. They also expanded the work beyond the single-turn brief. I would make that scope decision more carefully next time, as described in my reflection below.

## Annotated prompt highlights

1. **Choose a language the candidate can inspect**

   > i don't like to use next.js and i am more familiar with python, can we use python actually? i want to audie the whole process actually

   Intent: make review practical. The assistant confirmed that the brief permits Python; Python and typed schemas were kept. The candidate chose Strands because of existing familiarity, rather than implementing a custom agent loop.

2. **Inspect the plan before implementation**

   > before implementing on anything, i want to see your plans and repo structure first based on the framework and infra decisions we already made.

   Intent: retain control of architecture before code appeared. The assistant proposed a repository structure and implementation plan, then revised it in response to requirements about orchestration, evidence, and sessions. Implementation followed the candidate's explicit approval.

3. **Reject a fixed travel workflow**

   > it is NOT a fixed/determined workflow, we want the model/LLM layer to be the orchestration layer through-out the whole project.

   Intent: let the LLM interpret intent, clarify, and choose tools. The assistant withdrew a prescribed workflow. Strands owns the tool loop; Python validates arguments, calculations, evidence, and output rather than selecting a destination/flight/hotel sequence.

4. **Turn scattered artifacts into a human-readable logbook**

   > we want a whole and integrated pieces contains all the history, like an agent logbook

   Intent: make the saved history practical to review. The candidate pushed back on scattered artifact files and requested an integrated view. The assistant added a self-contained HTML logbook with expandable tool JSON, state changes, and source records. Separate feedback on terminal readability led to quieter diagnostics and indented debug output. This was a candidate-requested extension beyond the brief.

5. **Make storage append-only**

   > another thing, for audit purpose, i want that artifacts storage is append only, not overwriting previous results

   Intent: retain earlier interpretations and failures. Immutable artifact files and versioned logbook editions were kept; mutable indexes and current-state pointers were explicitly distinguished. The implementation does not claim tamper-proof storage. This extends the brief's original scope.

6. **Separate model identity from session identity, then defer switching**

   > switching provider/model in the middle should be supported but should not start a new session automatically if we are still in the same session.

   Intent: prevent backend changes from implicitly replacing conversations. The assistant corrected its proposed coupling. The candidate subsequently agreed that full switching should wait; the reserved command reports the limitation without changing a session.

7. **Demand tool-use evaluation**

   > good that works now. for the agent evaluation, can we add tests that certain tools included? i believe strands already supports that

   Intent: verify observable behavior, such as destination lookup in a relevant context, as well as final JSON. The assistant used Strands' deterministic ToolCalled checks. Required attempts, successful results, and forbidden tools remain separate; the LLM is not forced into a test-defined tool order.

8. **Investigate failures rather than trust the aggregate score**

   > can you deep dive both to see where they failed?

   Intent: explain the OpenAI and OpenRouter evaluation results. Original traces exposed repeated zero-budget arguments, mismatched nullable schemas, a too-restrictive exclusion-status expectation, and provider quota exhaustion. The fixes preserved original failed evidence and separated provider-blocked cases from agent-quality failures.

9. **Review the submission against the actual brief**

   > keep in mind we not only need to satisfy the requirements, we also want others can test it and use smoothly and easily, think deeply about the the requirements

   Intent: audit both compliance and reviewer experience. The assistant reread the PDF, checked a clean source copy, and deliberately corrupted two answers in memory. The then-current scorers still passed both; stronger final-claim checks and portable evidence were prioritized over more features.

10. **Stop feature growth and finish the submission**

    > i agree, we should stop adding features now. let's strengthen the two weak evaluations, package portable evidence, simplify and update the README, complete the genuine process materials, then validate the actual GitHub clone with a live example.

    Intent: set an explicit finish line. The assistant retained the agent contract, added adversarial evaluator regressions, bundled original evidence for credential-free replay, and moved detailed operating instructions out of the README. Further product features were stopped.

## Scope and trade-offs

The original assignment calls for a small single-turn agent and explicitly excludes persistence, sessions, and multi-turn behavior. Those extensions were requested during this conversation. They add review surface and took time beyond the minimal task; they should not be portrayed as required by the assignment. The single-turn `run` command remains available.

Three travel concerns are separate lookup tools (destination, flight, accommodation), while a calculation tool computes whole-party budgets from returned prices. This makes units and exclusions testable. Evidence/state tools support the requested session extension. Sequential execution applies to calls the model chooses together; it is not a hardcoded travel workflow.

Real travel APIs, a UI, authentication, hosted deployment, production infrastructure, and cross-provider model switching were cut or deferred. Provider adapters come from Strands; small compatibility shims handle the observed SDK schema/formatting mismatches. Free OpenRouter routing is useful for integration exploration but has shown schema/protocol failures and exhausted daily quotas. It is not the final reference quality baseline.

The final answer checks are deliberately limited deterministic English checks, not a universal semantic judge. A correctly cited answer can still misinterpret user intent outside their coverage. The evidence bundle and mutation tests make this boundary inspectable.

## Validation the assistant performed

- Offline tests exercise the actual Strands loop with scripted models, provider setup, session isolation/resumption, append-only artifacts, budget arithmetic, and evaluator behavior.
- A [clean source copy](submission/validation/20261006T051625Z/clean-source-check.json) without local credentials/configuration/sessions installed successfully using cached wheels, replayed all eight original cases, and passed all 70 offline tests. Testing the literal README command also caught and fixed missing repository imports when invoking `pytest` directly. This does not measure internet installation or a remote clone.
- The candidate ran live evaluations locally. The OpenAI eight-case run `20261006T044810289114Z` passed all cases; original outputs are included in the portable evidence bundle. Version-3 replay also passes those original responses.
- Mutated responses claiming `USD 1 all-in` or that Tokyo is outside Japan now fail. The original $2,000 beach and Lisbon-extension cases passed a separate live run from the GitHub clone: 2/2 cases and 6/6 applicable checks.
- The candidate published commit `ebe5a3320795794c1e389269843f3bd3e6ed0652` and ran the [actual GitHub-clone check](submission/validation/20261006T053840817424Z-github-clone/check.json). All 70 tests, the eight-case replay, and a real model/tool/structured-output probe passed. Setup took 146 seconds with download timeouts. The longer README example then failed on its first model request with `APIConnectionError`, before any travel tool ran. The [separate continuation](submission/validation/20261006T054836705601Z-github-clone/check.json) reused the same clean clone and model configuration and passed the full Porto example in 23.26 seconds. Only the local validation helper changed: it reused setup, created a fresh session, retained exception causes, cleaned Python environment overrides, and continued independent checks after an example failure. No agent-code, prompt, provider, timeout, or retry-policy change caused this success; the exact connection-failure cause remains unknown. The original failed attempt remains intact.

## Candidate reflection and time

The following account comes from the candidate, lightly edited for clarity.

**Time spent:** approximately two hours of development, plus twenty minutes preparing artifacts and the submission: two hours and twenty minutes total as reported at this preparation checkpoint.

**Personal review:** I reviewed `agent.py`, `config.py`, `prompts.py`, `tool_schema.py`, `persistence.py`, and `logbook.py` under `src/trip_agent/`; all of `evals/`; and `README.md` and `PROCESS.md`. I also exercised the CLI and OpenAI/OpenRouter evaluation flows, reporting the observed failures in the conversation. I am not claiming a personal line-by-line review of the remaining files; those relied on assistant implementation and automated checks.

**What I would do differently:** I would focus completely on single-turn interaction instead of spending time on longer-term interactions, evidence retention, and logbook persistence. I would also benchmark the LLM-orchestrated agent against a deterministic workflow, comparing correctness, clarification behavior, tool use, latency, and cost. That comparison is proposed future work (deterministic workflow needs expert level knowledge); it was not performed for this submission.

## If serving 10,000 requests an hour

Start by measuring cost, latency, failure categories, and constraint accuracy on representative traffic. Select the least expensive model that meets those measured requirements; pin model IDs for comparisons and keep prompt/schema versions with results. Add reviewed semantic examples and adversarial mutations before relying on aggregate scores.

Use explicit structured money/scope fields if downstream systems need financial comparisons, while still checking that user-facing explanations agree. Keep tool execution bounds and provider failure handling visible. If session persistence remains part of the product, move local files/locks to durable shared storage and define retention; avoid carrying the whole artifact history into every prompt. These are design proposals, not implemented production infrastructure.
