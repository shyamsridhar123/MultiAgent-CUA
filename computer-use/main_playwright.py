"""
This is a basic example of how to use the CUA model along with the Responses API.
The code will run a loop taking screenshots and perform actions suggested by the model.
Make sure to install the required packages before running the script.
"""

import argparse
import asyncio
import logging
import os
import re
import time
import random
from urllib.parse import urlparse
from logging.handlers import RotatingFileHandler
from functools import wraps

import cua
import local_computer
import openai
from openai import AsyncAzureOpenAI, AsyncOpenAI
from playwright_computer import PlaywrightComputer
from direct_navigator import DirectNavigator

# Add this after importing other modules

class CircuitBreaker:
    """
    Circuit breaker pattern implementation to prevent repeated failures.
    Follows Azure best practices for resilient service integration.
    """
    
    def __init__(self, fail_threshold=3, reset_timeout=60):
        self.fail_count = {}
        self.circuit_state = {}
        self.last_failure_time = {}
        self.fail_threshold = fail_threshold
        self.reset_timeout = reset_timeout
        self.logger = logging.getLogger(__name__)
    
    def record_failure(self, operation):
        """Record a failure for the given operation."""
        self.fail_count[operation] = self.fail_count.get(operation, 0) + 1
        self.last_failure_time[operation] = time.time()
        
        if self.fail_count[operation] >= self.fail_threshold:
            self.circuit_state[operation] = "open"
            self.logger.warning(f"Circuit opened for operation: {operation} after {self.fail_threshold} failures")
    
    def record_success(self, operation):
        """Record a successful operation."""
        self.fail_count[operation] = 0
        self.circuit_state[operation] = "closed"
    
    def can_execute(self, operation):
        """Check if an operation can be executed based on circuit state."""
        current_state = self.circuit_state.get(operation, "closed")
        
        if current_state == "closed":
            return True
        
        # Check if we should retry (half-open the circuit)
        last_failure = self.last_failure_time.get(operation, 0)
        if (time.time() - last_failure) > self.reset_timeout:
            self.logger.info(f"Circuit half-open for {operation}, allowing retry")
            return True
            
        return False


# Configure proper logging with rotation
def setup_logging():
    """Set up proper logging with rotation and formatting."""
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # Create handlers
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "cua_agent.log"),
        maxBytes=10*1024*1024,  # 10 MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    
    # Create formatters
    console_format = logging.Formatter("%(message)s")
    file_format = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    # Set formatters
    console_handler.setFormatter(console_format)
    file_handler.setFormatter(file_format)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Get the main application logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    return logger


