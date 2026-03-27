# Research-Compiler

A portable template for turning a topic into a shipped product through autonomous agent pipelines.

**Copy this folder. Edit two JSON files. Run one script. Get a research report, a lowering pass, and a compiler-ready ticket queue.**

---

## What This Does

Research-Compiler is a three-stage pipeline that takes a vague idea ("build something in X market") and produces:

1. **Research** — autonomous deep-loop agents explore the market, users, competitors, and product wedge
2. **Lowering Pass** — research output is compiled into a build constitution, work items, review gates, and execution order
3. **Factory Compiler** — the lowering pass is emitted as runnable tickets, session packages, and bootstrap scripts for coding agents

Each stage feeds the next. No manual handoff formatting. No copy-paste between tools.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        run-template/                                │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ research_config   │  │ lowering_config   │  │   materialize    │  │
│  │     .json         │  │     .json         │  │      .sh         │  │
│  │                   │  │                   │  │                  │  │
│  │ • topic           │  │ • constitution    │  │ Orchestrates all │  │
│  │ • directives      │  │ • debt items      │  │ three stages     │  │
│  │ • agent groups    │  │ • review gates    │  │                  │  │
│  │ • output target   │  │ • factory config  │  │                  │  │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘  │
│           │                     │                      │            │
│           ▼                     ▼                      │            │
│  ┌──────────────────────────────────────────┐          │            │
│  │              tools/                       │◄─────────┘            │
│  │                                           │                      │
│  │  scaffold.py ─────────► research/         │                      │
│  │  lowering_scaffold.py ► lowering-pass/    │                      │
│  │  compiler_bootstrap.py► factory/packages  │                      │
│  │  compiler_ticket_emitter.py► factory/queue│                      │
│  │  handoff_to_lowering.py (draft-lowering)  │                      │
│  └───────────────────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Stages

### Stage 1: Research

```
research_config.json
        │
        ▼
  scaffold.py ──► research/
                    │
                    ├── CLAUDE.md            ← Research constitution (invariants, rules)
                    ├── program.md           ← Mutable directives (rewritten by meta-agent)
                    ├── report.md            ← Primary output (populated during run)
                    ├── knowledge_index.tsv  ← Audit trail of every question researched
                    ├── process_log.md       ← Meta-analysis history
                    ├── deep_loop_project.json
                    │
                    ├── agent-1-prompt.md ┐
                    ├── agent-2-prompt.md │  Parallel research agents
                    ├── agent-3-prompt.md │  (one per directive group)
                    ├── agent-4-prompt.md ┘
                    ├── meta-prompt.md       ← Synthesis + steering agent
                    │
                    ├── swarm.sh             ← tmux launcher for all agents
                    ├── meta_analyze.py      ← Coverage analysis engine
                    └── notify.py            ← Event notifications → OpenClaw
```

**How it runs:**

```
 ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
 │ Agent 1  │  │ Agent 2  │  │ Agent 3  │  │ Agent 4  │
 │ Market   │  │ Workflow │  │ Compete  │  │ Product  │
 │ Structure│  │ & Pain   │  │ Landscape│  │ Defn     │
 └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
      │              │              │              │
      │   search → write → commit → search → write → commit
      │              │              │              │
      ▼              ▼              ▼              ▼
 partial-report-A  partial-B     partial-C     partial-D
      │              │              │              │
      └──────────────┴──────┬───────┴──────────────┘
                            │
                    ┌───────▼────────┐
                    │   Meta Agent    │
                    │                 │
                    │ • reads all     │
                    │   partials +    │
                    │   knowledge TSV │
                    │ • runs          │
                    │   meta_analyze  │
                    │ • rewrites      │
                    │   program.md    │
                    │ • merges into   │
                    │   report.md     │
                    └───────┬────────┘
                            │
                            ▼
                   report.md (complete)
                   knowledge_index.tsv
                   git log = full audit trail
```

