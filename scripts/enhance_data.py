#!/usr/bin/env python3
"""
Enhanced VIN data collection using multiple NHTSA vPIC API endpoints.
"""

import argparse
import asyncio
import sys
from typing import Dict, Any, List
import aiohttp

from utils import (
    setup_logging, load_json_file, save_json_file, create_timestamp,
    get_nhtsa_api_base, extract_vin_components
)


class VINDataEnhancer:
    """Enhanced VIN data collector using multiple API endpoints."""

    def __init__(self):
        self.logger = setup_logging()
        self.base_url = get_nhtsa_api_base()
        self.session = None

    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(limit=10)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()

    async def make_async_request(self, url: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Make async API request with error handling.

        Args:
            url: API endpoint URL
            params: Query parameters

        Returns:
            dict: API response data
        """
        try:
            self.logger.info(f"Making async request to {url}")

            async with self.session.get(url, params=params) as response:
                response.raise_for_status()
                data = await response.json()

                self.logger.info(f"Request successful: {url}")
                return data

        except Exception as e:
            self.logger.error(f"Request failed for {url}: {e}")
            return {}

    async def get_manufacturer_details(self, manufacturer: str) -> Dict[str, Any]:
        """Get detailed manufacturer information."""
        if not manufacturer:
            return {}

        url = f"{self.base_url}/GetManufacturerDetails/{manufacturer}"
        params = {'format': 'json'}

        data = await self.make_async_request(url, params)

        # Add 3-second delay for rate limiting
        await asyncio.sleep(3)

        return {
            'source': 'GetManufacturerDetails',
            'timestamp': create_timestamp(),
            'data': data
        }

    async def decode_wmi(self, vin: str) -> Dict[str, Any]:
        """Decode World Manufacturer Identifier."""
        wmi = vin[:3] if len(vin) >= 3 else ''
        if not wmi:
            return {}

        url = f"{self.base_url}/DecodeWMI/{wmi}"
        params = {'format': 'json'}

        data = await self.make_async_request(url, params)

        await asyncio.sleep(3)

        return {
            'source': 'DecodeWMI',
            'wmi': wmi,
            'timestamp': create_timestamp(),
            'data': data
        }

    async def get_models_for_make_year(self, make: str, year: str) -> Dict[str, Any]:
        """Get all models for make and year."""
        if not make or not year:
            return {}

        url = f"{self.base_url}/GetModelsForMakeYear/make/{make}/modelyear/{year}"
        params = {'format': 'json'}

        data = await self.make_async_request(url, params)

        await asyncio.sleep(3)

        return {
            'source': 'GetModelsForMakeYear',
            'make': make,
            'year': year,
            'timestamp': create_timestamp(),
            'data': data
        }

    async def get_equipment_plant_codes(self, year: str) -> Dict[str, Any]:
        """Get equipment plant codes for year."""
        if not year:
            return {}

        url = f"{self.base_url}/GetEquipmentPlantCodes"
        params = {'Year': year, 'format': 'json'}

        data = await self.make_async_request(url, params)

        await asyncio.sleep(3)

        return {
            'source': 'GetEquipmentPlantCodes',
            'year': year,
            'timestamp': create_timestamp(),
            'data': data
        }

    async def get_vehicle_types_for_make(self, make: str) -> Dict[str, Any]:
        """Get all vehicle types for make."""
        if not make:
            return {}

        url = f"{self.base_url}/GetVehicleTypesForMake/{make}"
        params = {'format': 'json'}

        data = await self.make_async_request(url, params)

        await asyncio.sleep(3)

        return {
            'source': 'GetVehicleTypesForMake',
            'make': make,
            'timestamp': create_timestamp(),
            'data': data
        }

    async def enhance_vin_data(self, vin: str, make: str, year: str, manufacturer: str) -> Dict[str, Any]:
        """
        Enhance VIN data using multiple API endpoints.

        Args:
            vin: Vehicle Identification Number
            make: Vehicle make
            year: Model year
            manufacturer: Manufacturer name

        Returns:
            dict: Enhanced VIN data
        """
        self.logger.info(f"Enhancing data for VIN {vin}")

        # Create tasks for parallel execution
        tasks = [
            self.get_manufacturer_details(manufacturer),
            self.decode_wmi(vin),
            self.get_models_for_make_year(make, year),
            self.get_equipment_plant_codes(year),
            self.get_vehicle_types_for_make(make)
        ]

        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        enhanced_data = {
            'vin': vin,
            'enhancement_timestamp': create_timestamp(),
            'enhancement_source': 'NHTSA_vPIC_Multiple_Endpoints',
            'enhanced_data': {}
        }

        # Map results to named keys
        endpoint_names = [
            'manufacturer_details',
            'wmi_decode',
            'models_for_make_year',
            'equipment_plant_codes',
            'vehicle_types_for_make'
        ]

        for i, result in enumerate(results):
            endpoint_name = endpoint_names[i]

            if isinstance(result, Exception):
                self.logger.error(f"Error in {endpoint_name}: {result}")
                enhanced_data['enhanced_data'][endpoint_name] = {
                    'error': str(result),
                    'success': False
                }
            else:
                enhanced_data['enhanced_data'][endpoint_name] = result
                self.logger.info(f"Successfully enhanced data from {endpoint_name}")

        return enhanced_data


async def enhance_data_async(vin: str, make: str, year: str, manufacturer: str, 
                           basic_data_file: str, output_file: str):
    """Async wrapper for data enhancement."""

    # Load basic data
    try:
        basic_data = load_json_file(basic_data_file)
    except Exception as e:
        raise ValueError(f"Failed to load basic data: {e}")

    # Enhance data
    async with VINDataEnhancer() as enhancer:
        enhanced_data = await enhancer.enhance_vin_data(vin, make, year, manufacturer)

    # Merge basic and enhanced data
    final_data = {
        'vin': vin,
        'processing_timestamp': create_timestamp(),
        'basic_decode': basic_data,
        'enhanced_decode': enhanced_data
    }

    # Save enhanced data
    save_json_file(final_data, output_file)

    return final_data


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Enhance VIN data using multiple APIs')
    parser.add_argument('--vin', required=True, help='Vehicle Identification Number')
    parser.add_argument('--make', required=True, help='Vehicle make')
    parser.add_argument('--year', required=True, help='Model year')
    parser.add_argument('--manufacturer', required=True, help='Manufacturer name')
    parser.add_argument('--basic-data', default='vin-basic-data.json',
                       help='Basic VIN data file')
    parser.add_argument('--output', default='vin-enhanced-data.json',
                       help='Output filename')

    args = parser.parse_args()

    try:
        # Run async enhancement
        enhanced_data = asyncio.run(
            enhance_data_async(
                args.vin, args.make, args.year, args.manufacturer,
                args.basic_data, args.output
            )
        )

        print(f"✅ VIN {args.vin} data enhanced successfully")
        print(f"📁 Results saved to {args.output}")

        # Print summary
        enhanced_apis = enhanced_data['enhanced_decode']['enhanced_data']
        successful_apis = sum(1 for api_data in enhanced_apis.values() 
                            if not api_data.get('error'))

        print(f"📊 Enhanced with {successful_apis}/{len(enhanced_apis)} API endpoints")

        return 0

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
