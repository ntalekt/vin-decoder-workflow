#!/usr/bin/env python3
"""
Bring a Trailer scraper for Porsche 911 listings (1981+).
- Scrapes both Live Auctions and Auction Results sections
- Clicks all Show More buttons to load complete inventory
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
from urllib.parse import urljoin, urlparse

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
    
    def search_porsche_911_listings(self) -> List[str]:
        """
        Search for Porsche 911 listings from both Live Auctions and Auction Results.
        Clicks all Show More buttons until no more content loads.
        """
        self.logger.info("Searching for Porsche 911 listings on BaT (Live + Results)")
        listing_urls = []
        driver = None
        
        try:
            driver = self.configure_chrome_driver()
            
            # Go to the Porsche 911 page
            porsche_url = f"{self.base_url}/porsche/911/"
            self.logger.info(f"Loading Porsche 911 page: {porsche_url}")
            driver.get(porsche_url)
            
            # Wait for page to load
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Give the page time to fully load
            time.sleep(5)
            
            def collect_current_listings():
                """Collect all valid listing URLs currently visible on page."""
                current_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/listing/"]')
                new_urls = []
                
                for link in current_links:
                    try:
                        href = link.get_attribute('href')
                        if href and self.is_valid_listing_url(href) and href not in listing_urls:
                            new_urls.append(href)
                            self.logger.info(f"DEBUG: Added valid listing: {href}")
                    except Exception as e:
                        self.logger.debug(f"Error processing link: {e}")
                        continue
                
                listing_urls.extend(new_urls)
                return len(new_urls)
            
            # Initial collection
            initial_count = collect_current_listings()
            self.logger.info(f"Initial collection: {initial_count} valid listings found")
            
            # Keep clicking Show More buttons until no more content loads
            show_more_clicks = 0
            max_clicks = 50  # Increased to handle both sections
            consecutive_empty_clicks = 0
            
            while show_more_clicks < max_clicks and consecutive_empty_clicks < 3 and self.should_continue():
                try:
                    # Find all Show More / Load More buttons
                    show_more_buttons = driver.find_elements(
                        By.XPATH, 
                        "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show more') or "
                        "contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'load more') or "
                        "contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'view more')]"
                    )
                    
                    self.logger.info(f"DEBUG: Found {len(show_more_buttons)} potential Show More buttons")
                    
                    # Find a clickable button
                    clickable_button = None
                    for i, button in enumerate(show_more_buttons):
                        try:
                            button_text = button.text.strip()
                            is_displayed = button.is_displayed()
                            is_enabled = button.is_enabled()
                            
                            self.logger.info(f"DEBUG: Button {i+1}: '{button_text}' - Displayed: {is_displayed}, Enabled: {is_enabled}")
                            
                            if is_displayed and is_enabled and button_text:
                                clickable_button = button
                                break
                        except Exception as e:
                            self.logger.debug(f"Error checking button {i+1}: {e}")
                            continue
                    
                    if not clickable_button:
                        self.logger.info("No more clickable Show More buttons found")
                        break
                    
                    # Record current count before clicking
                    pre_click_count = len(listing_urls)
                    
                    self.logger.info(f"DEBUG: Clicking Show More button #{show_more_clicks + 1}: '{clickable_button.text.strip()}'")
                    
                    # Scroll to button and click
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", clickable_button)
                    time.sleep(1)
                    
                    try:
                        clickable_button.click()
                    except Exception:
                        # Fallback to JavaScript click
                        driver.execute_script("arguments[0].click();", clickable_button)
                    
                    # Wait for content to load
                    time.sleep(4)
                    
                    # Collect new listings
                    new_listings_count = collect_current_listings()
                    post_click_count = len(listing_urls)
                    actual_new = post_click_count - pre_click_count
                    
                    self.logger.info(f"DEBUG: After clicking, found {actual_new} new listings (total: {post_click_count})")
                    
                    if actual_new == 0:
                        consecutive_empty_clicks += 1
                        self.logger.info(f"No new listings found (empty click #{consecutive_empty_clicks})")
                    else:
                        consecutive_empty_clicks = 0  # Reset counter
                    
                    show_more_clicks += 1
                    
                except Exception as e:
                    self.logger.warning(f"Error during Show More click #{show_more_clicks + 1}: {e}")
                    consecutive_empty_clicks += 1
                    show_more_clicks += 1
                    continue
            
            self.logger.info(f"Finished clicking Show More buttons after {show_more_clicks} attempts")
            
        except Exception as e:
            self.logger.error(f"Error loading Porsche 911 page: {e}")
        
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
        
        # Remove duplicates while preserving order
        unique_urls = list(dict.fromkeys(listing_urls))
        self.logger.info(f"Final collection: {len(unique_urls)} unique Porsche 911 listings")
        
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
        
        except Exception as e:
            self.logger.debug(f"Error parsing URL {url}: {e}")
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
                'auction_status': 'unknown',
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
            
            # Determine if this is an active auction or completed result
            if 'sold for' in page_text_lower or 'winning bid' in page_text_lower or 'hammer price' in page_text_lower:
                listing_data['auction_status'] = 'sold'
            elif 'current bid' in page_text_lower or 'bid:' in page_text_lower:
                listing_data['auction_status'] = 'active'
            else:
                listing_data['auction_status'] = 'ended'
            
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
            
            # Mileage extraction
            mileage_patterns = [
                r'(\d{1,3}(?:,\d{3})*)\s*(?:mile|mi\b)',
                r'(\d{1,3}(?:,\d{3})*)\s*(?:k|km)\s*(?:mile|mi)',
                r'showing\s*(\d{1,3}(?:,\d{3})*)',
                r'odometer[:\s]+(\d{1,3}(?:,\d{3})*)',
            ]
            
            for pattern in mileage_patterns:
                match = re.search(pattern, page_text.lower())
                if match:
                    listing_data['mileage'] = match.group(1)
                    break
            
            # Location extraction
            location_patterns = [
                r'(?:location|located)[:\s]+([^,\n]+(?:,\s*[A-Z]{2})?)',
                r'seller[:\s]+[^,\n]+[,\s]+([^,\n]+(?:,\s*[A-Z]{2})?)',
            ]
            
            for pattern in location_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    listing_data['location'] = match.group(1).strip()
                    break
            
            # Extract specifications
            specs_text = page_text.lower()
            
            # Engine info
            engine_patterns = [
                r'(\d\.\d)\s*(?:l|liter)',
                r'(\d\.\d)\s*(?:l|liter).*?(?:flat|boxer|engine)',
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
                    if len(description) > 20:  # Valid description
                        listing_data['description'] = description
                        break
            
            # Photo count
            img_tags = soup.find_all('img')
            photo_urls = []
            for img in img_tags:
                src = img.get('src') or img.get('data-src')
                if src and ('bringatrailer' in src or src.startswith('/')):
                    if src.startswith('/'):
                        src = urljoin(self.base_url, src)
                    photo_urls.append(src)
            
            listing_data['photos'] = photo_urls[:20]
            
            self.logger.info(f"Successfully scraped listing for VIN {vin} (Status: {listing_data['auction_status']})")
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
            
            # Engine information
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
            'source': 'BringATrailer',
            'target': 'Porsche 911 (1981+) - Live Auctions + Auction Results'
        },
        'listings': []
    }
    
    try:
        # Search for listings using the dedicated Porsche 911 page
        listing_urls = scraper.search_porsche_911_listings()
        results['metadata']['total_listings_found'] = len(listing_urls)
        
        # Scrape individual listings
        scraped_count = 0
        vins_found = 0
        
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
                
                # Small delay between listings
                time.sleep(3)  # Respectful delay
        
        results['metadata']['total_listings_scraped'] = scraped_count
        results['metadata']['listings_with_vins'] = vins_found
        results['metadata']['new_vins'] = vins_found
        
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
        logger.info(f"Starting BaT scrape with {args.max_runtime} minute limit")
        
        # Scrape listings
        results = scrape_bat_listings(args.max_runtime)
        
        # Save results
        save_json_file(results, args.output)
        
        # Print summary
        metadata = results['metadata']
        print(f"✅ BaT scraping completed")
        print(f"📁 Results saved to {args.output}")
        print(f"⏱️ Runtime: {metadata['runtime_minutes']} minutes")
        print(f"🔍 Listings found: {metadata['total_listings_found']}")
        print(f"📊 Listings scraped: {metadata['total_listings_scraped']}")
        print(f"🚗 Valid WP0 VINs collected: {metadata['listings_with_vins']}")
        
        # Show status breakdown
        if results['listings']:
            active_count = sum(1 for listing in results['listings'] 
                             if listing.get('bat_auction_status') == 'active')
            sold_count = sum(1 for listing in results['listings'] 
                           if listing.get('bat_auction_status') == 'sold')
            ended_count = sum(1 for listing in results['listings'] 
                            if listing.get('bat_auction_status') == 'ended')
            
            print(f"📈 Active auctions: {active_count}")
            print(f"✅ Sold auctions: {sold_count}")
            print(f"⏹️ Ended auctions: {ended_count}")
            
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
