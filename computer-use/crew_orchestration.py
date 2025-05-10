"""
Crew AI orchestration for Computer Use Agent.
Implements Azure best practices for resilient multi-agent orchestration.
"""

import os
import asyncio
import logging
import time
import json
import random
from typing import Dict, List, Any, Optional, Type
from urllib.parse import urlparse
from dotenv import load_dotenv
from functools import wraps
import functools
from dataclasses import dataclass

# Import LangChain
from langchain.agents import initialize_agent, Tool, AgentType
from langchain.tools import BaseTool as LangChainBaseTool
from langchain.schema import SystemMessage

# Import from existing modules
import cua
import openai
from openai import AsyncAzureOpenAI
from playwright_computer import PlaywrightComputer
from direct_navigator import DirectNavigator

# Add LangChain import
from langchain_openai import AzureChatOpenAI

# Add missing import for BaseModel and Field
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()

# Azure best practice: Structured log directory with proper permissions
log_dir = os.path.join(os.getcwd(), "logs")
os.makedirs(log_dir, exist_ok=True)
log_path = os.path.join(log_dir, "crew_orchestration.log")

# Configure logging with proper rotation policies
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_path)
        # Consider adding RotatingFileHandler for log rotation
    ]
)

logger = logging.getLogger(__name__)

class AzureOpenAIConfig:
    """Azure OpenAI configuration following best practices."""
    
    def __init__(self, model_type="o4_mini"):
        self.model_type = model_type
        self.fetch_config()
    
    def fetch_config(self):
        """Fetch configuration from environment variables."""
        model_type_upper = self.model_type.upper()
        
        # Required environment variables
        self.endpoint = os.environ.get(f"AZURE_OPENAI_ENDPOINT_{model_type_upper}")
        self.api_key = os.environ.get(f"AZURE_OPENAI_KEY_{model_type_upper}")
        self.deployment = os.environ.get(f"AZURE_OPENAI_DEPLOYMENT_{model_type_upper}")
        self.model = os.environ.get(f"AZURE_OPENAI_MODEL_{model_type_upper}")
        
        # Use the appropriate API version or default to the latest
        api_version_var = f"AZURE_OPENAI_API_VERSION_{model_type_upper}"
        self.api_version = os.environ.get(api_version_var, os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"))
        
        # Validate configuration
        missing = []
        if not self.endpoint: missing.append(f"AZURE_OPENAI_ENDPOINT_{model_type_upper}")
        if not self.api_key: missing.append(f"AZURE_OPENAI_KEY_{model_type_upper}")
        if not self.deployment: missing.append(f"AZURE_OPENAI_DEPLOYMENT_{model_type_upper}")
        if not self.model: missing.append(f"AZURE_OPENAI_MODEL_{model_type_upper}")
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
            
        # Log the configuration for debugging
        logger.info(f"Model {model_type_upper} configured with endpoint: {self.endpoint}, " 
                   f"deployment: {self.deployment}, model: {self.model}, " 
                   f"API version: {self.api_version}")
    
    def get_client(self):
        """Create an Azure OpenAI client following best practices."""
        return AsyncAzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version=self.api_version,
            timeout=30.0,  # Azure best practice: Set appropriate timeout
            max_retries=3   # Built-in retries
        )
    
    def get_llm_config(self):
        """Get LLM configuration dictionary for Crew AI."""
        return {
            "config_list": [
                {
                    "model": self.model,
                    "api_base": self.endpoint,
                    "api_key": self.api_key,
                    "api_version": self.api_version,
                    "api_type": "azure",
                    "deployment_id": self.deployment
                }
            ],
            "temperature": 0.2  # Lower temperature for more deterministic outputs
        }

class BrowserActionInput(BaseModel):
    action_desc: str = Field(..., description="Description of the browser action to execute.")

