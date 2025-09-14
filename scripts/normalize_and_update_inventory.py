#!/usr/bin/env python3

"""
Normalize finalized VIN data and maintain master inventory with deduplication.
"""

import argparse
import json
import os
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import glob


def setup_logging() -> logging.Logger:
    """Set up logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)


def load_json_file(filename: str) -> Dict[str, Any]:
    """Load JSON file, return empty dict if file doesn't exist."""
    if not os.path.exists(filename):
        return {}
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"Failed to load {filename}: {e}")
        return {}


def save_json_file(data: Dict[str, Any], filename: str) -> None:
    """Save data to JSON file with pretty formatting."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        logging.info(f"Successfully saved {filename}")
    except IOError as e:
        logging.error(f"Failed to save {filename}: {e}")
        raise


def normalize_vin_record(finalized_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a finalized VIN record into a flat, queryable structure.
    
    Args:
        finalized_data: Complete finalized VIN data
        
    Returns:
        dict: Normalized record for inventory
    """
    # Extract core vehicle information
    vehicle_summary = finalized_data.get('vehicle_summary', {})
    processing_info = finalized_data.get('processing_information', {})
    report_metadata = finalized_data.get('report_metadata', {})
    
    # Extract basic decode data for additional fields
    basic_decode = finalized_data.get('detailed_data', {}).get('basic_decode', {})
    decoded_data = basic_decode.get('decoded_data', {})
    vin_components = basic_decode.get('vin_components', {})
    
    # Extract enhanced data success metrics
    enhanced_data = finalized_data.get('detailed_data', {}).get('enhanced_decode', {}).get('enhanced_decode', {}).get('enhanced_data', {})
    
    # Count successful API enhancements
    successful_enhancements = []
    failed_enhancements = []
    
    for api_name, api_data in enhanced_data.items():
        if isinstance(api_data, dict):
            if api_data.get('error') or api_data.get('success') is False:
                failed_enhancements.append(api_name)
            else:
                successful_enhancements.append(api_name)
    
    # Create normalized record
    normalized = {
        # Primary identifiers
        'vin': vehicle_summary.get('vin', ''),
        'make': vehicle_summary.get('make', ''),
        'model': vehicle_summary.get('model', ''),
        'model_year': vehicle_summary.get('model_year', ''),
        'manufacturer': vehicle_summary.get('manufacturer', ''),
        
        # Vehicle specifications
        'body_class': vehicle_summary.get('body_class', ''),
        'body_style': decoded_data.get('NCSA Body Type', ''),
        'doors': decoded_data.get('Doors', ''),
        'drive_type': vehicle_summary.get('drive_type', ''),
        'fuel_type': vehicle_summary.get('fuel_type', ''),
        
        # Engine information
        'engine_cylinders': vehicle_summary.get('engine_cylinders', ''),
        'displacement_l': vehicle_summary.get('displacement_l', ''),
        'displacement_cc': decoded_data.get('Displacement (CC)', ''),
        'horsepower_min': decoded_data.get('Engine Brake (hp) From', ''),
        'horsepower_max': decoded_data.get('Engine Brake (hp) To', ''),
        'engine_info': decoded_data.get('Other Engine Info', ''),
        
        # Manufacturing information
        'plant_city': vehicle_summary.get('plant_city', ''),
        'plant_country': vehicle_summary.get('plant_country', ''),
        'plant_company': decoded_data.get('Plant Company Name', ''),
        
        # VIN components
        'wmi': vin_components.get('wmi', ''),
        'wmi_region': vin_components.get('wmi', '')[:1] if vin_components.get('wmi') else '',
        'check_digit': vin_components.get('check_digit', ''),
        'plant_code': vin_components.get('plant_code', ''),
        'serial_number': vin_components.get('serial', ''),
        
        # Data quality metrics
        'data_quality_score': processing_info.get('data_quality_score', 0),
        'api_success_rate': processing_info.get('api_success_rate', '0%'),
        'successful_api_calls': processing_info.get('successful_api_calls', 0),
        'total_api_calls': processing_info.get('total_api_calls', 0),
        'successful_enhancements': successful_enhancements,
        'failed_enhancements': failed_enhancements,
        
        # Additional details
        'trim': decoded_data.get('Trim', ''),
        'vehicle_type': decoded_data.get('Vehicle Type', ''),
        'gvwr': decoded_data.get('Gross Vehicle Weight Rating From', ''),
        'safety_features': {
            'airbags_front': decoded_data.get('Front Air Bag Locations', ''),
            'seat_belt_type': decoded_data.get('Seat Belt Type', ''),
            'restraint_info': decoded_data.get('Other Restraint System Info', '').strip()
        },
        
        # NCSA classifications
        'ncsa_make': decoded_data.get('NCSA Make', ''),
        'ncsa_model': decoded_data.get('NCSA Model', ''),
        'ncsa_body_type': decoded_data.get('NCSA Body Type', ''),
        
        # Processing metadata
        'first_processed': report_metadata.get('generated_at', ''),
        'last_updated': datetime.now().isoformat(),
        'workflow_version': report_metadata.get('workflow_version', ''),
        'update_count': 1,  # Will be incremented if record already exists
        
        # Data completeness flags
        'has_engine_model': bool(decoded_data.get('Engine Model')),
        'has_transmission_style': bool(decoded_data.get('Transmission Style')),
        'has_manufacturer_details': 'manufacturer_details' in successful_enhancements,
        'has_wmi_decode': 'wmi_decode' in successful_enhancements,
        'has_model_variations': 'models_for_make_year' in successful_enhancements,
        'has_vehicle_types': 'vehicle_types_for_make' in successful_enhancements,
        
        # Vehicle age classification
        'age_years': datetime.now().year - int(vehicle_summary.get('model_year', '0')) if vehicle_summary.get('model_year', '').isdigit() else 0,
        'is_classic': (datetime.now().year - int(vehicle_summary.get('model_year', '0')) > 15) if vehicle_summary.get('model_year', '').isdigit() else False,
        'is_vintage': (datetime.now().year - int(vehicle_summary.get('model_year', '0')) > 25) if vehicle_summary.get('model_year', '').isdigit() else False,
    }
    
    return normalized


