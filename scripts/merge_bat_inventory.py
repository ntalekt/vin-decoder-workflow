#!/usr/bin/env python3

"""
Merge BaT listings with master inventory and maintain BaT-specific inventory.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional

from utils import setup_logging, save_json_file, create_timestamp


def load_json_file(filename: str) -> Dict[str, Any]:
    """Load JSON file, return empty dict if file doesn't exist."""
    if not os.path.exists(filename):
        print(f"File {filename} doesn't exist, starting with empty inventory")
        return {}
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Failed to load {filename}: {e}")
        return {}


def find_existing_record_index(inventory: List[Dict[str, Any]], vin: str) -> Optional[int]:
    """Find the index of an existing record by VIN."""
    for i, record in enumerate(inventory):
        if record.get('vin') == vin:
            return i
    return None


def merge_bat_data(bat_listings: Dict[str, Any], 
                  bat_inventory_file: str = 'bat_inventory.json') -> Dict[str, Any]:
    """Merge new BaT listings with existing BaT inventory."""
    logger = setup_logging()
    
    # Load existing BaT inventory
    existing_inventory = load_json_file(bat_inventory_file)
    
    if not existing_inventory:
        existing_inventory = {
            'metadata': {
                'created_at': create_timestamp(),
                'last_updated': create_timestamp(),
                'total_updates': 0,
                'total_vins': 0,
                'total_scrapes': 0,
                'version': '1.0',
                'source': 'BringATrailer'
            },
            'inventory': []
        }
    
    inventory = existing_inventory.get('inventory', [])
    metadata = existing_inventory.get('metadata', {})
    
    new_count = 0
    updated_count = 0
    
    # Process each new listing
    for listing in bat_listings.get('listings', []):
        vin = listing.get('vin')
        if not vin:
            continue
            
        existing_index = find_existing_record_index(inventory, vin)
        
        if existing_index is not None:
            # Update existing record
            existing_record = inventory[existing_index]
            
            # Preserve creation data and increment counters
            listing['first_scraped'] = existing_record.get('first_scraped', listing.get('first_scraped'))
            listing['scrape_count'] = existing_record.get('scrape_count', 0) + 1
            listing['last_updated'] = create_timestamp()
            
            # Update auction status and pricing if changed
            if (existing_record.get('bat_current_bid') != listing.get('bat_current_bid') or
                existing_record.get('bat_sold_price') != listing.get('bat_sold_price') or  
                existing_record.get('bat_auction_status') != listing.get('bat_auction_status')):
                
                listing['price_updated'] = create_timestamp()
            
            inventory[existing_index] = listing
            updated_count += 1
            logger.info(f"Updated existing VIN: {vin}")
            
        else:
            # Add new record
            inventory.append(listing)
            new_count += 1
            logger.info(f"Added new VIN: {vin}")
    
    # Update metadata
    metadata.update({
        'last_updated': create_timestamp(),
        'total_updates': metadata.get('total_updates', 0) + 1,
        'total_vins': len(inventory),
        'total_scrapes': metadata.get('total_scrapes', 0) + 1,
        'last_scrape_new': new_count,
        'last_scrape_updated': updated_count,
        'last_scrape_timestamp': create_timestamp()
    })
    
    # Sort by VIN for consistency
    inventory.sort(key=lambda x: x.get('vin', ''))
    
    result = {
        'metadata': metadata,
        'inventory': inventory
    }
    
    logger.info(f"BaT inventory merge completed: {new_count} new, {updated_count} updated")
    return result


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Merge BaT listings with inventory')
    parser.add_argument('--input', required=True, 
                       help='Input BaT listings JSON file')
    parser.add_argument('--bat-inventory', default='bat_inventory.json',
                       help='BaT inventory JSON file')
    
    args = parser.parse_args()
    logger = setup_logging()
    
    try:
        # Load BaT listings
        logger.info(f"Loading BaT listings from {args.input}")
        bat_listings = load_json_file(args.input)
        
        if not bat_listings:
            raise ValueError(f"No data found in {args.input}")
        
        # Merge with existing inventory
        logger.info("Merging with existing BaT inventory")
        updated_inventory = merge_bat_data(bat_listings, args.bat_inventory)
        
        # Save updated inventory
        save_json_file(updated_inventory, args.bat_inventory)
        
        # Print summary
        metadata = updated_inventory['metadata']
        print(f"✅ BaT inventory merge completed")
        print(f"📁 Inventory saved to {args.bat_inventory}")
        print(f"🚗 Total VINs in BaT inventory: {metadata.get('total_vins', 0)}")
        print(f"🆕 New VINs this scrape: {metadata.get('last_scrape_new', 0)}")
        print(f"🔄 Updated VINs this scrape: {metadata.get('last_scrape_updated', 0)}")
        print(f"📊 Total scrapes: {metadata.get('total_scrapes', 0)}")
        
        return 0
        
    except Exception as e:
        logger.error(f"BaT inventory merge failed: {e}")
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
