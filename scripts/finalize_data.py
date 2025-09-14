#!/usr/bin/env python3

"""
Final VIN data processing and validation.
"""

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, Any

from utils import (
    setup_logging, load_json_file, save_json_file, create_timestamp,
    validate_against_schema
)


def create_final_report(basic_data: Dict[str, Any], enhanced_data: Dict[str, Any],
                       vinanalytics_data: Dict[str, Any], vin: str) -> Dict[str, Any]:
    """
    Create final consolidated VIN report.
    
    Args:
        basic_data: Basic VIN decode data
        enhanced_data: Enhanced VIN data
        vinanalytics_data: VinAnalytics scraped data
        vin: Vehicle Identification Number
        
    Returns:
        dict: Final consolidated report
    """
    logger = setup_logging()
    
    # Extract key information
    basic_decoded = basic_data.get('decoded_data', {})
    enhanced_apis = enhanced_data.get('enhanced_decode', {}).get('enhanced_data', {})
    vinanalytics_scraped = vinanalytics_data.get('data', {})
    
    # Calculate API success rate
    total_apis = len(enhanced_apis)
    successful_apis = sum(1 for api_data in enhanced_apis.values()
                         if not api_data.get('error'))
    success_rate = (successful_apis / total_apis * 100) if total_apis > 0 else 0
    
    # Create summary statistics with VinAnalytics data
    summary = {
        'vin': vin,
        'make': basic_decoded.get('Make', 'Unknown'),
        'model': basic_decoded.get('Model', 'Unknown'),
        'model_year': basic_decoded.get('Model Year', 'Unknown'),
        'manufacturer': basic_decoded.get('Manufacturer Name', 'Unknown'),
        'body_class': basic_decoded.get('Body Class', 'Unknown'),
        'engine_cylinders': basic_decoded.get('Engine Number of Cylinders', 'Unknown'),
        'displacement_l': basic_decoded.get('Displacement (L)', 'Unknown'),
        'fuel_type': basic_decoded.get('Fuel Type - Primary', 'Unknown'),
        'plant_city': basic_decoded.get('Plant City', 'Unknown'),
        'plant_country': basic_decoded.get('Plant Country', 'Unknown'),
        'drive_type': basic_decoded.get('Drive Type', 'Unknown'),
        # Enhanced with VinAnalytics data
        'exterior_color': vinanalytics_scraped.get('exterior_color', ''),
        'interior_color': vinanalytics_scraped.get('interior_color', ''),
        'options_count': len(vinanalytics_scraped.get('options', [])),
        'vinanalytics_success': vinanalytics_data.get('success', False)
    }
    
    # Create processing metadata
    processing_info = {
        'final_processing_timestamp': create_timestamp(),
        'processing_workflow': 'NHTSA_vPIC_Plus_VinAnalytics_Workflow',
        'api_endpoints_used': list(enhanced_apis.keys()),
        'api_success_rate': f"{success_rate:.1f}%",
        'successful_api_calls': successful_apis,
        'total_api_calls': total_apis,
        'vinanalytics_attempted': True,
        'vinanalytics_successful': vinanalytics_data.get('success', False),
        'data_quality_score': calculate_data_quality_score(basic_decoded, enhanced_apis, vinanalytics_data),
        'vin_components': basic_data.get('vin_components', {})
    }
    
    # Compile final report
    final_report = {
        'report_metadata': {
            'vin': vin,
            'report_type': 'Complete VIN Analysis with VinAnalytics',
            'generated_at': create_timestamp(),
            'data_sources': ['NHTSA vPIC DecodeVinExtended', 'NHTSA vPIC Enhancement APIs', 'VinAnalytics.com'],
            'workflow_version': '2.0'
        },
        'vehicle_summary': summary,
        'processing_information': processing_info,
        'detailed_data': {
            'basic_decode': basic_data,
            'enhanced_decode': enhanced_data,
            'vinanalytics_scrape': vinanalytics_data
        },
        'recommendations': generate_recommendations(basic_decoded, enhanced_apis, vinanalytics_data)
    }
    
    logger.info(f"Final report created for VIN {vin}")
    logger.info(f"Data quality score: {processing_info['data_quality_score']:.1f}%")
    logger.info(f"API success rate: {processing_info['api_success_rate']}")
    logger.info(f"VinAnalytics successful: {vinanalytics_data.get('success', False)}")
    
    return final_report


def calculate_data_quality_score(basic_data: Dict[str, Any],
                                enhanced_apis: Dict[str, Any],
                                vinanalytics_data: Dict[str, Any]) -> float:
    """
    Calculate data quality score based on available information.
    
    Args:
        basic_data: Basic decoded data
        enhanced_apis: Enhanced API data
        vinanalytics_data: VinAnalytics scraped data
        
    Returns:
        float: Quality score (0-100)
    """
    score = 0.0
    
    # Basic data completeness (50% of total score)
    essential_fields = [
        'Make', 'Model', 'Model Year', 'Body Class',
        'Engine Number of Cylinders', 'Fuel Type - Primary'
    ]
    
    filled_essential = sum(1 for field in essential_fields
                          if basic_data.get(field) and basic_data[field] != 'Unknown')
    basic_score = (filled_essential / len(essential_fields)) * 50
    
    # Enhanced data availability (30% of total score)
    successful_enhancements = sum(1 for api_data in enhanced_apis.values()
                                 if not api_data.get('error'))
    total_enhancements = len(enhanced_apis)
    enhancement_score = (successful_enhancements / total_enhancements * 30) if total_enhancements > 0 else 0
    
    # VinAnalytics data bonus (20% of total score)
    vinanalytics_score = 0
    if vinanalytics_data.get('success'):
        va_data = vinanalytics_data.get('data', {})
        va_score = 0
        
        # Color data (10 points each)
        if va_data.get('exterior_color'):
            va_score += 10
        if va_data.get('interior_color'):
            va_score += 10
            
        vinanalytics_score = min(va_score, 20)  # Cap at 20%
    
    score = basic_score + enhancement_score + vinanalytics_score
    return round(score, 1)


