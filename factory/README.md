# Factory

This directory is the stable compiler handoff point for the run.

Inputs the compiler should consume:
- `../lowering-pass/CLAUDE.md`
- `../lowering-pass/DEBT.md`
- `../lowering-pass/REVIEW_CHECKLIST.md`
- `../lowering-pass/factory.yaml`
- `./session-packages/`
- `./initiation/`

Typical flow:
1. Finish research in `../research/`
2. Run `../draft-lowering.sh`
3. Re-run `../materialize.sh --force` only if you made manual edits after the draft
4. Initialize the target compiler repo with `./bootstrap-compiler-repo.sh /path/to/compiler-repo`
5. In the target repo, run `./start-compiler-flow.sh`
6. Use `./status-compiler-flow.sh` and `./stop-compiler-flow.sh` to inspect or stop the run
7. Start compiler agents with `./factory/init-compiler.sh` if you also want the tmux session packages opened directly

Generated compiler bootstrap artifacts:
- `bootstrap-compiler-repo.sh`
- `start-compiler-flow.sh`
- `status-compiler-flow.sh`
- `stop-compiler-flow.sh`
- `session-manifest.json`
- `session-packages/coordinator.md`
- `session-packages/reviewer.md`
- `session-packages/worker-*.md`
- `initiation/coordinator.sh`
- `initiation/reviewer.sh`
- `initiation/worker-*.sh`
- `compiler-queue/.codex-autorunner/tickets/TICKET-*.md`
- `compiler-queue/install-into-repo.sh`
