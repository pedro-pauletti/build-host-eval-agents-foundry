"""Builder for notebooks/04_databricks_integration.en.ipynb (English).

Run: .venv\\Scripts\\python.exe notebooks/_builders/build_databricks_en.py
Mirrors the live scripts in data/databricks/ and agents/inventory-agent-databricks/.
"""
import os
import nbformat as nbf

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "04_databricks_integration.en.ipynb")

nb = nbf.v4.new_notebook()
cells = []
def md(t): cells.append(nbf.v4.new_markdown_cell(t.strip("\n")))
def code(t): cells.append(nbf.v4.new_code_cell(t.strip("\n")))

md(r"""
# 🧱 Zava · **Foundry + Azure Databricks** — the same demo, wired through MCP

> **Unity Catalog** · **Genie space** · **Databricks managed MCP** · Foundry `MCPTool` · Entra-only auth
>
> 🇧🇷 A Portuguese version of this notebook is available as `04_databricks_integration.pt-BR.ipynb`.

Notebook 01 gave the InventoryAgent an analytics brain with a **Microsoft Fabric Data Agent**, attached
through a first-party Foundry tool. This notebook does the same job with **Azure Databricks** — and the
interesting part is that it *cannot* use a first-party tool, because none exists.

That constraint is the lesson. Databricks arrives over **MCP**, which is the same mechanism the Zava
toolbox and knowledge base already use, and it turns out to need **less** machinery than the
first-party path.

We load the *same ten tables* with the *same row counts*, so both agents answer the same questions.
Only the plumbing differs.
""")

md(r"""
## 🏗️ Architecture

```mermaid
flowchart LR
  CSV[data/structured/*.csv<br/>the same 9 CSVs notebook 01 used] --> VOL[Unity Catalog volume<br/>zava_workspace.demo.raw]
  VOL -->|read_files + CAST| UC[(10 Delta tables<br/>+ comments + PK/FK)]
  UC --> GENIE[Genie space<br/>natural language to SQL]
  GENIE --> MCPS[Databricks managed MCP<br/>/api/2.0/mcp/genie/id]
  MCPS -->|Entra token| CONN[Foundry connection<br/>RemoteTool · project managed identity]
  CONN --> AGENT[InventoryAgentDatabricks<br/>MCPTool]
  AGENT --> Q[Same questions as notebook 01]

  subgraph GOV[Unity Catalog governance]
    UC
  end
```

**Side-by-side with notebook 01.**

| | Fabric (notebook 01) | Databricks (this notebook) |
|---|---|---|
| Analytics engine | Fabric **Data Agent** over a Direct Lake semantic model | **Genie space** over Unity Catalog tables |
| Foundry tool | `MicrosoftFabricPreviewTool` (first-party) | `MCPTool` (**no first-party tool exists**) |
| Can live in a Toolbox | ❌ `ToolboxToolType` only exposes `fabric_iq_preview` | ✅ |
| Connection kind | `CustomKeys` carrying `metadata.type` | plain `RemoteTool` |
| Credential | project managed identity | project managed identity — **no PAT anywhere** |
| Client SDK to build it | `fabric-data-agent-sdk`, Python 3.10–3.12 → separate venv | none |
| Compute | F8 capacity | serverless SQL warehouse, auto-stop |
| Per-principal data access | model-level | **Unity Catalog grants** |
""")

md(r"""
## ✅ Setup

You need an Azure Databricks workspace and `az login` as a workspace admin. Everything else is
created by this notebook.

```powershell
.\.venv\Scripts\pip.exe install requests python-dotenv azure-ai-projects azure-identity
```

Add to `.env`:

```
DATABRICKS_HOST=adb-0000000000000000.0.azuredatabricks.net   # hostname only, no https://
DATABRICKS_CATALOG=zava_workspace
DATABRICKS_SCHEMA=demo
```

> ⚠️ The first SQL statement starts a serverless warehouse and can take ~30 seconds.
""")