Each agent runs as a Claude Code instance in a tmux window. They:
- Pick questions from `program.md`
- Web search → read sources → synthesize
- Write findings to `partial-report-{directive}.md`
- Append to `knowledge_index.tsv`
- Commit after each entry

The meta-agent periodically:
- Reads all partial reports + the knowledge index
- Runs coverage analysis (`meta_analyze.py`)
- Rewrites `program.md` with updated priorities
- Merges partial reports into the final `report.md`

**Termination:** configurable minimum entries, meta-analysis cycles, and section coverage.

---

### Stage 2: Lowering Pass

```
                    ┌──────────────────┐
                    │  draft-lowering   │
                    │      .sh          │
                    │                   │
                    │ Feeds research    │
                    │ output through    │
                    │ Claude to draft   │
                    │ lowering_config   │
                    └────────┬──────────┘
                             │
         ┌───────────────────┤
         │                   │
         ▼                   ▼
 research/report.md    lowering_config.json
 research/program.md         │
 research/knowledge_         │
   index.tsv                 │
                             ▼
                   lowering_scaffold.py
                             │
                             ▼
                    lowering-pass/
                      │
                      ├── CLAUDE.md             ← Build constitution
                      │     • what the product is
                      │     • architectural invariants
                      │     • canonical primitives
                      │     • file ownership map
                      │     • done criteria
                      │
                      ├── DEBT.md               ← Sequenced work items
                      │     • ground truth per item
                      │     • scope boundaries
                      │     • acceptance criteria
                      │     • file targets
                      │     • execution order (waves)
                      │
                      ├── REVIEW_CHECKLIST.md   ← Verification gates
                      │     • type safety
                      │     • happy path verification
                      │     • scope discipline
                      │     • merge protocol
                      │
                      ├── factory.yaml          ← Machine-readable config
                      │     • risk tiers + classification
                      │     • execution order
                      │     • verification commands
                      │
                      └── lowering_project.json ← Full config snapshot
```

**Two paths to get here:**

```
Path A (automated):                    Path B (manual):
  ./draft-lowering.sh                    Edit lowering_config.json by hand
    │                                    using research findings
    ├─ reads research artifacts           │
    ├─ feeds through Claude               │
    ├─ writes lowering_config.json        │
    └─ runs materialize.sh --force        └─ run materialize.sh --force
```

The lowering pass converts research insights into compiler-consumable artifacts. Every work item has ground truth (from research), bounded scope, and acceptance criteria. No ambiguity for the compiler agents.

---

### Stage 3: Factory Compiler

`compiler_bootstrap.py` and `compiler_ticket_emitter.py` run during `materialize.sh` and produce two parallel execution surfaces:

```
lowering_config.json
        │
        ├──► compiler_bootstrap.py ──► factory/
        │                                │
        │                                ├── session-packages/
        │                                │     ├── coordinator.md    ← Orchestration role
        │                                │     ├── reviewer.md       ← Verification role
        │                                │     ├── worker-debt-001.md
        │                                │     └── worker-debt-002.md  (one per work item)
        │                                │
        │                                ├── initiation/
        │                                │     ├── coordinator.sh    ← Launch scripts
        │                                │     ├── reviewer.sh
        │                                │     ├── worker-debt-001.sh
        │                                │     └── worker-debt-002.sh
        │                                │
        │                                ├── init-compiler.sh        ← tmux swarm launcher
        │                                ├── bootstrap-compiler-repo.sh
        │                                ├── start-compiler-flow.sh  ← CAR ticket-flow
        │                                ├── status-compiler-flow.sh
        │                                ├── stop-compiler-flow.sh
        │                                └── session-manifest.json
        │
        └──► compiler_ticket_emitter.py ──► factory/compiler-queue/
                                              │
                                              ├── .codex-autorunner/
                                              │     ├── tickets/
                                              │     │     ├── AGENTS.md
                                              │     │     ├── TICKET-001.md
                                              │     │     └── TICKET-002.md
                                              │     └── contextspace/
                                              │           ├── active_context.md
                                              │           ├── spec.md
                                              │           └── decisions.md
                                              │
                                              ├── queue-manifest.json
                                              ├── install-into-repo.sh
                                              └── README.md
```