class BrowserInteractionTool(LangChainBaseTool):
    class Config:
        extra = 'allow'
        arbitrary_types_allowed = True

    name: str = "browser_interaction"
    description: str = "Execute a browser interaction like navigation, clicking, or typing."
    args_schema: Type[BaseModel] = BrowserActionInput

    def __init__(self, computer, agent=None):
        super().__init__()
        self.computer = computer
        self.agent = agent

    def _run(self, action_desc: str) -> str:
        """Execute browser interaction with enhanced transparency for human observers."""
        if not self.agent:
            return "Error: CUA agent not initialized"
        
        # Azure best practice: Log interaction for transparency
        logger.info(f"Orchestrator instructing CUA: {action_desc}")
        
        try:
            # Create a new event loop for this thread if one doesn't exist
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                # No event loop exists in this thread, create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Add timing telemetry for Azure monitoring
            start_time = time.time()
            
            # Run the coroutine in the event loop
            result = loop.run_until_complete(self.agent.continue_task(action_desc))
            
            # Capture performance metrics for Azure monitoring
            execution_time = time.time() - start_time
            logger.info(f"CUA action executed in {execution_time:.2f}s: {action_desc[:50]}...")
            
            # Azure best practice: Create human-readable summary of actions taken
            actions_text = []
            for action, args in getattr(self.agent, "actions", []):
                # Format for human readability
                formatted_action = f"{action} {args}"
                actions_text.append(formatted_action)
            
            # Build observation summary
            messages = "".join(getattr(self.agent, "messages", []))
            
            # Get current page state for context - Azure best practice: Properly await coroutines
            current_url = "unknown"
            page_title = "unknown"
            screenshot_path = None
            
            if hasattr(self.computer, 'page') and self.computer.page:
                try:
                    current_url = self.computer.page.url
                    
                    # Azure best practice: Properly handle coroutines in sync context
                    if loop.is_running():
                        # Create a new loop if we're already in one
                        title_loop = asyncio.new_event_loop()
                        page_title = title_loop.run_until_complete(self.computer.page.title())
                        title_loop.close()
                    else:
                        page_title = loop.run_until_complete(self.computer.page.title())
                    
                    # Capture screenshot with unique filename
                    timestamp = time.strftime("%Y%m%d%H%M%S")
                    random_id = random.randint(1000, 9999)
                    
                    # Get screenshots directory from the orchestrator if available
                    screenshots_dir = getattr(getattr(self, 'agent', None), 'screenshots_dir', 
                                      os.path.join(os.getcwd(), "screenshots"))
                    os.makedirs(screenshots_dir, exist_ok=True)
                    
                    screenshot_filename = f"screenshot_{timestamp}_{random_id}.png"
                    screenshot_path = os.path.join(screenshots_dir, screenshot_filename)
                    
                    # Azure best practice: Capture screenshot with error handling and telemetry
                    try:
                        # Use Playwright's screenshot method directly for reliability
                        if loop.is_running():
                            ss_loop = asyncio.new_event_loop()
                            ss_loop.run_until_complete(
                                self.computer.page.screenshot(path=screenshot_path, full_page=False)
                            )
                            ss_loop.close()
                        else:
                            loop.run_until_complete(
                                self.computer.page.screenshot(path=screenshot_path, full_page=False)
                            )
                        logger.info(f"Screenshot captured at: {screenshot_path}")
                    except Exception as e:
                        logger.error(f"Failed to capture screenshot: {str(e)}", exc_info=True)
                        screenshot_path = None
                        
                except Exception as e:
                    logger.warning(f"Could not retrieve page details: {str(e)}")
                    page_title = "unknown"
            
            # Azure best practice: Return structured, visible results
            screenshot_info = f"\n📷 Screenshot: {os.path.basename(screenshot_path)}" if screenshot_path else ""
            
            return (
                f"✅ Action completed: {action_desc}\n\n"
                f"📋 Steps performed:\n- " + "\n- ".join(actions_text) + "\n\n"
                f"👁️ Current state:\n"
                f"- URL: {current_url}\n"
                f"- Title: {page_title}{screenshot_info}\n\n"
                f"📝 Observations:\n{messages}\n"
            )
        except Exception as e:
            # Azure best practice: Detailed error reporting
            logger.error(f"Browser interaction failed: {str(e)}", exc_info=True)
            return f"❌ Error executing interaction: {str(e)}\nTry a simpler instruction or verify the browser state."

class DirectNavigationInput(BaseModel):
    url_or_site: str = Field(..., description="URL or website to navigate to.")

class DirectNavigationTool(LangChainBaseTool):
    class Config:
        extra = 'allow'  # Use string literal instead of Extra.allow
        arbitrary_types_allowed = True

    name: str = "direct_navigation"
    description: str = "Directly navigate to a specific URL or website."
    args_schema: Type[BaseModel] = DirectNavigationInput

    def __init__(self, computer):
        super().__init__()
        self.computer = computer

    def _run(self, url_or_site: str) -> str:
        """Execute direct navigation with enhanced resilience and error handling."""
        try:
            import asyncio
            # Azure best practice: Create a new event loop if one doesn't exist
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            # Azure best practice: Log the navigation attempt for transparency
            logger.info(f"Attempting direct navigation to {url_or_site}")
                
            if not hasattr(self.computer, 'navigate_directly'):
                from direct_navigator import DirectNavigator
                navigator = DirectNavigator(self.computer)
                success = loop.run_until_complete(navigator.navigate_directly(url_or_site))
            else:
                success = loop.run_until_complete(self.computer.navigate_directly(url_or_site))
                
            if success:
                # Azure best practice: Enhanced observability with more context
                current_url = "unknown"
                page_title = "unknown"
                
                if hasattr(self.computer, 'page') and self.computer.page:
                    try:
                        current_url = self.computer.page.url
                        
                        # Azure best practice: Safely await coroutines in synchronous contexts
                        if hasattr(navigator, '_last_page_title'):
                            # Use cached title if available
                            page_title = navigator._last_page_title
                        else:
                            # Otherwise, properly await the coroutine
                            page_title = loop.run_until_complete(self.computer.page.title())
                    except Exception as e:
                        logger.warning(f"Could not retrieve page details: {str(e)}")
                
                # Return structured result for better user experience
                return (
                    f"✅ Successfully navigated to: {current_url}\n"
                    f"📄 Page title: {page_title}"
                )
            else:
                # Azure best practice: Informative fallback suggestion
                return "⚠️ Navigation failed. Please try using the browser_interaction tool instead."
        except Exception as e:
            # Azure best practice: Comprehensive error reporting
            logger.error(f"Error during direct navigation: {str(e)}", exc_info=True)
            return f"❌ Error during navigation: {str(e)}"