code(r"""
import json, os, subprocess, sys, time
from pathlib import Path
from dotenv import load_dotenv
import requests

REPO = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
load_dotenv(REPO / ".env", override=False)

HOST = os.environ["DATABRICKS_HOST"].replace("https://", "").rstrip("/")
CATALOG = os.getenv("DATABRICKS_CATALOG", "zava_workspace")
SCHEMA = os.getenv("DATABRICKS_SCHEMA", "demo")

# The Azure Databricks service has a FIXED application id. Asking Entra for a token with this
# audience is what lets `az login` stand in for a Databricks personal access token.
DBX_RESOURCE = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"

TOKEN = subprocess.run(
    ["az", "account", "get-access-token", "--resource", DBX_RESOURCE, "--query", "accessToken", "-o", "tsv"],
    capture_output=True, text=True, shell=True,
).stdout.strip()

H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def api(method, path, **kw):
    return requests.request(method, f"https://{HOST}{path}", headers=H, timeout=120, **kw)

me = api("GET", "/api/2.0/preview/scim/v2/Me").json()
print("workspace :", HOST)
print("auth      :", me.get("userName"), "(token Entra, sem PAT)")
print("target    :", f"{CATALOG}.{SCHEMA}")
""")

md(r"""
## 1️⃣ The SQL warehouse

Genie runs its generated SQL on a **SQL warehouse**. A serverless one with auto-stop is the cheapest
option for a demo: it costs nothing while idle and cold-starts on the first query.

Everything in this notebook goes through the **Statement Execution API**, so there is no Spark
session, no cluster to attach to, and nothing to install.
""")

code(r'''
warehouses = api("GET", "/api/2.0/sql/warehouses").json().get("warehouses", [])
for w in warehouses:
    print(f"  {w['name']:34s} state={w['state']:8s} serverless={w.get('enable_serverless_compute')}  id={w['id']}")

WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID") or warehouses[0]["id"]
print("\nusando:", WAREHOUSE_ID)

def sql(statement: str, wait: int = 50) -> dict:
    """Run a statement to completion. The first call auto-starts a stopped serverless warehouse."""
    r = api("POST", "/api/2.0/sql/statements", data=json.dumps({
        "warehouse_id": WAREHOUSE_ID, "statement": statement, "wait_timeout": f"{wait}s"}))
    r.raise_for_status()
    out = r.json()
    while out.get("status", {}).get("state") in ("PENDING", "RUNNING"):
        time.sleep(3)
        out = api("GET", f"/api/2.0/sql/statements/{out['statement_id']}").json()
    if out.get("status", {}).get("state") != "SUCCEEDED":
        raise RuntimeError(json.dumps(out.get("status"))[:400])
    return out

def rows(statement: str):
    return (sql(statement).get("result") or {}).get("data_array") or []
''')

md(r"""
## 2️⃣ Load the same ten tables into Unity Catalog

The path is **CSV → Unity Catalog volume → `read_files` → typed Delta table**. Volumes are the
governed landing zone for files in Unity Catalog, and `read_files` reads them straight into SQL.

Two deliberate choices:

* Every column is read as `STRING` and then **cast explicitly**. Type inference on a CSV is a
  coin flip; explicit casts make the load reproducible.
* `NULLIF(col, '')` before each cast. Without it an empty CSV field casts to `0` for a number
  instead of `NULL` — which silently corrupts averages and, here, would break the `sales → stores`
  relationship for online sales.
""")

code(r'''
sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA} COMMENT 'Zava demo: retail apparel sales, inventory and orders.'")
sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.raw COMMENT 'Raw CSV landing zone.'")
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/raw"
print("schema + volume prontos:", VOLUME_PATH)

def upload(local: Path, name: str):
    """Files API: PUT the bytes straight into the governed volume."""
    r = requests.put(
        f"https://{HOST}/api/2.0/fs/files{VOLUME_PATH}/{name}?overwrite=true",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/octet-stream"},
        data=local.read_bytes(), timeout=300)
    r.raise_for_status()

SRC = REPO / "data" / "structured"
for csv in ["product_lines.csv", "facilities.csv", "stores.csv", "customers.csv", "products.csv",
            "inventory.csv", "sales.csv", "orders.csv", "order_items.csv"]:
    upload(SRC / csv, csv)
    print("  uploaded", csv)
''')

