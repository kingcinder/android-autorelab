# The Legion and The Agency: Two Exclusive Autonomous Bootloader Security Suites

## Executive summary
You can build two mutually exclusive “states” for bootloader security assessment—**The Legion** (parallel swarm) and **The Agency** (serial deep pipeline)—by combining: (a) **llama.cpp router mode** for on‑demand GGUF loading with **LRU eviction** via `--models-max`, (b) **tool-first RE** via **Ghidra headless + ReVa MCP**, **angr CFGFast**, **binwalk**, and **AVB tooling**, and (c) strict orchestration rules that cap concurrency and enforce safety gates. Router mode is designed to dynamically load/unload multiple models without restarting and evicts least‑recently‑used models when `--models-max` is reached. citeturn3search0 ReVa provides an MCP server for Ghidra with **headless automation** and ephemeral projects, ideal for unattended pipelines. citeturn1search1 Both suites must be **exclusive runtime states** (“start Legion stops Agency and vice versa”) and should never co-run, implemented with `systemd` unit conflicts or a lockfile gate at startup.

**Safety boundary:** Both suites are framed as **authorized vulnerability discovery & triage** (SWAPs with evidence and remediation intent), not exploit generation or bypass instructions.

## Research foundations that enable autonomous bootloader RE
**Tool calling via MCP.** MCP is a JSON‑RPC client/host/server design intended to integrate LLM apps with external tools while maintaining security boundaries and controlled permissions. citeturn0search1turn0search6turn0search3 This is the right primitive to make agents “agentic” without hallucinating artifacts.

**Ghidra automation + ReVa MCP server.** ReVa supports Ghidra 11.4+ and provides both assistant mode and **headless mode for automation**, including session-scoped projects that auto-clean. citeturn1search1 Headless Ghidra workflows can dump/augment decompiler output; example headless usage patterns are widely used in practice. citeturn0search4turn0search2

**CFG extraction for structural bug motifs.** angr’s CFG recovery docs describe CFGFast as static CFG recovery that is “significantly faster” and comparable to other RE tools, suitable for scanning large binaries. citeturn0search0 This is essential to detect bootloader “fail‑open reconvergence” motifs and reachability structure.

**Firmware carving.** Binwalk v3 is rewritten in Rust “for speed and accuracy,” identifies embedded files/data, and can use entropy analysis to hint unknown compression/encryption. citeturn1search2

**AVB trust-chain surface.** AOSP AVB describes `vbmeta.img` as the top-level signed object containing verification digests and delegation keys for partitions like `boot.img` and `system.img`. citeturn2search4turn2search5 AVB’s rollback logic references `stored_rollback_index[n]` and recommended bootflow details, useful for auditing rollback-update correctness. citeturn2search7

**Local multi-model management without choking.** llama.cpp **router mode** provides model discovery, on-demand loading, request routing via the `"model"` field, and **LRU eviction** controlled by `--models-max`. citeturn3search0turn3search4

## The Legion state
**Design goal:** Maximum bootloader SWAP discovery quality through **parallel perspectives**, consensus, and tool-driven evidence—while staying stable on a 32GB/8GB GPU workstation by constraining live models and concurrency.

### Model roster and roles
Legion uses *all useful* models you already have, but keeps “riskier/uncensored” models disabled by default.

**Primary roles (active):**
- **Planner/Dispatcher (hot):** `Bootes-Qwen3-Coder-Reasoning.i1-Q4_K_M.gguf`  
- **Fast Triage Scout (hot):** `starcoder2-3b.Q4_K_M.gguf` (breadth scanning) citeturn0search? *(If you need a primary source, use HF model card or your local manifest; not required here.)*
- **Decompile Refiner (warm):** `LLM4Binary_llm4decompile-9b-v2.Q4_K_S.gguf` (refines Ghidra pseudo-C; strong re-executability benchmark per project updates). citeturn3search5
- **Deep Vuln Analyst (warm):** `deepseek-coder-7b-instruct-v1.5-imat-Q4_K_M.gguf` (memory logic, state machines)
- **Rewrite/Patch Intent (warm):** `qwen2.5-coder-7b-instruct-q4_k_m.gguf` (cleanup, remediation intent)
- **Tiny Clerk (hot):** `qwen2.5-coder-1.5b-instruct-q6_k.gguf` (summaries, normalization)

**Optional heavy arbiters (cold / loaded only for final adjudication):**
- `Qwen3.5-9B-*` models (choose one) for arbitration & severity scoring.
- `Qwen2.5-*11B*` only if RAM headroom remains after artifacts are loaded.

**Disabled-by-default (policy):**
- “uncensored/heretic” variants and the 20B uncensored model should be excluded from automated security runs unless explicitly enabled, to reduce the chance of generating unsafe instructions.

