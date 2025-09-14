"""
Utility functions for VIN decoding workflow.
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Dict, Any, Optional
import requests
from jsonschema import validate, ValidationError


def setup_logging() -> logging.Logger:
    """Set up structured logging with timestamps."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger(__name__)


def validate_vin(vin: str) -> bool:
    """
    Validate VIN format and check digit.

    Args:
        vin: Vehicle Identification Number

    Returns:
        bool: True if VIN is valid
    """
    if not vin or len(vin) != 17:
        return False

    # Check for invalid characters
    if not re.match(r'^[A-HJ-NPR-Z0-9]{17}$', vin.upper()):
        return False

    return True


def make_api_request(url: str, params: Optional[Dict[str, Any]] = None, 
                    retries: int = 3, delay: float = 3.0) -> Dict[str, Any]:
    """
    Make API request with retry logic and rate limiting.

    Args:
        url: API endpoint URL
        params: Query parameters
        retries: Number of retry attempts
        delay: Delay between retries in seconds

    Returns:
        dict: API response data

    Raises:
        requests.RequestException: If all retries fail
    """
    logger = logging.getLogger(__name__)

    for attempt in range(retries):
        try:
            logger.info(f"Making API request to {url} (attempt {attempt + 1})")

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            logger.info(f"API request successful, received {len(data)} items")

            # Rate limiting - respect NHTSA API
            if delay > 0:
                time.sleep(delay)

            return data

        except requests.RequestException as e:
            logger.warning(f"API request failed (attempt {attempt + 1}): {e}")

            if attempt == retries - 1:
                logger.error(f"All retry attempts failed for {url}")
                raise

            time.sleep(delay * (attempt + 1))  # Exponential backoff

    raise requests.RequestException("All retry attempts failed")


def save_json_file(data: Dict[str, Any], filename: str) -> None:
    """
    Save data to JSON file with proper formatting.

    Args:
        data: Data to save
        filename: Output filename
    """
    logger = logging.getLogger(__name__)

    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully saved data to {filename}")

    except Exception as e:
        logger.error(f"Failed to save data to {filename}: {e}")
        raise


def load_json_file(filename: str) -> Dict[str, Any]:
    """
    Load data from JSON file.

    Args:
        filename: Input filename

    Returns:
        dict: Loaded data
    """
    logger = logging.getLogger(__name__)

    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)

        logger.info(f"Successfully loaded data from {filename}")
        return data

    except Exception as e:
        logger.error(f"Failed to load data from {filename}: {e}")
        raise


def validate_against_schema(data: Dict[str, Any], schema_path: str) -> bool:
    """
    Validate data against JSON schema.

    Args:
        data: Data to validate
        schema_path: Path to JSON schema file

    Returns:
        bool: True if validation passes
    """
    logger = logging.getLogger(__name__)

    try:
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema = json.load(f)

        validate(data, schema)
        logger.info("Data validation passed")
        return True

    except ValidationError as e:
        logger.error(f"Data validation failed: {e.message}")
        return False

    except Exception as e:
        logger.error(f"Schema validation error: {e}")
        return False


def extract_vin_components(vin: str) -> Dict[str, str]:
    """
    Extract VIN components (WMI, VDS, VIS).

    Args:
        vin: Vehicle Identification Number

    Returns:
        dict: VIN components
    """
    if not validate_vin(vin):
        raise ValueError(f"Invalid VIN: {vin}")

    return {
        'wmi': vin[:3],       # World Manufacturer Identifier
        'vds': vin[3:9],      # Vehicle Descriptor Section
        'check_digit': vin[8], # Check digit
        'model_year': vin[9],  # Model year
        'plant_code': vin[10], # Plant code
        'vis': vin[10:],      # Vehicle Identifier Section
        'serial': vin[11:]    # Serial number
    }


def create_timestamp() -> str:
    """Create ISO format timestamp."""
    return datetime.now().isoformat()


def get_nhtsa_api_base() -> str:
    """Get NHTSA API base URL from environment or default."""
    return os.environ.get('NHTSA_API_BASE', 'https://vpic.nhtsa.dot.gov/api/vehicles')
