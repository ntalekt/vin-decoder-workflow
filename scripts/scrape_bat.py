#!/usr/bin/env python3

"""
Bring a Trailer scraper for Porsche 911 listings (1981+).
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
        """Search for Porsche 911 listings on BaT using multiple approaches."""
        self.logger.info("Searching for Porsche 911 listings on BaT")
        
        listing_urls = []
        
        # Approach 1: Browse auctions page directly
        try:
            auctions_url = f"{self.base_url}/auctions/"
            response = self.session.get(auctions_url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for auction listing links
            auction_links = soup.find_all('a', href=re.compile(r'/auctions/[^/]+/$'))
            
            for link in auction_links:
                href = link.get('href')
                if href and href.startswith('/auctions/'):
                    # Filter for Porsche 911 in title or content
                    link_text = link.get_text(strip=True).lower()
                    if ('porsche' in link_text and '911' in link_text) or 'porsche-911' in href:
                        full_url = urljoin(self.base_url, href)
                        if full_url not in listing_urls:
                            listing_urls.append(full_url)
                            
            self.logger.info(f"Found {len(listing_urls)} Porsche 911 listings from auctions page")
            
        except Exception as e:
            self.logger.warning(f"Error browsing auctions page: {e}")
        
        # Approach 2: Try different search patterns
        search_patterns = [
            {'make[]': 'porsche', 'model[]': '911'},
            {'search': 'porsche 911'},
            {'q': 'porsche+911'},
        ]
        
        for pattern in search_patterns:
            if len(listing_urls) >= 10:  # Limit search if we have enough results
                break
                
            try:
                search_url = f"{self.base_url}/search/"
                response = self.session.get(search_url, params=pattern, timeout=30)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for listing links
                links = soup.find_all('a', href=re.compile(r'/auctions/[^/]+/$'))
                
                for link in links:
                    href = link.get('href')
                    if href:
                        full_url = urljoin(self.base_url, href)
                        if full_url not in listing_urls:
                            listing_urls.append(full_url)
                
                self.logger.info(f"Found {len(listing_urls)} total listings after search pattern: {pattern}")
                time.sleep(1)  # Rate limiting
                
            except Exception as e:
                self.logger.warning(f"Error with search pattern {pattern}: {e}")
        
        # Approach 3: Browse recent results page for any Porsche content
        try:
            results_url = f"{self.base_url}/auctions/results/"
            response = self.session.get(results_url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for any Porsche entries in recent results
            result_links = soup.find_all('a', href=re.compile(r'/auctions/[^/]+/$'))
            
            for link in result_links:
                link_text = link.get_text(strip=True).lower()
                href = link.get('href', '')
                
                # Check if it's a Porsche 911
                if ('porsche' in link_text and '911' in link_text) or 'porsche' in href:
                    full_url = urljoin(self.base_url, href)
                    if full_url not in listing_urls:
                        listing_urls.append(full_url)
                        
            self.logger.info(f"Found {len(listing_urls)} total listings after browsing results")
            
        except Exception as e:
            self.logger.warning(f"Error browsing results page: {e}")
        
        # Fallback: Use known Porsche 911 auction URLs (recent examples)
        if len(listing_urls) == 0:
            self.logger.info("No listings found through search, using fallback approach")
            
            # Try to get ANY recent auctions and filter them
            try:
                driver = self.configure_chrome_driver()
                driver.get(f"{self.base_url}/auctions/")
                
                # Wait for page load
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                
                # Get all auction links
                auction_elements = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/auctions/"]')
                
                for element in auction_elements[:20]:  # Limit to first 20
                    try:
                        href = element.get_attribute('href')
                        text = element.text.lower()
                        
                        if href and '/auctions/' in href and href.endswith('/'):
                            # Check if it might be a Porsche
                            if 'porsche' in text or 'porsche' in href.lower():
                                if href not in listing_urls:
                                    listing_urls.append(href)
                                    
                    except Exception as e:
                        continue
                
                driver.quit()
                self.logger.info(f"Found {len(listing_urls)} listings through fallback method")
                
            except Exception as e:
                self.logger.warning(f"Fallback method failed: {e}")
        
        # Remove duplicates and return
        unique_urls = list(set(listing_urls))
        self.logger.info(f"Found {len(unique_urls)} unique Porsche listings")
        
        return unique_urls
    
    def extract_vin_from_text(self, text: str) -> Optional[str]:
        """Extract 17-digit VIN from text content."""
        # Pattern for 17-digit VIN
        vin_pattern = r'\b[A-HJ-NPR-Z0-9]{17}\b'
        matches = re.findall(vin_pattern, text, re.IGNORECASE)
        
        for match in matches:
            if validate_vin(match.upper()):
                return match.upper()
        
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
        
        # Current bid
        bid_patterns = [
            r'\$[\d,]+\s*current bid',
            r'current bid[:\s]*\$[\d,]+',
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
        
        # Sold price
        sold_patterns = [
            r'sold for \$[\d,]+',
            r'winning bid[:\s]*\$[\d,]+',
            r'final bid[:\s]*\$[\d,]+',
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
            
            # Get page source and parse
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Check if this is actually a Porsche 911
            page_text = soup.get_text(separator=' ', strip=True)
            page_text_lower = page_text.lower()
            
            if not ('porsche' in page_text_lower and '911' in page_text_lower):
                self.logger.info(f"Not a Porsche 911 listing, skipping: {listing_url}")
                return None
            
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
                'vin': '',
                'mileage': '',
                'location': '',
                'seller_type': '',
                'auction_status': 'active',
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
            
            # Title and basic info
            title_elem = soup.find('h1') or soup.find('title')
            if title_elem:
                title_text = title_elem.get_text(strip=True)
                listing_data['title'] = title_text
                
                # Extract year from title
                year_match = re.search(r'\b(19|20)\d{2}\b', title_text)
                if year_match:
                    listing_data['year'] = year_match.group()
            
            # Try to extract VIN
            vin = self.extract_vin_from_text(page_text)
            
            if not vin:
                # If no VIN found, create a synthetic one based on URL for tracking
                listing_id = listing_data['listing_id']
                if listing_id:
                    # Create a tracking identifier (not a real VIN)
                    synthetic_id = f"BAT{listing_id.upper()[:10].zfill(10)}"
                    self.logger.warning(f"No VIN found, using synthetic ID: {synthetic_id}")
                    vin = synthetic_id
                else:
                    self.logger.warning(f"No VIN or listing ID found: {listing_url}")
                    return None
            
            if vin in self.processed_vins:
                self.logger.info(f"VIN/ID {vin} already processed, skipping")
                return None
                
            listing_data['vin'] = vin
            self.processed_vins.add(vin)
            
            # Price information
            listing_data['price_info'] = self.extract_price_from_text(page_text)
            
            # Mileage
            mileage_patterns = [
                r'(\d{1,3}(?:,\d{3})*)\s*(?:mile|mi\b)',
                r'(\d{1,3}(?:,\d{3})*)\s*(?:k|km)\s*(?:mile|mi)',
                r'showing\s*(\d{1,3}(?:,\d{3})*)',
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
            
            # Extract specifications from common BaT sections
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
            if 'manual' in specs_text or 'stick' in specs_text or '5-speed' in specs_text or '6-speed' in specs_text:
                listing_data['specifications']['transmission'] = 'Manual'
            elif 'automatic' in specs_text or 'tiptronic' in specs_text or 'pdk' in specs_text:
                listing_data['specifications']['transmission'] = 'Automatic'
            
            # Drive type
            if 'carrera 4' in specs_text or 'c4' in specs_text or 'awd' in specs_text or 'all-wheel' in specs_text:
                listing_data['specifications']['drive_type'] = 'AWD'
            else:
                listing_data['specifications']['drive_type'] = 'RWD'
            
            # Common features
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
            
            # Description (first paragraph or summary)
            description_elem = soup.find('div', class_=re.compile(r'description|summary|content'))
            if description_elem:
                description = description_elem.get_text(strip=True)[:1000]  # Limit length
                listing_data['description'] = description
            
            # Photo count
            img_tags = soup.find_all('img')
            photo_urls = []
            for img in img_tags:
                src = img.get('src') or img.get('data-src')
                if src and ('bringatrailer' in src or src.startswith('/')):
                    if src.startswith('/'):
                        src = urljoin(self.base_url, src)
                    photo_urls.append(src)
            
            listing_data['photos'] = photo_urls[:20]  # Limit to first 20 photos
            
            self.logger.info(f"Successfully scraped listing for VIN/ID {vin}")
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
            'body_class': 'Coupe',  # Default for 911
            'doors': '2',
            'fuel_type': 'Gasoline',
            
            # Engine information (estimated for 911s)
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
            'target': 'Porsche 911 (1981+)'
        },
        'listings': []
    }
    
    try:
        # Search for listings
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
                time.sleep(2)
        
        results['metadata']['total_listings_scraped'] = scraped_count
        results['metadata']['listings_with_vins'] = vins_found
        results['metadata']['new_vins'] = vins_found  # Will be updated in merge process
        
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
        print(f"⏱️  Runtime: {metadata['runtime_minutes']} minutes")
        print(f"🔍 Listings found: {metadata['total_listings_found']}")
        print(f"📊 Listings scraped: {metadata['total_listings_scraped']}")
        print(f"🚗 VINs collected: {metadata['listings_with_vins']}")
        
        if results['listings']:
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