**Two execution modes:**

```
Mode A: Session Packages (tmux)         Mode B: CAR Ticket Flow (automated)
┌──────────────────────────────┐       ┌──────────────────────────────┐
│  ./factory/init-compiler.sh  │       │  ./start-compiler-flow.sh   │
│                              │       │                              │
│  tmux session with windows:  │       │  CAR (codex-autorunner):     │
│  ┌─────────────────────────┐ │       │  ┌─────────────────────────┐ │
│  │ coordinator │ reviewer  │ │       │  │ Reads TICKET-001.md     │ │
│  │─────────────│───────────│ │       │  │ Executes scope          │ │
│  │ worker-001  │ worker-002│ │       │  │ Runs verification       │ │
│  └─────────────────────────┘ │       │  │ Marks done: true        │ │
│                              │       │  │ Moves to TICKET-002     │ │
│  Each window runs Claude     │       │  └─────────────────────────┘ │
│  Code with its session       │       │                              │
│  package as input            │       │  Autonomous queue runner     │
└──────────────────────────────┘       └──────────────────────────────┘
```

**Bootstrap flow for a fresh repo:**

```
./factory/bootstrap-compiler-repo.sh /path/to/new-repo
        │
        ├── copies lowering-pass/ into repo
        ├── copies session-packages + initiation scripts
        ├── copies CAR tickets + contextspace
        └── copies flow control scripts

Then in the new repo:
        │
        ▼
./start-compiler-flow.sh
        │
        ├── car init .
        ├── car hub create (registers repo)
        ├── car ticket-flow preflight (validates tickets)
        └── car ticket-flow start (begins execution)
```

---

## Complete End-to-End Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   1. CONFIGURE                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Edit research_config.json    Edit lowering_config.json            │   │
│   │  (topic, directives,          (or let draft-lowering.sh            │   │
│   │   questions, agents)           auto-generate from research)        │   │
│   └──────────────────────┬──────────────────────────────────────────────┘   │
│                          │                                                  │
│   2. MATERIALIZE         ▼                                                  │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  ./materialize.sh                                                   │   │
│   │                                                                     │   │
│   │  scaffold.py ──────────────────────────► research/                  │   │
│   │  lowering_scaffold.py ─────────────────► lowering-pass/             │   │
│   │  compiler_bootstrap.py ────────────────► factory/packages           │   │
│   │  compiler_ticket_emitter.py ───────────► factory/compiler-queue     │   │
│   └──────────────────────┬──────────────────────────────────────────────┘   │
│                          │                                                  │
│   3. RESEARCH            ▼                                                  │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  cd research && ./swarm.sh                                          │   │
│   │                                                                     │   │
│   │  4 research agents (parallel) + 1 meta-agent (periodic)            │   │
│   │  → web search → synthesize → write → commit                        │   │
│   │  → meta-analysis rewrites program.md                               │   │
│   │  → agents merge into report.md                                     │   │
│   │                                                                     │   │
│   │  Output: report.md, knowledge_index.tsv, git audit trail           │   │
│   └──────────────────────┬──────────────────────────────────────────────┘   │
│                          │                                                  │
│   4. LOWER               ▼                                                  │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  ./draft-lowering.sh                                                │   │
│   │                                                                     │   │
│   │  Feeds report + program + knowledge through Claude                  │   │
│   │  → Drafts lowering_config.json from research evidence               │   │
│   │  → Re-runs materialize.sh --force                                   │   │
│   │  → Regenerates lowering-pass/ and factory/ with real content        │   │
│   └──────────────────────┬──────────────────────────────────────────────┘   │
│                          │                                                  │
│   5. COMPILE             ▼                                                  │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Option A: ./factory/bootstrap-compiler-repo.sh /path/to/repo      │   │
│   │            cd /path/to/repo && ./start-compiler-flow.sh            │   │
│   │                                                                     │   │
│   │  Option B: ./factory/init-compiler.sh                               │   │
│   │            (tmux session with coordinator + reviewer + workers)     │   │
│   │                                                                     │   │
│   │  Coding agents execute DEBT items against the repo                  │   │
│   │  → Governed by CLAUDE.md constitution                               │   │
│   │  → Verified by REVIEW_CHECKLIST.md gates                            │   │
│   │  → Sequenced by factory.yaml execution order                        │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

