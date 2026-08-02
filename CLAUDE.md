# Login Query Agent — Claude Code Instructions

## Mandatory Tool Call Sequence

Intent classification is LLM-native — **you classify the category yourself, with no
tool call.** Then every login diagnostic request MUST follow this exact sequence.
**Never call a data-mcp tool without first getting a diagnosis plan.**

```
Step 0  (you)        → classify the complaint into a category (no tool call)
Step 0  ontology-mcp → get_diagnosis_plan(category)          ← returns capability_id
Step 1a data-mcp     → query_sql_user(username, capability_id)
Step 1b data-mcp     → query_sql_mobile_verification(username, capability_id)
Step 1c data-mcp     → query_sql_partner_mappings(username, capability_id)
Step 1d data-mcp     → query_mongo_user(username, capability_id)
Step 2  data-mcp     → validate_login_shapes(username, capability_id, validation_sequence)
Step 3a/3b           → the plan's newrelic_tool ONLY if all_shapes_pass=true AND newrelic_tool != null
```

Categories: `login_failure`, `password_reset`, `otp_email`, `sms_otp`,
`account_state`, `account_locked`, `partner_mapping`, `data_sync`.

Pass the `capability_id` from Step 0 into every data-mcp call.
Pass the `validation_sequence` from the plan into `validate_login_shapes`.
Call `get_diagnosis_plan` exactly once. `resolve_intent` no longer exists.
Only fetch the entities the plan lists in `required_entities`.

## Secrets

`.env` must NEVER be committed to git.
API keys and connection strings live in `.env` only.

## Starting the Stack

```powershell
# 1. Start Fuseki
java -jar infra\fuseki\fuseki-server.jar --config infra\fuseki\config\login-kg.ttl

# 2. After any YAML schema change: regenerate + reload
$env:PYTHONIOENCODING = "utf-8"
python scripts/generate/generate.py --schema login --version 1.0.0
python scripts/kg/load_kg.py --schema login --version 1.0.0
python scripts/kg/promote.py --schema login --version 1.0.0
```

## Tool Descriptions

All MCP tool descriptions live in `config/tool_descriptions.yaml`.
Never write description strings inline in `server.py` or `diagnostic_server.py`.
Edit the YAML file and restart the MCP servers to pick up changes.
