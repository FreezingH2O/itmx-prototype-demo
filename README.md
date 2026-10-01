# 03-solution: Bank × Crypto Risk Graph

Solution documents and the working prototype for the NITMX Fintech Bootcamp 2026 final (Track 2: Linking Chance for All).

- **Prototype (Engine API + 4-page demo, synthetic data):** [PROTOTYPE.md](PROTOTYPE.md). Runs with hand-set demo rules; no experiment results are plugged in yet.
- **Plug in the experiment model:** [PLUGIN.md](PLUGIN.md)

- Current experiment implementation plan: [05-model-experiments](../05-model-experiments/README.md) (Kaggle; design only, no executed results yet)
- Project brief for Claude Code / the team: [CLAUDE.md](CLAUDE.md)
- Independent solution/technical review (start here): [docs/independent-review-2026-10-01.md](docs/independent-review-2026-10-01.md)
- Proposed optimized architecture and acceptance scenarios: [docs/optimized-architecture-2026-10-01.md](docs/optimized-architecture-2026-10-01.md)
- Fact-check register: [docs/fact-check-register-2026-10-01.md](docs/fact-check-register-2026-10-01.md)
- Earlier final-round evaluation and solution v2 (contains claims corrected by the independent review): [docs/final-evaluation-and-v2.md](docs/final-evaluation-and-v2.md)
- Solution v1 summary (users, flow, architecture, competitors): [docs/solution-summary.md](docs/solution-summary.md)

```
data/            raw/, processed/ (gitignored)
src/
  generator/     synthetic mule-flow simulator
  ingest/        loaders for IBM AML, Elliptic, TRON sample
  linking/       entity linker
  features/      tabular + graph features
  models/        gbdt.py, gnn.py, hybrid.py
  eval/          temporal split, metrics, cost-based threshold
  api/           FastAPI risk score endpoint
demo/            Streamlit demo app
notebooks/       exploration only
docs/            solution docs
```

All demo data is synthetic. Do not commit real data.