md(r"""
### 2️⃣.1 One table, in full

`products` shows the whole pattern. The rest of the tables are identical in shape — the live loader
[`data/databricks/load_uc_tables.py`](../data/databricks/load_uc_tables.py) drives all nine from a
declarative spec.

Note the **`COMMENT` on every column**. This is not documentation for humans: Genie reads table and
column comments to decide which tables a question needs and how to filter them. Comments are the
single highest-leverage thing you can do for answer quality.
""")

code(r'''
PRODUCTS_COLS = {
    "sku": ("STRING", "Stock keeping unit, e.g. ZCPTM-SS-S-B0. Unique per size/colour variant."),
    "product_line": ("STRING", "Full product line name."),
    "line_code": ("STRING", "Line code joining to product_lines: C=Core, R=Pro, P=Premium, E=Elite."),
    "garment": ("STRING", "Garment type, e.g. tee, shorts, long-sleeve top."),
    "gender": ("STRING", "Target gender."),
    "cut": ("STRING", "Garment cut."),
    "size": ("STRING", "Size code."),
    "size_label": ("STRING", "Human readable size."),
    "color_code": ("STRING", "Colour code."),
    "color_name": ("STRING", "Colour name."),
    "name": ("STRING", "Full product name."),
    "channel": ("STRING", "Channel the SKU is sold through."),
    "unit_cost": ("DECIMAL(18,2)", "Cost per unit in USD."),
    "unit_price": ("DECIMAL(18,2)", "List price per unit in USD."),
    "active": ("BOOLEAN", "Whether the SKU is currently active."),
}

read_schema = ", ".join(f"{c} STRING" for c in PRODUCTS_COLS)          # read raw, cast later
select = ",\n    ".join(f"CAST(NULLIF({c}, '') AS {t}) AS {c}" for c, (t, _) in PRODUCTS_COLS.items())

sql(f"""
    CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.products
    COMMENT 'Product catalogue at SKU (size/colour variant) grain.'
    AS SELECT
    {select}
    FROM read_files('{VOLUME_PATH}/products.csv',
                    format => 'csv', header => true, schema => '{read_schema}')
""")

for col, (_, comment) in PRODUCTS_COLS.items():
    sql(f"ALTER TABLE {CATALOG}.{SCHEMA}.products ALTER COLUMN {col} COMMENT '{comment}'")

print("products:", rows(f"SELECT count(*) FROM {CATALOG}.{SCHEMA}.products")[0][0], "linhas")
print(rows(f"SELECT sku, name, unit_price FROM {CATALOG}.{SCHEMA}.products LIMIT 3"))
''')

md(r"""
### 2️⃣.2 The other nine

Same pattern, driven from the spec in the live loader. Running the module directly keeps the
notebook honest — this is exactly the code the repo ships, not a paraphrase of it.
""")

code(r"""
import subprocess
out = subprocess.run([sys.executable, str(REPO / "data" / "databricks" / "load_uc_tables.py")],
                     capture_output=True, text=True, cwd=str(REPO))
print(out.stdout[-2000:] or out.stderr[-2000:])
""")

md(r"""
### 2️⃣.3 Keys and relationships

Unity Catalog supports **informational** primary and foreign keys: it does not enforce them, but
Genie reads them to work out how to join. These are the same 11 relationships the Fabric semantic
model declares — the star schema is identical, only the notation differs.
""")

code(r'''
constraints = rows(f"""
    SELECT constraint_name, constraint_type
    FROM {CATALOG}.information_schema.table_constraints
    WHERE table_schema = '{SCHEMA}'
    ORDER BY constraint_type, constraint_name
""")
pk = [c for c, t in constraints if t == "PRIMARY KEY"]
fk = [c for c, t in constraints if t == "FOREIGN KEY"]
print(f"{len(pk)} primary keys, {len(fk)} foreign keys")
for c in fk:
    print("   ", c)
''')

md(r"""
### 2️⃣.4 Parity check with Fabric

The demo only makes its point if both engines see the same numbers. These are the values notebook 01
reports from Fabric and the Zava API.
""")

