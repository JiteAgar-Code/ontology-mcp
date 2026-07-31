# Login Query Agent — Ontology MCP & Knowledge Graph

A production-ready POC that uses an **OWL/SHACL/SKOS Knowledge Graph** + **MCP Semantic Descriptor Service**
to route login-diagnosis queries across SQL Server and MongoDB, with conditional New Relic escalation.

---

## Architecture at a Glance

```
User prompt (VS Code Copilot)
        │
        ▼
  ontology-mcp  ──► Fuseki KG (local)  ──► SPARQL query
        │
        ▼
  JSON-LD descriptor
  (WHERE to query, WHAT to validate, HOW to route)
        │
        ▼
  Agent executes queries
  ├── SQL Server  (UM_Users, Um_Userpartnermapping, um_usermobileverificationstatus)
  ├── MongoDB     (users collection)
  └── New Relic   (only if all SHACL shapes pass)
```

---

## Services Overview

| Service | Type | Who starts it | Required for |
|---|---|---|---|
| Apache Jena Fuseki | Local process | **You (manual)** | MCP to work |
| MCP Server (`ontology-mcp`) | stdio child process | VS Code auto-spawns | Agent tool calls |
| SQL Server | Remote server | Already running | Data queries (Layer 7+) |
| MongoDB | Remote server | Already running | Data queries (Layer 7+) |
| New Relic | Cloud service | Always available | Escalation (Layer 7+) |

> Only **Fuseki** requires a manual start. Everything else is either auto-spawned or remote.

---

## Prerequisites

### 1. Java 11+
Required to run the Fuseki JAR.

```powershell
java -version
# Expected: openjdk version "11.x.x" or higher
```

### 2. Apache Jena Fuseki JAR (not committed — download manually)

The JAR is excluded from git due to its size (54 MB).

