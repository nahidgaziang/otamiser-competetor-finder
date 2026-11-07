import logging
from typing import List, Dict, Any
from compare_pipeline.config import settings
from compare_pipeline.discovery.dedupe import extract_canonical_domain

logger = logging.getLogger("search")


class SearchClient:
    def __init__(self):
        self.tavily_key = settings.TAVILY_API_KEY
        self.exa_key = settings.EXA_API_KEY

    def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Executes web search using DDGS as primary provider,
        falling back to Tavily or Exa if configured.
        """
        results: List[Dict[str, Any]] = []

        # 1. Primary: DuckDuckGo (ddgs)
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                ddg_res = list(ddgs.text(query, max_results=max_results))
                for item in ddg_res:
                    url = item.get("href") or item.get("link") or ""
                    if not url:
                        continue
                    results.append({
                        "title": item.get("title", ""),
                        "url": url,
                        "snippet": item.get("body", ""),
                        "provider": "ddgs",
                        "domain": extract_canonical_domain(url),
                    })
            if results:
                logger.info("Search '%s' via DDGS returned %d results", query, len(results))
                return results
        except Exception as e:
            logger.warning("DDGS search failed for '%s': %s", query, e)

        # 2. Fallback: Tavily
        if self.tavily_key:
            try:
                from tavily import TavilyClient
                tavily = TavilyClient(api_key=self.tavily_key)
                tav_res = tavily.search(query=query, max_results=max_results)
                for item in tav_res.get("results", []):
                    url = item.get("url", "")
                    if not url:
                        continue
                    results.append({
                        "title": item.get("title", ""),
                        "url": url,
                        "snippet": item.get("content", ""),
                        "provider": "tavily",
                        "domain": extract_canonical_domain(url),
                    })
                if results:
                    logger.info("Search '%s' via Tavily returned %d results", query, len(results))
                    return results
            except Exception as e:
                logger.warning("Tavily search failed for '%s': %s", query, e)

        # 3. Fallback: Exa
        if self.exa_key:
            try:
                from exa_py import Exa
                exa = Exa(api_key=self.exa_key)
                exa_res = exa.search(query, num_results=max_results)
                for item in exa_res.results:
                    url = getattr(item, "url", "")
                    if not url:
                        continue
                    results.append({
                        "title": getattr(item, "title", ""),
                        "url": url,
                        "snippet": getattr(item, "text", "")[:300] if hasattr(item, "text") else "",
                        "provider": "exa",
                        "domain": extract_canonical_domain(url),
                    })
                if results:
                    logger.info("Search '%s' via Exa returned %d results", query, len(results))
                    return results
            except Exception as e:
                logger.warning("Exa search failed for '%s': %s", query, e)

        return results