class BrowserSearchInput(BaseModel):
    query: str = Field(..., description="The search query to perform")

class BrowserSearchTool(LangChainBaseTool):
    class Config:
        extra = 'allow'
        arbitrary_types_allowed = True

    name: str = "search_browser"
    description: str = "Search for information using a web browser when you don't know the answer."
    args_schema: Type[BaseModel] = BrowserSearchInput

    def __init__(self, computer, agent=None):
        super().__init__()
        self.computer = computer
        self.agent = agent

    def _run(self, query: str) -> str:
        """Execute a browser search with enhanced guidance."""
        if not self.agent:
            return "Error: CUA agent not initialized"
        
        # Azure best practice: Log interaction for transparency
        logger.info(f"Orchestrator initiating browser search: {query}")
        
        try:
            # Create a new event loop for this thread if one doesn't exist
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                # No event loop exists in this thread, create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Construct a step-by-step search guidance
            search_instructions = (
                f"I'll help you search for information about: '{query}'.\n"
                f"1. First, look at the current page to see if we're already on a search engine.\n"
                f"2. If not on a search engine, click in the address bar and type 'www.bing.com'.\n"
                f"3. Once on the search engine, click on the search box.\n"
                f"4. Type the following search query: {query}\n"
                f"5. Press Enter or click the search button.\n"
                f"6. Once the search results appear, scan through them to find the most relevant information."
            )
            
            # Run the coroutine in the event loop
            result = loop.run_until_complete(self.agent.continue_task(search_instructions))
            
            # Azure best practice: Detailed logging
            logger.info(f"Browser search initiated for: '{query}'")
            
            return f"✅ Search initiated for: '{query}'\n\nPlease review the search results and extract the most relevant information."
            
        except Exception as e:
            # Azure best practice: Detailed error reporting
            logger.error(f"Browser search failed: {str(e)}", exc_info=True)
            return f"❌ Error executing search: {str(e)}\nTry a simpler search query or verify the browser state."

class ScrollPageInput(BaseModel):
    direction: str = Field(..., description="Direction to scroll: 'up', 'down', 'left', 'right', or specific like 'page down'")
    amount: str = Field(default="medium", description="Amount to scroll: 'small', 'medium', 'large', or specific like '300px'")

class ScrollPageTool(LangChainBaseTool):
    class Config:
        extra = 'allow'
        arbitrary_types_allowed = True

    name: str = "scroll_page"
    description: str = "Scroll the webpage in a specified direction and amount"
    args_schema: Type[BaseModel] = ScrollPageInput

    def __init__(self, computer, agent=None):
        super().__init__()
        self.computer = computer
        self.agent = agent

    def _run(self, direction: str, amount: str = "medium") -> str:
        """Execute page scrolling with reliable implementation."""
        if not self.agent:
            return "Error: CUA agent not initialized"
        
        # Map amount to pixels for more deterministic scrolling
        amount_map = {
            "small": 100,
            "medium": 300,
            "large": 600,
            "page": 800  # Approximate page height
        }
        
        # Extract numeric value if present (e.g. "300px" -> 300)
        try:
            if "px" in amount:
                scroll_amount = int(amount.replace("px", "").strip())
            elif amount.isdigit():
                scroll_amount = int(amount)
            else:
                scroll_amount = amount_map.get(amount.lower(), 300)
        except:
            scroll_amount = 300  # Default to medium if parsing fails
            
        # Convert direction to x,y coordinates
        x_change, y_change = 0, 0
        if "down" in direction.lower():
            y_change = scroll_amount
        elif "up" in direction.lower():
            y_change = -scroll_amount
        elif "right" in direction.lower():
            x_change = scroll_amount
        elif "left" in direction.lower():
            x_change = -scroll_amount
            
        # Format instruction for the agent in its preferred format
        if "page" in direction.lower() or "page" in amount.lower():
            # Use page down/up key instead of scrolling
            key = "PageDown" if y_change > 0 else "PageUp"
            instruction = f"Press the {key} key to scroll the page"
        else:
            # Construct a drag instruction from middle of page
            instruction = f"Scroll the page by dragging from the middle of the screen {direction} by about {abs(y_change or x_change)} pixels"
            
        try:
            # Create a new event loop for this thread if one doesn't exist
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            # Execute the scroll instruction
            logger.info(f"Executing scroll: {instruction}")
            result = loop.run_until_complete(self.agent.continue_task(instruction))
            
            return f"✅ Scrolled {direction} by {amount} amount\n\n📝 Observations:\n{result}"
            
        except Exception as e:
            logger.error(f"Scrolling failed: {str(e)}", exc_info=True)
            return f"❌ Error during scrolling: {str(e)}"

