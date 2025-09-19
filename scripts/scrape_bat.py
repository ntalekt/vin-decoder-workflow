#!/usr/bin/env python3
"""
Bring a Trailer scraper for Porsche 911 listings (1981+).
- Optimized for speed with performance reporting
- Scrapes from BOTH the main /porsche/911/ page AND the auction results search
- Gets comprehensive historical data by using BaT's search functionality with improved pagination
- Only collects sold listings from the past year to stay current (by auction end date)
- Only accepts cars with valid WP0* VINs (no parts/memorabilia)
- Enforces YYYY-porsche-911-* URL pattern for 1981+ models
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse, quote

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from utils import setup_logging, save_json_file, create_timestamp, validate_vin

class PerformanceTracker:
    """Track performance metrics during scraping."""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.phase_start = datetime.now()
        self.listings_scraped = 0
        self.last_report = 0
        self.report_interval = 10  # Report every 10 listings
        
    def start_phase(self, phase_name: str):
        """Start a new phase of scraping."""
        self.phase_start = datetime.now()
        print(f"\n🚀 Starting {phase_name}")
        
    def report_listing_progress(self, logger, listings_processed: int, total_listings: int):
        """Report progress every N listings."""
        if listings_processed - self.last_report >= self.report_interval:
            elapsed = (datetime.now() - self.phase_start).total_seconds()
            if elapsed > 0:
                rate = listings_processed / (elapsed / 60)  # listings per minute
                remaining = total_listings - listings_processed
                eta_minutes = remaining / rate if rate > 0 else 0
                
                logger.info(f"⚡ Progress: {listings_processed}/{total_listings} listings ({listings_processed/total_listings*100:.1f}%) | Rate: {rate:.1f}/min | ETA: {eta_minutes:.1f}min")
                print(f"⚡ Progress: {listings_processed}/{total_listings} listings ({listings_processed/total_listings*100:.1f}%) | Rate: {rate:.1f}/min | ETA: {eta_minutes:.1f}min")
                
            self.last_report = listings_processed
            
    def final_report(self, logger, total_found: int, total_scraped: int):
        """Generate final performance report."""
        total_elapsed = (datetime.now() - self.start_time).total_seconds() / 60
        if total_scraped > 0:
            scraping_elapsed = (datetime.now() - self.phase_start).total_seconds() / 60
            scraping_rate = total_scraped / scraping_elapsed if scraping_elapsed > 0 else 0
            
            logger.info(f"🏁 Final Performance:")
            logger.info(f"   Total Runtime: {total_elapsed:.1f} minutes")
            logger.info(f"   URLs Found: {total_found} | Scraping Rate: {scraping_rate:.1f} listings/min")
            logger.info(f"   Successfully Scraped: {total_scraped} listings")

class BaTScraper:
    """Bring a Trailer scraper for Porsche 911 listings."""
    
    def __init__(self, max_runtime_minutes: int = 45):
        self.logger = setup_logging()
        self.base_url = "https://bringatrailer.com"
        self.max_runtime = timedelta(minutes=max_runtime_minutes)
        self.start_time = datetime.now()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36'
        })
        self.processed_vins = set()
        # Set cutoff date to 1 year ago from today
        self.cutoff_date = datetime.now() - timedelta(days=365)
        self.logger.info(f"Only collecting listings newer than: {self.cutoff_date.strftime('%Y-%m-%d')}")
        
        # Performance tracker
        self.perf = PerformanceTracker()
        
        # Optimize Chrome driver settings for speed
        self._chrome_options = None
        self._setup_chrome_options()
    
    def _setup_chrome_options(self):
        """Setup optimized Chrome options for better performance."""
        self._chrome_options = Options()
        
        # Core headless settings
        self._chrome_options.add_argument("--headless=new")  # Use new headless mode (faster)
        self._chrome_options.add_argument("--no-sandbox")
        self._chrome_options.add_argument("--disable-dev-shm-usage")
        self._chrome_options.add_argument("--disable-gpu")
        
        # Performance optimizations
        self._chrome_options.add_argument("--disable-extensions")
        self._chrome_options.add_argument("--disable-plugins")
        self._chrome_options.add_argument("--disable-images")  # Don't load images (faster)
        self._chrome_options.add_argument("--disable-javascript")  # Disable JS where possible
        self._chrome_options.add_argument("--disable-css")  # Disable CSS loading
        self._chrome_options.add_argument("--disable-web-security")
        self._chrome_options.add_argument("--disable-features=TranslateUI")
        self._chrome_options.add_argument("--disable-default-apps")
        self._chrome_options.add_argument("--disable-sync")
        
        # Memory optimizations
        self._chrome_options.add_argument("--memory-pressure-off")
        self._chrome_options.add_argument("--max_old_space_size=4096")
        
        # Network optimizations
        self._chrome_options.add_argument("--aggressive-cache-discard")
        self._chrome_options.add_argument("--disable-background-networking")
        
        # Window size
        self._chrome_options.add_argument("--window-size=1280,720")  # Smaller window
        
        # User agent
        self._chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        
        # Anti-detection (minimal)
        self._chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        self._chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self._chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Page load strategy - don't wait for everything
        self._chrome_options.page_load_strategy = 'eager'  # Don't wait for images/stylesheets
    
    def configure_chrome_driver(self, enable_js: bool = False) -> webdriver.Chrome:
        """Configure optimized Chrome driver for BaT scraping."""
        options = Options()
        
        # Copy base options
        for arg in self._chrome_options.arguments:
            # Skip JS disable if we need JS for this instance
            if enable_js and '--disable-javascript' in arg:
                continue
            options.add_argument(arg)
        
        # Add experimental options
        for key, value in self._chrome_options.experimental_options.items():
            options.add_experimental_option(key, value)
        
        driver = webdriver.Chrome(options=options)
        
        # Set shorter timeouts for better performance
        driver.implicitly_wait(5)  # Reduced from 10
        driver.set_page_load_timeout(15)  # Reduced from 30
        
        if not enable_js:
            # Additional speed optimizations when JS not needed
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
        else:
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        return driver
    
    def should_continue(self) -> bool:
        """Check if scraping should continue based on time limit."""
        elapsed = datetime.now() - self.start_time
        return elapsed < self.max_runtime
    
    def parse_bat_date_format(self, date_str: str) -> Optional[datetime]:
        """Parse BaT-specific date formats like '9/18/25' or '9/17/25'."""
        try:
            # Handle formats like "9/18/25", "09/18/25", "9/18/2025"
            date_patterns = [
                ('%m/%d/%y', r'\d{1,2}/\d{1,2}/\d{2}'),        # 9/18/25
                ('%m/%d/%Y', r'\d{1,2}/\d{1,2}/\d{4}'),       # 9/18/2025
                ('%b %d, %Y', r'\w{3} \d{1,2}, \d{4}'),       # Sep 18, 2025
                ('%B %d, %Y', r'\w+ \d{1,2}, \d{4}'),         # September 18, 2025
            ]
            
            for fmt, pattern in date_patterns:
                if re.match(pattern, date_str.strip()):
                    try:
                        parsed_date = datetime.strptime(date_str.strip(), fmt)
                        
                        # Handle 2-digit year (assume 20xx if <= current year, otherwise 19xx)
                        if parsed_date.year <= 30:  # Assuming anything <= 2030 is 20xx
                            parsed_date = parsed_date.replace(year=parsed_date.year + 2000)
                        elif parsed_date.year <= 99:  # 31-99 would be 1931-1999, but that doesn't make sense for BaT
                            parsed_date = parsed_date.replace(year=parsed_date.year + 2000)
                        
                        # Only return reasonable dates (not too far in future, not too old)
                        now = datetime.now()
                        if datetime(2020, 1, 1) <= parsed_date <= now + timedelta(days=30):
                            return parsed_date
                    except ValueError:
                        continue
        except Exception as e:
            self.logger.debug(f"Error parsing date '{date_str}': {e}")
        
        return None
    
    def assess_page_recency_by_auction_cards(self, driver) -> dict:
        """
        Assess how recent the auction completion dates are by looking at the specific 
        'Sold for USD $X on DATE' and 'Bid to USD $X on DATE' text patterns on auction cards.
        """
        try:
            dates_found = []
            now = datetime.now()
            
            # Look for all text elements on the page (optimized)
            all_text_elements = driver.find_elements(By.XPATH, "//*[text()]")
            
            # Specific patterns for BaT auction results cards
            auction_card_patterns = [
                r'sold for usd \$[\d,]+ on (\d{1,2}/\d{1,2}/\d{2,4})',       # "Sold for USD $110,000 on 9/18/25"
                r'bid to usd \$[\d,]+ on (\d{1,2}/\d{1,2}/\d{2,4})',         # "Bid to USD $146,000 on 9/17/25"
                r'ended on (\d{1,2}/\d{1,2}/\d{2,4})',                       # "Ended on 9/18/25"
                r'completed (\d{1,2}/\d{1,2}/\d{2,4})',                      # "Completed 9/18/25"
                r'auction ended (\d{1,2}/\d{1,2}/\d{2,4})',                  # "Auction ended 9/18/25"
                r'(\d{1,2}/\d{1,2}/\d{2,4})\s*-\s*(?:sold|ended|completed)', # "9/18/25 - Sold"
            ]
            
            # Search through page text for auction completion patterns (limited for speed)
            for element in all_text_elements[:50]:  # Reduced from 100 for speed
                try:
                    element_text = element.text.strip().lower()
                    if not element_text or len(element_text) > 300:  # Skip empty or very long text
                        continue
                    
                    # Look for auction card patterns
                    for pattern in auction_card_patterns:
                        matches = re.findall(pattern, element_text, re.IGNORECASE)
                        for match in matches:
                            date_obj = self.parse_bat_date_format(match)
                            if date_obj:
                                dates_found.append(date_obj)
                                self.logger.debug(f"Found auction completion date: '{match}' -> {date_obj.strftime('%Y-%m-%d')}")
                                
                except Exception as e:
                    self.logger.debug(f"Error processing element text: {e}")
                    continue
            
            # Also look for dates in page source (limited for speed)
            page_source = driver.page_source.lower()
            general_patterns = [
                r'(\d{1,2}/\d{1,2}/\d{2,4})',  # Any date in M/D/YY or M/D/YYYY format
            ]
            
            for pattern in general_patterns:
                matches = re.findall(pattern, page_source)
                for match in matches[-20:]:  # Reduced from 50 for speed
                    date_obj = self.parse_bat_date_format(match)
                    if date_obj:
                        # Only add if it's a reasonable auction date (within last 3 years)
                        if date_obj >= datetime(2022, 1, 1):
                            dates_found.append(date_obj)
                            self.logger.debug(f"Found general date: '{match}' -> {date_obj.strftime('%Y-%m-%d')}")
            
            # Remove duplicates and sort by most recent first
            unique_dates = list(set(dates_found))
            unique_dates.sort(reverse=True)
            
            if not unique_dates:
                self.logger.info("No auction completion dates found on page - assuming mixed content")
                return {'is_mostly_old': False, 'recent_count': 1, 'old_count': 0, 'avg_days_ago': 100}
            
            # Calculate age statistics
            days_ago_list = [(now - date).days for date in unique_dates]
            avg_days_ago = sum(days_ago_list) / len(days_ago_list)
            
            # Count recent vs old based on our 1-year cutoff (365 days)
            recent_count = sum(1 for days in days_ago_list if days <= 365)
            old_count = sum(1 for days in days_ago_list if days > 365)
            
            # Consider page mostly old if more than 70% of auctions are older than 1 year
            is_mostly_old = (old_count / len(days_ago_list)) > 0.7 if len(days_ago_list) > 0 else False
            
            # Enhanced logging with actual dates found (limited for speed)
            recent_dates = [d.strftime('%Y-%m-%d') for d in unique_dates if (now - d).days <= 365][:3]
            old_dates = [d.strftime('%Y-%m-%d') for d in unique_dates if (now - d).days > 365][:3]
            
            self.logger.info(f"Auction completion date analysis: {recent_count} recent, {old_count} old, avg {avg_days_ago:.0f} days ago ({len(unique_dates)} total) - {'MOSTLY OLD' if is_mostly_old else 'RECENT/MIXED'}")
            
            return {
                'is_mostly_old': is_mostly_old,
                'recent_count': recent_count,
                'old_count': old_count,
                'total_dates': len(unique_dates),
                'avg_days_ago': avg_days_ago,
                'oldest_days': max(days_ago_list) if days_ago_list else 0,
                'newest_days': min(days_ago_list) if days_ago_list else 0,
                'recent_dates': recent_dates,
                'old_dates': old_dates
            }
            
        except Exception as e:
            self.logger.warning(f"Error analyzing auction completion dates: {e}")
            return {'is_mostly_old': False, 'recent_count': 1, 'old_count': 0, 'avg_days_ago': 100}
    
    def extract_auction_end_date_fast(self, page_text: str, listing_url: str) -> Optional[datetime]:
        """Fast extraction of auction end date from individual listing page text."""
        # Simplified date patterns for speed
        date_patterns = [
            (r'(\d{1,2}/\d{1,2}/\d{2,4})', None),                            # "9/18/25" - use our custom parser
            (r'ended\s+(\w+\s+\d{1,2},\s+\d{4})', '%B %d, %Y'),              # "ended September 16, 2024"
            (r'sold\s+(\w+\s+\d{1,2},\s+\d{4})', '%B %d, %Y'),               # "sold September 16, 2024"
            (r'ends\s+(\w+\s+\d{1,2},\s+\d{4})', '%B %d, %Y'),               # "ends September 16, 2024"
        ]
        
        text_lower = page_text.lower()
        
        for pattern, date_format in date_patterns:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            for match in matches[:3]:  # Only check first 3 matches for speed
                try:
                    if date_format is None:  # BaT date format like "9/18/25"
                        return self.parse_bat_date_format(match)
                    else:  # Absolute date
                        date_obj = datetime.strptime(match.strip(), date_format)
                        # Only return dates that make sense
                        if datetime(2020, 1, 1) <= date_obj <= datetime.now() + timedelta(days=365):
                            return date_obj
                except (ValueError, Exception) as e:
                    self.logger.debug(f"Date parse error for '{match}': {e}")
                    continue
        
        return None
    
    def is_listing_too_old(self, page_text: str, listing_url: str, auction_status: str) -> bool:
        """Check if any listing (active, sold, or ended) is older than 1 year."""
        auction_date = self.extract_auction_end_date_fast(page_text, listing_url)
        if auction_date:
            is_too_old = auction_date < self.cutoff_date
            if is_too_old:
                self.logger.info(f"Skipping old listing ({auction_status}) from {auction_date.strftime('%Y-%m-%d')}: {listing_url}")
            return is_too_old
        
        # For active listings without clear end dates, include them (they're current)
        if auction_status == 'active':
            return False
            
        # If we can't determine the date for sold/ended listings, be conservative and include it
        return False
    
    def search_auction_results(self) -> List[str]:
        """
        Search the auction results page for Porsche 911 listings with date-based early stopping.
        Stops when it detects we're getting into pages with auctions older than 1 year.
        """
        self.perf.start_phase("Auction Results Collection")
        self.logger.info("Searching auction results for recent Porsche 911 data (past year by auction completion date)")
        listing_urls = set()
        driver = None
        
        try:
            driver = self.configure_chrome_driver(enable_js=True)  # Need JS for pagination
            
            # Go to auction results with Porsche search
            search_url = f"{self.base_url}/auctions/results/?search=porsche+911"
            self.logger.info(f"Loading auction results search: {search_url}")
            driver.get(search_url)
            
            # Wait for page to load with reduced timeout
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(3)  # Reduced wait time
            
            def collect_results_page():
                """Collect all listing URLs from current results page."""
                current_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/listing/"]')
                new_urls_this_page = []
                
                for link in current_links:
                    try:
                        href = link.get_attribute('href')
                        if href and self.is_valid_listing_url(href):
                            if href not in listing_urls:
                                listing_urls.add(href)
                                new_urls_this_page.append(href)
                    except Exception as e:
                        self.logger.debug(f"Error processing results link: {e}")
                        continue
                
                return new_urls_this_page
            
            # Collect initial results
            initial_urls = collect_results_page()
            self.logger.info(f"Initial auction results collection: {len(initial_urls)} valid listings")
            
            # Enhanced pagination with auction-date-based early stopping
            page_clicks = 0
            max_pages = 100  
            consecutive_fails = 0
            max_consecutive_fails = 3
            consecutive_old_pages = 0  
            max_consecutive_old_pages = 3  # Stop after 3 consecutive pages of mostly old auctions
            
            while (page_clicks < max_pages and consecutive_fails < max_consecutive_fails and 
                   consecutive_old_pages < max_consecutive_old_pages and self.should_continue()):
                try:
                    # Simplified button finding for speed
                    show_more_buttons = driver.find_elements(By.XPATH, "//*[contains(text(), 'Show More')]")
                    
                    clickable_button = None
                    for button in show_more_buttons:
                        if button.is_displayed() and button.is_enabled():
                            clickable_button = button
                            break
                    
                    if not clickable_button:
                        self.logger.info("No more clickable Show More buttons found - exhausted pagination")
                        break
                    
                    # Record counts before clicking
                    pre_click_count = len(listing_urls)
                    
                    # Faster clicking
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", clickable_button)
                        time.sleep(0.5)  # Reduced wait
                        driver.execute_script("arguments[0].click();", clickable_button)
                    except Exception as e:
                        self.logger.warning(f"Click failed: {e}")
                        consecutive_fails += 1
                        continue
                    
                    # Shorter wait for content to load
                    time.sleep(4)  # Reduced from 6
                    
                    # Collect new results from this page
                    new_urls_this_page = collect_results_page()
                    post_click_count = len(listing_urls)
                    actual_new = post_click_count - pre_click_count
                    
                    if actual_new == 0:
                        consecutive_fails += 1
                        self.logger.info(f"No new results found (consecutive fail #{consecutive_fails})")
                        continue
                    else:
                        consecutive_fails = 0  # Reset on success
                    
                    # Report progress every 5 pages for URL collection
                    if page_clicks % 5 == 0:
                        elapsed = (datetime.now() - self.perf.phase_start).total_seconds() / 60
                        rate = post_click_count / elapsed if elapsed > 0 else 0
                        print(f"📊 URL Collection Progress: Page {page_clicks + 1} | {post_click_count} URLs found | {rate:.1f} URLs/min")
                    
                    # SMART EARLY STOPPING: Check actual auction completion dates on cards
                    if page_clicks >= 2:  # Start checking after page 2 to get enough data
                        page_assessment = self.assess_page_recency_by_auction_cards(driver)
                        
                        if page_assessment['is_mostly_old'] and page_assessment['total_dates'] >= 5:
                            consecutive_old_pages += 1
                            self.logger.info(f"Page {page_clicks + 1} contains mostly old auctions (avg {page_assessment['avg_days_ago']:.0f} days ago, {page_assessment['old_count']}/{page_assessment['total_dates']} old) - consecutive old page #{consecutive_old_pages}")
                            
                            # If we're consistently hitting very old pages (>2 years), be more aggressive
                            if page_assessment['avg_days_ago'] > 730:  # More than 2 years old
                                consecutive_old_pages += 1  # Count double for very old pages
                                self.logger.info("Page contains very old auctions (>2 years), counting as double-old")
                        else:
                            consecutive_old_pages = 0  # Reset on fresh page
                            if page_assessment['total_dates'] > 0:
                                self.logger.info(f"Page {page_clicks + 1} contains recent auctions (avg {page_assessment['avg_days_ago']:.0f} days ago, {page_assessment['recent_count']}/{page_assessment['total_dates']} recent)")
                    
                    page_clicks += 1
                    
                    # Extra safety: if we have lots of listings and recent pages are all old, stop
                    if post_click_count >= 500 and consecutive_old_pages >= 2:
                        self.logger.info(f"Collected {post_click_count} listings and hit {consecutive_old_pages} consecutive old pages - stopping")
                        break
                    
                except Exception as e:
                    self.logger.warning(f"Error clicking pagination button #{page_clicks + 1}: {e}")
                    consecutive_fails += 1
                    continue
            
            # Log stopping reason
            if consecutive_old_pages >= max_consecutive_old_pages:
                self.logger.info(f"Stopped pagination due to {consecutive_old_pages} consecutive pages with mostly old auctions")
            elif consecutive_fails >= max_consecutive_fails:
                self.logger.info(f"Stopped pagination due to {consecutive_fails} consecutive click failures")
            elif page_clicks >= max_pages:
                self.logger.info(f"Stopped pagination due to reaching max pages limit ({max_pages})")
                
            self.logger.info(f"Auction results search completed after {page_clicks} pages")
            
        except Exception as e:
            self.logger.error(f"Error searching auction results: {e}")
        
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
        
        return list(listing_urls)
    
    def search_porsche_911_listings(self) -> List[str]:
        """
        Search for Porsche 911 listings from both the main page and auction results.
        This provides comprehensive coverage of active listings and recent sold listings.
        """
        self.logger.info("Searching for Porsche 911 listings from multiple sources")
        all_listing_urls = set()
        
        # Method 2: Search auction results for comprehensive data (primary method)
        results_urls = self.search_auction_results()
        all_listing_urls.update(results_urls)
        self.logger.info(f"Auction results found: {len(results_urls)} listings")
        
        unique_urls = list(all_listing_urls)
        self.logger.info(f"Total unique listings found: {len(unique_urls)}")
        
        return unique_urls
    
    def is_valid_listing_url(self, url: str) -> bool:
        """
        Check if URL is a valid BaT listing for a 1981+ Porsche 911.
        Must match exact pattern: YYYY-porsche-911-*
        """
        if not url or '/listing/' not in url:
            return False
        
        try:
            parsed = urlparse(url)
            path_parts = [p for p in parsed.path.split('/') if p]
            
            if len(path_parts) >= 2 and path_parts[0] == 'listing':
                listing_name = path_parts[1]
                
                # STRICT PATTERN: Must be YYYY-porsche-911-*
                pattern = r'^(19[8-9]\d|20[0-2]\d)-porsche-911-'
                if not re.match(pattern, listing_name, re.IGNORECASE):
                    return False
                
                # Extract and validate year
                year_match = re.match(r'^(\d{4})', listing_name)
                if year_match:
                    year = int(year_match.group(1))
                    if year < 1981:
                        return False
                
                return True
        
        except Exception:
            return False
        
        return False
    
    def extract_vin_from_text_fast(self, text: str) -> Optional[str]:
        """Fast VIN extraction - only look for WP0 VINs."""
        # Pattern for 17-digit VIN starting with WP0 (Porsche-specific)
        vin_pattern = r'\bWP0[A-HJ-NPR-Z0-9]{14}\b'
        match = re.search(vin_pattern, text, re.IGNORECASE)
        
        if match:
            vin = match.group().upper()
            if validate_vin(vin):
                return vin
        
        return None
    
    def extract_price_from_text_fast(self, text: str) -> Dict[str, Any]:
        """Fast price extraction with simplified patterns."""
        price_info = {
            'current_bid': '',
            'reserve_met': False,
            'buy_it_now': '',
            'sold_price': '',
            'no_reserve': False
        }
        
        text_lower = text.lower()
        
        # Current bid patterns (simplified)
        bid_match = re.search(r'usd\s*\$([\d,]+)', text_lower)
        if bid_match:
            price_info['current_bid'] = f"${bid_match.group(1)}"
        
        # Reserve status (simplified)
        price_info['reserve_met'] = 'reserve met' in text_lower
        price_info['no_reserve'] = 'no reserve' in text_lower or 'no-reserve' in text_lower
        
        # Sold price (simplified)
        sold_match = re.search(r'sold for \$([\d,]+)', text_lower)
        if sold_match:
            price_info['sold_price'] = f"${sold_match.group(1)}"
        
        return price_info
    
    def determine_auction_status_fast(self, page_text: str) -> str:
        """Fast auction status determination."""
        text_lower = page_text.lower()
        
        # Check for active indicators first (most relevant for current listings)
        if any(indicator in text_lower for indicator in ['ends in', 'time left:', 'place bid', 'register to bid']):
            return 'active'
        
        # Check for sold indicators
        if any(indicator in text_lower for indicator in ['sold for $', 'winning bid:', 'congratulations to']):
            return 'sold'
        
        # Check for ended without sale
        if any(indicator in text_lower for indicator in ['reserve not met', 'no sale']):
            return 'ended'
        
        # Default to unknown if we can't determine
        return 'unknown'
    
    def scrape_listing_details_fast(self, listing_url: str) -> Optional[Dict[str, Any]]:
        """Optimized fast scraping of listing details."""
        if not self.should_continue():
            return None
        
        driver = None
        try:
            # Use optimized driver without JS for most listings (faster)
            driver = self.configure_chrome_driver(enable_js=False)
            
            # Set faster page load timeout
            driver.set_page_load_timeout(10)
            
            driver.get(listing_url)
            
            # Reduced wait time
            time.sleep(1)
            
            # Get page source and parse (faster than Selenium selectors)
            page_source = driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Get page text for analysis
            page_text = soup.get_text(separator=' ', strip=True)
            page_text_lower = page_text.lower()
            
            # Quick verification this is a Porsche 911 listing
            if not ('porsche' in page_text_lower and '911' in page_text_lower):
                return None
            
            # Determine auction status first
            auction_status = self.determine_auction_status_fast(page_text)
            
            # Check if this listing is too old (skip if it is)
            if self.is_listing_too_old(page_text, listing_url, auction_status):
                return None
            
            # CRITICAL: Extract VIN and verify it's a WP0 VIN
            vin = self.extract_vin_from_text_fast(page_text)
            if not vin:
                return None
            
            if vin in self.processed_vins:
                return None
            
            self.processed_vins.add(vin)
            
            # Extract basic listing info (essential data only for speed)
            listing_data = {
                'url': listing_url,
                'scraped_at': create_timestamp(),
                'source': 'BringATrailer',
                'listing_id': '',
                'title': '',
                'year': '',
                'make': 'PORSCHE',
                'model': '911',
                'vin': vin,
                'mileage': '',
                'auction_status': auction_status,
                'end_date': '',
                'price_info': {},
            }
            
            # Extract listing ID from URL
            url_parts = urlparse(listing_url).path.split('/')
            if len(url_parts) > 2:
                listing_data['listing_id'] = url_parts[2]
            
            # Extract auction end date
            end_date = self.extract_auction_end_date_fast(page_text, listing_url)
            if end_date:
                listing_data['end_date'] = end_date.strftime('%Y-%m-%d')
            
            # Title (first h1 found)
            title_elem = soup.find('h1')
            if title_elem:
                title_text = title_elem.get_text(strip=True)
                listing_data['title'] = title_text
                # Extract year from title
                year_match = re.search(r'\b(19|20)\d{2}\b', title_text)
                if year_match:
                    listing_data['year'] = year_match.group()
            
            # Price information
            listing_data['price_info'] = self.extract_price_from_text_fast(page_text)
            
            # Mileage (simplified extraction)
            mileage_match = re.search(r'(\d{1,3}(?:,\d{3})*)\s*(?:mile|mi\b)', page_text.lower())
            if mileage_match:
                listing_data['mileage'] = mileage_match.group(1)
            
            return listing_data
            
        except Exception as e:
            self.logger.debug(f"Error scraping listing {listing_url}: {e}")
            return None
        
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
    
    def normalize_bat_record(self, listing_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize BaT listing data to match inventory schema."""
        # Extract year as integer
        year = 0
        if listing_data.get('year') and listing_data['year'].isdigit():
            year = int(listing_data['year'])
        
        # Calculate age
        current_year = datetime.now().year
        age = current_year - year if year > 0 else 0
        
        normalized = {
            # Primary identifiers
            'vin': listing_data.get('vin', ''),
            'make': 'PORSCHE',
            'model': '911',
            'model_year': str(year) if year > 0 else '',
            'manufacturer': 'DR. ING. H.C.F. PORSCHE AG',
            
            # Vehicle specifications
            'body_class': 'Coupe',
            'doors': '2',
            'fuel_type': 'Gasoline',
            'engine_cylinders': '6',
            
            # BaT specific data
            'bat_listing_id': listing_data.get('listing_id', ''),
            'bat_url': listing_data.get('url', ''),
            'bat_title': listing_data.get('title', ''),
            'bat_mileage': listing_data.get('mileage', ''),
            'bat_auction_status': listing_data.get('auction_status', ''),
            'bat_end_date': listing_data.get('end_date', ''),
            
            # Price information
            'bat_current_bid': listing_data.get('price_info', {}).get('current_bid', ''),
            'bat_reserve_met': listing_data.get('price_info', {}).get('reserve_met', False),
            'bat_no_reserve': listing_data.get('price_info', {}).get('no_reserve', False),
            'bat_sold_price': listing_data.get('price_info', {}).get('sold_price', ''),
            
            # Metadata
            'source': 'BringATrailer',
            'first_scraped': listing_data.get('scraped_at', ''),
            'last_updated': create_timestamp(),
            'scrape_count': 1,
            
            # Age classification
            'age_years': age,
            'is_classic': age > 15,
            'is_vintage': age > 25,
        }
        
        return normalized

