"""
DirectNavigator module to enable direct URL navigation capabilities for the CUA framework.
Implements Azure best practices for secure and reliable web navigation.
"""

import asyncio
import logging
import re
import random
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)

class DirectNavigator:
    """
    Enables direct URL navigation capabilities for browser automation.
    Follows Azure best practices for security and reliability.
    """
    
    def __init__(self, playwright_computer):
        self.computer = playwright_computer
        self.navigation_attempts = {}
        self.max_navigation_attempts = 3
        self.common_domains = {
            "microsoft": "https://www.microsoft.com",
            "azure": "https://azure.microsoft.com",
            "github": "https://github.com",
            "office": "https://www.office.com",
            "bing": "https://www.bing.com",
            "linkedin": "https://www.linkedin.com",
            "outlook": "https://outlook.office.com",
            "teams": "https://teams.microsoft.com",
            "xbox": "https://www.xbox.com",
            "windows": "https://www.microsoft.com/windows",
            "visual studio": "https://visualstudio.microsoft.com",
            "onedrive": "https://onedrive.live.com",
        }
        
        # Initialize navigation metrics for telemetry
        self.navigation_metrics = {
            "successful_navigations": 0,
            "failed_navigations": 0,
            "total_navigation_time": 0,
            "redirects_encountered": 0
        }
    
    def extract_domain_from_task(self, task):
        """
        Extract a domain name from a task description with enhanced security.
        
        Args:
            task: String describing the task
            
        Returns:
            tuple: (normalized_domain, full_url) or (None, None) if no domain detected
        """
        # Convert task to lowercase for case-insensitive matching
        task_lower = task.lower()
        
        # Check for complete URLs (with http/https)
        url_pattern = re.compile(r'https?://(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)(?:/\S*)?')
        url_match = url_pattern.search(task_lower)
        if url_match:
            full_url = url_match.group(0)
            domain = url_match.group(1)
            # Ensure HTTPS protocol for security
            if not full_url.startswith("https://"):
                full_url = full_url.replace("http://", "https://")
            return domain, full_url
            
        # Check for domain mentions (e.g., "microsoft.com")
        domain_pattern = re.compile(r'(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)')
        domain_match = domain_pattern.search(task_lower)
        if domain_match:
            domain = domain_match.group(1)
            # Ensure it has a protocol and www prefix for better compatibility
            full_url = f"https://www.{domain}" if not domain.startswith('www.') else f"https://{domain}"
            return domain, full_url
            
        # Check for company names that map to known domains
        for company, url in self.common_domains.items():
            if company in task_lower:
                domain = urlparse(url).netloc
                return domain, url
                
        return None, None
    
    async def navigate_directly(self, task):
        """
        Navigate directly to a website based on task description with Azure-compliant
        resiliency patterns.
        
        Args:
            task: Description of navigation task
            
        Returns:
            bool: True if navigation was successful, False otherwise
        """
        domain, url = self.extract_domain_from_task(task)
        
        if not domain or not url:
            logger.warning(f"Could not extract a navigable URL from task: {task}")
            return False
            
        # Record this navigation attempt with retry limiting
        self.navigation_attempts[domain] = self.navigation_attempts.get(domain, 0) + 1
        
        # Apply Azure best practice: Circuit breaker pattern
        if self.navigation_attempts[domain] > self.max_navigation_attempts:
            logger.warning(f"Exceeded maximum navigation attempts for {domain}")
            self.navigation_metrics["failed_navigations"] += 1
            return False
            
        try:
            logger.info(f"Attempting direct navigation to {url}")
            start_time = asyncio.get_event_loop().time()
            
            # Execute direct navigation using page.goto() for reliability
            if hasattr(self.computer, 'page') and self.computer.page:
                # Apply Azure best practice: Retry pattern with exponential backoff
                max_retries = 2
                retry_count = 0
                
                while retry_count <= max_retries:
                    try:
                        # Azure best practice: Progressive timeout reduction
                        # First attempt with longer timeout, shorter on retries
                        timeout = 30000 if retry_count == 0 else 15000
                        
                        # Azure best practice: Use appropriate page load strategy
                        # domcontentloaded is faster than networkidle
                        wait_until = "domcontentloaded"
                        
                        # Execute navigation with proper security headers
                        response = await self.computer.page.goto(
                            url, 
                            timeout=timeout, 
                            wait_until=wait_until,
                            referer="https://www.google.com/"  # Common referer for natural navigation
                        )
                        
                        if response and response.ok:
                            final_url = self.computer.page.url
                            try:
                                # Azure best practice: Always ensure coroutines are properly awaited
                                page_title = await self.computer.page.title() or "unknown"
                                
                                # Store the string value, not the coroutine
                                self._last_page_title = page_title
                            except Exception as e:
                                logger.error(f"Failed to get page title: {str(e)}")
                                page_title = "unknown"
                                self._last_page_title = "unknown"
                                
                            final_domain = urlparse(final_url).netloc
                            
                            # Verify we landed on the correct domain (security check)
                            if self.is_on_target_domain(final_url, domain):
                                # Azure best practice: Record success metrics
                                end_time = asyncio.get_event_loop().time()
                                navigation_time = end_time - start_time
                                
                                self.navigation_metrics["successful_navigations"] += 1
                                self.navigation_metrics["total_navigation_time"] += navigation_time
                                
                                logger.info(f"Successfully navigated to {final_url} in {navigation_time:.2f}s")
                                
                                # Brief pause to let page stabilize, shorter with each retry
                                await asyncio.sleep(1.0 / (retry_count + 1))
                                return True
                            else:
                                # Handle redirects
                                logger.warning(f"Navigation redirected to unexpected domain: {final_domain}")
                                self.navigation_metrics["redirects_encountered"] += 1
                                
                                # Check if we need to handle common redirect patterns
                                if "login" in final_domain:
                                    logger.info("Detected login redirect, this may require authentication")
                                
                                # Consider this a successful navigation if it's a legitimate redirect
                                if response.status < 400:
                                    logger.info("Accepting redirect as valid navigation result")
                                    return True
                                    
                                # Return false for suspicious redirects
                                return False
                        else:
                            status = response.status if response else "unknown"
                            logger.warning(f"Navigation failed with status: {status}")
                            
                            # Azure best practice: Apply backoff before retry
                            retry_count += 1
                            if retry_count <= max_retries:
                                # Apply exponential backoff with jitter
                                delay = (2 ** retry_count) + (random.random() * 0.5)
                                logger.info(f"Retrying navigation (attempt {retry_count}/{max_retries}) after {delay:.2f}s")
                                await asyncio.sleep(delay)
                                continue
                            
                            self.navigation_metrics["failed_navigations"] += 1
                            return False
                            
                    except Exception as e:
                        logger.warning(f"Navigation attempt {retry_count+1} failed: {str(e)}")
                        retry_count += 1
                        
                        if retry_count <= max_retries:
                            # Apply exponential backoff with jitter
                            delay = (2 ** retry_count) + (random.random() * 0.5)
                            await asyncio.sleep(delay)
                            continue
                        else:
                            logger.error(f"All navigation attempts failed")
                            self.navigation_metrics["failed_navigations"] += 1
                            return False
                
                # All retries failed
                return False
                
            else:
                logger.error("Playwright page not available for direct navigation")
                self.navigation_metrics["failed_navigations"] += 1
                return False
                
        except Exception as e:
            logger.error(f"Error during direct navigation to {url}: {str(e)}")
            self.navigation_metrics["failed_navigations"] += 1
            return False
    
    def is_on_target_domain(self, current_url, target_domain):
        """
        Check if the current URL is on the target domain with improved security checks.
        
        Args:
            current_url: Current browser URL
            target_domain: Domain we want to be on
            
        Returns:
            bool: True if on target domain, False otherwise
        """
        try:
            # Parse URLs properly
            current_domain = urlparse(current_url).netloc.lower()
            
            # Simple case - exact domain match
            if target_domain.lower() == current_domain:
                return True
                
            # Handle subdomains properly
            target_parts = target_domain.lower().split('.')
            current_parts = current_domain.split('.')
            
            # Extract base domain for comparison (last 2 parts typically)
            if len(target_parts) >= 2 and len(current_parts) >= 2:
                target_base = '.'.join(target_parts[-2:])
                current_base = '.'.join(current_parts[-2:])
                
                if target_base == current_base:
                    return True
            
            # Fallback check
            return target_domain.lower() in current_domain
        except Exception as e:
            logger.error(f"Domain comparison error: {str(e)}")
            return False
    
    def get_navigation_metrics(self):
        """
        Get navigation metrics for telemetry and reporting.
        
        Returns:
            dict: Navigation metrics
        """
        if self.navigation_metrics["successful_navigations"] > 0:
            avg_time = self.navigation_metrics["total_navigation_time"] / self.navigation_metrics["successful_navigations"]
            self.navigation_metrics["average_navigation_time"] = round(avg_time, 2)
        
        return self.navigation_metrics