class ComputerUseTools:
    """Tools for interacting with the Computer Use Agent."""

    def __init__(self, computer, cua_agent):
        self.computer = computer
        self.cua_agent = cua_agent

    def browser_interaction_tool(self):
        return BrowserInteractionTool(self.computer, self.cua_agent)

@dataclass
class BrowserPolicy:
    keep_open: bool = True

class CrewOrchestration:
    """LangChain multi-agent orchestration for Computer Use Agent."""
    def __init__(self):
        self.computer_use_config = AzureOpenAIConfig("computer_use")
        self.gpt41_config = AzureOpenAIConfig("gpt41")
        # Removed o4_mini_config initialization
        self.metrics = {
            "tasks_started": 0,
            "tasks_completed": 0,
            "execution_time": 0,
            "errors": 0
        }
        self.computer = None
        self.cua_agent = None
        self.tools = None
        self.agent_executor = None
        self.keep_browser_open: bool = True

    async def initialize(self, args):
        logger.info("Initializing CrewOrchestration (LangChain)...")
        
        # Create screenshots directory with proper permissions
        self.screenshots_dir = os.path.join(os.getcwd(), "screenshots")
        os.makedirs(self.screenshots_dir, exist_ok=True)
        logger.info(f"Screenshots will be stored in: {self.screenshots_dir}")
        
        if args.use_playwright:
            try:
                self.computer = PlaywrightComputer(
                    headless=args.headless, 
                    browser_type=args.browser,
                    environment=args.environment.lower(),
                    start_url=args.start_url,
                    focus_address_bar=args.focus_address_bar,
                    performance_mode=args.performance_mode,
                    reduced_waits=args.reduced_waits,
                )
                logger.info(f"Initialized Playwright with {args.browser} browser")
            except Exception as e:
                logger.error(f"Failed to initialize Playwright: {str(e)}")
                raise
        else:
            from local_computer import LocalComputer
            self.computer = LocalComputer()
            logger.info("Initialized local computer control")
        client = self.computer_use_config.get_client()
        scaled_computer = cua.Scaler(self.computer, (1024, 768))
        self.cua_agent = cua.Agent(client, self.computer_use_config.model, scaled_computer)
        logger.info(f"Initialized CUA Agent with model: {self.computer_use_config.model}")
        self.tools = ComputerUseTools(self.computer, self.cua_agent)
        await self.setup_agents()
        logger.info("CrewOrchestration initialization complete (LangChain)")

    async def setup_agents(self):
        logger.info("Setting up LangChain multi-agent system...")
        # Define tools for LangChain agents - these still use the existing Computer Use wrapper
        browser_tool = Tool(
            name="browser_interaction",
            func=self.tools.browser_interaction_tool()._run,
            description="Execute a browser interaction like navigation, clicking, or typing."
        )
        navigation_tool = Tool(
            name="direct_navigation",
            func=DirectNavigationTool(self.computer)._run,
            description="Directly navigate to a specific URL or website."
        )
        
        # Add specialized tools for common actions
        scroll_tool = Tool(
            name="scroll_page",
            func=ScrollPageTool(self.computer, self.cua_agent)._run,
            description="Scroll the page in a specific direction (up, down, left, right) by a certain amount."
        )
        
        search_tool = Tool(
            name="search_browser",
            func=BrowserSearchTool(self.computer, self.cua_agent)._run,
            description="Search for information using a web browser when you don't know the answer."
        )
        
        # Azure best practice: Use GPT-4.1 for the LangChain orchestration layer
        # This only changes the decision-making model, not the Computer Use Agent
        llm = AzureChatOpenAI(
            azure_endpoint=self.gpt41_config.endpoint,
            openai_api_key=self.gpt41_config.api_key,
            openai_api_version=self.gpt41_config.api_version,
            openai_api_type="azure",
            azure_deployment=self.gpt41_config.deployment,
            model_name=self.gpt41_config.model,
            temperature=0.2,  # Azure best practice: Lower temperature for deterministic orchestration
            request_timeout=60  # Azure best practice: Adequate timeout for complex reasoning
        )
        
        # Fix screenshot quality parameter issue for Playwright
        if hasattr(self.computer, 'page') and hasattr(self.computer, 'screenshot'):
            # Set default screenshot options that work for both PNG and JPEG formats
            self.computer.screenshot_options = {
                "type": "jpeg" if getattr(self.computer, 'performance_mode', False) else "png",
                "full_page": False,  # Azure best practice: Use viewport screenshots for reliability
            }
            # Add quality only for JPEG format
            if self.computer.screenshot_options["type"] == "jpeg":
                self.computer.screenshot_options["quality"] = 80
        
        # Azure best practice: Define clear system instructions emphasizing transparency
        system_message = SystemMessage(content="""You are an AI orchestrator providing transparent guidance to a Computer Use Agent (CUA).
        Your role is to:
        1. EXPLAIN your plan clearly before taking actions
        2. PROVIDE step-by-step guidance that is visible to both the CUA and human user
        3. DESCRIBE what you're seeing on screen after each action
        4. NARRATE your decision-making process visibly
        
        The browser_interaction tool will invoke the CUA to interact with web pages.
        Always provide clear, descriptive instructions that would make sense to a human watching.
        For example, instead of "click the button" say "click the blue Sign In button at the top right corner of the page".
        
        IMPORTANT INTERACTION GUIDELINES:
        - For SCROLLING: Use specific instructions like "scroll down by dragging from the middle of the page downward" or "press the Page Down key"
        - For SEARCH: First clearly identify the search box with visual cues (e.g., "click the search box at the top of the page that says 'Search'"), then provide the query to type
        - Break complex tasks into simple, individual steps
        - After each action, observe what changed before deciding the next action
        
        The direct_navigation tool provides a simple way to navigate to specific URLs.
        Always explain why you're navigating to a particular site.
        
        The search_browser tool helps you find information online when you don't know the answer.
        When asked about real-time information like stock prices, market data, or current events:
        1. ACKNOWLEDGE that you need to search for up-to-date information
        2. USE search_browser tool to find the most current data
        3. EXPLAIN what information you're looking for
        4. EXTRACT and SUMMARIZE the relevant details from search results
        
        Make each instruction self-contained and specific - the CUA doesn't remember previous context.
        
        IMPORTANT: To use a tool, ALWAYS follow this specific format:
        Action: tool_name
        Action Input: your input here
        
        DO NOT put quotes around your input or include the tool name in the input.
        """)
        
        # Initialize the agent executor with tools
        self.agent_executor = initialize_agent(
            tools=[browser_tool, navigation_tool, search_tool, scroll_tool],
            llm=llm,
            agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
            verbose=True,
            system_message=system_message
        )
        logger.info("LangChain multi-agent system setup complete with GPT-4.1 orchestration")

    async def execute_task(self, user_instruction):
        """Execute task with iterative CUA/orchestrator back-and-forth."""
        logger.info(f"Starting task execution: {user_instruction}")
        self.metrics["tasks_started"] += 1
        start_time = time.time()
        all_turns: list[str] = []          # ⬅ holds running transcript
        result = None
        report_task = None
        MAX_TURNS = 20                      # safety stop

        try:
            # 1.  Augment the user prompt (unchanged logic)
            is_question = any(q in user_instruction.lower() for q in
                              ["what", "how", "why", "when", "where", "who",
                               "can", "could", "would", "is", "are", "find",
                               "search", "look up", "tell me about"])
            if is_question and "search" not in user_instruction.lower():
                enhanced_instruction = (
                    f"{user_instruction}\n\n"
                    f"If you don't have direct knowledge to fully answer this question, "
                    f"use the browser to search for relevant information. "
                    f"Explain your plan clearly before taking any actions."
                )
            else:
                enhanced_instruction = user_instruction

            # 2.  Main loop – keep feeding latest browser observations back
            latest_input = enhanced_instruction
            for turn in range(MAX_TURNS):
                agent_reply: str = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.agent_executor.run(latest_input)
                )
                all_turns.append(agent_reply)

                # stop once a final answer is produced
                if "Final Answer:" in agent_reply:
                    result = agent_reply
                    break

                # Otherwise grab observations / screenshot summary
                obs_start = agent_reply.find("📝 Observations:")
                if obs_start == -1:
                    # nothing to feed back → break to avoid infinite loop
                    result = agent_reply
                    break

                # Everything after "Observations:" becomes new context
                observations = agent_reply[obs_start + len("📝 Observations:"):].strip()
                latest_input = (
                    "Here is what the browser currently shows:\n"
                    f"{observations}\n\n"
                    "Please decide the next concrete browser action. "
                    "Remember to use the tool-call format."
                )

            else:
                result = ("Reached maximum interaction turns without a "
                          "Final Answer. Latest state:\n" + all_turns[-1])

            # 3.  Metrics / reporting (original logic but uses `result`)
            self.metrics["tasks_completed"] += 1
            exec_time = time.time() - start_time
            self.metrics["execution_time"] += exec_time
            logger.info(f"Task execution completed in {exec_time:.2f} seconds")

            task_metrics = {
                "execution_time": exec_time,
                "errors": self.metrics["errors"]
            }
            
            # Pass detailed interaction transcript to report generation
            report_task = asyncio.create_task(
                self._finalize_report(user_instruction, result, task_metrics, interaction_transcript=all_turns)
            )
            return result
        except Exception as e:
            logger.error(f"Error during task execution: {str(e)}")
            self.metrics["errors"] += 1
            
            # Azure best practice: Still generate report even on failure with available information
            if result is None:
                result = f"Task execution failed: {str(e)}"
                
            task_metrics = {
                "execution_time": time.time() - start_time,
                "errors": self.metrics["errors"]
            }
            # Generate failure report in background with available interaction transcript
            report_task = asyncio.create_task(
                self._finalize_report(user_instruction, result, task_metrics, 
                                     is_error=True, 
                                     interaction_transcript=all_turns if 'all_turns' in locals() else [])
            )
            
            raise

    async def cleanup(self):
        """
        Release Playwright resources safely.

        If ``self.keep_browser_open`` is True the browser / Playwright instance
        are left running so the user can continue interacting in a follow-up
        session; only “cleanup” bookkeeping is performed.
        """
        logger.info("Starting resource cleanup...")
        try:
            if not self.computer:
                return

            if self.keep_browser_open:
                logger.info("Browser left open for further interaction")
                return

            loop = asyncio.get_running_loop()

            def _run(coro):
                """Run an async coroutine in a fresh event-loop inside a worker thread."""
                return asyncio.run(coro)

            # Close browser
            browser = getattr(self.computer, "browser", None)
            if browser:
                try:
                    await loop.run_in_executor(None, functools.partial(_run, browser.close()))
                except Exception as exc:
                    logger.warning(f"Browser close error during cleanup: {exc}")

            # Stop Playwright
            playwright_obj = getattr(self.computer, "playwright", None)
            if playwright_obj:
                try:
                    await loop.run_in_executor(None, functools.partial(_run, playwright_obj.stop()))
                except Exception as exc:
                    logger.warning(f"Playwright stop error during cleanup: {exc}")

            logger.info("Cleaned up computer resources")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}", exc_info=True)

    async def shutdown(self):
        """
        Gracefully shutdown the application ensuring all resources are properly released
        and reports are completed.
        """
        logger.info("Starting application shutdown sequence")
        
        # 1. Wait for pending reports to complete (with timeout)
        if hasattr(self, "_pending_reports") and self._pending_reports:
            logger.info(f"Waiting for {len(self._pending_reports)} pending report(s) to complete")
            try:
                # Wait up to 10 seconds for reports to complete
                done, pending = await asyncio.wait(
                    [t for t in self._pending_reports if t is not None], 
                    timeout=10.0
                )
                
                if pending:
                    logger.warning(f"{len(pending)} report(s) did not complete within timeout")
            except Exception as e:
                logger.error(f"Error waiting for reports: {str(e)}")
        
        # 2. Clean up browser resources
        await self.cleanup()
        
        logger.info("Application shutdown complete")

    async def _graceful_shutdown(self) -> None:
        """
        Catch-all shutdown:
        1. Run regular shutdown (waits for reports, calls cleanup()).
        2. Cancel any still-pending asyncio tasks so the loop can exit cleanly.
        """
        try:
            await self.shutdown()
        except Exception as exc:
            logger.warning(f"Graceful shutdown encountered an error: {exc}")

        # Cancel stray tasks / transports
        pending = {t for t in asyncio.all_tasks() if t is not asyncio.current_task()}
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def generate_report(self, task_description, result, execution_metrics, interaction_transcript=None):
        """Generate and save a comprehensive report following Azure best practices."""
        correlation_id = f"report_{int(time.time())}_{random.randint(1000, 9999)}"
        report_start_time = time.time()
        logger.info(f"Starting report generation [correlation_id={correlation_id}]")

        try:
            # 1. Ensure reports directory exists
            reports_dir = os.path.join(os.getcwd(), "reports")
            os.makedirs(reports_dir, exist_ok=True)

            # 2. Build safe filename
            timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            task_slug = "".join(c if c.isalnum() else "_" for c in task_description[:30]).rstrip("_")
            filename = os.path.join(reports_dir, f"report_{timestamp}_{task_slug}.md")

            # 3. Get insights via Azure OpenAI
            insights = await self._generate_insights(task_description, result, correlation_id)
            
            # 4. Format the detailed interaction transcript
            detailed_transcript = ""
            if interaction_transcript and len(interaction_transcript) > 0:
                detailed_transcript = "## Detailed Orchestrator Transcript\n\n"
                for i, turn in enumerate(interaction_transcript):
                    # Azure best practice: Add clear separators and turn numbers for readability
                    detailed_transcript += f"### Turn {i+1}\n\n"
                    detailed_transcript += "```\n"
                    # Truncate extremely long turns for readability while preserving key information
                    if len(turn) > 5000:
                        # Keep the beginning and end of the turn
                        turn_text = turn[:2000] + "\n...[content truncated for readability]...\n" + turn[-2000:]
                    else:
                        turn_text = turn
                    detailed_transcript += turn_text + "\n"
                    detailed_transcript += "```\n\n"
                    
                    # Azure best practice: Add a screenshot reference if available
                    screenshot_ref = f"screenshot_{timestamp}_{i+1}.png"
                    if hasattr(self, 'screenshots_dir') and os.path.exists(os.path.join(self.screenshots_dir, screenshot_ref)):
                        detailed_transcript += f"![Screenshot for Turn {i+1}]({screenshot_ref})\n\n"
                    
                    # Azure best practice: Extract and highlight key actions for readability
                    if "Action:" in turn:
                        actions = []
                        for line in turn.split('\n'):
                            if line.startswith("Action:") or line.startswith("Action Input:"):
                                actions.append(line)
                        
                        if actions:
                            detailed_transcript += "**Key Actions:**\n\n"
                            for action in actions:
                                detailed_transcript += f"- `{action}`\n"
                            detailed_transcript += "\n"
                    
                    detailed_transcript += "---\n\n"

            # 5. Compose Markdown content with enhanced transcript
            report_content = f"""# Task Execution Report

## Task Overview
**Date and Time:** {time.strftime("%Y-%m-%d %H:%M:%S")}
**Task Description:** {task_description}
**Correlation ID:** {correlation_id}

## Execution Metrics
- **Execution Time:** {execution_metrics['execution_time']:.2f} seconds
- **Total Turns:** {len(interaction_transcript) if interaction_transcript else 0}
- **Status:** {"Completed Successfully" if execution_metrics.get('errors', 0) == 0 else f"Completed with {execution_metrics.get('errors', 0)} errors"}

## Findings and Results
{result}

## Insights and Recommendations
{insights}

{detailed_transcript}

## Technical Information
- **Environment:** {"Playwright browser" if hasattr(self, 'computer') and hasattr(self.computer, 'browser') else "Local computer"}
- **Browser:** {getattr(getattr(self, 'computer', None), 'browser_type', 'N/A')}
- **Orchestrator Model:** {self.gpt41_config.model if hasattr(self, 'gpt41_config') else "Unknown"}
- **Computer Use Agent Model:** {self.computer_use_config.model if hasattr(self, 'computer_use_config') else "Unknown"}
"""

            # 6. Atomic write - Azure best practice: Use atomic operations for file writes
            temp_filename = f"{filename}.tmp"
            try:
                with open(temp_filename, "w", encoding="utf-8") as f:
                    f.write(report_content)

                if os.path.exists(filename):
                    os.remove(filename)
                os.rename(temp_filename, filename)

                logger.info(
                    f"Enhanced report generated and saved to {filename} "
                    f"in {time.time() - report_start_time:.2f}s [correlation_id={correlation_id}]"
                )
                return filename
            except Exception as e:
                logger.error(f"Failed to write report: {e} [correlation_id={correlation_id}]", exc_info=True)
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)
                return None

        except Exception as e:
            logger.error(f"Error in report generation process: {e} [correlation_id={correlation_id}]", exc_info=True)
            return None

    async def _generate_insights(self, task_description, result, correlation_id=None):
        """Use AI to generate insights and recommendations based on task results."""
        log_prefix = f"[correlation_id={correlation_id}] " if correlation_id else ""
        logger.info(f"{log_prefix}Generating insights using Azure OpenAI")
        
        # Azure best practice: Implement retry logic with exponential backoff
        max_retries = 3
        retry_count = 0
        backoff_factor = 2
        
        while retry_count <= max_retries:
            try:
                # Azure best practice: Use the correct model for the task
                # GPT-4.1 is good for summarization and recommendations
                client = self.gpt41_config.get_client()
                
                # Format a prompt with clear instructions
                prompt = f"""
                Based on the following task and results, provide insights and actionable recommendations:
                
                TASK: {task_description}
                
                RESULTS:
                {result}
                
                Please provide:
                1. Key Findings - The most important information discovered
                2. Recommendations - What actions should be taken based on these findings
                3. Next Steps - What should be investigated or explored next
                
                Format your response using Markdown headings and bullet points for clarity.
                """
                
                # Azure best practice: Add timeout for external service calls
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=self.gpt41_config.deployment,
                        messages=[
                            {"role": "system", "content": "You are an expert analyst providing concise, actionable insights and recommendations."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.3,
                        # Azure best practice: Use max_completion_tokens instead of max_tokens for newer Azure OpenAI models
                        max_completion_tokens=1000
                    ),
                    timeout=30.0  # 30 second timeout
                )
                
                insights = response.choices[0].message.content
                logger.info(f"{log_prefix}Successfully generated insights ({len(insights)} chars)")
                return insights
                
            except asyncio.TimeoutError:
                retry_count += 1
                wait_time = backoff_factor ** retry_count
                logger.warning(f"{log_prefix}Insight generation timed out. Retry {retry_count}/{max_retries} after {wait_time}s")
                if retry_count > max_retries:
                    return "**Note:** Insight generation timed out. Please review the findings manually."
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                retry_count += 1
                wait_time = backoff_factor ** retry_count
                logger.warning(f"{log_prefix}Error generating insights: {str(e)}. Retry {retry_count}/{max_retries} after {wait_time}s")
                if retry_count > max_retries:
                    return "**Note:** Unable to generate insights due to technical issues. Please review the findings manually."
                await asyncio.sleep(wait_time)

    async def _finalize_report(self, task_description, result, execution_metrics, is_error=False, interaction_transcript=None):
        """Finalize report after task execution - forwards to generate_report with detailed interaction information."""
        try:
            if is_error:
                logger.info(f"Generating error report for task: {task_description[:50]}...")
            else:
                logger.info(f"Generating report for completed task: {task_description[:50]}...")
            
            # Call the existing report generation method with enhanced information
            report_path = await self.generate_report(
                task_description, 
                result, 
                execution_metrics, 
                interaction_transcript=interaction_transcript
            )
            
            if report_path:
                logger.info(f"Report saved to: {report_path}")
            else:
                logger.warning(f"Report generation failed for task: {task_description[:50]}")
                
            return report_path
        except Exception as e:
            logger.error(f"Error in report finalization: {str(e)}", exc_info=True)
            return None

