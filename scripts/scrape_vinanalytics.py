#!/usr/bin/env python3

"""
VinAnalytics.com scraper for enhanced Porsche vehicle data.
"""

import argparse
import json
import os
import sys
import time
from typing import Dict, Any, List, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from bs4 import BeautifulSoup

from utils import setup_logging, save_json_file, create_timestamp


def configure_chrome_driver() -> webdriver.Chrome:
    """Configure Chrome driver with stealth settings."""
    chrome_options = Options()
    
    # Headless mode for GitHub Actions
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Anti-detection settings
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver


def extract_vinanalytics_data(page_source: str, vin: str) -> Dict[str, Any]:
    """
    Extract vehicle data from VinAnalytics page source.
    
    Args:
        page_source: HTML source of the results page
        vin: Vehicle Identification Number
        
    Returns:
        dict: Extracted vehicle data
    """
    logger = setup_logging()
    soup = BeautifulSoup(page_source, 'html.parser')
    
    # Initialize results
    results = {
        'vin': vin,
        'source': 'VinAnalytics.com',
        'timestamp': create_timestamp(),
        'success': False,
        'data': {
            'exterior_color': '',
            'interior_color': '',
            'options': [],
            'packages': [],
            'equipment': [],
            'specifications': {}
        },
        'raw_text': ''
    }
    
    try:
        # Get all text content for fallback parsing
        results['raw_text'] = soup.get_text(separator=' ', strip=True)[:5000]  # Limit size
        
        # Try multiple selector strategies for exterior color
        exterior_selectors = [
            'exterior-color', 'ext-color', 'paint-color', 'vehicle-color',
            'color-exterior', 'body-color'
        ]
        
        for selector in exterior_selectors:
            elements = soup.find_all(class_=selector) or soup.find_all(id=selector)
            if elements:
                results['data']['exterior_color'] = elements[0].get_text(strip=True)
                break
        
        # Try multiple selector strategies for interior color
        interior_selectors = [
            'interior-color', 'int-color', 'cabin-color', 'trim-color',
            'color-interior', 'upholstery-color'
        ]
        
        for selector in interior_selectors:
            elements = soup.find_all(class_=selector) or soup.find_all(id=selector)
            if elements:
                results['data']['interior_color'] = elements[0].get_text(strip=True)
                break
        
        # Extract options/equipment lists
        option_selectors = [
            'option-item', 'equipment-item', 'feature-item', 'package-item',
            'option', 'equipment', 'feature', 'package'
        ]
        
        for selector in option_selectors:
            elements = soup.find_all(class_=selector)
            if elements:
                options = [elem.get_text(strip=True) for elem in elements if elem.get_text(strip=True)]
                if options:
                    results['data']['options'].extend(options)
        
        # Look for tables with vehicle data
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True).lower()
                    value = cells[1].get_text(strip=True)
                    
                    if any(color_term in key for color_term in ['exterior', 'paint', 'body']):
                        if not results['data']['exterior_color'] and value:
                            results['data']['exterior_color'] = value
                    
                    elif any(color_term in key for color_term in ['interior', 'trim', 'upholstery']):
                        if not results['data']['interior_color'] and value:
                            results['data']['interior_color'] = value
                    
                    elif value and key not in ['', 'n/a', 'unknown']:
                        results['data']['specifications'][key] = value
        
        # Fallback: Parse text for color information
        if not results['data']['exterior_color'] or not results['data']['interior_color']:
            text_lower = results['raw_text'].lower()
            
            # Common Porsche exterior colors
            exterior_colors = [
                'guards red', 'racing yellow', 'miami blue', 'chalk', 'white',
                'black', 'silver', 'grey', 'gray', 'blue', 'red', 'green',
                'orange', 'yellow', 'brown', 'beige', 'gold'
            ]
            
            # Common Porsche interior colors/materials
            interior_materials = [
                'black leather', 'tan leather', 'brown leather', 'red leather',
                'beige leather', 'alcantara', 'leather', 'cloth', 'fabric'
            ]
            
            if not results['data']['exterior_color']:
                for color in exterior_colors:
                    if color in text_lower:
                        results['data']['exterior_color'] = color.title()
                        break
            
            if not results['data']['interior_color']:
                for material in interior_materials:
                    if material in text_lower:
                        results['data']['interior_color'] = material.title()
                        break
        
        # Determine success based on data found
        results['success'] = bool(
            results['data']['exterior_color'] or 
            results['data']['interior_color'] or 
            results['data']['options'] or 
            results['data']['specifications']
        )
        
        logger.info(f"VinAnalytics extraction {'successful' if results['success'] else 'failed'} for VIN {vin}")
        
    except Exception as e:
        logger.error(f"Error extracting VinAnalytics data: {e}")
        results['error'] = str(e)
    
    return results