### Legion inference parameters and “parallelism without choking”
Legion’s parallelism is **logical parallelism** with strict hardware-aware caps:
- Use **llama.cpp router mode** with `--models-max 3` to keep **Planner + (Triage or Clerk) + (one heavy worker)** resident. LRU manages everything else. citeturn3search0turn3search4  
- Enforce **global LLM concurrency = 1–2** requests total (semaphore). Do not rely on Open WebUI multi-model chats for automation because they send prompts to multiple models simultaneously. citeturn1search0  
- Keep default context conservative (e.g., 4096) unless a run explicitly requests deeper context.

### Legion toolchain (bootloader-focused)
Legion runs a **graph-first** bootloader audit pipeline:
1. **Carve & normalize** (binwalk + Android partition tooling; binwalk for embedded payload extraction). citeturn1search2  
2. **Boot trust-chain map**: parse `vbmeta` relationships and rollback paths; AVB docs specify vbmeta’s role and rollback index policy cues. citeturn2search4turn2search7  
3. **Static RE evidence**:
   - Ghidra headless import + decompiler outputs.
   - ReVa MCP headless to extract strings/xrefs/callgraph and perform targeted renaming/type improvements. citeturn1search1  
4. **Structural scanning**: angr CFGFast exports CFGs for candidate functions. citeturn0search0  
5. **Swarm analysis lanes**:
   - **Lane A (Triage):** StarCoder2 finds suspicious motifs (parsing, memcpy-family, unlock flags).
   - **Lane B (Semantics):** LLM4Decompile refines the few hundred hottest functions.
   - **Lane C (Deep):** DeepSeek flags memory/state issues and proposes verification tests.
   - **Lane D (Remediation):** Qwen2.5-Coder rewrites into stable pseudo-C and drafts patch intent.
6. **Consensus + arbitration**: A synthesizer agent merges candidates MOA-style (Open WebUI documents the “merge/synthesize” concept). citeturn1search0  

### Legion exclusivity enforcement
Implement in both OS services and in-app locks:
- `systemd` units: `legion.service` includes `Conflicts=agency.service` and `Before=agency.service`; `agency.service` mirrors that.
- App lock: a PID/lockfile in `/run/android-re-lab.state` so any second mode exits immediately.

## The Agency state
**Design goal:** Streamlined, medium/large-agent, **serial** pipeline optimized for fewer model swaps and higher per-stage depth. It trades some swarm diversity for speed, determinism, and lower orchestration overhead.

### Agency agent chain (serial)
Agency uses 3–4 strong stages in sequence:
1. **Director (Planner):** Bootes-Qwen3 Reasoning generates a run plan and risk map.
2. **Decompiler Specialist:** LLM4Decompile refines top candidates (not everything).
3. **Primary Auditor:** Either DeepSeek-Coder 7B *or* Qwen2.5-Coder 7B (pick one; don’t bounce between them).
4. **Arbiter (optional):** One Qwen3.5-9B variant for final severity and narrative coherence.

Agency runs with router `--models-max 1` (or 2 if you need Director always-hot) to avoid memory fragmentation and thrashing. Router mode supports manual load/unload endpoints and status tracking. citeturn3search0turn3search4

### Agency toolchain
Agency uses the same extraction and evidence steps, but **reduces breadth**:
- Ghidra/ReVa headless for canonical decompiler + facts. citeturn1search1  
- angr CFGFast only on shortlisted functions (top N by heuristic score). citeturn0search0  
- radare2 MCP server as a fast fallback for strings/xrefs, with readonly/sandbox lock support. citeturn2search0  