```bash
# 1. Copy the template
cp -R Research-Compiler ~/Desktop/my-new-project
cd ~/Desktop/my-new-project

# 2. Edit the research config
#    Replace "New Topic" placeholders with your actual topic,
#    questions, directives, and agent groups
$EDITOR research_config.json

# 3. Materialize the workspace
./materialize.sh

# 4. Run the research swarm
cd research
./swarm.sh
# Monitor: tmux attach -t run-template-research

# 5. After research completes, draft the lowering pass
cd ..
./draft-lowering.sh

# 6. Review and optionally tighten lowering_config.json
$EDITOR lowering_config.json
./materialize.sh --force   # only if you made manual edits

# 7. Bootstrap and run the compiler
./factory/bootstrap-compiler-repo.sh /path/to/new-repo
cd /path/to/new-repo
./start-compiler-flow.sh
```

---

## File Reference

| File | Purpose | Edit? |
|------|---------|-------|
| `research_config.json` | Research topic, directives, agent groups, output target | ✅ Yes — your starting point |
| `lowering_config.json` | Build constitution, work items, review gates, factory config | ✅ Yes — or auto-draft from research |
| `materialize.sh` | Orchestrates all generators | No |
| `draft-lowering.sh` | Auto-drafts lowering config from research output | No |
| `tools/scaffold.py` | Generates research workspace | No |
| `tools/lowering_scaffold.py` | Generates lowering-pass artifacts | No |
| `tools/handoff_to_lowering.py` | Feeds research through Claude to draft lowering config | No |
| `tools/compiler_bootstrap.py` | Generates session packages + initiation scripts | No |
| `tools/compiler_ticket_emitter.py` | Generates CAR-compatible ticket queue | No |
| `factory/README.md` | Compiler handoff documentation | No |

---

## Requirements

- **Python 3.10+** (stdlib only — no pip dependencies)
- **Claude Code** (`claude` CLI) — for research agents and lowering draft
- **tmux** — for parallel agent execution
- **git** — research agents commit after each finding
- **CAR** (`codex-autorunner`) — optional, for automated ticket-flow execution
- **OpenClaw** — optional, for event notifications during research
- **tree-sitter** + **tree-sitter-language-pack** — optional, for the higher-fidelity polyglot middle-end

---

## Tree-sitter Middle-End

The middle-end now prefers real `tree-sitter` grammars for supported languages:

- Python
- TypeScript / TSX
- JavaScript / JSX
- Go
- Rust

This path is driven by `core/optimizers/tree_sitter_adapter.py` and the `.scm` query files under `core/optimizers/queries/`.

Install the optional parser dependencies with:

```bash
python3 -m pip install --user --break-system-packages tree-sitter tree-sitter-language-pack
```

If those packages are unavailable, the compiler falls back to the existing regex and Python-`ast` backends. The tree-sitter path is preferred because it improves polyglot slicing, cross-file linking, and best-effort parsing for broken code.

---

## Design Principles

- **Self-contained.** Copy the folder anywhere. No external imports or framework dependencies.
- **Config-driven.** Edit JSON, not Python. The generators handle all formatting.
- **Auditable.** Every research finding is committed with a git message. Every work item traces to research evidence.
- **Two execution modes.** tmux session packages for supervised runs, CAR ticket-flow for autonomous runs.
- **Idempotent.** `materialize.sh --force` regenerates everything cleanly.

---

## License

MIT
