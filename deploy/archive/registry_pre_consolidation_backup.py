"""
Tool registry: maps tool names to their functions and JSON schemas.

Consolidation v3.7.0 (2026-03-11):
  148 → 115 tools. Removed:
  - 3 longevity tools (never implemented — caused crash loop)
  - 13 domain-specific correlation tools (get_cross_source_correlation covers all)
  - 8 Claude-derivable tools (daily_summary + reasoning)
  - 7 low-usage/aspirational tools
  - 2 BoD metadata tools (→ admin scripts)
  See docs/reviews/mcp_architecture_review_2026-03-11.md for full rationale.
"""
from mcp.config import SOURCES, RAW_DAY_LIMIT, P40_GROUPS
from mcp.tools_data import *
from mcp.tools_strength import *
from mcp.tools_training import *
from mcp.tools_health import *
from mcp.tools_sleep import *
from mcp.tools_nutrition import *
from mcp.tools_correlation import *
from mcp.tools_habits import *
from mcp.tools_labs import *
from mcp.tools_cgm import *
from mcp.tools_journal import *
from mcp.tools_lifestyle import *
from mcp.tools_board import *
from mcp.tools_character import *
from mcp.tools_social import *
from mcp.tools_adaptive import *
from mcp.tools_todoist import *
from mcp.tools_memory import *
from mcp.tools_decisions import *
from mcp.tools_hypotheses import *
from mcp.tools_sick_days import *