# Implement exponential backoff retry decorator
def azure_retry(max_retries=3, base_delay=1.0, max_delay=16.0):
    """
    Decorator that implements exponential backoff for Azure API calls.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            retries = 0
            last_exception = None
            
            while retries <= max_retries:
                try:
                    return await func(*args, **kwargs)
                except (openai.APITimeoutError, openai.APIConnectionError) as e:
                    last_exception = e
                    retries += 1
                    
                    if retries > max_retries:
                        logging.error(f"API call failed after {max_retries} retries")
                        raise
                        
                    # Calculate delay with exponential backoff and jitter
                    delay = min(base_delay * (2 ** (retries - 1)) + random.random(), max_delay)
                    logging.warning(f"API timeout/connection error, retrying in {delay:.2f}s ({retries}/{max_retries})")
                    await asyncio.sleep(delay)
                    
                except Exception as e:
                    # For other exceptions, don't retry
                    logging.error(f"Non-retryable error occurred: {type(e).__name__}: {str(e)}")
                    raise
                    
            # We shouldn't reach here, but just in case
            raise last_exception
            
        return wrapper
    return decorator


# Add this new class for task status tracking
class TaskStatusTracker:
    """Tracks the status of tasks being performed by the Computer Use Assistant."""
    
    def __init__(self):
        self.current_task = None
        self.completed_tasks = set()
        self.last_url = None
        self.task_attempts = 0
        self.max_attempts = 3
        self.logger = logging.getLogger(__name__)
    
    def set_current_task(self, task):
        """Set the current task being performed."""
        self.current_task = task
        self.task_attempts = 0
        self.logger.info(f"New task: {task}")
    
    def increment_attempt(self):
        """Increment the attempt counter for the current task."""
        self.task_attempts += 1
        return self.task_attempts
    
    def mark_task_completed(self, task=None):
        """Mark a task as completed."""
        task_to_complete = task or self.current_task
        if task_to_complete:
            self.completed_tasks.add(task_to_complete)
            self.logger.info(f"Task completed: {task_to_complete}")
            return True
        return False
    
    def is_task_completed(self, task=None):
        """Check if a task is already completed."""
        check_task = task or self.current_task
        return check_task in self.completed_tasks
    
    def update_url(self, url):
        """Update the last visited URL."""
        if url != self.last_url:
            self.logger.info(f"URL changed: {url}")
            self.last_url = url
            return True
        return False
    
    async def verify_task_completion(self, page, task):
        """
        Verify if a task has been completed based on visual and DOM content.
        
        Returns:
            bool: True if task appears to be completed, False otherwise
        """
        try:
            # Extract domain from task if it mentions a website
            domains = re.findall(r'(?:https?://)?(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', task)
            
            # If URL contains any of the domains mentioned in the task, it might be completed
            current_url = page.url
            url_domain = urlparse(current_url).netloc.lower()
            
            # Check if we're on a domain mentioned in the task
            domain_match = any(domain.lower() in url_domain for domain in domains)
            
            # Additional domain-specific checks
            if "microsoft.com" in url_domain and "microsoft" in task.lower():
                # Check if we're actually on a Microsoft page
                try:
                    # Check for Microsoft logo or navigation
                    ms_elements = await page.query_selector_all('a[aria-label*="Microsoft"], img[alt*="Microsoft"], .c-logo')
                    if ms_elements:
                        self.logger.info(f"Microsoft elements detected on page, confirming task completion")
                        return True
                except Exception as e:
                    self.logger.debug(f"Error checking Microsoft elements: {e}")
            
            # Check for common completion indicators in page content
            if domain_match:
                try:
                    # Get page title - helps confirm we're on the right site
                    title = await page.title()
                    content_text = await page.evaluate('document.body.innerText')
                    
                    # Check if title or content contains keywords related to the task
                    keywords = task.lower().split()
                    important_keywords = [w for w in keywords if len(w) > 3 and w not in 
                                         ('open', 'navigate', 'browse', 'visit', 'check', 'look', 'search')]
                    
                    # If we find important keywords from the task in the page title or content
                    if any(keyword in title.lower() for keyword in important_keywords):
                        self.logger.info(f"Task keywords found in page title, likely completed: {title}")
                        return True
                        
                    # For Microsoft specifically
                    if "microsoft" in task.lower() and "microsoft" in title.lower():
                        self.logger.info(f"Microsoft found in title for Microsoft-related task")
                        return True
                        
                except Exception as e:
                    self.logger.debug(f"Error analyzing page content: {e}")
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error verifying task completion: {e}")
            return False


# Enhance the Agent class to add Azure-specific retry logic
class EnhancedAgent(cua.Agent):
    """Enhanced agent with Azure best practices for resilience."""
    
    def __init__(self, client, model, computer):
        super().__init__(client, model, computer)
        self.circuit_breaker = CircuitBreaker(fail_threshold=3, reset_timeout=60)
        self.logger = logging.getLogger(__name__)
    
    @azure_retry(max_retries=3, base_delay=2.0, max_delay=20.0)
    async def continue_task(self, user_input=None):
        """Override the continue_task method with retry logic."""
        
        # Check if screenshots are failing too often
        if not self.circuit_breaker.can_execute("screenshot"):
            self.logger.warning("Screenshot circuit is open, using lower quality settings")
            
            # Apply special handling for complex pages
            if isinstance(self.computer, cua.Scaler) and hasattr(self.computer.computer, "performance_mode"):
                inner_computer = self.computer.computer
                # Force performance mode temporarily
                original_perf_mode = inner_computer.performance_mode
                inner_computer.performance_mode = True
                
                try:
                    result = await super().continue_task(user_input)
                    self.circuit_breaker.record_success("screenshot")
                    return result
                finally:
                    # Restore original settings
                    inner_computer.performance_mode = original_perf_mode
        
        try:
            return await super().continue_task(user_input)
        except Exception as e:
            if "screenshot" in str(e).lower() or "timeout" in str(e).lower():
                self.circuit_breaker.record_failure("screenshot")
            raise
    
    async def optimize_screenshot(self, screenshot_data):
        """
        Optimize screenshot size and quality for Azure OpenAI API.
        
        Args:
            screenshot_data: Base64-encoded screenshot data
            
        Returns:
            str: Optimized base64-encoded screenshot data
        """
        try:
            import base64
            from io import BytesIO
            from PIL import Image
            
            # Decode base64 data
            img_data = base64.b64decode(screenshot_data)
            img = Image.open(BytesIO(img_data))
            
            # Resize and compress image
            max_size = (1024, 768)  # Maximum dimensions
            img.thumbnail(max_size, Image.LANCZOS)
            
            # Save with optimized settings
            output = BytesIO()
            img.save(output, format="JPEG", quality=80, optimize=True)
            
            # Return as base64
            return base64.b64encode(output.getvalue()).decode('ascii')
        except Exception as e:
            self.logger.warning(f"Screenshot optimization failed: {str(e)}")
            return screenshot_data  # Return original if optimization fails


async def create_azure_client(args):
    """
    Create an Azure OpenAI client with best practices for resilience.
    
    Args:
        args: Command-line arguments
        
    Returns:
        The configured Azure OpenAI client
    """
    # Verify environment variables 
    required_vars = ["AZURE_OPENAI_ENDPOINT_COMPUTER_USE", "AZURE_OPENAI_KEY_COMPUTER_USE"]
    missing = [var for var in required_vars if not os.environ.get(var)]
    
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    
    # Azure OpenAI client configuration with resilience best practices
    if args.endpoint == "azure":
        client = AsyncAzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT_COMPUTER_USE"],
            api_key=os.environ["AZURE_OPENAI_KEY_COMPUTER_USE"],
            api_version="2025-03-01-preview",
            timeout=60.0,  # Increased timeout for larger payloads
            max_retries=5,  # More retries for transient issues
            default_headers={"x-ms-client-application-name": "computer-use-agent"}  # Telemetry header
        )
    else:
        client = AsyncOpenAI(
            timeout=60.0,
            max_retries=5,
        )
    
    return client


async def main():
    # Set up proper logging
    logger = setup_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--instructions", dest="instructions",
        default="Open web browser and go to microsoft.com.",
        help="Instructions to follow")
    parser.add_argument("--model", dest="model",
        default="computer-use-preview")
    parser.add_argument("--endpoint", default="azure",
        help="The endpoint to use, either OpenAI or Azure OpenAI")
    parser.add_argument("--autoplay", dest="autoplay", action="store_true",
        default=True, help="Autoplay actions without confirmation")
    parser.add_argument("--environment", dest="environment", default="windows",
        choices=["windows", "mac", "linux", "browser"],
        help="Environment to simulate (must be lowercase: windows, mac, linux, or browser)")
    parser.add_argument("--use-playwright", dest="use_playwright", action="store_true",
        default=False, help="Use Playwright for browser automation")
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
    parser.add_argument("--reduced-waits", dest="reduced_waits", action="store_true",
        default=False, help="Reduce artificial waiting times between actions")
    parser.add_argument("--timeout", dest="timeout", type=int, default=60,
        help="Timeout in seconds for Azure OpenAI API calls")
    parser.add_argument("--optimize-screenshots", dest="optimize_screenshots", action="store_true",
        default=True, help="Optimize screenshots before sending to Azure OpenAI")
    parser.add_argument("--screenshot-timeout", dest="screenshot_timeout", type=int, default=10000,
        help="Maximum time in ms to wait for screenshots")
    parser.add_argument("--disable-complex-screenshots", dest="disable_complex_screenshots", 
        action="store_true", default=False,
        help="Only take simple viewport screenshots for better performance")
    parser.add_argument("--auto-recovery", dest="auto_recovery", action="store_true", default=True,
        help="Automatically recover from errors by refreshing pages")
    args = parser.parse_args()

    # Create resilient Azure OpenAI client
    try:
        client = await create_azure_client(args)
        logger.info(f"Successfully configured {args.endpoint} client")
    except ValueError as e:
        logger.error(f"Configuration error: {str(e)}")
        return
    except Exception as e:
        logger.error(f"Failed to create API client: {str(e)}")
        return

    model = args.model
    environment = args.environment.lower()
    
    # Initialize task tracker
    task_tracker = TaskStatusTracker()
    
    # Choose computer implementation based on arguments
    if args.use_playwright:
        try:
            computer = PlaywrightComputer(
                headless=args.headless, 
                browser_type=args.browser,
                environment=environment,
                start_url=args.start_url,
                focus_address_bar=args.focus_address_bar,
                performance_mode=args.performance_mode,
                reduced_waits=args.reduced_waits,
            )
            logger.info(f"Using Playwright with {args.browser} browser")
            logger.info(f"Initial URL: {args.start_url}")
            
            # Initialize the direct navigator
            direct_navigator = DirectNavigator(computer)
            
        except Exception as e:
            logger.error(f"Failed to initialize Playwright: {str(e)}")
            return
    else:
        computer = local_computer.LocalComputer()
        logger.info("Using LocalComputer for system control")

    # Scaler configuration - smaller resolution is faster to process
    # Use smaller resolution for Azure OpenAI to improve reliability
    scaled_resolution = (640, 480) if args.optimize_screenshots else (800, 600) if args.performance_mode else (1024, 768)
    scaled_computer = cua.Scaler(computer, scaled_resolution)

    # Create enhanced agent with Azure best practices
    agent = EnhancedAgent(client, model, scaled_computer)

    # Get the user request
    user_input = args.instructions if args.instructions else input("Please enter the initial task: ")
    task_tracker.set_current_task(user_input)

    try:
        logger.info(f"User: {user_input}")
        agent.start_task()
        
        # Task management variables
        last_action_time = asyncio.get_event_loop().time()
        idle_timeout = 8.0 if args.performance_mode else 10.0
        idle_detection = False if args.performance_mode else True
        task_complete = False
        completion_indicators = ["done", "completed", "finished", "task complete", "complete"]
        consecutive_failures = 0
        max_consecutive_failures = 3
        
        while True:
            try:
                if not user_input and agent.requires_user_input:
                    user_input = input("User: ")
                    last_action_time = asyncio.get_event_loop().time()
                    task_tracker.set_current_task(user_input)
                    task_complete = False
                
                # Execute agent action with automatic retries (via decorator)
                start_time = time.time()
                await agent.continue_task(user_input)
                api_call_time = time.time() - start_time
                logger.debug(f"API call completed in {api_call_time:.2f}s")
                
                # Reset failure counter after successful API call
                consecutive_failures = 0
                
                user_input = None
                last_action_time = asyncio.get_event_loop().time()
                
                # Handle consent and safety checks
                if agent.requires_consent and not args.autoplay:
                    input("Press Enter to run computer tool...")
                elif agent.pending_safety_checks and not args.autoplay:
                    logger.info(f"Safety checks: {agent.pending_safety_checks}")
                    input("Press Enter to acknowledge and continue...")
                
                # Display reasoning and actions
                if agent.reasoning_summary:
                    logger.info(f"Action: {agent.reasoning_summary}")
                for action, action_args in agent.actions:
                    logger.info(f"  {action} {action_args}")
                
                # Detect task completion based on agent messages
                if agent.messages:
                    message_text = ''.join(agent.messages).lower()
                    logger.info(f"Agent: {''.join(agent.messages)}")
                    
                    # Check if any completion indicators are in the message
                    if any(indicator in message_text for indicator in completion_indicators):
                        logger.info("Task completion detected from agent message")
                        task_complete = True
                
                # Check if we can verify task completion by examining the page
                # Only do this for Playwright where we have access to the page
                if args.use_playwright and not task_complete:
                    inner_computer = scaled_computer.computer
                    if isinstance(inner_computer, PlaywrightComputer) and inner_computer.page:
                        # Check if we can directly navigate for known sites
                        if "microsoft.com" in task_tracker.current_task.lower() and not task_complete:
                            domain, _ = direct_navigator.extract_domain_from_task(task_tracker.current_task)
                            current_url = inner_computer.page.url
                            
                            # Only navigate if we're not already on the correct domain
                            if domain and not direct_navigator.is_on_target_domain(current_url, domain):
                                logger.info(f"Attempting direct navigation to {domain} for task: {task_tracker.current_task}")
                                navigation_successful = await direct_navigator.navigate_directly(task_tracker.current_task)
                                
                                if navigation_successful:
                                    # Get the new URL after direct navigation
                                    current_url = inner_computer.page.url
                                    task_tracker.update_url(current_url)
                                    
                                    # Check if we reached the correct domain
                                    if direct_navigator.is_on_target_domain(current_url, domain):
                                        logger.info(f"Successfully navigated to {domain} via direct navigation")
                                        task_complete = True
                                    else:
                                        logger.warning(f"Direct navigation completed but landed on {urlparse(current_url).netloc}")
                            elif domain and direct_navigator.is_on_target_domain(current_url, domain):
                                # We're already on the right domain
                                logger.info(f"Already on correct domain: {domain}")
                                task_complete = True
                        else:
                            # Existing URL check code for non-direct navigation cases
                            # Update URL tracking
                            current_url = inner_computer.page.url
                            task_tracker.update_url(current_url)
                            
                            # Check if URL contains "microsoft.com" for this specific task - BUT check the domain, not just the URL string
                            if task_tracker.current_task and "microsoft.com" in task_tracker.current_task.lower():
                                current_domain = urlparse(current_url).netloc.lower()
                                if "microsoft.com" in current_domain:  # Check the actual domain
                                    logger.info(f"Detected microsoft.com domain, marking task as completed")
                                    task_complete = True
                                elif "bing.com" in current_domain and "microsoft.com" in current_url:
                                    # We're on Bing search results for Microsoft
                                    logger.info("On Bing search results for Microsoft - attempting to navigate to Microsoft.com")
                                    
                                    # Try clicking the first search result for Microsoft
                                    try:
                                        # Look for Microsoft.com link in search results
                                        results = await inner_computer.page.query_selector_all('a[href*="microsoft.com"]')
                                        if results and len(results) > 0:
                                            # Click the first Microsoft link
                                            await results[0].click()
                                            logger.info("Clicked Microsoft.com link in search results")
                                            await asyncio.sleep(2)  # Wait for navigation
                                            
                                            # Check if we landed on Microsoft.com
                                            current_url = inner_computer.page.url
                                            task_tracker.update_url(current_url)
                                            
                                            if "microsoft.com" in urlparse(current_url).netloc.lower():
                                                logger.info("Successfully navigated to Microsoft.com domain")
                                                task_complete = True
                                    except Exception as e:
                                        logger.error(f"Error clicking search result: {str(e)}")
                            else:
                                # Verify if task appears to be completed based on page content
                                try:
                                    task_complete = await task_tracker.verify_task_completion(
                                        inner_computer.page, 
                                        task_tracker.current_task
                                    )
                                except Exception as e:
                                    logger.warning(f"Task verification error: {str(e)}")
                        
                        if task_complete:
                            logger.info(f"Task completion verified by page content analysis")
                            # Provide feedback to the model about task completion
                            feedback = f"I've successfully completed the task: {task_tracker.current_task}. The current page is {current_url}."
                            try:
                                await agent.continue_task(feedback)
                            except Exception as e:
                                logger.warning(f"Error sending completion feedback: {str(e)}")
                            
                            # Mark task as completed
                            task_tracker.mark_task_completed()
                            
                            # Prompt for new task
                            print("\nTask completed. Enter a new instruction or press Ctrl+C to exit.")
                            user_input = input("User: ")
                            task_tracker.set_current_task(user_input)
                            task_complete = False
                            last_action_time = asyncio.get_event_loop().time()
                
                # Check for idle timeout if enabled
                if idle_detection and args.use_playwright:
                    current_time = asyncio.get_event_loop().time()
                    idle_time = current_time - last_action_time
                    
                    if idle_time > idle_timeout and not task_complete:
                        # Check if we're really idle or still working
                        if not agent.actions and not agent.messages:
                            logger.info(f"No activity for {idle_timeout} seconds")
                            print("\nNo recent activity detected. Enter a new instruction or press Ctrl+C to exit.")
                            user_input = input("User: ")
                            task_tracker.set_current_task(user_input)
                            task_complete = False
                            last_action_time = current_time
                
            except openai.APITimeoutError as e:
                consecutive_failures += 1
                logger.error(f"API timeout error: {str(e)} (failure {consecutive_failures}/{max_consecutive_failures})")
                
                # After multiple consecutive failures, prompt user for next steps
                if consecutive_failures >= max_consecutive_failures:
                    logger.error("Maximum consecutive API failures reached")
                    print("\nThe Azure OpenAI service is experiencing timeouts. Would you like to:")
                    print("1. Try again with optimized settings")
                    print("2. Restart with a new task")
                    print("3. Exit the program")
                    choice = input("Enter your choice (1-3): ").strip()
                    
                    if choice == "1":
                        # Try with more aggressive optimizations
                        args.optimize_screenshots = True
                        args.performance_mode = True
                        args.reduced_waits = True
                        scaled_computer.size = (640, 480)  # Reduce resolution further
                        consecutive_failures = 0
                        logger.info("Continuing with optimized settings")
                    elif choice == "2":
                        # Get a new task
                        user_input = input("Enter a new task: ")
                        task_tracker.set_current_task(user_input)
                        consecutive_failures = 0
                    else:
                        logger.info("Exiting due to persistent API failures")
                        return
                        
                await asyncio.sleep(1)  # Brief pause before retry
                
            except Exception as e:
                logger.error(f"Unexpected error: {type(e).__name__}: {str(e)}")
                
                # Special handling for screenshot errors
                if "screenshot" in str(e).lower() and args.use_playwright:
                    logger.warning("Screenshot failure detected, attempting recovery")
                    
                    try:
                        # Force browser refresh as recovery mechanism
                        inner_computer = scaled_computer.computer
                        if isinstance(inner_computer, PlaywrightComputer) and inner_computer.page:
                            logger.info("Refreshing page to recover from screenshot error")
                            await inner_computer.page.reload(timeout=10000)
                            logger.info("Page refreshed successfully")
                            
                            # Wait a moment for the page to stabilize
                            await asyncio.sleep(2)
                            
                            # Continue without screenshot for this iteration
                            continue
                            
                    except Exception as refresh_error:
                        logger.error(f"Page refresh recovery failed: {str(refresh_error)}")
                
                await asyncio.sleep(1)  # Brief pause before continuing
            
            # Small pause to prevent CPU spinning
            await asyncio.sleep(0.1)
                
    finally:
        # Clean up resources
        if args.use_playwright:
            inner_computer = scaled_computer.computer
            if isinstance(inner_computer, PlaywrightComputer):
                try:
                    await inner_computer.cleanup()
                    logger.info("Playwright resources cleaned up")
                except Exception as e:
                    logger.error(f"Error during cleanup: {str(e)}")


if __name__ == "__main__":
    # Use uvloop for faster asyncio performance if available
    try:
        import uvloop
        uvloop.install()
        print("Using uvloop for improved performance")
    except ImportError:
        pass
    
    # Run the main function with proper error handling
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting due to user interrupt")
    except Exception as e:
        print(f"\nUnhandled error: {type(e).__name__}: {str(e)}")
