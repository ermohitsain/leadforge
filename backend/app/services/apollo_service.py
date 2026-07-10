"""Apollo.io API integration service for LeadForge."""

import httpx
import json
import logging
import asyncio
from typing import Optional
from datetime import datetime

from app.config import get_settings

logger = logging.getLogger(__name__)


class ApolloError(Exception):
    """Base exception for Apollo API errors."""
    pass


class ApolloAuthenticationError(ApolloError):
    """Invalid or missing API key."""
    pass


class ApolloRateLimitError(ApolloError):
    """API rate limit exceeded."""
    pass


class ApolloService:
    """Apollo.io API client for lead search and enrichment."""

    BASE_URL = "https://api.apollo.io/api/v1"

    def __init__(self, api_key: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.apollo_api_key
        self.timeout = 30
        self.max_retries = 3

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        retry_count: int = 0,
    ) -> dict:
        """Make an HTTP request to Apollo API with retry logic.

        Handles:
        - 401: Invalid/expired API key -> ApolloAuthenticationError
        - 429: Rate limit hit -> ApolloRateLimitError (with retry)
        - 5xx: Server errors -> ApolloError (with retry)
        """
        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                if method.upper() == "GET":
                    response = await client.get(url, headers=headers, params=data)
                else:
                    response = await client.post(url, headers=headers, json=data or {})

                if response.status_code == 200:
                    return response.json()

                elif response.status_code == 401:
                    raise ApolloAuthenticationError(
                        "Invalid or expired Apollo API key. "
                        "Check your API key at https://app.apollo.io/api-key"
                    )

                elif response.status_code == 403:
                    raise ApolloError(
                        "Access denied. Your Apollo plan may not support this endpoint."
                    )

                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "60"))
                    if retry_count < self.max_retries:
                        wait = retry_after * (2 ** retry_count)  # Exponential backoff
                        logger.warning(
                            f"Apollo rate limited. Retrying in {wait}s "
                            f"(attempt {retry_count + 1}/{self.max_retries})"
                        )
                        await asyncio.sleep(wait)
                        return await self._request(method, endpoint, data, retry_count + 1)
                    raise ApolloRateLimitError(
                        f"Apollo API rate limit exceeded after {self.max_retries} retries. "
                        f"Try again later or reduce batch size."
                    )

                elif 500 <= response.status_code < 600:
                    if retry_count < self.max_retries:
                        wait = 10 * (2 ** retry_count)
                        logger.warning(
                            f"Apollo server error {response.status_code}. "
                            f"Retrying in {wait}s (attempt {retry_count + 1}/{self.max_retries})"
                        )
                        await asyncio.sleep(wait)
                        return await self._request(method, endpoint, data, retry_count + 1)
                    raise ApolloError(
                        f"Apollo server error ({response.status_code}). Please try again later."
                    )

                else:
                    raise ApolloError(
                        f"Apollo API returned {response.status_code}: {response.text[:200]}"
                    )

            except httpx.TimeoutException:
                if retry_count < self.max_retries:
                    wait = 10 * (2 ** retry_count)
                    logger.warning(f"Apollo timeout. Retrying in {wait}s")
                    await asyncio.sleep(wait)
                    return await self._request(method, endpoint, data, retry_count + 1)
                raise ApolloError("Apollo API request timed out")

            except httpx.RequestError as e:
                raise ApolloError(f"Network error connecting to Apollo: {str(e)}")

    async def search_people(self, params: dict) -> list[dict]:
        """Search for people on Apollo.io.

        Args:
            params: Apollo search parameters (roles, industries, company size, etc.)

        Returns:
            List of lead dicts with person + company data
        """
        result = await self._request("POST", "/mixed_people/search", params)
        people = result.get("people", []) or result.get("contacts", [])
        total = result.get("total_entries", len(people))

        leads = []
        for person in people:
            org = person.get("organization", {}) or {}
            lead = {
                "first_name": (person.get("first_name") or "").strip(),
                "last_name": (person.get("last_name") or "").strip(),
                "email": (person.get("email") or "").strip().lower(),
                "title": (person.get("title") or "").strip(),
                "company": (org.get("name") or "").strip(),
                "company_website": (org.get("website_url") or "").strip(),
                "company_size": org.get("employee_count"),
                "company_industry": (org.get("industry") or "").strip(),
                "company_revenue_range": org.get("revenue_range"),
                "company_founded_year": org.get("founded_year"),
                "linkedin_url": (person.get("linkedin_url") or "").strip(),
                "phone": (person.get("phone_number") or person.get("phone") or "").strip(),
                "source": "apollo",
                "prospect_signals": {
                    "revenue_range": org.get("revenue_range"),
                    "employee_count": org.get("employee_count"),
                    "keywords": org.get("keywords", []),
                    "technologies": org.get("technology_names", []),
                    "funding": org.get("funding_info"),
                },
            }
            leads.append(lead)

        return leads

    async def enrich_lead(self, email: str) -> Optional[dict]:
        """Enrich a single lead by email via Apollo People Match endpoint.

        Args:
            email: Email address to look up

        Returns:
            Enriched lead data or None if not found
        """
        try:
            result = await self._request(
                "GET", "/people/match", {"email": email}
            )
            person = result.get("person", result.get("contact"))
            if not person:
                return None

            org = person.get("organization", {}) or {}
            return {
                "first_name": (person.get("first_name") or "").strip(),
                "last_name": (person.get("last_name") or "").strip(),
                "email": (person.get("email") or "").strip().lower(),
                "title": (person.get("title") or "").strip(),
                "company": (org.get("name") or "").strip(),
                "company_website": (org.get("website_url") or "").strip(),
                "company_size": org.get("employee_count"),
                "company_industry": (org.get("industry") or "").strip(),
                "linkedin_url": (person.get("linkedin_url") or "").strip(),
                "phone": (person.get("phone_number") or person.get("phone") or "").strip(),
                "prospect_signals": {
                    "employee_count": org.get("employee_count"),
                    "keywords": org.get("keywords", []),
                    "technologies": org.get("technology_names", []),
                },
            }
        except ApolloError as e:
            logger.warning(f"Enrichment failed for {email}: {e}")
            return None
