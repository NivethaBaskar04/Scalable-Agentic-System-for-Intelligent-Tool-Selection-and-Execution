"""
Central configuration for the Scalable Agentic System.

Everything that a real deployment would want to tune lives here and is
overridable via environment variables (see .env.example). Nothing here is
hardcoded routing logic - these are knobs for the retrieval/ranking math.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
TOOLS_FILE = DATA_DIR / "tools.json"
AGENT_DB = DATA_DIR / "agent_state.sqlite3"
PAYPAL_DB = DATA_DIR / "mock_paypal.sqlite3"

DATA_DIR.mkdir(parents=True, exist_ok=True)
KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

# ---- Retrieval ----
TOP_K_TOOLS = int(os.getenv("TOP_K_TOOLS", "5"))
TOP_K_DOMAIN_CANDIDATES = int(os.getenv("TOP_K_DOMAIN_CANDIDATES", "3"))
# The retriever pulls this many candidates (a superset of TOP_K_TOOLS) so the
# ranker - which also weighs domain/parameter/history signals, not just raw
# text similarity - has real options to re-order. Only the top TOP_K_TOOLS
# *after* ranking are ever shown to the planner/LLM.
RETRIEVAL_CANDIDATE_K = int(os.getenv("RETRIEVAL_CANDIDATE_K", "15"))

# ---- Ranking weights (must sum to ~1.0, but not enforced strictly) ----
RANK_WEIGHTS = {
    "semantic_similarity": float(os.getenv("W_SEMANTIC", "0.45")),
    "domain_match": float(os.getenv("W_DOMAIN", "0.20")),
    "parameter_match": float(os.getenv("W_PARAM", "0.15")),
    "historical_success": float(os.getenv("W_HISTORY", "0.10")),
    "reliability": float(os.getenv("W_RELIABILITY", "0.10")),
}

# ---- LLM provider ----
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")  # anthropic | openai | mock
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ---- Execution ----
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BASE_DELAY_SECONDS = float(os.getenv("RETRY_BASE_DELAY_SECONDS", "0.2"))
EXECUTION_TIMEOUT_SECONDS = float(os.getenv("EXECUTION_TIMEOUT_SECONDS", "5.0"))

# ---- Risk / confirmation ----
RISK_LEVELS_REQUIRING_CONFIRMATION = {"high"}

# ---- RAG ----
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "3"))
