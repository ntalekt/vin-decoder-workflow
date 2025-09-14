#!/usr/bin/env python3
"""
Primary VIN decoder using NHTSA vPIC DecodeVinExtended API.
"""

import argparse
import os
import sys
from typing import Dict, Any

from utils import (
    setup_logging, validate_vin, make_api_request, save_json_file,
    extract_vin_components, create_timestamp, get_nhtsa_api_base
)


def decode_vin_extended(vin: str) -> Dict[str, Any]:
    """
    Decode VIN using NHTSA DecodeVinExtended API.

    Args:
        vin: Vehicle Identification Number

    Returns:
        dict: Decoded VIN data
    """
    logger = setup_logging()

    if not validate_vin(vin):
        raise ValueError(f"Invalid VIN format: {vin}")

    base_url = get_nhtsa_api_base()
    url = f"{base_url}/DecodeVinExtended/{vin}"
    params = {'format': 'json'}

    logger.info(f"Decoding VIN: {vin}")

    try:
        response_data = make_api_request(url, params)

        # Extract the Results array from NHTSA response
        if 'Results' not in response_data:
            raise ValueError("Invalid API response format")

        decoded_variables = response_data['Results']

        # Convert to more usable format
        decoded_data = {}
        for variable in decoded_variables:
            var_name = variable.get('Variable', '')
            value = variable.get('Value', '')

            if value and value != 'Not Applicable':
                decoded_data[var_name] = value

        # Add metadata
        vin_components = extract_vin_components(vin)

        result = {
            'vin': vin,
            'timestamp': create_timestamp(),
            'source': 'NHTSA_DecodeVinExtended',
            'vin_components': vin_components,
            'decoded_data': decoded_data,
            'raw_response': {
                'count': response_data.get('Count', 0),
                'message': response_data.get('Message', ''),
                'search_criteria': response_data.get('SearchCriteria', '')
            }
        }

        logger.info(f"Successfully decoded VIN {vin}")
        logger.info(f"Make: {decoded_data.get('Make', 'Unknown')}")
        logger.info(f"Model: {decoded_data.get('Model', 'Unknown')}")
        logger.info(f"Year: {decoded_data.get('Model Year', 'Unknown')}")

        return result

    except Exception as e:
        logger.error(f"Failed to decode VIN {vin}: {e}")
        raise


def extract_essential_data(decoded_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract essential data for subsequent jobs.

    Args:
        decoded_data: Full decoded VIN data

    Returns:
        dict: Essential data for next jobs
    """
    essential = decoded_data.get('decoded_data', {})

    return {
        'make': essential.get('Make', ''),
        'model_year': essential.get('Model Year', ''),
        'manufacturer': essential.get('Manufacturer Name', ''),
        'model': essential.get('Model', ''),
        'plant_city': essential.get('Plant City', ''),
        'plant_country': essential.get('Plant Country', '')
    }


def set_github_outputs(data: Dict[str, str]) -> None:
    """
    Set GitHub Actions outputs for subsequent jobs.

    Args:
        data: Data to set as outputs
    """
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a') as f:
            for key, value in data.items():
                f.write(f"{key}={value}\n")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Decode VIN using NHTSA API')
    parser.add_argument('vin', help='Vehicle Identification Number')
    parser.add_argument('--output', default='vin-basic-data.json',
                       help='Output filename')

    args = parser.parse_args()

    try:
        # Decode VIN
        decoded_data = decode_vin_extended(args.vin)

        # Save results
        save_json_file(decoded_data, args.output)

        # Extract essential data for GitHub Actions outputs
        essential_data = extract_essential_data(decoded_data)
        essential_data['vin'] = args.vin

        # Set GitHub Actions outputs
        set_github_outputs(essential_data)

        print(f"✅ VIN {args.vin} decoded successfully")
        print(f"📁 Results saved to {args.output}")

        return 0

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