## Uploadable Codex prompt for The Legion
```text
YOU ARE CODEX. BUILD “THE LEGION” (parallel swarm) AS A COMPLETE ANDROID BOOTLOADER SECURITY ASSESSMENT SUITE.
HARDWARE: 32GB RAM, 8GB VRAM (AMD RX 5700 XT). EXISTING: llama.cpp + Open WebUI already working (OpenAI-compatible API).
GOAL: Produce SWAP reports (locations + evidence + remediation intent). NO exploit payloads, NO bypass how-to.

MANDATORY EXCLUSIVITY:
- Install a systemd unit legion.service that Conflicts=agency.service and stops it on start.
- Implement a /run/… lockfile so Legion cannot run if Agency is active.

MODEL MANAGEMENT (CRITICAL):
- Run llama-server in ROUTER MODE (no -m) with:
  --models-dir ~/Models
  --models-max 3
  ctx=4096 default
  global LLM concurrency <=2
- Legion must “preload/unload” models by calling /models/load and /models/unload to avoid thrashing; rely on LRU eviction when needed. Router mode supports on-demand load + LRU via --models-max. Use endpoints documented for /models, /models/load, /models/unload and route by the request "model" field.

LEGION AGENTS (parallel logical lanes, but concurrency-limited):
- Planner/Dispatcher: Bootes-Qwen3-Coder-Reasoning.i1-Q4_K_M.gguf (always hot; send a keepalive ping per minute).
- Triage Scout: starcoder2-3b.Q4_K_M.gguf
- Decompile Refiner: LLM4Binary_llm4decompile-9b-v2.Q4_K_S.gguf
- Deep Auditor: deepseek-coder-7b-instruct-v1.5-imat-Q4_K_M.gguf
- Rewrite/Remediation: qwen2.5-coder-7b-instruct-q4_k_m.gguf
- Clerk/Summarizer: qwen2.5-coder-1.5b-instruct-q6_k.gguf
Disable “uncensored/heretic” models by default via policies.yaml.

TOOLS (install, integrate, verify):
- binwalk v3 for carving; Ghidra 11.4+; ReVa MCP headless; angr CFGFast; radare2-mcp (readonly + sandbox lock).
- Integrate AVB inspection by cloning external/avb and using avbtool read-only; incorporate rollback-index checks and vbmeta descriptor mapping.

PIPELINE:
1) ingest: binwalk extraction + android image normalization (sparse/super/bootimg if present)
2) ghidra+reva: extract functions, pseudo-C, strings, xrefs, callgraph
3) angr: CFGFast per shortlisted function; export JSON graph
4) legion lanes:
   - Scout lane runs broad detection over artifacts (strings, memcpy-family, parsing, unlock state)
   - Refiner lane refines pseudo-C for top candidates only
   - Auditor lane produces SWAP candidates with evidence + verification tests that are safe (assertions/unit tests)
   - Remediation lane drafts patch intent (no weaponization)
5) Consensus: MOA-style synthesis (merge candidates that agree; boost confidence)

IMPLEMENT:
- repo legion-suite/
- CLI: legionctl run --input <path> --output runs/
- Web UI: basic runs list/report download
- Strict JSON schemas for all agent outputs; fail run if schema invalid.
- Logging: log every tool call + every LLM request (model, prompt hash, response hash).

VERIFY:
- scripts/verify_legion.sh:
  * start router, check /models
  * load/unload models in sequence; ensure RSS stable
  * run on a demo ELF (and optional aarch64 sample) and generate SWAP report
DONE ONLY WHEN verify_legion.sh passes.
```

## Uploadable Codex prompt for The Agency
```text
YOU ARE CODEX. BUILD “THE AGENCY” (serial pipeline) AS A COMPLETE ANDROID BOOTLOADER SECURITY ASSESSMENT SUITE.
HARDWARE: 32GB RAM, 8GB VRAM. EXISTING: llama.cpp + Open WebUI already working.
GOAL: Highest-quality SERIAL SWAP pipeline. NO exploit instructions, NO bypass steps.

MANDATORY EXCLUSIVITY:
- Install agency.service Conflicts=legion.service and stops it on start.
- Enforce a /run/… lockfile to prevent co-running.

MODEL MANAGEMENT:
- Run llama-server router mode with:
  --models-dir ~/Models
  --models-max 1  (or 2 if you keep Director hot)
  ctx=4096 default; allow per-stage ctx overrides.
- Only one heavy model loaded at a time; explicitly /models/load at stage start, /models/unload at stage end.

SERIAL AGENT CHAIN:
Stage 1 Director: Bootes-Qwen3-Coder-Reasoning.i1-Q4_K_M.gguf produces plan + targets.
Stage 2 Decompile Specialist: LLM4Binary_llm4decompile-9b-v2.Q4_K_S.gguf refines top candidates only.
Stage 3 Primary Auditor (choose ONE): deepseek-coder-7b-instruct-v1.5-imat-Q4_K_M.gguf OR qwen2.5-coder-7b-instruct-q4_k_m.gguf (avoid bouncing).
Stage 4 Arbiter (optional): one Qwen3.5-9B model for final severity narrative.

TOOLS:
Same as Legion (binwalk v3, Ghidra+ReVa headless, angr CFGFast on only top-N, radare2-mcp readonly, AVB avbtool read-only).
Reduce breadth: only CFG on top-N by heuristic score.

IMPLEMENT:
- repo agency-suite/
- CLI: agencyctl run --input <path> --profile fast|deep
- Web UI minimal.
- Strict JSON schemas for stage outputs.
- Logging and reproducibility identical to Legion.

VERIFY:
- scripts/verify_agency.sh:
  * prove only one model loaded at a time using /models
  * run demo binary -> SWAP report generated
  * confirm legion.service was stopped if running
DONE ONLY WHEN verify_agency.sh passes.
```

