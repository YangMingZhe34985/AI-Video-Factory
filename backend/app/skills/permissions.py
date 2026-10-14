"""Caller roles and permission levels for skill-layer tools."""

# Caller roles. The three agent roles come from the refactor plan; "system"
# is a human operator calling through the REST API.
DIRECTOR = "director"
CREATIVE = "creative"
PRODUCTION = "production"
SYSTEM = "system"
ROLES = (DIRECTOR, CREATIVE, PRODUCTION, SYSTEM)

# Permission levels, from least to most sensitive.
READ = "read"          # pure query, not recorded in the ledger
WRITE = "write"        # local side effects only (e.g. packaging), free
LLM = "llm"            # runs billed text / vision LLM calls
GENERATE = "generate"  # submits billed image / video generation

LEDGER_PERMISSIONS = frozenset({WRITE, LLM, GENERATE})
