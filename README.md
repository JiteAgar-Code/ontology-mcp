# Login Query Agent — Ontology MCP & Knowledge Graph

A production-ready POC that uses an **OWL/SHACL/SKOS Knowledge Graph** + **two MCP servers**
to route login-diagnosis queries across SQL Server and MongoDB, with conditional New Relic escalation.

---

## Architecture at a Glance

```
User prompt (VS Code Copilot)
        │
        ▼
  ontology-mcp  ──► Fuseki KG (Fuseki SPARQL)
        │              returns: intent_id, entities,
        │              validation_sequence, decision_rules
        ▼
  data-mcp  ──► SQL Server  (UM_Users, UM_UserPartnermapping,
        │                    UM_UserMobileNumberVerified)
        ├──────► MongoDB     (users collection — 9 projected fields)
        ├──────► SHACL Validator  (7 shapes evaluated in order)
        └──────► New Relic   (only when all shapes pass — 2-step NRQL)
```

---

## Services Overview

| Service | Type | Who starts it | Required for |
|---|---|---|---|
| Apache Jena Fuseki | Local process | **You (manual)** | ontology-mcp to work |
| `ontology-mcp` | stdio child process | VS Code auto-spawns | KG / intent resolution |
| `data-mcp` | stdio child process | VS Code auto-spawns | DB queries + validation |
| SQL Server | Remote/LocalDB | Already running | Data queries |
| MongoDB | Remote server | Already running | Data queries |
| New Relic | Cloud service | Always available | Escalation (all shapes pass) |

> Only **Fuseki** requires a manual start. Both MCP servers are auto-spawned by VS Code.

---

## Prerequisites

### 1. Java 11+
```powershell
java -version
```

