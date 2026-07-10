"""ICP (Ideal Customer Profile) parser using LLM."""

import json
import logging
from datetime import datetime
from typing import Optional

from app.services.llm_service import LLMClient, LLMClientError

logger = logging.getLogger(__name__)


ICP_PARSER_SYSTEM_PROMPT = """You are an ICP (Ideal Customer Profile) parser for a B2B lead generation system.
Your job is to convert natural language descriptions of an ideal customer into structured JSON.

The output must follow this exact schema:
{
  "industries": ["list of target industries, lowercase"],
  "roles": ["list of job titles/roles to target"],
  "company_size": {"min": min_employees, "max": max_employees} or null,
  "geo": ["list of target locations (countries, states, cities)"],
  "funding_stage": ["list: bootstrapped, seed, series_a, series_b, series_c, public"] or null,
  "funding_recency_months": null or number (how recent funding must be),
  "technologies": ["list of tech stack keywords"] or null,
  "exclusion_industries": ["industries to exclude"] or null,
  "exclusion_keywords": ["company keywords to exclude"] or null,
  "batch_size": 25 or number (default 25),
  "urgency_signals": ["hiring", "funding", "product_launch", "expansion"] or null
}

Rules:
- Extract structured data even from vague descriptions
- If a dimension isn't mentioned, use null (don't guess)
- Company size should be inferred from terms like "startup" (1-50), "mid-size" (50-500), "enterprise" (500+)
- Geography: "US" or "USA" → ["United States"]. "UK" → ["United Kingdom"]
- Roles: match common title variations (e.g., "CTO" and "Chief Technology Officer")
- Return ONLY valid JSON, no markdown, no explanation"""


class IcpParserError(Exception):
    """ICP parser errors."""
    pass


class IcpParser:
    """Converts natural language ICP descriptions to structured Apollo search params."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    async def parse_to_icp(self, natural_language: str) -> dict:
        """Parse natural language ICP description to structured ICP dict."""
        try:
            result = await self.llm.extract_json(
                ICP_PARSER_SYSTEM_PROMPT,
                f"Parse this ICP description:\n\n{natural_language}",
            )
            # Ensure minimum fields
            result.setdefault("industries", [])
            result.setdefault("roles", [])
            result.setdefault("batch_size", 25)
            return result
        except (LLMClientError, json.JSONDecodeError) as e:
            raise IcpParserError(f"Failed to parse ICP: {str(e)}")

    def icp_to_apollo_params(self, icp: dict) -> dict:
        """Convert structured ICP dict to Apollo.io API search parameters.

        Maps our ICP schema to Apollo's /v1/mixed_people/search endpoint params.
        """
        params: dict = {"page": 1, "per_page": icp.get("batch_size", 25)}

        # Map industries to Apollo organization_industry_tag_ids
        # Apollo uses tag IDs; we pass keywords for now
        if icp.get("industries"):
            params["q_organization_keyword_tags"] = icp["industries"]

        # Map roles/titles
        if icp.get("roles"):
            params["person_titles"] = icp["roles"]

        # Company size range
        cs = icp.get("company_size")
        if cs and (cs.get("min") or cs.get("max")):
            min_emp = cs.get("min", 1)
            max_emp = cs.get("max", 10000)
            params["organization_num_employees_ranges"] = [f"{min_emp},{max_emp}"]

        # Geography
        if icp.get("geo"):
            params["organization_locations"] = icp["geo"]

        # Funding stage
        if icp.get("funding_stage"):
            params["organization_industry_tag_ids"] = icp["funding_stage"]

        # Technologies
        if icp.get("technologies"):
            params.setdefault("q_organization_keyword_tags", [])
            params["q_organization_keyword_tags"].extend(icp["technologies"])

        return params

    async def natural_language_to_apollo_params(
        self, natural_language: str
    ) -> dict:
        """One-step: NL -> ICP -> Apollo params."""
        icp = await self.parse_to_icp(natural_language)
        apollo_params = self.icp_to_apollo_params(icp)
        return {
            "icp": icp,
            "apollo_params": apollo_params,
        }

    def validate_icp(self, icp: dict) -> tuple[bool, list[str]]:
        """Validate an ICP dict has minimum required fields.

        Returns (is_valid, list_of_issues).
        """
        issues = []
        if not icp.get("roles") and not icp.get("industries"):
            issues.append("At least one of 'roles' or 'industries' is required")
        if not isinstance(icp.get("batch_size", 25), int):
            issues.append("batch_size must be an integer")
        if icp.get("company_size"):
            cs = icp["company_size"]
            if not isinstance(cs, dict):
                issues.append("company_size must be a dict with min/max")
            elif cs.get("min") and cs.get("max") and cs["min"] > cs["max"]:
                issues.append("company_size.min cannot exceed company_size.max")
        return (len(issues) == 0, issues)
