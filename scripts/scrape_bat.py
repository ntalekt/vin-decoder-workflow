#!/usr/bin/env python3
"""
Bring a Trailer scraper for Porsche 911 listings (1981+).
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
    
    def configure_chrome_driver(self) -> webdriver.Chrome:
        """Configure Chrome driver for BaT scraping."""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return driver
    
    def should_continue(self) -> bool:
        """Check if scraping should continue based on time limit."""
        elapsed = datetime.now() - self.start_time
        return elapsed < self.max_runtime
    
    def extract_auction_date_from_page_preview(self, page_html: str) -> Optional[datetime]:
        """Extract auction end dates from the auction results page HTML (not individual listing pages)."""
        soup = BeautifulSoup(page_html, 'html.parser')
        
        # Common patterns for auction dates on results pages
        date_patterns = [
            # Look for elements containing dates
            r'(\w+\s+\d{1,2},\s+\d{4})',  # "September 18, 2024"
            r'(\w{3}\s+\d{1,2},\s+\d{4})',  # "Sep 18, 2024"
            r'(\d{1,2}/\d{1,2}/\d{4})',     # "09/18/2024"
            r'(\d{4}-\d{2}-\d{2})',         # "2024-09-18"
        ]
        
        # Get all text from the page
        page_text = soup.get_text()
        
        dates_found = []
        for pattern in date_patterns:
            matches = re.findall(pattern, page_text, re.IGNORECASE)
            for match in matches:
                try:
                    # Try different date formats
                    date_formats = [
                        '%B %d, %Y',   # September 18, 2024
                        '%b %d, %Y',   # Sep 18, 2024
                        '%m/%d/%Y',    # 09/18/2024
                        '%Y-%m-%d'     # 2024-09-18
                    ]
                    
                    for fmt in date_formats:
                        try:
                            date_obj = datetime.strptime(match.strip(), fmt)
                            # Only consider dates that make sense (not in future, not too old)
                            if date_obj <= datetime.now() and date_obj >= datetime(2020, 1, 1):
                                dates_found.append(date_obj)
                                break
                        except ValueError:
                            continue
                except Exception:
                    continue
        
        # Return the most recent date found (should be representative of the page)
        return max(dates_found) if dates_found else None
    
    def assess_page_recency_by_dates(self, driver) -> dict:
        """Assess how recent the auction end dates are on the current page."""
        try:
            page_html = driver.page_source
            
            # Look for date information in various elements
            date_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '2024') or contains(text(), '2023') or contains(text(), '2022') or contains(text(), '2021')]")
            
            dates_found = []
            current_year = datetime.now().year
            
            for element in date_elements[:20]:  # Limit to first 20 elements to avoid processing too much
                try:
                    element_text = element.text.strip()
                    if not element_text:
                        continue
                    
                    # Look for date patterns in the element text
                    date_patterns = [
                        r'(\w+\s+\d{1,2},\s+\d{4})',  # "September 18, 2024"
                        r'(\w{3}\s+\d{1,2},\s+\d{4})',  # "Sep 18, 2024" 
                        r'(\d{1,2}/\d{1,2}/\d{4})',     # "09/18/2024"
                    ]
                    
                    for pattern in date_patterns:
                        matches = re.findall(pattern, element_text, re.IGNORECASE)
                        for match in matches:
                            try:
                                date_formats = ['%B %d, %Y', '%b %d, %Y', '%m/%d/%Y']
                                for fmt in date_formats:
                                    try:
                                        date_obj = datetime.strptime(match.strip(), fmt)
                                        if date_obj <= datetime.now() and date_obj >= datetime(2022, 1, 1):
                                            dates_found.append(date_obj)
                                            break
                                    except ValueError:
                                        continue
                            except:
                                continue
                                
                except Exception:
                    continue
            
            if not dates_found:
                self.logger.info("No auction dates found on page - assuming mixed content")
                return {'is_mostly_old': False, 'recent_count': 1, 'old_count': 0, 'avg_days_ago': 100}
            
            # Calculate how old these auctions are
            now = datetime.now()
            days_ago_list = [(now - date).days for date in dates_found]
            avg_days_ago = sum(days_ago_list) / len(days_ago_list)
            
            # Count recent vs old based on our 1-year cutoff (365 days)
            recent_count = sum(1 for days in days_ago_list if days <= 365)
            old_count = sum(1 for days in days_ago_list if days > 365)
            
            # Consider page mostly old if more than 70% of auctions are older than 1 year
            is_mostly_old = (old_count / len(days_ago_list)) > 0.7 if len(days_ago_list) > 0 else False
            
            self.logger.info(f"Page date analysis: {recent_count} recent auctions, {old_count} old auctions, avg {avg_days_ago:.0f} days ago - {'MOSTLY OLD' if is_mostly_old else 'RECENT/MIXED'}")
            
            return {
                'is_mostly_old': is_mostly_old,
                'recent_count': recent_count,
                'old_count': old_count,
                'total_dates': len(dates_found),
                'avg_days_ago': avg_days_ago,
                'oldest_days': max(days_ago_list) if days_ago_list else 0,
                'newest_days': min(days_ago_list) if days_ago_list else 0
            }
            
        except Exception as e:
            self.logger.warning(f"Error analyzing page dates: {e}")
            return {'is_mostly_old': False, 'recent_count': 1, 'old_count': 0, 'avg_days_ago': 100}
    
    def extract_auction_end_date(self, page_text: str, listing_url: str) -> Optional[datetime]:
        """Extract auction end date from individual listing page text."""
        # Common date patterns on BaT
        date_patterns = [
            # "Ended September 16, 2024"
            r'ended\s+(\w+\s+\d{1,2},\s+\d{4})',
            # "Auction ended on September 16, 2024"
            r'auction ended on\s+(\w+\s+\d{1,2},\s+\d{4})',
            # "September 16, 2024" in various contexts
            r'(\w+\s+\d{1,2},\s+\d{4})',
            # "Sep 16, 2024"
            r'(\w{3}\s+\d{1,2},\s+\d{4})',
            # "2024-09-16" format
            r'(\d{4}-\d{2}-\d{2})'
        ]
        
        text_lower = page_text.lower()
        
        for pattern in date_patterns:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                try:
                    # Try different date formats
                    date_formats = [
                        '%B %d, %Y',   # September 16, 2024
                        '%b %d, %Y',   # Sep 16, 2024
                        '%Y-%m-%d'     # 2024-09-16
                    ]
                    
                    for fmt in date_formats:
                        try:
                            date_obj = datetime.strptime(match.strip(), fmt)
                            # Only return dates that make sense (not in future, not too old)
                            if date_obj <= datetime.now() and date_obj >= datetime(2020, 1, 1):
                                return date_obj
                        except ValueError:
                            continue
                except Exception:
                    continue
        
        return None
    
    def is_listing_too_old(self, page_text: str, listing_url: str, auction_status: str) -> bool:
        """Check if any listing (active, sold, or ended) is older than 1 year."""
        auction_date = self.extract_auction_end_date(page_text, listing_url)
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
        self.logger.info("Searching auction results for recent Porsche 911 data (past year by auction date)")
        listing_urls = set()
        driver = None
        
        try:
            driver = self.configure_chrome_driver()
            
            # Go to auction results with Porsche search
            search_url = f"{self.base_url}/auctions/results/?search=porsche+911"
            self.logger.info(f"Loading auction results search: {search_url}")
            driver.get(search_url)
            
            # Wait for page to load
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(5)
            
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
                                self.logger.info(f"DEBUG: Added auction result: {href}")
                    except Exception as e:
                        self.logger.debug(f"Error processing results link: {e}")
                        continue
                
                return new_urls_this_page
            
            # Collect initial results
            initial_urls = collect_results_page()
            self.logger.info(f"Initial auction results collection: {len(initial_urls)} valid listings")
            
            # Enhanced pagination with date-based early stopping
            page_clicks = 0
            max_pages = 100  
            consecutive_fails = 0
            max_consecutive_fails = 3
            consecutive_old_pages = 0  
            max_consecutive_old_pages = 3  # Stop after 3 consecutive pages of mostly old auctions
            
            while (page_clicks < max_pages and consecutive_fails < max_consecutive_fails and 
                   consecutive_old_pages < max_consecutive_old_pages and self.should_continue()):
                try:
                    # Multiple strategies to find Show More buttons
                    show_more_selectors = [
                        "//*[contains(text(), 'Show More')]",
                        "//*[contains(text(), 'Load More')]",
                        "//*[contains(text(), 'See More')]",
                        "//*[contains(text(), 'View More')]",
                        "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show more')]",
                        "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'load more')]",
                        "//button[contains(text(), 'Show More')]",
                        "//button[contains(text(), 'Load More')]",
                        "//a[contains(text(), 'Show More')]",
                        "//a[contains(text(), 'Load More')]",
                        "//*[contains(@class, 'show-more')]",
                        "//*[contains(@class, 'load-more')]",
                        "//*[contains(@class, 'more-results')]",
                        "//*[contains(@id, 'show-more')]",
                        "//*[contains(@id, 'load-more')]"
                    ]
                    
                    clickable_button = None
                    button_info = ""
                    
                    # Try each selector until we find a clickable button
                    for selector in show_more_selectors:
                        try:
                            buttons = driver.find_elements(By.XPATH, selector)
                            self.logger.info(f"DEBUG: Selector '{selector}' found {len(buttons)} elements")
                            
                            for i, button in enumerate(buttons):
                                try:
                                    button_text = button.text.strip()
                                    tag_name = button.tag_name
                                    is_displayed = button.is_displayed()
                                    is_enabled = button.is_enabled()
                                    
                                    self.logger.info(f"DEBUG: Button {i+1}: <{tag_name}> '{button_text}' - Displayed: {is_displayed}, Enabled: {is_enabled}")
                                    
                                    if is_displayed and is_enabled and button_text:
                                        clickable_button = button
                                        button_info = f"<{tag_name}> '{button_text}' via selector: {selector}"
                                        break
                                except Exception as e:
                                    self.logger.debug(f"Error checking button {i+1}: {e}")
                                    continue
                            
                            if clickable_button:
                                break
                                
                        except Exception as e:
                            self.logger.debug(f"Error with selector '{selector}': {e}")
                            continue
                    
                    if not clickable_button:
                        self.logger.info("No more clickable Show More buttons found - exhausted pagination")
                        break
                    
                    # Record counts before clicking
                    pre_click_count = len(listing_urls)
                    self.logger.info(f"DEBUG: Clicking pagination button #{page_clicks + 1}: {button_info}")
                    
                    # Enhanced clicking with multiple attempts
                    click_successful = False
                    for attempt in range(3):
                        try:
                            # Scroll button into view
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", clickable_button)
                            time.sleep(1)
                            
                            # Try regular click first
                            try:
                                clickable_button.click()
                                click_successful = True
                                break
                            except Exception:
                                # Fallback to JavaScript click
                                driver.execute_script("arguments[0].click();", clickable_button)
                                click_successful = True
                                break
                        except Exception as e:
                            self.logger.warning(f"Click attempt {attempt + 1} failed: {e}")
                            time.sleep(1)
                            continue
                    
                    if not click_successful:
                        self.logger.warning("All click attempts failed, moving to next iteration")
                        consecutive_fails += 1
                        continue
                    
                    # Wait longer for content to load (auction results can be slow)
                    time.sleep(6)
                    
                    # Collect new results from this page
                    new_urls_this_page = collect_results_page()
                    post_click_count = len(listing_urls)
                    actual_new = post_click_count - pre_click_count
                    
                    self.logger.info(f"Found {actual_new} new auction results (total: {post_click_count})")
                    
                    if actual_new == 0:
                        consecutive_fails += 1
                        self.logger.info(f"No new results found (consecutive fail #{consecutive_fails})")
                        continue
                    else:
                        consecutive_fails = 0  # Reset on success
                    
                    # SMART EARLY STOPPING: Check if this page has mostly old auction dates
                    if page_clicks >= 5:  # Only start checking after page 5
                        page_assessment = self.assess_page_recency_by_dates(driver)
                        
                        if page_assessment['is_mostly_old']:
                            consecutive_old_pages += 1
                            self.logger.info(f"Page {page_clicks + 1} contains mostly old auctions (avg {page_assessment['avg_days_ago']:.0f} days ago) - consecutive old page #{consecutive_old_pages}")
                            
                            # If we're consistently hitting very old pages (>2 years), be more aggressive
                            if page_assessment['avg_days_ago'] > 730:  # More than 2 years old
                                consecutive_old_pages += 1  # Count double for very old pages
                                self.logger.info("Page contains very old auctions (>2 years), counting as double-old")
                        else:
                            consecutive_old_pages = 0  # Reset on fresh page
                            self.logger.info(f"Page {page_clicks + 1} contains recent auctions (avg {page_assessment['avg_days_ago']:.0f} days ago)")
                    
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
        
        # Method 1: Search the main Porsche 911 page for current/featured listings
        self.logger.info("Phase 1: Searching main Porsche 911 page")
        main_page_urls = self._search_main_page()
        all_listing_urls.update(main_page_urls)
        self.logger.info(f"Main page found: {len(main_page_urls)} listings")
        
        # Method 2: Search auction results for comprehensive data
        self.logger.info("Phase 2: Searching auction results for recent data")
        results_urls = self.search_auction_results()
        all_listing_urls.update(results_urls)
        self.logger.info(f"Auction results found: {len(results_urls)} listings")
        
        unique_urls = list(all_listing_urls)
        self.logger.info(f"Total unique listings found: {len(unique_urls)}")
        
        return unique_urls
    
    def _search_main_page(self) -> List[str]:
        """Search the main Porsche 911 page for current listings."""
        listing_urls = set()
        driver = None
        
        try:
            driver = self.configure_chrome_driver()
            
            # Go to the Porsche 911 page
            porsche_url = f"{self.base_url}/porsche/911/"
            driver.get(porsche_url)
            
            # Wait for page to load
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(5)
            
            def collect_main_listings():
                """Collect listings from main page."""
                current_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/listing/"]')
                new_urls_added = 0
                
                for link in current_links:
                    try:
                        href = link.get_attribute('href')
                        if href and self.is_valid_listing_url(href):
                            if href not in listing_urls:
                                listing_urls.add(href)
                                new_urls_added += 1
                    except:
                        continue
                
                return new_urls_added
            
            # Initial collection
            collect_main_listings()
            
            # Try clicking Show More buttons on main page
            show_more_clicks = 0
            max_clicks = 10
            
            while show_more_clicks < max_clicks and self.should_continue():
                try:
                    show_more_buttons = driver.find_elements(
                        By.XPATH,
                        "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show more')]"
                    )
                    
                    clickable_button = next(
                        (b for b in show_more_buttons if b.is_displayed() and b.is_enabled()), 
                        None
                    )
                    
                    if not clickable_button:
                        break
                    
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", clickable_button)
                    time.sleep(1)
                    
                    try:
                        clickable_button.click()
                    except:
                        driver.execute_script("arguments[0].click();", clickable_button)
                    
                    time.sleep(4)
                    
                    new_listings = collect_main_listings()
                    if new_listings == 0:
                        break
                    
                    show_more_clicks += 1
                    
                except Exception:
                    break
            
        except Exception as e:
            self.logger.error(f"Error searching main page: {e}")
        
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
        
        return list(listing_urls)
    
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
    
    def extract_vin_from_text(self, text: str) -> Optional[str]:
        """Extract 17-digit VIN starting with WP0 from text content."""
        # Pattern for 17-digit VIN
        vin_pattern = r'\b[A-HJ-NPR-Z0-9]{17}\b'
        matches = re.findall(vin_pattern, text, re.IGNORECASE)
        
        for match in matches:
            vin = match.upper()
            # Only accept Porsche VINs starting with WP0
            if vin.startswith('WP0') and validate_vin(vin):
                return vin
        
        return None
    
    def extract_price_from_text(self, text: str) -> Dict[str, Any]:
        """Extract price information from text."""
        price_info = {
            'current_bid': '',
            'reserve_met': False,
            'buy_it_now': '',
            'sold_price': '',
            'no_reserve': False
        }
        
        text_lower = text.lower()
        
        # Current bid patterns
        bid_patterns = [
            r'bid:\s*usd\s*\$[\d,]+',
            r'current bid[:\s]*\$[\d,]+',
            r'\$[\d,]+\s*current bid',
            r'bid[:\s]*\$[\d,]+',
        ]
        
        for pattern in bid_patterns:
            match = re.search(pattern, text_lower)
            if match:
                price_match = re.search(r'\$[\d,]+', match.group())
                if price_match:
                    price_info['current_bid'] = price_match.group()
                    break
        
        # Reserve status
        if 'reserve met' in text_lower or 'reserve has been met' in text_lower:
            price_info['reserve_met'] = True
        
        if 'no reserve' in text_lower or 'no-reserve' in text_lower:
            price_info['no_reserve'] = True
        
        # Sold price (for auction results)
        sold_patterns = [
            r'sold for \$[\d,]+',
            r'winning bid[:\s]*\$[\d,]+',
            r'final bid[:\s]*\$[\d,]+',
            r'hammer price[:\s]*\$[\d,]+',
        ]
        
        for pattern in sold_patterns:
            match = re.search(pattern, text_lower)
            if match:
                price_match = re.search(r'\$[\d,]+', match.group())
                if price_match:
                    price_info['sold_price'] = price_match.group()
                    break
        
        return price_info
    
    def determine_auction_status(self, page_text: str) -> str:
        """Determine if this is an active auction, sold auction, or ended without sale."""
        text_lower = page_text.lower()
        
        # Check for sold indicators first (most definitive)
        sold_indicators = [
            'sold for $',
            'winning bid:',
            'final bid:',
            'hammer price:',
            'sale completed',
            'auction ended',
            'congratulations to'
        ]
        
        for indicator in sold_indicators:
            if indicator in text_lower:
                return 'sold'
        
        # Check for active auction indicators
        active_indicators = [
            'current bid:',
            'bid: usd $',
            'time left:',
            'days left',
            'hours left',
            'minutes left',
            'bidding ends',
            'reserve not met',
            'reserve met'
        ]
        
        for indicator in active_indicators:
            if indicator in text_lower:
                return 'active'
        
        # Check for ended without sale
        ended_indicators = [
            'reserve not met',
            'auction ended without sale',
            'no sale',
            'did not meet reserve'
        ]
        
        for indicator in ended_indicators:
            if indicator in text_lower:
                return 'ended'
        
        # Default to unknown if we can't determine
        return 'unknown'
    
    def scrape_listing_details(self, listing_url: str) -> Optional[Dict[str, Any]]:
        """Scrape detailed information from a BaT listing."""
        if not self.should_continue():
            return None
        
        self.logger.info(f"Scraping listing: {listing_url}")
        
        driver = None
        try:
            driver = self.configure_chrome_driver()
            driver.get(listing_url)
            
            # Wait for page to load
            wait = WebDriverWait(driver, 15)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            # Give page time to fully load
            time.sleep(3)
            
            # Get page source and parse
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Get page text for analysis
            page_text = soup.get_text(separator=' ', strip=True)
            page_text_lower = page_text.lower()
            
            # Verify this is actually a Porsche 911 listing
            if not ('porsche' in page_text_lower and '911' in page_text_lower):
                self.logger.info(f"Not a Porsche 911 listing, skipping: {listing_url}")
                return None
            
            # Determine auction status first
            auction_status = self.determine_auction_status(page_text)
            
            # Check if this listing is too old (skip if it is)
            if self.is_listing_too_old(page_text, listing_url, auction_status):
                return None
            
            # CRITICAL: Extract VIN and verify it's a WP0 VIN
            vin = self.extract_vin_from_text(page_text)
            if not vin:
                self.logger.info(f"No valid WP0 VIN found, skipping: {listing_url}")
                return None
            
            if vin in self.processed_vins:
                self.logger.info(f"VIN {vin} already processed, skipping")
                return None
            
            self.processed_vins.add(vin)
            
            # Extract basic listing info
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
                'location': '',
                'seller_type': '',
                'auction_status': auction_status,
                'end_date': '',
                'price_info': {},
                'description': '',
                'specifications': {},
                'features': [],
                'condition_notes': [],
                'service_history': [],
                'modifications': [],
                'photos': []
            }
            
            # Extract listing ID from URL
            url_parts = urlparse(listing_url).path.split('/')
            if len(url_parts) > 2:
                listing_data['listing_id'] = url_parts[2]
            
            # Extract auction end date
            end_date = self.extract_auction_end_date(page_text, listing_url)
            if end_date:
                listing_data['end_date'] = end_date.strftime('%Y-%m-%d')
            
            # Title and basic info
            title_selectors = ['h1', '.listing-title', '.auction-title', 'title']
            for selector in title_selectors:
                title_elem = soup.find(selector)
                if title_elem:
                    title_text = title_elem.get_text(strip=True)
                    if title_text and len(title_text) > 5:  # Valid title
                        listing_data['title'] = title_text
                        # Extract year from title
                        year_match = re.search(r'\b(19|20)\d{2}\b', title_text)
                        if year_match:
                            listing_data['year'] = year_match.group()
                        break
            
            # Price information
            listing_data['price_info'] = self.extract_price_from_text(page_text)
            
            # Extract full details for comprehensive data collection
            # Mileage
            mileage_patterns = [
                r'(\d{1,3}(?:,\d{3})*)\s*(?:mile|mi\b)',
                r'showing\s*(\d{1,3}(?:,\d{3})*)',
                r'odometer[:\s]+(\d{1,3}(?:,\d{3})*)',
            ]
            
            for pattern in mileage_patterns:
                match = re.search(pattern, page_text.lower())
                if match:
                    listing_data['mileage'] = match.group(1)
                    break
            
            # Location
            location_patterns = [
                r'(?:location|located)[:\s]+([^,\n]+(?:,\s*[A-Z]{2})?)',
                r'seller[:\s]+[^,\n]+[,\s]+([^,\n]+(?:,\s*[A-Z]{2})?)',
            ]
            
            for pattern in location_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    listing_data['location'] = match.group(1).strip()
                    break
            
            # Specifications
            specs_text = page_text.lower()
            
            # Engine
            engine_patterns = [
                r'(\d\.\d)\s*(?:l|liter)',
                r'(\d,?\d{3})\s*cc',
            ]
            
            for pattern in engine_patterns:
                match = re.search(pattern, specs_text)
                if match:
                    listing_data['specifications']['engine'] = match.group(1)
                    break
            
            # Transmission
            if any(word in specs_text for word in ['manual', 'stick', '5-speed', '6-speed']):
                listing_data['specifications']['transmission'] = 'Manual'
            elif any(word in specs_text for word in ['automatic', 'tiptronic', 'pdk']):
                listing_data['specifications']['transmission'] = 'Automatic'
            
            # Drive type
            if any(word in specs_text for word in ['carrera 4', 'c4', 'awd', 'all-wheel']):
                listing_data['specifications']['drive_type'] = 'AWD'
            else:
                listing_data['specifications']['drive_type'] = 'RWD'
            
            # Features
            features = []
            feature_keywords = [
                'sport chrono', 'pasm', 'pdls', 'pccb', 'sport exhaust',
                'sunroof', 'navigation', 'heated seats', 'air conditioning',
                'leather', 'alcantara', 'bose', 'xenon', 'led'
            ]
            
            for keyword in feature_keywords:
                if keyword in specs_text:
                    features.append(keyword.title())
            
            listing_data['features'] = features
            
            # Description
            description_selectors = [
                'div[class*="description"]',
                'div[class*="summary"]',
                'div[class*="content"]',
                '.listing-description',
                '.auction-description'
            ]
            
            for selector in description_selectors:
                description_elem = soup.select_one(selector)
                if description_elem:
                    description = description_elem.get_text(strip=True)[:1000]
                    if len(description) > 20:
                        listing_data['description'] = description
                        break
            
            # Photos
            img_tags = soup.find_all('img')
            photo_urls = []
            for img in img_tags:
                src = img.get('src') or img.get('data-src')
                if src and ('bringatrailer' in src or src.startswith('/')):
                    if src.startswith('/'):
                        src = urljoin(self.base_url, src)
                    photo_urls.append(src)
            
            listing_data['photos'] = photo_urls[:20]
            
            self.logger.info(f"Successfully scraped listing for VIN {vin} (Status: {listing_data['auction_status']}) {listing_data.get('end_date', '')}")
            return listing_data
            
        except Exception as e:
            self.logger.error(f"Error scraping listing {listing_url}: {e}")
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
            'displacement_l': listing_data.get('specifications', {}).get('engine', ''),
            'drive_type': listing_data.get('specifications', {}).get('drive_type', ''),
            
            # BaT specific data
            'bat_listing_id': listing_data.get('listing_id', ''),
            'bat_url': listing_data.get('url', ''),
            'bat_title': listing_data.get('title', ''),
            'bat_mileage': listing_data.get('mileage', ''),
            'bat_location': listing_data.get('location', ''),
            'bat_auction_status': listing_data.get('auction_status', ''),
            'bat_end_date': listing_data.get('end_date', ''),
            'bat_description': listing_data.get('description', ''),
            'bat_features': listing_data.get('features', []),
            'bat_photo_count': len(listing_data.get('photos', [])),
            
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
    """Scrape BaT for Porsche 911 listings."""
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
            'target': 'Porsche 911 (1981+) - Date-Based Smart Stopping'
        },
        'listings': []
    }
    
    try:
        # Search for listings using comprehensive approach
        listing_urls = scraper.search_porsche_911_listings()
        results['metadata']['total_listings_found'] = len(listing_urls)
        
        # Scrape individual listings
        scraped_count = 0
        vins_found = 0
        skipped_old = 0
        
        for url in listing_urls:
            if not scraper.should_continue():
                logger.info("Time limit reached, stopping scrape")
                break
            
            listing_data = scraper.scrape_listing_details(url)
            if listing_data:
                scraped_count += 1
                if listing_data.get('vin'):
                    vins_found += 1
                
                normalized_record = scraper.normalize_bat_record(listing_data)
                results['listings'].append(normalized_record)
            else:
                skipped_old += 1
                
            # Small delay between listings
            time.sleep(2)
        
        results['metadata']['total_listings_scraped'] = scraped_count
        results['metadata']['listings_with_vins'] = vins_found
        results['metadata']['new_vins'] = vins_found
        results['metadata']['skipped_old_listings'] = skipped_old
        
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
        logger.info(f"Starting date-aware BaT scrape with {args.max_runtime} minute limit")
        
        # Scrape listings
        results = scrape_bat_listings(args.max_runtime)
        
        # Save results
        save_json_file(results, args.output)
        
        # Print summary
        metadata = results['metadata']
        print(f"✅ BaT date-aware scraping completed")
        print(f"📁 Results saved to {args.output}")
        print(f"⏱️ Runtime: {metadata['runtime_minutes']} minutes")
        print(f"📅 Cutoff date: {metadata['cutoff_date']} (auction end date)")
        print(f"🔍 Listings found: {metadata['total_listings_found']}")
        print(f"📊 Listings scraped: {metadata['total_listings_scraped']}")
        print(f"🚗 Valid WP0 VINs collected: {metadata['listings_with_vins']}")
        print(f"⏭️ Old listings skipped: {metadata.get('skipped_old_listings', 0)}")
        
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