### 2. Apache Jena Fuseki JAR
The JAR is excluded from git (54 MB). Download from [jena.apache.org](https://jena.apache.org/download/) and place at:
```
infra/fuseki/fuseki-server.jar
```

### 3. Python 3.12+
```powershell
python --version
```

### 4. Python dependencies
```powershell
cd c:\Ontology
python -m pip install -r requirements.txt
```

### 5. ODBC Driver for SQL Server
Download **ODBC Driver 17 or 18 for SQL Server** from Microsoft if not already installed.

### 6. VS Code with GitHub Copilot (Agent mode)
VS Code 1.99+ with the GitHub Copilot extension.

---

## Step-by-Step Local Startup

### Step 1 — Start Fuseki
```powershell
cd c:\Ontology
java -jar infra\fuseki\fuseki-server.jar --config infra\fuseki\config\login-kg.ttl
```
Keep this terminal open. Verify at [http://localhost:3030](http://localhost:3030).

### Step 2 — Load the Knowledge Graph
> Required on first run or after any schema/artifact change.

```powershell
$env:PYTHONIOENCODING = "utf-8"
python scripts/kg/load_kg.py  --schema login --version 1.0.0
python scripts/kg/promote.py  --schema login --version 1.0.0
```

### Step 3 — Configure secrets
Copy `.env.example` to `.env` and fill in your values:
```
SQL_SERVER_HOST=your-server
SQL_SERVER_DATABASE=your-database
SQL_SERVER_TRUSTED_CONNECTION=yes
SQL_SERVER_ENCRYPT=yes
SQL_SERVER_TRUST_CERT=yes

MONGODB_URI=mongodb://your-host:27017
MONGODB_DATABASE=your-database

NEW_RELIC_API_KEY=NRAK-xxxxxxxxxxxxxxxxxxxx
NEW_RELIC_ACCOUNT_ID=your-account-id
NEW_RELIC_REGION=US

APP_ENV=prod
```

### Step 4 — Register both MCP servers
Create `.vscode/mcp.json` in the workspace root:

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
    },
    "data-mcp": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp_server.diagnostic_server"],
      "cwd": "c:\\Ontology",
      "env": {
        "PYTHONPATH": "c:\\Ontology\\src",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

Reload VS Code (`Ctrl+Shift+P` → `Developer: Reload Window`).

---

## Full Diagnostic Flow (8 Tool Calls)

```
User: "testgdpr1235@gep.com can't reset password"
        │
        ▼
① ontology-mcp / resolve_intent(prompt)
     Fuseki SPARQL → KG returns intent_id, validation_sequence, decision_rules
        │
        ▼  (agent extracts username; asks user if missing)
        │
② data-mcp / query_sql_user(username)
     SELECT from UM_Users → islocked, isactive, isdeleted, usertype, ...
        │
③ data-mcp / query_sql_mobile_verification(username)
     SELECT from UM_UserMobileNumberVerified → ismobilenumberverified
        │
④ data-mcp / query_sql_partner_mappings(username)
     SELECT from UM_UserPartnermapping → bpc, partnercode, isactive, contactcode
        │
⑤ data-mcp / query_mongo_user(username)
     db.users.find_one({...}, { 9 diagnostic fields }) → MongoDB document
        │
⑥ data-mcp / validate_login_shapes(username, validation_sequence)
     7 SHACL shapes evaluated in order → PASS/FAIL per shape
        │
   ┌────┴──────────────────┐
violations              all pass
   │                       │
report dr_003..dr_008   ⑦a data-mcp / query_newrelic_login_mfa(username)
(from KG rules)            OR
                        ⑦b data-mcp / query_newrelic_reset_password(username, email)
                            → Transaction → Log per traceId (max 7 days)
```

---

## MCP Tools Reference

### ontology-mcp — Knowledge Graph tools

| Tool | Input | Returns |
|---|---|---|
| `resolve_intent` | `prompt`, `schema` | intent_id, entities, validation_sequence, decision_rules |
| `get_entity_descriptor` | `class_name`, `schema` | Full column/field mapping for one entity |
| `list_intents` | `schema` | All supported intent patterns |

### data-mcp — Data & diagnostic tools

| Tool | Step | Source | Returns |
|---|---|---|---|
| `query_sql_user` | 1a | `UM_Users` | Full user row + SQL executed |
| `query_sql_mobile_verification` | 1b | `UM_UserMobileNumberVerified` | ismobilenumberverified + SQL |
| `query_sql_partner_mappings` | 1c | `UM_UserPartnermapping` | All mapping rows + active count |
| `query_mongo_user` | 1d | `users` collection | 9 projected fields + query |
| `validate_login_shapes` | 2 | SQL + MongoDB | Per-shape PASS/FAIL + next_step |
| `query_newrelic_login_mfa` | 3a | New Relic | Transaction + Log for `/Account/Login` |
| `query_newrelic_reset_password` | 3b | New Relic | Transaction + Log for 3 reset URIs |

### Supported intents

| Intent ID | Matches |
|---|---|
| `intent_diagnose_login_failure` | "can't login", "login not working", "login failed" |
| `intent_diagnose_sms_otp` | "not receiving OTP", "SMS OTP not received" |
| `intent_diagnose_otp_email` | "OTP email not received", "email OTP not coming" |
| `intent_diagnose_reset_password_link` | "can't reset password", "reset link not received" |
| `intent_diagnose_account_locked` | "account locked", "locked after multiple attempts" |
| `intent_diagnose_mobile_otp` | "mobile OTP issue", "OTP on mobile not received" |

### SHACL Shapes (evaluated in order)

| Shape | Condition | Rule |
|---|---|---|
| `LoginBlockShape` | isLocked=1 OR isActive=0 OR isDeleted=1 | dr_003 |
| `SystemUserShape` | isSystemUser=1 | dr_005 |
| `BuyerSSOShape` | userType=Buyer AND authenticationType=SSO | dr_006 |
| `PartnerMappingShape` | No active partner mapping | dr_004 |
| `SupplierPartnerMappingShape` | Supplier with no valid BPC | dr_007 |
| `MobileConsistencyShape` | SQL vs MongoDB isMobileNumberVerified mismatch | dr_002 |
| `PartnerMappingDataSyncShape` | SQL vs MongoDB partner mapping fields mismatch | dr_008 |

### New Relic Query Structure (2-step)

```
Step 1: Transaction table (max 7 days ago)
  /Account/Login          → LoginUserName, traceId, RequiresTwoFactor, TwoFactorDetails
  /Account/RecoverPassword → traceId, errorMessage, RecoveryUserName, RecoveryEmail
  /Account/PreResetPassword → traceId, errorMessage, PreResetUserName
  /Account/ResetPassword  → LoginUserName, traceId, errorMessage

Step 2: Log table (per traceId from Step 1)
  SELECT * FROM Log WHERE trace.id = '{traceId}' SINCE {transaction_timestamp}
```

---

## Artifact Regeneration

When any YAML schema file changes:
```powershell
$env:PYTHONIOENCODING = "utf-8"
python scripts/generate/generate.py --schema login --version 1.0.0
python scripts/kg/load_kg.py       --schema login --version 1.0.0
python scripts/kg/promote.py       --schema login --version 1.0.0
```

---

## Project Structure

```
c:\Ontology\
├── src/
│   └── mcp_server/                        # PYTHONPATH=c:\Ontology\src
│       ├── server.py                      # ontology-mcp entrypoint (KG tools)
│       ├── diagnostic_server.py           # data-mcp entrypoint (DB/NR tools)
│       ├── connectors/
│       │   ├── sql_connector.py           # pyodbc — UM_Users, UM_UserPartnermapping, ...
│       │   ├── mongo_connector.py         # pymongo — users collection (projected)
│       │   └── newrelic_connector.py      # NerdGraph GraphQL — 2-step NRQL
│       ├── diagnostics/
│       │   ├── data_fetcher.py            # orchestrates SQL + MongoDB fetch
│       │   ├── shacl_validator.py         # programmatic 7-shape evaluation
│       │   └── rule_engine.py             # maps violations → rules, dispatches NR
│       ├── tools/
│       │   ├── resolve_intent.py          # KG tool handler
│       │   ├── get_descriptor.py          # KG tool handler
│       │   ├── list_intents.py            # KG tool handler
│       │   ├── fetch_user_data.py         # DB tool handlers (4 SQL/Mongo queries)
│       │   ├── validate_shapes.py         # shape validation handler
│       │   ├── query_newrelic.py          # New Relic tool handlers
│       │   └── diagnose_login.py          # combined flow (legacy)
│       ├── kg/sparql_client.py
│       └── registry/schema_registry.py
│
├── ontology/
│   ├── schemas/
│   │   ├── registry.yaml
│   │   └── login/v1.0.0/
│   │       ├── login.yaml                 # root: imports + intents + rules + shapes
│   │       ├── shared/types.yaml
│   │       ├── shared/enums.yaml          # AuthenticationTypeEnum, UserTypeEnum
│   │       ├── shared/subsets.yaml
│   │       └── entities/
│   │           ├── abstract_user.yaml
│   │           ├── user.yaml              # SQL UM_Users
│   │           ├── partner_mapping.yaml   # SQL UM_UserPartnermapping
│   │           ├── mobile_verification.yaml # SQL UM_UserMobileNumberVerified
│   │           └── user_document.yaml     # MongoDB users (+ IsdCode, MongoPartnerMapping)
│   └── sparql/
│       ├── resolve_intent.sparql
│       ├── get_entity_descriptor.sparql
│       ├── list_intents.sparql
│       └── get_decision_rules.sparql
│
├── artifacts/login/v1.0.0/
│   ├── owl/login.owl.ttl
│   ├── shacl/login.shacl.ttl
│   ├── skos/login.skos.ttl
│   ├── rules/login.rules.ttl
│   ├── descriptors/login.descriptors.json
│   └── jsonld/login.context.jsonld + login.agent_template.json
│
├── scripts/
│   ├── generate/generate.py + gen_*.py + _yaml_loader.py
│   └── kg/load_kg.py + promote.py
│
├── infra/fuseki/
│   ├── fuseki-server.jar                  # not committed — download separately
│   ├── config/login-kg.ttl
│   └── data/                              # TDB2 storage — gitignored
│
├── .vscode/mcp.json                       # MCP server registration (2 servers)
├── config/settings.yaml
├── .env / .env.example
├── requirements.txt
└── README.md
```

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `sparql_failed` | Fuseki not running | Start Fuseki (Step 1) |
| `no_intent_match` | Prompt not matching any pattern | Call `list_intents` first, rephrase |
| `SQL Server connection error` | Wrong host/credentials in `.env` | Check `SQL_SERVER_HOST`, `TRUSTED_CONNECTION` |
| `No module named 'pyodbc'` | Missing dependency | `pip install pyodbc` |
| `UnicodeEncodeError` | Windows console encoding | Add `$env:PYTHONIOENCODING = "utf-8"` |
| Fuseki graphs empty | Fresh Fuseki start | Run load_kg.py + promote.py |

---

## Daily Workflow

```powershell
# 1. Start Fuseki
java -jar infra\fuseki\fuseki-server.jar --config infra\fuseki\config\login-kg.ttl

# 2. Load KG (only after schema or artifact changes)
$env:PYTHONIOENCODING = "utf-8"
python scripts/kg/load_kg.py --schema login --version 1.0.0
python scripts/kg/promote.py --schema login --version 1.0.0

# 3. Open VS Code — both MCP servers start automatically
```

## Extending the Schema

### Add a new entity (new SQL table or MongoDB collection)
1. Create `ontology/schemas/login/v1.0.0/entities/new_entity.yaml`
2. Add `- entities/new_entity` to `login.yaml` imports
3. Run generate + load + promote

### Add a new schema version
1. Copy `ontology/schemas/login/v1.0.0/` → `v1.1.0/`
2. Edit entity files in `v1.1.0/`
3. Run generate + load + promote for `v1.1.0`

Both versions coexist in the KG — rollback is always available.