code(r'''
CHECKS = [
    ("Premium on-hand", f"SELECT sum(i.on_hand) FROM {CATALOG}.{SCHEMA}.inventory i "
                        f"JOIN {CATALOG}.{SCHEMA}.products p ON p.sku=i.sku WHERE p.line_code='P'", "203857"),
    ("Elite on-hand", f"SELECT sum(i.on_hand) FROM {CATALOG}.{SCHEMA}.inventory i "
                      f"JOIN {CATALOG}.{SCHEMA}.products p ON p.sku=i.sku WHERE p.line_code='E'", "198596"),
    ("ZCPTM-SS-S-B0", f"SELECT sum(on_hand) FROM {CATALOG}.{SCHEMA}.inventory WHERE sku='ZCPTM-SS-S-B0'", "1672"),
    ("critical at FC-CLT", f"SELECT count(*) FROM {CATALOG}.{SCHEMA}.inventory "
                           f"WHERE facility_code='FC-CLT' AND status='critical'", "49"),
]
for label, stmt, expected in CHECKS:
    got = str(rows(stmt)[0][0])
    print(f"  {'OK ' if got == expected else 'XX '}{label:22s} esperado {expected:8s} obtido {got}")

print("\nreceita por linha:")
for line, rev in rows(f"""
        SELECT p.product_line, round(sum(s.revenue), 2)
        FROM {CATALOG}.{SCHEMA}.sales s JOIN {CATALOG}.{SCHEMA}.products p ON p.sku = s.sku
        GROUP BY p.product_line ORDER BY 2 DESC"""):
    print(f"   {line:28s} {rev}")
''')

md(r"""
## 3️⃣ The Genie space — the Fabric Data Agent's counterpart

A **Genie space** is Databricks' natural-language-to-SQL surface over a curated set of tables. It
plays exactly the role the Fabric Data Agent plays over the semantic model: a question goes in, SQL
runs on the warehouse, rows come back.

The `serialized_space` payload is a **versioned export proto** and is undocumented. Its shape:

```json
{"version": 2,
 "data_sources": {"tables": [{"identifier": "cat.schema.table"}]},
 "instructions": {"text_instructions": [{"content": ["line", "line"]}]}}
```

Two constraints that produce errors which don't explain themselves:

* `data_sources.tables` must be **sorted by identifier**.
* `text_instructions` is a **list**, and its `content` is a **list of strings** — not a string.
""")

code(r"""
TABLES = sorted(f"{CATALOG}.{SCHEMA}.{t}" for t in
                ["product_lines", "facilities", "stores", "customers", "products",
                 "inventory", "sales", "orders", "order_items", "dim_date"])

# Deliberately close to the Fabric Data Agent's instructions, so the comparison is about
# plumbing rather than prompt quality.
INSTRUCTIONS = [
    "You answer analytical questions about Zava, a direct-to-consumer athletic apparel brand. "
    "The product family is ZavaCore Field, sold in four lines: Core (C), Pro (R), Premium (P), Elite (E).",
    "Revenue always comes from sales.revenue, which is already net of discount. Never recompute it "
    "as quantity * unit_price.",
    "Units sold come from sales.quantity; stock on hand comes from inventory.on_hand. Never mix them.",
    "Facilities are identified by code: FC-MEM Memphis, FC-CLT Charlotte, FC-SEA Seattle, FC-DFW Dallas, "
    "FC-EWR Newark, FC-RNO Reno, FC-CMH Columbus. Users say city names, so translate before filtering.",
    "inventory.status is exactly one of 'in stock', 'low stock', 'critical' - spaces, not underscores.",
    "For time analysis join sales.sale_date or orders.order_date to dim_date.date.",
    "sales.store_code is NULL for online sales, so exclude NULLs when comparing stores.",
]

SPACE_TITLE = os.getenv("DATABRICKS_GENIE_SPACE_NAME", "Zava Analytics")
body = {
    "title": SPACE_TITLE,
    "description": "Analytics over Zava retail apparel sales, inventory and orders.",
    "warehouse_id": WAREHOUSE_ID,
    "serialized_space": json.dumps({
        "version": 2,
        "data_sources": {"tables": [{"identifier": t} for t in TABLES]},
        "instructions": {"text_instructions": [{"content": INSTRUCTIONS}]},
    }),
}

existing = next((s for s in api("GET", "/api/2.0/genie/spaces").json().get("spaces", [])
                 if s.get("title") == SPACE_TITLE), None)
if existing:
    SPACE_ID = existing["space_id"]
    print("PATCH ->", api("PATCH", f"/api/2.0/genie/spaces/{SPACE_ID}", data=json.dumps(body)).status_code)
else:
    r = api("POST", "/api/2.0/genie/spaces", data=json.dumps(body))
    r.raise_for_status()
    SPACE_ID = r.json()["space_id"]
    print("criado")

print("space id :", SPACE_ID)
print("MCP url  :", f"https://{HOST}/api/2.0/mcp/genie/{SPACE_ID}")
""")