async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Crew AI orchestration for Computer Use Agent")
    parser.add_argument("--instructions", dest="instructions",
        default="Open a web browser, go to microsoft.com, and check the latest products",
        help="Instructions to follow")
    parser.add_argument("--environment", dest="environment", default="windows",
        choices=["windows", "mac", "linux", "browser"],
        help="Environment to simulate")
    parser.add_argument("--use-playwright", dest="use_playwright", action="store_true",
        default=True, help="Use Playwright for browser automation")
    parser.add_argument("--headless", dest="headless", action="store_true",
        default=False, help="Run Playwright in headless mode")
    parser.add_argument("--browser", dest="browser", default="chromium",
        choices=["chromium", "firefox", "webkit"], help="Browser type for Playwright")
    parser.add_argument("--start-url", dest="start_url", default="https://www.bing.com/",
        help="URL to navigate to immediately after browser launch") 
    parser.add_argument("--focus-address-bar", dest="focus_address_bar", action="store_true",
        default=True, help="Focus on address bar immediately after startup")
    parser.add_argument("--performance-mode", dest="performance_mode", action="store_true", 
        default=False, help="Enable high-performance mode with reduced stealth features")
    parser.add_argument("--reduced_waits", dest="reduced_waits", action="store_true",
        default=False, help="Reduce artificial waiting times between actions")
    parser.add_argument("--close-browser-on-exit", dest="close_browser", action="store_true",
        default=False, help="Close the Playwright browser when the script exits")
    args = parser.parse_args()
    
    try:
        orchestration = CrewOrchestration()
        await orchestration.initialize(args)
        orchestration.keep_browser_open = not args.close_browser

        # ───────────────────────────────────────────────────
        # REPL loop ─ keeps Playwright session alive
        # ───────────────────────────────────────────────────
        while True:
            if args.instructions:
                next_instruction = args.instructions
                args.instructions = None           # run once, then prompt
            else:
                # Prompt user for follow-up
                print("\nEnter next instruction (or 'exit' to quit): ", end="", flush=True)
                next_instruction = input().strip()
                if next_instruction.lower() in {"exit", "quit"}:
                    break
                if not next_instruction:
                    continue

            result = await orchestration.execute_task(next_instruction)
            logger.info("\n==== Task Result ====\n%s", result)

    except KeyboardInterrupt:
        logger.info("Execution interrupted by user")
    except Exception as exc:
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
    finally:
        # Close only if flag set
        if 'orchestration' in locals():
            if args.close_browser:
                await orchestration._graceful_shutdown()
            else:
                logger.info("Browser session left open. Exiting without cleanup.")

if __name__ == "__main__":
    asyncio.run(main())