"""
Specialized browser tools for Crew AI integration with Computer Use Agent.
Implements Azure best practices for browser automation.
"""

import asyncio
import logging
from typing import Type
from crewai.tools import BaseTool
from pydantic import BaseModel, Field, Extra

logger = logging.getLogger(__name__)

class SearchToolInput(BaseModel):
    query: str = Field(..., description="Search query to perform.")

class SearchTool(BaseTool):
    class Config:
        extra = Extra.allow
        arbitrary_types_allowed = True

    name: str = "web_search"
    description: str = "Perform a web search and return the results"
    args_schema: Type[BaseModel] = SearchToolInput

    def __init__(self, computer, cua_agent):
        super().__init__()
        self.computer = computer
        self.cua_agent = cua_agent

    def _run(self, query: str) -> str:
        return asyncio.run(self._async_run(query))

    async def _async_run(self, query: str) -> str:
        # Navigate to search engine if not already there
        if hasattr(self.computer, 'page'):
            current_url = self.computer.page.url
            if "bing.com" not in current_url and "google.com" not in current_url:
                await self.cua_agent.continue_task("Go to Bing.com")
        # Perform search
        await self.cua_agent.continue_task(f"Search for: {query}")
        # Collect search results
        results = []
        if hasattr(self.computer, 'page'):
            try:
                page = self.computer.page
                result_elements = await page.query_selector_all("h2 a[href]")
                for i, element in enumerate(result_elements[:5]):
                    title = await element.inner_text()
                    href = await element.get_attribute("href")
                    results.append(f"{i+1}. {title} - {href}")
            except Exception as e:
                logger.error(f"Error extracting search results: {str(e)}")
        results_text = "\n".join(results) if results else "No structured results extracted"
        return (
            f"Search Query: {query}\nResults:\n{results_text}\n\n"
            f"Current URL: {self.computer.page.url if hasattr(self.computer, 'page') else 'unknown'}"
        )

class ExtractPageInfoInput(BaseModel):
    info_type: str = Field("all", description="Specify 'all', 'links', 'headings', or 'title'.")

class ExtractPageInfoTool(BaseTool):
    class Config:
        extra = Extra.allow
        arbitrary_types_allowed = True

    name: str = "extract_page_info"
    description: str = "Extract information from the current page (specify 'all', 'links', 'headings', or 'title')"
    args_schema: Type[BaseModel] = ExtractPageInfoInput

    def __init__(self, computer, cua_agent):
        super().__init__()
        self.computer = computer
        self.cua_agent = cua_agent

    def _run(self, info_type: str = "all") -> str:
        return asyncio.run(self._async_run(info_type))

    async def _async_run(self, info_type: str = "all") -> str:
        if not hasattr(self.computer, 'page'):
            return "Error: Browser page not available"
        page = self.computer.page
        try:
            if info_type.lower() == "links" or info_type.lower() == "all":
                links = await page.eval_on_selector_all("a[href]", """
                    elements => elements.slice(0, 10).map(el => ({
                        text: el.innerText.trim().substring(0, 50) || '[No text]',
                        href: el.getAttribute('href')
                    }))
                """)
                links_text = "\n".join([f"- {link['text']}: {link['href']}" for link in links])
            if info_type.lower() == "headings" or info_type.lower() == "all":
                headings = await page.eval_on_selector_all("h1, h2, h3", """
                    elements => elements.map(el => ({
                        level: el.tagName,
                        text: el.innerText.trim()
                    }))
                """)
                headings_text = "\n".join([f"{h['level']}: {h['text']}" for h in headings])
            if info_type.lower() == "title" or info_type.lower() == "all":
                title = await page.title()
            else:
                title = "Not extracted"
            result = f"Current URL: {page.url}\nPage Title: {title}\n\n"
            if info_type.lower() == "all" or info_type.lower() == "headings":
                result += f"Headings:\n{headings_text if 'headings_text' in locals() else 'None extracted'}\n\n"
            if info_type.lower() == "all" or info_type.lower() == "links":
                result += f"Important Links:\n{links_text if 'links_text' in locals() else 'None extracted'}\n\n"
            return result
        except Exception as e:
            logger.error(f"Error extracting page info: {str(e)}")
            return f"Error extracting page information: {str(e)}"

class BrowserTools:
    """Enhanced browser tools for Crew AI integration."""

    def __init__(self, computer, cua_agent):
        self.computer = computer
        self.cua_agent = cua_agent

    def search_tool(self):
        return SearchTool(self.computer, self.cua_agent)

    def extract_page_info_tool(self):
        return ExtractPageInfoTool(self.computer, self.cua_agent)

    def browser_interaction_tool(self):
        return BrowserInteractionTool(self.computer, self.cua_agent)

    def get_all_tools(self):
        return [
            self.search_tool(),
            self.extract_page_info_tool(),
            self.browser_interaction_tool()
        ]