md(r"""
## 4️⃣ The identity — where this demo actually goes wrong

This is the part worth reading slowly, because both mistakes below produce **HTTP 403 and never
401**. A 401 would mean the token was rejected; a **403 means the token was accepted** but the
principal is unknown to the workspace or is missing a grant.

**Trap 1 — the project's identity, not the account's.** A Foundry connection created with
`--auth-type project-managed-identity` presents the managed identity of the *project*
(`<account>/projects/<project>`). That is a different principal from the Foundry **account's** own
managed identity, which is what `az cognitiveservices account show` returns.

**Trap 2 — application id, not object id.** ARM gives you `identity.principalId`, which is an
**object id**. Databricks SCIM wants the **application (client) id**.

The grants that matter: `USE CATALOG`, `USE SCHEMA`, `SELECT`, `EXECUTE`, `CAN_USE` on the
warehouse, `CAN_RUN` on the Genie space. Forgetting `SELECT` is especially sneaky — Genie answers
politely that it lacks permission, so it reads like a model problem rather than a grants problem.
""")

code(r"""
SUB = os.environ["AZURE_SUBSCRIPTION_ID"]
RG = os.environ["AZURE_RESOURCE_GROUP"]
ACCOUNT = os.environ["AZURE_AI_ACCOUNT_ENDPOINT"].split("//")[1].split(".")[0]
PROJECT = os.getenv("AZURE_AI_PROJECT_NAME", "zava-project")

def az(*args):
    return subprocess.run(["az", *args], capture_output=True, text=True, shell=True).stdout.strip()

# The PROJECT identity — note the /projects/ segment. This is not the account identity.
principal_id = az("resource", "show", "--ids",
                  f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.CognitiveServices"
                  f"/accounts/{ACCOUNT}/projects/{PROJECT}",
                  "--query", "identity.principalId", "-o", "tsv")
# principalId is the OBJECT id; Databricks SCIM needs the APPLICATION id.
app_id = az("ad", "sp", "show", "--id", principal_id, "--query", "appId", "-o", "tsv")

print("project principalId (object id):", principal_id)
print("project applicationId  (usar!) :", app_id)
""")

code(r"""
# Register the identity as a workspace service principal, then grant it.
found = api("GET", f'/api/2.0/preview/scim/v2/ServicePrincipals?filter=applicationId eq "{app_id}"').json()
if not (found.get("Resources") or []):
    api("POST", "/api/2.0/preview/scim/v2/ServicePrincipals", data=json.dumps({
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServicePrincipal"],
        "applicationId": app_id,
        "displayName": f"{PROJECT} (Foundry project managed identity)",
        "entitlements": [{"value": "workspace-access"}, {"value": "databricks-sql-access"}],
        "active": True,
    }))
    print("service principal criado")
else:
    print("service principal ja existe")

for securable, name, privs in [
    ("catalog", CATALOG, ["USE CATALOG"]),
    ("schema", f"{CATALOG}.{SCHEMA}", ["USE SCHEMA", "SELECT", "EXECUTE"]),   # SELECT e o mais esquecido
]:
    r = api("PATCH", f"/api/2.1/unity-catalog/permissions/{securable}/{name}",
            data=json.dumps({"changes": [{"principal": app_id, "add": privs}]}))
    print(f"  {','.join(privs):28s} on {name:28s} -> {r.status_code}")

for path, level in [(f"/api/2.0/permissions/warehouses/{WAREHOUSE_ID}", "CAN_USE"),
                    (f"/api/2.0/permissions/genie/{SPACE_ID}", "CAN_RUN")]:
    r = api("PATCH", path, data=json.dumps({"access_control_list": [
        {"service_principal_name": app_id, "permission_level": level}]}))
    print(f"  {level:28s} on {path.split('/')[-2]:28s} -> {r.status_code}")
""")

