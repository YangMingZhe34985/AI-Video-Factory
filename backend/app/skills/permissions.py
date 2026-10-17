"""Caller roles and permission levels for skill-layer tools."""

# Caller roles include v1 and v2 agents; "system" is an operator calling
# through the REST API. The API validates ownership for every caller role.
DIRECTOR = "director"
CREATIVE = "creative"
PRODUCTION = "production"
SYSTEM = "system"
INTAKE = "intake"
RESEARCH = "research"
ROLES = (DIRECTOR, CREATIVE, PRODUCTION, SYSTEM, INTAKE, RESEARCH)

# Permission levels, from least to most sensitive.
READ = "read"          # pure query, not recorded in the ledger
WRITE = "write"        # local side effects only (e.g. packaging), free
LLM = "llm"            # runs billed text / vision LLM calls
GENERATE = "generate"  # submits billed image / video generation

LEDGER_PERMISSIONS = frozenset({WRITE, LLM, GENERATE})
