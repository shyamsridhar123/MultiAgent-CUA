"""
Playwright implementation for CUA model integration.
This class allows the CUA model to control a browser through Playwright.
"""

import asyncio
import base64
import json
import logging
import os
import random
from io import BytesIO
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

class PlaywrightComputer:
    """Implementation of computer interface using Playwright for browser automation."""
    
    def __init__(self, headless=False, browser_type="chromium", environment="windows", 
                 start_url="https://www.bing.com/", focus_address_bar=True,
                 performance_mode=False, reduced_waits=False):
        self.browser_type = browser_type
        self.headless = headless
        self._environment = environment.lower()  # Ensure lowercase for API compatibility
        self.start_url = start_url
        self.focus_address_bar = focus_address_bar
        self.performance_mode = performance_mode
        self.reduced_waits = reduced_waits
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._setup_done = False
        
        # Use fewer user agents in performance mode
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ] if self.performance_mode else [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0"
        ]
        
        # Directory for storing persistent browser data
        self.user_data_dir = Path(os.path.expanduser("~")) / ".playwright_user_data"
        os.makedirs(self.user_data_dir, exist_ok=True)
    
    @property
    def environment(self):
        """Return the operating system environment."""
        return self._environment
    
    async def setup(self):
        """Initialize the Playwright browser with optimized settings."""
        if self._setup_done:
            return
            
        try:
            self.playwright = await async_playwright().start()
            
            # Select a user agent (first one in performance mode for consistency/speed)
            user_agent = self.user_agents[0] if self.performance_mode else random.choice(self.user_agents)
            
            # Optimized browser launch options
            browser_kwargs = {
                "headless": self.headless,
                # In performance mode, disable slow browser features
                "args": [
                    "--disable-extensions",
                    "--disable-component-extensions-with-background-pages",
                    "--disable-features=TranslateUI",
                    "--disable-background-networking",
                ] if self.performance_mode else [],
            }
            
            # Browser-specific configurations - simplified in performance mode
            if self.browser_type == "chromium":
                if not self.performance_mode:
                    # Only add stealth args if not in performance mode
                    browser_kwargs["args"].extend([
                        "--disable-blink-features=AutomationControlled",
                        f"--user-agent={user_agent}"
                    ])
                self.browser = await self.playwright.chromium.launch(**browser_kwargs)
            elif self.browser_type == "firefox":
                self.browser = await self.playwright.firefox.launch(**browser_kwargs)
            elif self.browser_type == "webkit":
                self.browser = await self.playwright.webkit.launch(**browser_kwargs)
            else:
                raise ValueError(f"Unsupported browser type: {self.browser_type}")
            
            # Create context with optimized settings
            context_options = {
                "viewport": {"width": 1280, "height": 800},
                "user_agent": user_agent,
            }
            
            # Only add advanced options if not in performance mode
            if not self.performance_mode:
                context_options.update({
                    "locale": "en-US",
                    "timezone_id": "America/New_York",
                })
            
            self.context = await self.browser.new_context(**context_options)
            
            # Apply stealth scripts only if not in performance mode
            if not self.performance_mode:
                await self.apply_stealth_scripts()
            
            # Create page with faster navigation options
            self.page = await self.context.new_page()
            
            # Navigate directly to start URL with optimized timeouts
            if self.start_url:
                wait_until = "domcontentloaded" if self.performance_mode else "networkidle"
                timeout = 10000 if self.performance_mode else 30000
                
                try:
                    await self.page.goto(
                        self.start_url, 
                        timeout=timeout,
                        wait_until=wait_until
                    )
                    
                    # Focus on address bar if requested, with minimal delay
                    if self.focus_address_bar:
                        await self._focus_address_bar()
                        
                except Exception as e:
                    logging.error(f"Failed to navigate to initial URL: {str(e)}")
            
            self._setup_done = True
            
        except Exception as e:
            logging.error(f"Failed to set up Playwright: {str(e)}")
            # Clean up any partially initialized resources
            await self.cleanup()
            raise
    
    async def apply_stealth_scripts(self):
        """Apply JavaScript patches to avoid bot detection."""
        if not self.context or self.browser_type != "chromium":
            return
            
        # Execute stealth script in the context
        await self.context.add_init_script("""
        // Override the navigator properties
        Object.defineProperty(navigator, 'webdriver', {
            get: () => false,
        });
        
        // Override the permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        
        // Pass the Plugins and Mimetypes length test
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                const plugins = [1, 2, 3, 4, 5];
                plugins.item = () => null;
                plugins.namedItem = () => null;
                plugins.refresh = () => {};
                plugins.length = 5;
                return plugins;
            },
        });
        
        // Pass the languages test
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
        
        // Prevent fingerprinting via canvas
        const getImageData = CanvasRenderingContext2D.prototype.getImageData;
        CanvasRenderingContext2D.prototype.getImageData = function(x, y, w, h) {
            const imageData = getImageData.call(this, x, y, w, h);
            for (let i = 0; i < imageData.data.length; i += 4) {
                // Add very slight noise to prevent fingerprinting
                const noise = Math.floor(Math.random() * 3) - 1;
                imageData.data[i] = Math.max(0, Math.min(255, imageData.data[i] + noise));
                imageData.data[i+1] = Math.max(0, Math.min(255, imageData.data[i+1] + noise));
                imageData.data[i+2] = Math.max(0, Math.min(255, imageData.data[i+2] + noise));
            }
            return imageData;
        };
        """)
    
    async def add_stealth_delay(self, route):
        """Add random delays to network requests to simulate human behavior."""
        # Only delay certain types of requests
        if route.request.resource_type in ["document", "xhr", "fetch"]:
            delay = random.randint(10, 100)
            await asyncio.sleep(delay / 1000)  # Convert ms to seconds
        
        await route.continue_()
    
    async def handle_dialog(self, dialog):
        """Handle browser dialogs automatically."""
        logger.info(f"Dialog appeared: {dialog.message}")
        await dialog.dismiss()
    
    async def cleanup(self):
        """Close the browser and Playwright."""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
        finally:
            self._setup_done = False
    
    async def wait(self, ms):
        """
        Wait for the specified number of milliseconds, with optimization for performance mode.
        """
        try:
            # Apply wait time reduction based on settings
            if self.reduced_waits:
                ms = min(ms, 200)  # Cap wait times at 200ms in reduced wait mode
                
            if self.performance_mode and ms > 100:
                ms = ms // 2  # Cut wait times in half in performance mode
                
            # Skip random additions in performance mode
            if self.performance_mode or self.reduced_waits:
                additional_ms = 0
            else:
                additional_ms = random.randint(0, 50) if ms > 100 else 0
                
            total_ms = ms + additional_ms
            seconds = total_ms / 1000.0
            
            await asyncio.sleep(seconds)
            return True
        except Exception as e:
            logging.error(f"Wait operation failed: {str(e)}")
            return False
    
    async def screenshot(self):
        """
        Take a screenshot of the current browser page with Azure best practice resilience.
        Implements graceful degradation and multiple fallback mechanisms.
        
        Returns:
            str: Base64-encoded screenshot data
        """
        await self.setup()
        try:
            # Performance optimized screenshot settings
            screenshot_opts = {
                # Don't specify timeout here - will be passed as a direct parameter
                "type": "jpeg" if self.performance_mode else "png",
                "omit_background": self.performance_mode,
            }
            
            # Only add quality for JPEG screenshots, not for PNG
            if screenshot_opts["type"] == "jpeg":
                screenshot_opts["quality"] = 70 if self.performance_mode else 90
            
            # Try standard screenshot first with shorter timeout
            try:
                screenshot_bytes = await self.page.screenshot(timeout=10000, **screenshot_opts)
                return base64.b64encode(screenshot_bytes).decode('ascii')
            except PlaywrightTimeoutError as e:
                # First fallback: Try viewport-only screenshot
                logging.warning("Full page screenshot timed out, trying viewport only")
                
                # Get viewport dimensions
                viewport = await self.page.evaluate("""
                    () => ({ 
                        width: Math.min(window.innerWidth, 1280), 
                        height: Math.min(window.innerHeight, 800),
                        x: 0, y: 0
                    })
                """)
                
                # Set clip to viewport dimensions but remove timeout from options
                # as it will be passed directly
                screenshot_opts["clip"] = viewport
                
                try:
                    screenshot_bytes = await self.page.screenshot(timeout=5000, **screenshot_opts)
                    logging.info("Viewport-only screenshot succeeded")
                    return base64.b64encode(screenshot_bytes).decode('ascii')
                except Exception as inner_e:
                    # Second fallback: Use error screenshot
                    logging.error(f"Viewport screenshot also failed: {str(inner_e)}")
                    error_screenshot = await self._create_error_screenshot(str(e))
                    return error_screenshot
        
        except Exception as e:
            # Handle any other exceptions
            logging.error(f"Screenshot failed: {str(e)}")
            # Create a minimal error image - making sure to await the coroutine
            return await self._create_error_screenshot(str(e))
    
    async def take_screenshot(self, **kwargs):
        """Take a screenshot with appropriate options based on format."""
        try:
            # Azure best practice: Don't set quality for PNG screenshots
            screenshot_options = kwargs.copy()
            
            # Remove quality parameter for PNG screenshots
            if 'type' not in screenshot_options or screenshot_options.get('type') == 'png':
                if 'quality' in screenshot_options:
                    del screenshot_options['quality']
            
            return await self.page.screenshot(**screenshot_options)
        except Exception as e:
            logger.error(f"Screenshot failed: {str(e)}")
            return None

    async def _create_error_screenshot(self, error_message):
        """Create a simple error screenshot when normal screenshots fail."""
        try:
            from PIL import Image, ImageDraw
            import io
            
            # Create a simple error image
            img = Image.new('RGB', (640, 480), color=(245, 245, 245))
            d = ImageDraw.Draw(img)
            d.text((20, 20), "Screenshot Error", fill=(255, 0, 0))
            d.text((20, 50), error_message[:100], fill=(0, 0, 0))
            
            # Save to bytes
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=80)
            buffer.seek(0)
            
            # Return as base64
            return base64.b64encode(buffer.getvalue()).decode('ascii')
        except Exception as e:
            # Ultimate fallback - return an empty image if even the error image fails
            logging.error(f"Failed to create error screenshot: {str(e)}")
            return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="

    async def click(self, x, y, button="left"):
        """Optimized click operation."""
        await self.setup()
        try:
            # Validate button parameter
            valid_buttons = ["left", "right", "middle"]
            if button not in valid_buttons:
                button = "left"
            
            # Performance mode: direct click without human-like movements
            if self.performance_mode or self.reduced_waits:
                await self.page.mouse.click(x, y, button=button)
            else:
                # Human-like clicking for normal mode
                await self.page.mouse.move(x, y, steps=random.randint(3, 7))
                await asyncio.sleep(random.uniform(0.05, 0.15))
                await self.page.mouse.click(x, y, button=button, delay=random.randint(30, 100))
                
            return True
        except Exception as e:
            logging.error(f"Click failed at ({x}, {y}) with {button} button: {str(e)}")
            return False
    
    async def move(self, x, y):
        """
        Move the mouse pointer to the specified coordinates.
        
        Args:
            x: X coordinate to move to
            y: Y coordinate to move to
            
        Returns:
            bool: True if the move operation succeeded, False otherwise
        """
        await self.setup()
        try:
            # Validate coordinates are within reasonable bounds
            if not (0 <= x <= 10000 and 0 <= y <= 10000):
                logger.warning(f"Mouse coordinates ({x}, {y}) outside reasonable bounds, but attempting anyway")
            
            # Move the mouse in a more human-like way with multiple steps
            await self.page.mouse.move(x, y, steps=random.randint(3, 8))
            logger.debug(f"Moved mouse to ({x}, {y})")
            return True
        except Exception as e:
            logger.error(f"Mouse move failed to ({x}, {y}): {str(e)}")
            return False
    
    async def type(self, text):
        """Optimized typing operation."""
        await self.setup()
        try:
            # Performance mode: type all at once
            if self.performance_mode or self.reduced_waits:
                await self.page.keyboard.type(text, delay=10)
            else:
                # Human-like typing for normal mode
                for char in text:
                    await self.page.keyboard.type(char, delay=random.randint(30, 150))
                await asyncio.sleep(random.uniform(0.1, 0.3))
                
            return True
        except Exception as e:
            logging.error(f"Type failed: {str(e)}")
            return False
    
    async def press(self, key):
        """Press the specified key."""
        await self.setup()
        try:
            # Normalize key names to match Playwright expectations
            normalized_key = self._normalize_key_name(key)
            
            # Add a small random delay before pressing key
            await asyncio.sleep(random.uniform(0.05, 0.15))
            await self.page.keyboard.press(normalized_key, delay=random.randint(20, 100))
            logger.debug(f"Pressed key: {normalized_key} (original: {key})")
            return True
        except Exception as e:
            logger.error(f"Key press failed for '{key}': {str(e)}")
            return False
    
    def _normalize_key_name(self, key):
        """
        Normalize key names to match Playwright expectations.
        
        Args:
            key: Key name to normalize
            
        Returns:
            str: Normalized key name
        """
        # Map of common key name variations to Playwright key names
        key_mapping = {
            "ENTER": "Enter",
            "RETURN": "Enter",
            "ESC": "Escape",
            "DEL": "Delete",
            "BACKSPACE": "Backspace",
            "SPACE": " ",
            "SPACEBAR": " ",
            "UP": "ArrowUp",
            "DOWN": "ArrowDown",
            "LEFT": "ArrowLeft",
            "RIGHT": "ArrowRight",
            "TAB": "Tab",
            "CTRL": "Control",
            "CMD": "Meta",
            "META": "Meta",
            "ALT": "Alt",
            "SHIFT": "Shift",
            "PAGEUP": "PageUp",
            "PAGEDOWN": "PageDown",
            "HOME": "Home",
            "END": "End",
        }
        
        # If the key is in our mapping, use the mapped value
        if key.upper() in key_mapping:
            return key_mapping[key.upper()]
            
        # Single character keys are case-sensitive in Playwright
        if len(key) == 1:
            return key
            
        # For other keys, use title case (first letter capitalized)
        # This handles cases like "Enter", "Backspace", etc.
        return key.title()
    
    async def keypress(self, keys):
        """
        Press a combination of keys simultaneously or a single key.
        
        Args:
            keys: A single key string or list of keys to press simultaneously
            
        Returns:
            bool: True if the keypress succeeded, False otherwise
        """
        await self.setup()
        try:
            # Validate input
            if not keys:
                logger.warning("No keys provided to keypress method")
                return False
                
            # Normalize to list if a single key is provided
            if not isinstance(keys, list):
                keys = [keys]
                
            # Check for empty list
            if len(keys) == 0:
                return True
                
            # Normalize key names
            normalized_keys = [self._normalize_key_name(key) for key in keys]
            
            # Handle single key press
            if len(normalized_keys) == 1:
                return await self.press(normalized_keys[0])
                
            # Handle key combinations - press all modifier keys, then press and release the last key
            modifiers = normalized_keys[:-1]
            last_key = normalized_keys[-1]
            
            # Press and hold all modifier keys
            for modifier in modifiers:
                await self.page.keyboard.down(modifier)
                logger.debug(f"Holding down key: {modifier}")
                
            # Small random delay between modifier keys and main key
            await asyncio.sleep(random.uniform(0.05, 0.1))
            
            # Press and release the last key
            await self.page.keyboard.press(last_key)
            logger.debug(f"Pressed key: {last_key}")
            
            # Release modifiers in reverse order (best practice)
            for modifier in reversed(modifiers):
                await self.page.keyboard.up(modifier)
                logger.debug(f"Released key: {modifier}")
                
            logger.debug(f"Completed keypress combination: {normalized_keys} (original: {keys})")
            return True
            
        except Exception as e:
            logger.error(f"Keypress failed for {keys}: {str(e)}")
            
            # Recovery: try to release any potentially stuck modifier keys
            try:
                for key in ["Control", "Alt", "Shift", "Meta"]:
                    await self.page.keyboard.up(key)
            except:
                pass
                
            return False
    
    async def navigate(self, url):
        """
        Navigate to the specified URL with improved completion detection and control return.
        
        Args:
            url: The URL to navigate to
            
        Returns:
            bool: True if navigation was successful, False otherwise
        """
        await self.setup()
        try:
            # Store initial URL for comparison
            initial_url = self.page.url
            logger.info(f"Navigating from {initial_url} to {url}")
            
            # Set shorter timeout in performance mode
            timeout = 15000 if self.performance_mode else 30000
            
            # Use faster wait_until in performance mode
            wait_until = "domcontentloaded" if self.performance_mode or self.reduced_waits else "networkidle"
            
            # Navigate with proper error handling
            response = await self.page.goto(
                url, 
                timeout=timeout, 
                wait_until=wait_until,
                referer="https://www.google.com/"  # Add a common referer
            )
            
            # Verify successful navigation
            if response and response.ok:
                # Get final URL after any redirects
                final_url = self.page.url
                logger.info(f"Successfully navigated to {final_url}")
                
                # Force a short wait to ensure page rendering is complete
                await asyncio.sleep(0.5 if self.reduced_waits else 1.0)
                
                # Check if we got a CAPTCHA
                page_content = await self.page.content()
                captcha_indicators = [
                    "captcha", "CAPTCHA", "robot", "Robot", 
                    "recaptcha", "verify human", "human verification",
                    "security check", "Security check"
                ]
                
                if any(indicator in page_content for indicator in captcha_indicators):
                    logger.warning(f"CAPTCHA detected on {url}")
                
                # Signal task completion to CUA
                await self.signal_navigation_complete(final_url)
                return True
            else:
                logger.warning(f"Navigation to {url} returned status {response.status if response else 'unknown'}")
                return False
            
        except PlaywrightTimeoutError:
            logger.warning(f"Navigation to {url} timed out but may have partially loaded")
            # Return true to allow continuing with potentially partially loaded page
            return True 
        except Exception as e:
            logger.error(f"Navigation to {url} failed: {str(e)}")
            return False
    
    async def signal_navigation_complete(self, url):
        """
        Signal to the CUA framework that navigation is complete.
        This helps prevent continuous loop of navigation attempts.
        
        Args:
            url: The URL that was successfully loaded
        """
        try:
            # Add a custom attribute to the page body to indicate navigation completion
            await self.page.evaluate(f"""() => {{
                document.body.setAttribute('data-cua-navigation-complete', 'true');
                document.body.setAttribute('data-cua-current-url', '{url}');
                
                // Create a visible indicator for 2 seconds
                const indicator = document.createElement('div');
                indicator.style.position = 'fixed';
                indicator.style.bottom = '10px';
                indicator.style.right = '10px';
                indicator.style.padding = '8px 12px';
                indicator.style.background = 'rgba(0,200,0,0.7)';
                indicator.style.color = 'white';
                indicator.style.borderRadius = '4px';
                indicator.style.zIndex = '9999';
                indicator.style.fontFamily = 'system-ui, sans-serif';
                indicator.style.fontSize = '14px';
                indicator.textContent = 'Navigation Complete';
                document.body.appendChild(indicator);
                
                setTimeout(() => {{
                    indicator.style.opacity = '0';
                    indicator.style.transition = 'opacity 0.5s';
                    setTimeout(() => indicator.remove(), 500);
                }}, 2000);
            }}""")
            
            logger.debug(f"Signaled navigation completion for {url}")
            
            # Take a new screenshot to reflect the updated state
            await self.screenshot()
            
        except Exception as e:
            logger.error(f"Failed to signal navigation completion: {str(e)}")
    
    async def get_current_url(self):
        """Get the current URL."""
        await self.setup()
        try:
            return self.page.url
        except Exception as e:
            logger.error(f"Failed to get current URL: {str(e)}")
            return None
    
    async def scroll(self, x, y, scroll_x, scroll_y):
        """
        Scroll the page to the specified position.
        
        Args:
            x: X coordinate of the reference point
            y: Y coordinate of the reference point
            scroll_x: Horizontal scroll amount
            scroll_y: Vertical scroll amount
            
        Returns:
            bool: True if the scroll operation succeeded, False otherwise
        """
        await self.setup()
        try:
            # Validate input parameters
            if not all(isinstance(param, (int, float)) for param in [x, y, scroll_x, scroll_y]):
                logger.warning("Invalid scroll parameters, expecting numbers")
                return False
                
            # Move mouse to the reference point first (optional but more human-like)
            await self.page.mouse.move(x, y)
            
            # Execute JavaScript to scroll the page
            # This is more reliable than using mouse wheel events
            await self.page.evaluate(f"""
                window.scrollTo({{
                    left: window.scrollX + {scroll_x},
                    top: window.scrollY + {scroll_y},
                    behavior: 'smooth'
                }});
            """)
            
            # Wait a moment for the scroll to complete
            await asyncio.sleep(random.uniform(0.3, 0.7))
            logger.debug(f"Scrolled page: x={scroll_x}, y={scroll_y} from position ({x}, {y})")
            return True
            
        except Exception as e:
            logger.error(f"Scroll failed: {str(e)}")
            return False
    
    async def _focus_address_bar(self):
        """Focus on the browser's address bar with performance optimizations."""
        try:
            # Fast focus method for performance mode
            if self.performance_mode or self.reduced_waits:
                if self.browser_type == "chromium":
                    await self.page.keyboard.press("Control+l")
                else:
                    await self.page.mouse.click(300, 40)
                return True
                
            # More thorough approach for normal mode
            if self.browser_type == "chromium":
                await self.page.keyboard.press("Alt+d")
                await asyncio.sleep(0.2)
            elif self.browser_type == "firefox":
                await self.page.keyboard.press("F6")
                await asyncio.sleep(0.2)
            else:
                await self.page.mouse.click(300, 40)
                await asyncio.sleep(0.2)
                
            # Select all text in the address bar
            await self.page.keyboard.press("Control+a")
            await asyncio.sleep(0.1)
            
            return True
        except Exception as e:
            logging.warning(f"Failed to focus on address bar: {str(e)}")
            return False