md(r"""
## 5️⃣ The Foundry connection

`RemoteTool` is the same connection kind the Zava toolbox and knowledge base use. The only
Databricks-specific part is the **audience**: `2ff814a6-3304-4ab8-85cb-cd0e6f879c1d`, the fixed
application id of the Azure Databricks service. That is what makes an Entra token acceptable to
Databricks and removes the need for a personal access token.

```powershell
azd ai connection create databricks-genie-mcp `
  --kind remote-tool `
  --target "https://<workspace>/api/2.0/mcp/genie/<space_id>" `
  --auth-type project-managed-identity `
  --audience "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"
```

Compare with the Fabric connection from notebook 01: kind `CustomKeys`, an empty target, and a
magic `metadata.type = "fabric_dataagent_preview"` that the tool looks for. The MCP one is a plain
URL plus an identity.
""")

code(r"""
CONN = os.getenv("DATABRICKS_GENIE_CONNECTION_NAME", "databricks-genie-mcp")
MCP_URL = f"https://{HOST}/api/2.0/mcp/genie/{SPACE_ID}"

out = subprocess.run(["azd", "ai", "connection", "create", CONN,
                      "--kind", "remote-tool", "--target", MCP_URL,
                      "--auth-type", "project-managed-identity",
                      "--audience", DBX_RESOURCE, "--force"],
                     capture_output=True, text=True, shell=True, cwd=str(REPO))
print(out.stdout.strip() or out.stderr.strip())
""")

md(r"""
## 6️⃣ The agent

One `MCPTool`. That is the entire Databricks-specific surface area on the Foundry side — compare
with the `MicrosoftFabricPreviewTool` + `FabricDataAgentToolParameters` + `project_connections`
construction that notebook 01 needed.

The instructions carry one rule that is not obvious and that you will hit: **Genie is
asynchronous.** `query_space_*` usually returns before the answer exists, and the caller must poll
`poll_response_*`. Without an explicit instruction the model tends to reply *"this may take a
moment"* — and since the user only ever sees the final message, that reads as a failure.
""")

code(r'''
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential

AGENT_NAME = os.getenv("DATABRICKS_AGENT_NAME", "InventoryAgentDatabricks")
MODEL = os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1")

project = AIProjectClient(
    endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(exclude_interactive_browser_credential=True, process_timeout=30),
)

INSTRUCTIONS = """You are the Zava analytics assistant backed by Azure Databricks.

Your tools come from a Databricks Genie space over the Zava tables in Unity Catalog.

Genie is asynchronous, and this is the rule you must not break:
- `query_space_*` starts the question and often comes back before the answer is ready.
- When it does, call `poll_response_*` with the conversation_id and message_id it gave you,
  and keep polling until you have the rows.
- NEVER reply with "this may take a moment" or any other waiting message. The user only sees
  your final answer, so a waiting message reads as a failure. Poll instead.
- A cold serverless warehouse can add ~30 seconds to the first question. Absorb that by polling.

Always call the Genie tool for numbers; never estimate and never invent a SKU or facility.
Pass the user's question through largely as-is - Genie has its own schema instructions.
You only have analytics: for policy or how-to questions, say so and point at the InventoryAgent."""

version = project.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(
        model=MODEL,
        instructions=INSTRUCTIONS,
        tools=[MCPTool(server_label="databricks_genie", server_url=MCP_URL,
                       require_approval="never", project_connection_id=CONN)],
    ),
)
print(f"{version.name} v{getattr(version, 'version', '?')}  ->  {MCP_URL}")
''')