1. Download `apache-jena-fuseki-X.Y.Z.zip` from [https://jena.apache.org/download/](https://jena.apache.org/download/)
2. Extract `fuseki-server.jar` and place it at:
   ```
   infra/fuseki/fuseki-server.jar
   ```

### 3. Python (3.12+)

```powershell
python --version
# Expected: Python 3.12.x or higher
```

### 4. Python dependencies

```powershell
cd c:\Ontology
python -m pip install -r requirements.txt
```

### 5. VS Code Copilot (MCP support)
- VS Code **1.99 or later**
- GitHub Copilot extension installed and signed in
- Global MCP config at `C:\Users\<you>\AppData\Roaming\Code\User\mcp.json` (see below)

---

## Step-by-Step Local Startup

### Step 1 — Start Fuseki (Knowledge Graph)

Open a terminal and run:

```powershell
cd c:\Ontology
java -jar infra\fuseki\fuseki-server.jar --config infra\fuseki\config\login-kg.ttl
```

**Keep this terminal open** — Fuseki runs as a foreground process.

Verify it is running:
```powershell
# Open a second terminal and run:
python -c "import requests; r = requests.get('http://localhost:3030/$/ping'); print('Fuseki UP:', r.status_code)"
# Expected: Fuseki UP: 200
```

Fuseki UI: [http://localhost:3030](http://localhost:3030)

---

### Step 2 — Load the Knowledge Graph

> Required every time Fuseki starts fresh (first time, or after a restart where data was lost).
> Skip if Fuseki already has data from a previous session.

Open a **second terminal**:

```powershell
cd c:\Ontology
$env:PYTHONIOENCODING = "utf-8"

# Load all 7 named graphs into Fuseki
python scripts/kg/load_kg.py --schema login --version 1.0.0

# Promote v1.0.0 as the active version
python scripts/kg/promote.py --schema login --version 1.0.0
```

Expected output ends with:
```
✅ Promoted successfully. login current = v1.0.0
```

**Verify the KG is loaded:**
```powershell
python -c "
import requests, json
r = requests.post('http://localhost:3030/login-kg/sparql',
    data={'query': 'SELECT (COUNT(*) AS ?n) WHERE { GRAPH <urn:kg:login:v1.0.0:ontology> { ?s ?p ?o } }'},
    headers={'Accept': 'application/sparql-results+json'})
print('Triples in ontology graph:', r.json()['results']['bindings'][0]['n']['value'])
"
# Expected: Triples in ontology graph: 949
```

---

### Step 3 — VS Code MCP Registration (one-time setup)

This only needs to be done **once**. If already configured, skip.

Create or update the global MCP config file:

**`C:\Users\<your-username>\AppData\Roaming\Code\User\mcp.json`**

```json
{
  "servers": {
    "ontology-mcp": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "c:\\Ontology",
      "env": {
        "PYTHONPATH": "c:\\Ontology\\src",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

Then reload VS Code (`Ctrl+Shift+P` → `Developer: Reload Window`).

> The MCP server is **not started manually**. VS Code spawns it automatically as a child process
> when Copilot Agent mode makes a tool call.

---

### Step 4 — Use in VS Code Copilot

1. Open Copilot Chat (`Ctrl+Alt+I`)
2. Switch to **Agent mode** (dropdown next to send button → Agent)
3. Ask a login-related question:

```
Why can't a user login? Use the ontology-mcp to get the diagnostic descriptor.
```

or more specifically:

```
The user leosmab.admin cannot login.
First call resolve_intent with prompt "user cannot login" to get the descriptor,
then show me which tables to query and what to check.
```

> **Tip:** Pass the intent signal separately from the username.
> The MCP matches on pattern keywords (`login issue`, `user cannot login`, etc.),
> not on the actual username value.

---

## MCP Tools Reference

| Tool | Input | Returns |
|---|---|---|
| `resolve_intent` | `prompt` (string), `schema` (default: `login`) | JSON-LD descriptor — entities, shapes, rules |
| `get_entity_descriptor` | `class_name` (e.g. `User`), `schema` | Full column/field mapping for one entity |
| `list_intents` | `schema` | All supported intent patterns |

### Valid class names for `get_entity_descriptor`
- `User` → SQL Server `UM_Users`
- `PartnerMapping` → SQL Server `Um_Userpartnermapping`
- `MobileVerificationStatus` → SQL Server `um_usermobileverificationstatus`
- `UserDocument` → MongoDB `users`

### Supported intent patterns (login schema)
```
"can't login"
"login failure"
"login issue"
"login not working"
"login problem"
"unable to login"
"user cannot login"
"user login failed"
"why can't {username} login"
```

---

## Troubleshooting

### MCP returns `sparql_failed`
Fuseki is not running. Go back to **Step 1** and start it.

### MCP returns `no_intent_match`
The prompt doesn't contain any of the known patterns. Call `list_intents` first,
then rephrase using one of the listed patterns.

### MCP returns `schema_not_found`
The schema name is wrong. Currently only `login` is registered in `ontology/schemas/registry.yaml`.

### Fuseki starts but KG graphs are empty
Run **Step 2** (load + promote). This happens after every fresh Fuseki start since
the TDB2 data directory (`infra/fuseki/data/`) was not persisted from a previous session.

### `UnicodeEncodeError` on Windows
Add `$env:PYTHONIOENCODING = "utf-8"` before running any Python script in PowerShell.

---

## Project Structure

```
c:\Ontology\
├── src/
│   └── mcp_server/                      # MCP server package (PYTHONPATH=src)
│       ├── server.py                    # MCP stdio entrypoint
│       ├── kg/sparql_client.py          # Fuseki SPARQL client
│       ├── registry/schema_registry.py  # reads registry.yaml
│       └── tools/
│           ├── resolve_intent.py
│           ├── get_descriptor.py
│           └── list_intents.py
│
├── ontology/
│   ├── schemas/
│   │   ├── registry.yaml                # schema manifest
│   │   └── login/v1.0.0/login.yaml      # LinkML source of truth
│   └── sparql/
│       ├── resolve_intent.sparql
│       ├── get_entity_descriptor.sparql
│       ├── list_intents.sparql
│       └── get_decision_rules.sparql
│
├── artifacts/login/v1.0.0/
│   ├── owl/login.owl.ttl                # OWL 2 DL (949 triples)
│   ├── shacl/login.shacl.ttl           # SHACL shapes (332 triples)
│   ├── skos/login.skos.ttl             # SKOS concept scheme (129 triples)
│   ├── rules/login.rules.ttl           # Decision rules (58 triples)
│   ├── descriptors/login.descriptors.json
│   └── jsonld/login.context.jsonld
│
├── scripts/
│   ├── generate/                        # artifact generation pipeline
│   └── kg/
│       ├── load_kg.py                   # load named graphs into Fuseki
│       └── promote.py                   # promote a version as current
│
├── infra/
│   └── fuseki/
│       ├── fuseki-server.jar            # Apache Jena Fuseki 6.1.0
│       ├── config/login-kg.ttl          # dataset config (TDB2)
│       └── data/                        # TDB2 persistent storage (gitignored)
│
├── config/settings.yaml                 # non-secret runtime config
├── .env.example                         # secrets template — copy to .env
├── .env                                 # local secrets — never committed
├── requirements.txt
└── README.md                            # this file
```

---

## Daily Workflow

```
Every session:
  1. Start Fuseki          →  java -jar infra\fuseki\fuseki-server.jar --config infra\fuseki\config\login-kg.ttl
  2. Load KG (if needed)   →  python scripts/kg/load_kg.py --schema login --version 1.0.0
  3. Promote (if needed)   →  python scripts/kg/promote.py --schema login --version 1.0.0
  4. Open VS Code          →  Copilot Agent mode picks up ontology-mcp automatically

One-time setup:
  - pip install -r requirements.txt
  - Configure C:\Users\<you>\AppData\Roaming\Code\User\mcp.json  (PYTHONPATH: c:\\Ontology\\src)
  - Reload VS Code window
```