def find_existing_record_index(inventory: List[Dict[str, Any]], vin: str) -> Optional[int]:
    """Find the index of an existing record by VIN."""
    for i, record in enumerate(inventory):
        if record.get('vin') == vin:
            return i
    return None


def update_inventory(inventory_data: Dict[str, Any], normalized_record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update inventory with new or updated record.
    
    Args:
        inventory_data: Current inventory data structure
        normalized_record: New normalized record to add/update
        
    Returns:
        dict: Updated inventory data
    """
    logger = logging.getLogger(__name__)
    
    # Initialize inventory structure if empty
    if not inventory_data:
        inventory_data = {
            'metadata': {
                'created_at': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'total_updates': 0,
                'total_vins': 0,
                'version': '1.0'
            },
            'inventory': []
        }
    
    inventory = inventory_data.get('inventory', [])
    metadata = inventory_data.get('metadata', {})
    
    vin = normalized_record.get('vin')
    existing_index = find_existing_record_index(inventory, vin)
    
    if existing_index is not None:
        # Update existing record
        existing_record = inventory[existing_index]
        
        # Preserve first_processed date and increment update_count
        normalized_record['first_processed'] = existing_record.get('first_processed', normalized_record['first_processed'])
        normalized_record['update_count'] = existing_record.get('update_count', 0) + 1
        
        # Replace the record
        inventory[existing_index] = normalized_record
        
        logger.info(f"Updated existing VIN record: {vin} (update #{normalized_record['update_count']})")
        action = 'updated'
        
    else:
        # Add new record
        inventory.append(normalized_record)
        logger.info(f"Added new VIN record: {vin}")
        action = 'added'
    
    # Update metadata
    metadata.update({
        'last_updated': datetime.now().isoformat(),
        'total_updates': metadata.get('total_updates', 0) + 1,
        'total_vins': len(inventory),
        'last_action': action,
        'last_vin_processed': vin
    })
    
    # Sort inventory by VIN for consistency
    inventory.sort(key=lambda x: x.get('vin', ''))
    
    inventory_data['inventory'] = inventory
    inventory_data['metadata'] = metadata
    
    return inventory_data


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Normalize VIN data and update master inventory')
    parser.add_argument('--vin', required=True, help='VIN being processed')
    parser.add_argument('--input', required=True, help='Input finalized JSON file (supports wildcards)')
    parser.add_argument('--inventory', default='master_inventory.json', help='Master inventory JSON file')
    
    args = parser.parse_args()
    logger = setup_logging()
    
    try:
        # Find input file (support wildcards)
        input_files = glob.glob(args.input)
        if not input_files:
            raise FileNotFoundError(f"No files found matching pattern: {args.input}")
        
        input_file = input_files[0]  # Use first match
        logger.info(f"Processing input file: {input_file}")
        
        # Load finalized data
        finalized_data = load_json_file(input_file)
        if not finalized_data:
            raise ValueError(f"No data found in input file: {input_file}")
        
        # Normalize the record
        logger.info(f"Normalizing VIN record: {args.vin}")
        normalized_record = normalize_vin_record(finalized_data)
        
        # Load existing inventory
        logger.info(f"Loading inventory: {args.inventory}")
        inventory_data = load_json_file(args.inventory)
        
        # Update inventory with new/updated record
        updated_inventory = update_inventory(inventory_data, normalized_record)
        
        # Save updated inventory
        save_json_file(updated_inventory, args.inventory)
        
        # Print summary
        metadata = updated_inventory['metadata']
        record = normalized_record
        
        print(f"✅ Inventory updated successfully")
        print(f"🚗 VIN: {args.vin}")
        print(f"📝 Action: {metadata.get('last_action', 'unknown')}")
        print(f"🔢 Update count for this VIN: {record.get('update_count', 1)}")
        print(f"📊 Total VINs in inventory: {metadata.get('total_vins', 0)}")
        print(f"🔄 Total inventory updates: {metadata.get('total_updates', 0)}")
        print(f"📈 Data quality score: {record.get('data_quality_score', 0)}%")
        print(f"🌐 API success rate: {record.get('api_success_rate', '0%')}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Failed to update inventory: {e}")
        print(f"❌ Error: {e}")
        return 1


if __name__ == '__main__':
    exit(main())