def scrape_vinanalytics(vin: str, max_retries: int = 2) -> Dict[str, Any]:
    """
    Scrape VinAnalytics.com for vehicle build sheet data.
    
    Args:
        vin: Vehicle Identification Number
        max_retries: Maximum number of retry attempts
        
    Returns:
        dict: Scraped vehicle data
    """
    logger = setup_logging()
    
    for attempt in range(max_retries + 1):
        driver = None
        
        try:
            logger.info(f"Attempting VinAnalytics scrape for VIN {vin} (attempt {attempt + 1})")
            
            # Configure and start driver
            driver = configure_chrome_driver()
            
            # Navigate to VinAnalytics
            logger.info("Navigating to VinAnalytics.com")
            driver.get("https://vinanalytics.com/")
            
            # Wait for page load
            wait = WebDriverWait(driver, 15)
            
            # Try multiple possible selectors for VIN input
            vin_input = None
            input_selectors = [
                (By.NAME, "vin"),
                (By.ID, "vin"),
                (By.CLASS_NAME, "vin-input"),
                (By.XPATH, "//input[@placeholder*='VIN' or @placeholder*='vin']"),
                (By.XPATH, "//input[@type='text']")
            ]
            
            for selector_type, selector_value in input_selectors:
                try:
                    vin_input = wait.until(EC.presence_of_element_located((selector_type, selector_value)))
                    logger.info(f"Found VIN input using selector: {selector_type}='{selector_value}'")
                    break
                except TimeoutException:
                    continue
            
            if not vin_input:
                raise TimeoutException("Could not locate VIN input field")
            
            # Enter VIN
            vin_input.clear()
            vin_input.send_keys(vin)
            logger.info(f"Entered VIN: {vin}")
            
            # Try to find and click submit button
            submit_selectors = [
                (By.XPATH, "//input[@type='submit']"),
                (By.XPATH, "//button[@type='submit']"),
                (By.XPATH, "//button[contains(text(), 'Search') or contains(text(), 'Decode') or contains(text(), 'Submit')]"),
                (By.CLASS_NAME, "submit"),
                (By.CLASS_NAME, "btn-submit")
            ]
            
            submit_button = None
            for selector_type, selector_value in submit_selectors:
                try:
                    submit_button = driver.find_element(selector_type, selector_value)
                    logger.info(f"Found submit button using selector: {selector_type}='{selector_value}'")
                    break
                except NoSuchElementException:
                    continue
            
            if not submit_button:
                # Try pressing Enter if no submit button found
                logger.info("No submit button found, trying Enter key")
                from selenium.webdriver.common.keys import Keys
                vin_input.send_keys(Keys.RETURN)
            else:
                submit_button.click()
                logger.info("Clicked submit button")
            
            # Wait for results page to load
            time.sleep(8)  # Give extra time for results to load
            
            # Check if we're on a results page or if there's an error
            page_source = driver.page_source
            
            if "error" in page_source.lower() or "not found" in page_source.lower():
                logger.warning("Possible error or no results found on page")
            
            # Extract data from the page
            results = extract_vinanalytics_data(page_source, vin)
            
            if results['success']:
                logger.info("Successfully scraped VinAnalytics data")
                return results
            else:
                logger.warning(f"No meaningful data found on attempt {attempt + 1}")
                if attempt < max_retries:
                    time.sleep(5)  # Wait before retry
                    continue
                else:
                    return results  # Return whatever we got on final attempt
                    
        except Exception as e:
            logger.error(f"VinAnalytics scrape attempt {attempt + 1} failed: {e}")
            
            if attempt < max_retries:
                logger.info(f"Retrying in 10 seconds... ({max_retries - attempt} attempts remaining)")
                time.sleep(10)
            else:
                # Return error result
                return {
                    'vin': vin,
                    'source': 'VinAnalytics.com',
                    'timestamp': create_timestamp(),
                    'success': False,
                    'error': str(e),
                    'data': {
                        'exterior_color': '',
                        'interior_color': '',
                        'options': [],
                        'packages': [],
                        'equipment': [],
                        'specifications': {}
                    }
                }
        
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Scrape VinAnalytics.com for vehicle data')
    parser.add_argument('--vin', required=True, help='Vehicle Identification Number')
    parser.add_argument('--output', default='vin-vinanalytics-data.json', help='Output filename')
    
    args = parser.parse_args()
    logger = setup_logging()
    
    try:
        logger.info(f"Starting VinAnalytics scrape for VIN: {args.vin}")
        
        # Scrape VinAnalytics data
        scraped_data = scrape_vinanalytics(args.vin)
        
        # Save results
        save_json_file(scraped_data, args.output)
        
        if scraped_data['success']:
            print(f"✅ VinAnalytics scraping completed successfully for VIN {args.vin}")
            print(f"📁 Results saved to {args.output}")
            
            data = scraped_data['data']
            if data['exterior_color']:
                print(f"🎨 Exterior Color: {data['exterior_color']}")
            if data['interior_color']:
                print(f"🪑 Interior Color: {data['interior_color']}")
            if data['options']:
                print(f"⚙️  Options Found: {len(data['options'])}")
        else:
            print(f"⚠️  VinAnalytics scraping completed with limited results for VIN {args.vin}")
            print(f"📁 Results saved to {args.output}")
            if scraped_data.get('error'):
                print(f"❌ Error: {scraped_data['error']}")
        
        return 0
        
    except Exception as e:
        logger.error(f"VinAnalytics scraping failed: {e}")
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
