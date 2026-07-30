# Zava · Notebooks

The didactic, runnable walkthroughs. Each agent has an English and a Portuguese (pt-BR) version — the
**code is identical** across languages, only the narrative differs.

| Notebook | Agent | Language |
|----------|-------|----------|
| `01_inventory_agent.en.ipynb` | InventoryAgent (prompt agent) | English |
| `01_inventory_agent.pt-BR.ipynb` | InventoryAgent (prompt agent) | Português |
| `02_delivery_support_agent.en.ipynb` | DeliverySupport (hosted agent, MAF) | English |
| `02_delivery_support_agent.pt-BR.ipynb` | DeliverySupport (hosted agent, MAF) | Português |

## How to run
1. Provision + deploy the demo first (see the repo `README.md` quickstart) so `.env` and the live services exist.
2. Select the repo virtual environment (`.venv`) as the Jupyter kernel.
3. Open a notebook and run the cells top to bottom.

`_builders/` contains the Python scripts that generate these notebooks (via `nbformat`) — run one to
regenerate its `.ipynb`. Diagrams use Mermaid (rendered by GitHub) and the reference UI images in
`../docs/ux-reference/`.
