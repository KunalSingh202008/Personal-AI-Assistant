"""
Nexus AI — Real Browser & Computer Agent
Provides web navigation, content extraction, link following, form inspection,
and search engine retrieval with strict security boundaries and approval gating.
"""

from html.parser import HTMLParser
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse
import httpx

logger = logging.getLogger("nexus.browser")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 NexusAI/1.0"
)


class SimpleDOMParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.title = ""
        self.meta_description = ""
        self.in_title = False
        self.in_script_or_style = False
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.forms: list[dict[str, Any]] = []
        self.current_form: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attr_dict = {k.lower(): v or "" for k, v in attrs}

        if tag in {"script", "style", "noscript", "svg"}:
            self.in_script_or_style = True
            return

        if tag == "title":
            self.in_title = True
            return

        if tag == "meta":
            name = attr_dict.get("name", "").lower()
            prop = attr_dict.get("property", "").lower()
            if name == "description" or prop == "og:description":
                self.meta_description = attr_dict.get("content", "")

        if tag == "a" and "href" in attr_dict:
            href = attr_dict["href"]
            abs_url = urljoin(self.base_url, href)
            # Store placeholder, text filled in handle_data
            self.links.append({"href": abs_url, "raw_href": href, "text": ""})

        if tag == "form":
            action = urljoin(self.base_url, attr_dict.get("action", ""))
            self.current_form = {
                "action": action,
                "method": attr_dict.get("method", "GET").upper(),
                "inputs": [],
            }
            self.forms.append(self.current_form)

        if tag in {"input", "textarea", "select"} and self.current_form:
            self.current_form["inputs"].append({
                "name": attr_dict.get("name", ""),
                "type": attr_dict.get("type", "text"),
                "placeholder": attr_dict.get("placeholder", ""),
                "value": attr_dict.get("value", ""),
            })

        if tag in {"h1", "h2", "h3", "h4", "p", "li", "tr"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag in {"script", "style", "noscript", "svg"}:
            self.in_script_or_style = False
        if tag == "title":
            self.in_title = False
        if tag == "form":
            self.current_form = None

    def handle_data(self, data: str):
        if self.in_script_or_style:
            return
        cleaned = data.strip()
        if not cleaned:
            return

        if self.in_title:
            self.title += " " + cleaned
        else:
            self.text_parts.append(cleaned + " ")
            if self.links and not self.links[-1]["text"]:
                self.links[-1]["text"] = cleaned


class BrowserAgent:
    def __init__(self):
        self.history: list[str] = []
        self.current_url: str = ""
        self.current_page_data: dict[str, Any] = {}

    async def navigate(self, url: str) -> dict[str, Any]:
        """Navigate to a URL, parse HTML DOM, and extract structured page content."""
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url

        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(clean_url, headers=headers)
                resp.raise_for_status()

                final_url = str(resp.url)
                html_text = resp.text

                parser = SimpleDOMParser(base_url=final_url)
                parser.feed(html_text)

                raw_text = "".join(parser.text_parts)
                # Normalize excessive whitespace
                normalized_text = re.sub(r"\n\s*\n+", "\n\n", raw_text).strip()

                page_info = {
                    "url": final_url,
                    "status_code": resp.status_code,
                    "title": parser.title.strip() or final_url,
                    "description": parser.meta_description.strip(),
                    "text_preview": normalized_text[:6000],
                    "total_text_length": len(normalized_text),
                    "links_count": len(parser.links),
                    "forms_count": len(parser.forms),
                    "links": parser.links[:50],  # bounded top 50 links
                    "forms": parser.forms[:10],
                }

                self.current_url = final_url
                self.history.append(final_url)
                self.current_page_data = page_info

                return {"success": True, "page": page_info}

        except Exception as exc:
            logger.error(f"Failed to navigate to {clean_url}: {exc}")
            return {
                "success": False,
                "url": clean_url,
                "error": f"Failed to load page: {str(exc)}",
            }

    async def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """
        Search the web using DuckDuckGo HTML endpoint with zero API key dependencies.
        """
        clean_query = query.strip()
        if not clean_query:
            return []

        search_url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.post(search_url, data={"q": clean_query}, headers=headers)
                if resp.status_code != 200:
                    return []

                html = resp.text
                results = []

                # Extract result blocks from DuckDuckGo HTML
                # Pattern: <a class="result__url" href="..."> or <a class="result__snippet" ...>
                title_matches = re.findall(
                    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                    html,
                    re.DOTALL,
                )
                link_matches = re.findall(
                    r'<a[^>]+class="result__url"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                    html,
                    re.DOTALL,
                )

                for idx, (raw_url, display_url) in enumerate(link_matches[:limit]):
                    snippet = ""
                    if idx < len(title_matches):
                        # Strip html tags from snippet
                        snippet = re.sub(r"<[^>]+>", "", title_matches[idx]).strip()

                    clean_href = raw_url.strip()
                    # Resolve DuckDuckGo redirect uddg= parameter if present
                    if "uddg=" in clean_href:
                        m = re.search(r"uddg=([^&]+)", clean_href)
                        if m:
                            import urllib.parse
                            clean_href = urllib.parse.unquote(m.group(1))

                    results.append({
                        "title": re.sub(r"<[^>]+>", "", display_url).strip() or clean_query,
                        "url": clean_href,
                        "snippet": snippet,
                    })

                return results
        except Exception as exc:
            logger.warning(f"Web search failed: {exc}")
            return []