def generate_recommendations(basic_data: Dict[str, Any],
                           enhanced_apis: Dict[str, Any],
                           vinanalytics_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate recommendations based on available data.
    
    Args:
        basic_data: Basic decoded data
        enhanced_apis: Enhanced API data
        vinanalytics_data: VinAnalytics scraped data
        
    Returns:
        dict: Recommendations and insights
    """
    recommendations = {
        'data_completeness': [],
        'vehicle_insights': [],
        'potential_issues': []
    }
    
    # Check data completeness
    if not basic_data.get('Engine Model'):
        recommendations['data_completeness'].append(
            "Engine model information not available - consider checking with manufacturer"
        )
    
    if not basic_data.get('Transmission Style'):
        recommendations['data_completeness'].append(
            "Transmission information not available - manual verification recommended"
        )
    
    # VinAnalytics specific recommendations
    if not vinanalytics_data.get('success'):
        recommendations['potential_issues'].append(
            "VinAnalytics scraping failed - color and option data may be incomplete"
        )
    else:
        va_data = vinanalytics_data.get('data', {})
        if not va_data.get('exterior_color') and not va_data.get('interior_color'):
            recommendations['data_completeness'].append(
                "No color information found from VinAnalytics - may need manual verification"
            )
        
        if va_data.get('options'):
            recommendations['vehicle_insights'].append(
                f"Found {len(va_data['options'])} factory options from VinAnalytics"
            )
    
    # Vehicle insights
    year = basic_data.get('Model Year')
    if year and year.isdigit():
        current_year = datetime.now().year
        age = current_year - int(year)
        if age > 15:
            recommendations['vehicle_insights'].append(
                f"Vehicle is {age} years old - classified as vintage/classic"
            )
        elif age > 10:
            recommendations['vehicle_insights'].append(
                f"Vehicle is {age} years old - may have limited parts availability"
            )
    
    # Check for failed API calls
    failed_apis = [name for name, data in enhanced_apis.items() if data.get('error')]
    if failed_apis:
        recommendations['potential_issues'].append(
            f"Enhancement data incomplete - failed APIs: {', '.join(failed_apis)}"
        )
    
    return recommendations


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Finalize VIN data processing')
    parser.add_argument('--vin', required=True, help='Vehicle Identification Number')
    parser.add_argument('--basic-data', default='vin-basic-data.json',
                       help='Basic VIN data file')
    parser.add_argument('--enhanced-data', default='vin-enhanced-data.json',
                       help='Enhanced VIN data file')
    parser.add_argument('--vinanalytics-data', default='vin-vinanalytics-data.json',
                       help='VinAnalytics scraped data file')
    parser.add_argument('--schema', default='data/schemas/vin_data_schema.json',
                       help='JSON schema file for validation')
    
    args = parser.parse_args()
    logger = setup_logging()
    
    try:
        # Load input data
        logger.info("Loading input data files")
        basic_data = load_json_file(args.basic_data)
        enhanced_data = load_json_file(args.enhanced_data)
        
        # Load VinAnalytics data (optional - may not exist if scraping failed)
        vinanalytics_data = {}
        if os.path.exists(args.vinanalytics_data):
            vinanalytics_data = load_json_file(args.vinanalytics_data)
        else:
            logger.warning(f"VinAnalytics data file not found: {args.vinanalytics_data}")
            vinanalytics_data = {
                'vin': args.vin,
                'success': False,
                'error': 'VinAnalytics data file not found',
                'data': {}
            }
        
        # Create final report
        logger.info("Creating final consolidated report")
        final_report = create_final_report(basic_data, enhanced_data, vinanalytics_data, args.vin)
        
        # Generate output filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"vin-complete-{args.vin}-{timestamp}.json"
        
        # Save final report
        save_json_file(final_report, output_filename)
        
        # Validate against schema if available
        if os.path.exists(args.schema):
            logger.info("Validating final report against schema")
            if validate_against_schema(final_report, args.schema):
                logger.info("✅ Schema validation passed")
            else:
                logger.warning("⚠️ Schema validation failed")
        else:
            logger.info("Schema file not found, skipping validation")
        
        # Print summary
        summary = final_report['vehicle_summary']
        processing = final_report['processing_information']
        
        print(f"✅ Final processing completed for VIN {args.vin}")
        print(f"📁 Final report saved to {output_filename}")
        print(f"🚗 Vehicle: {summary['model_year']} {summary['make']} {summary['model']}")
        print(f"📊 Data Quality Score: {processing['data_quality_score']}%")
        print(f"🔗 API Success Rate: {processing['api_success_rate']}")
        print(f"🔍 VinAnalytics: {'✅ Success' if summary['vinanalytics_success'] else '❌ Failed'}")
        
        if summary.get('exterior_color'):
            print(f"🎨 Exterior Color: {summary['exterior_color']}")
        if summary.get('interior_color'):
            print(f"🪑 Interior Color: {summary['interior_color']}")
        if summary.get('options_count', 0) > 0:
            print(f"⚙️  Options Found: {summary['options_count']}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Final processing failed: {e}")
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