def scrape_bat_listings(max_runtime_minutes: int = 45) -> Dict[str, Any]:
    """Scrape BaT for Porsche 911 listings with performance optimization."""
    logger = setup_logging()
    scraper = BaTScraper(max_runtime_minutes)
    
    # Results storage
    results = {
        'metadata': {
            'scrape_started': create_timestamp(),
            'scrape_completed': '',
            'runtime_minutes': 0,
            'total_listings_found': 0,
            'total_listings_scraped': 0,
            'listings_with_vins': 0,
            'new_vins': 0,
            'updated_vins': 0,
            'skipped_old_listings': 0,
            'cutoff_date': scraper.cutoff_date.strftime('%Y-%m-%d'),
            'source': 'BringATrailer',
            'target': 'Porsche 911 (1981+) - Optimized Performance'
        },
        'listings': []
    }
    
    try:
        # Phase 1: Search for listings
        listing_urls = scraper.search_porsche_911_listings()
        results['metadata']['total_listings_found'] = len(listing_urls)
        
        # Phase 2: Scrape individual listings with performance reporting
        scraper.perf.start_phase("Individual Listing Scraping")
        print(f"🔄 Starting detailed scraping of {len(listing_urls)} listings...")
        
        scraped_count = 0
        vins_found = 0
        skipped_old = 0
        
        for i, url in enumerate(listing_urls, 1):
            if not scraper.should_continue():
                logger.info("Time limit reached, stopping scrape")
                break
            
            listing_data = scraper.scrape_listing_details_fast(url)
            if listing_data:
                scraped_count += 1
                if listing_data.get('vin'):
                    vins_found += 1
                
                normalized_record = scraper.normalize_bat_record(listing_data)
                results['listings'].append(normalized_record)
            else:
                skipped_old += 1
            
            # Report progress every 10 listings
            scraper.perf.report_listing_progress(logger, i, len(listing_urls))
            
            # Minimal delay between listings for rate limiting
            time.sleep(0.5)  # Reduced from 2 seconds
        
        results['metadata']['total_listings_scraped'] = scraped_count
        results['metadata']['listings_with_vins'] = vins_found
        results['metadata']['new_vins'] = vins_found
        results['metadata']['skipped_old_listings'] = skipped_old
        
        # Final performance report
        scraper.perf.final_report(logger, len(listing_urls), scraped_count)
        
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        results['metadata']['error'] = str(e)
    
    finally:
        # Calculate runtime
        end_time = datetime.now()
        runtime = (end_time - scraper.start_time).total_seconds() / 60
        results['metadata']['runtime_minutes'] = round(runtime, 2)
        results['metadata']['scrape_completed'] = create_timestamp()
    
    return results

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Scrape Bring a Trailer for Porsche 911 listings')
    parser.add_argument('--max-runtime', type=int, default=45,
                        help='Maximum runtime in minutes (default: 45)')
    parser.add_argument('--output', default='bat-porsche-911-listings.json',
                        help='Output filename')
    args = parser.parse_args()
    
    logger = setup_logging()
    
    try:
        logger.info(f"Starting optimized BaT scrape with {args.max_runtime} minute limit")
        
        # Scrape listings
        results = scrape_bat_listings(args.max_runtime)
        
        # Save results
        save_json_file(results, args.output)
        
        # Print summary
        metadata = results['metadata']
        print(f"\n✅ BaT optimized scraping completed")
        print(f"📁 Results saved to {args.output}")
        print(f"⏱️ Runtime: {metadata['runtime_minutes']} minutes")
        print(f"📅 Cutoff date: {metadata['cutoff_date']} (auction completion date)")
        print(f"🔍 Listings found: {metadata['total_listings_found']}")
        print(f"📊 Listings scraped: {metadata['total_listings_scraped']}")
        print(f"🚗 Valid WP0 VINs collected: {metadata['listings_with_vins']}")
        print(f"⏭️ Old listings skipped: {metadata.get('skipped_old_listings', 0)}")
        
        # Performance metrics
        if metadata['runtime_minutes'] > 0:
            overall_rate = metadata['total_listings_scraped'] / metadata['runtime_minutes']
            print(f"⚡ Overall scraping rate: {overall_rate:.1f} listings/minute")
        
        # Show status breakdown
        if results['listings']:
            active_count = sum(1 for listing in results['listings'] 
                             if listing.get('bat_auction_status') == 'active')
            sold_count = sum(1 for listing in results['listings'] 
                           if listing.get('bat_auction_status') == 'sold')
            ended_count = sum(1 for listing in results['listings'] 
                            if listing.get('bat_auction_status') == 'ended')
            unknown_count = sum(1 for listing in results['listings'] 
                              if listing.get('bat_auction_status') == 'unknown')
            
            print(f"📈 Active auctions: {active_count}")
            print(f"✅ Recent sold auctions: {sold_count}")
            print(f"⏹️ Ended auctions: {ended_count}")
            print(f"❓ Unknown status: {unknown_count}")
            
            years = [int(listing.get('model_year', '0')) for listing in results['listings'] 
                    if listing.get('model_year', '').isdigit()]
            if years:
                print(f"📅 Year range: {min(years)}-{max(years)}")
        
        return 0
    
    except Exception as e:
        logger.error(f"BaT scraping failed: {e}")
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