md(r"""
## 7️⃣ Ask it the same questions as notebook 01

Watch the tool traffic: `query_space_*` then, when needed, `poll_response_*`. The numbers should
match the Fabric answers exactly, because the tables are identical.
""")

code(r"""
oai = project.get_openai_client()

def ask(question: str):
    print("\n" + "=" * 76)
    print("Q:", question)
    resp = oai.responses.create(
        input=question,
        extra_body={"agent_reference": {"type": "agent_reference", "name": AGENT_NAME}})
    for item in resp.output:
        kind = getattr(item, "type", "")
        if kind == "mcp_list_tools":
            names = [t.get("name") if isinstance(t, dict) else getattr(t, "name", "?")
                     for t in (getattr(item, "tools", None) or [])]
            print("   [tools]", ", ".join(names))
        elif kind == "mcp_call":
            print(f"   [call ] {getattr(item, 'name', '?')}  {str(getattr(item, 'arguments', ''))[:120]}")
    print("\n  ", resp.output_text.strip()[:700])

ask("What is total revenue by product line?")
ask("How many units of ZCPTM-SS-S-B0 do we have across facilities?")
ask("Which SKUs are critical at FC-CLT?")
""")

code(r"""
# Out of scope on purpose: this agent has analytics and nothing else.
ask("What's our return policy for worn apparel?")
""")

md(r"""
## 8️⃣ The axis Fabric does not have — governance you can demo live

Unity Catalog enforces grants **per principal**. The agent's reach is not a property of the agent:
it is a property of what the Foundry identity was granted. Revoke `SELECT` and the same agent, same
prompt, same model, stops being able to answer — then grant it back.

This is the most convincing 60 seconds in the whole Databricks story, and it has no Fabric
equivalent in this demo.
""")

code(r"""
def select_grant(action: str):
    r = api("PATCH", f"/api/2.1/unity-catalog/permissions/schema/{CATALOG}.{SCHEMA}",
            data=json.dumps({"changes": [{"principal": app_id, action: ["SELECT"]}]}))
    print(f"{action.upper()} SELECT -> {r.status_code}")

select_grant("remove")
ask("How many units of ZCPTM-SS-S-B0 do we have across facilities?")
""")

code(r"""
select_grant("add")
ask("How many units of ZCPTM-SS-S-B0 do we have across facilities?")
""")

md(r"""
## 🔄 Recap

You built the same analytics capability twice, on two platforms, and the difference was entirely in
the wiring:

| | Fabric (notebook 01) | Databricks (this notebook) |
|---|---|---|
| Engine | Fabric Data Agent over a Direct Lake semantic model | Genie space over Unity Catalog |
| Foundry tool | `MicrosoftFabricPreviewTool` — first-party | `MCPTool` — **no first-party tool exists** |
| Connection | `CustomKeys` + `metadata.type` magic | `RemoteTool` + a URL |
| Credential | project managed identity | project managed identity, **no PAT** |
| Extra tooling to build it | `fabric-data-agent-sdk` on Python 3.10–3.12 | none |
| Governance | model-level | Unity Catalog grants, demoable live |

The headline is not that one platform wins. It is that **MCP made the platform without a
first-party tool the easier of the two to integrate** — and that the same agent shape (`MCPTool` +
a `RemoteTool` connection + a managed identity) is how you would reach *any* third-party system.

Things worth trying next:

- put the Genie MCP tool **inside the Zava toolbox** next to `zava_tools` and `zava_kb`, which the
  Fabric tool cannot do,
- give the InventoryAgent **both** engines and let the instructions route between them,
- add the `/api/2.0/mcp/functions/...` server so governed **Unity Catalog functions** become tools —
  the deterministic counterpart to Genie's natural-language-to-SQL,
- run the notebook 01 evaluation suite against this agent to compare answer quality head to head.
""")

nb["cells"] = cells
nb.metadata = {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
               "language_info": {"name": "python"}}
with open(OUT, "w", encoding="utf-8") as f:
    nbf.write(nb, f)
print(f"Wrote {OUT} with {len(cells)} cells")
