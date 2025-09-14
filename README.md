# VIN Decoder Workflow

[![GitHub Actions](https://github.com/username/vin-decoder-workflow/workflows/VIN%20Decoder%20Workflow/badge.svg)](https://github.com/username/vin-decoder-workflow/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A comprehensive GitHub Actions workflow for decoding Vehicle Identification Numbers (VINs) using the NHTSA vPIC API. This workflow provides complete vehicle information through multiple API endpoints and delivers detailed analysis reports.

## 🚗 Features

- **Complete VIN Decoding**: Uses NHTSA's DecodeVinExtended API for comprehensive vehicle data
- **Enhanced Data Collection**: Parallel API calls to 5 additional NHTSA endpoints
- **Data Quality Scoring**: Automatic assessment of data completeness and reliability
- **Webhook Triggered**: Easy integration with external systems via repository dispatch
- **Structured Outputs**: JSON reports with detailed vehicle information and recommendations
- **Error Handling**: Robust retry logic and graceful failure handling
- **Rate Limiting**: Respects NHTSA API guidelines with built-in delays

## 📋 Table of Contents

- [Quick Start](#quick-start)
- [Workflow Overview](#workflow-overview)
- [API Endpoints Used](#api-endpoints-used)
- [Setup Instructions](#setup-instructions)
- [Usage Examples](#usage-examples)
- [Output Format](#output-format)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

## 🚀 Quick Start

### 1. Fork/Clone Repository

```bash
git clone https://github.com/username/vin-decoder-workflow.git
cd vin-decoder-workflow
```

### 2. Enable GitHub Actions

Ensure GitHub Actions is enabled in your repository settings.

### 3. Trigger Workflow

Use PowerShell to trigger the workflow:

```powershell
$headers = @{
    "Authorization" = "token YOUR_GITHUB_TOKEN"
    "Accept" = "application/vnd.github.v3+json"
    "Content-Type" = "application/json"
}

$body = @{
    event_type = "decode_vin"
    client_payload = @{
        vin = "WP0AA29936S715303"
    }
} | ConvertTo-Json

Invoke-RestMethod -Uri "https://api.github.com/repos/USERNAME/REPO/dispatches" -Method POST -Headers $headers -Body $body
```

### 4. Monitor Progress

Check the "Actions" tab in your GitHub repository to monitor workflow progress.

## 🔄 Workflow Overview

The workflow consists of three sequential jobs:

### Job 1: Primary VIN Decode (`primary-decode`)
- **Duration**: ~30 seconds
- **Purpose**: Decode VIN using NHTSA DecodeVinExtended API
- **Output**: `vin-basic-data.json`
- **Key Data**: Make, model, year, engine, manufacturing details

### Job 2: Enhanced Data Collection (`enhance-data`)
- **Duration**: ~2-3 minutes
- **Purpose**: Collect additional data from 5 NHTSA APIs
- **Output**: `vin-enhanced-data.json`
- **Dependencies**: Requires Job 1 completion

### Job 3: Final Processing (`finalize-data`)
- **Duration**: ~15 seconds
- **Purpose**: Consolidate data, validate, and generate final report
- **Output**: `vin-complete-{VIN}-{timestamp}.json`
- **Dependencies**: Requires Job 2 completion

## 🔌 API Endpoints Used

| Endpoint | Purpose | Data Provided |
|----------|---------|---------------|
| `DecodeVinExtended` | Primary VIN decode | 144 vehicle variables |
| `GetManufacturerDetails` | Manufacturer info | Contact details, plant locations |
| `DecodeWMI` | WMI analysis | World Manufacturer Identifier details |
| `GetModelsForMakeYear` | Model variations | Available trims and configurations |
| `GetEquipmentPlantCodes` | Plant capabilities | Manufacturing equipment details |
| `GetVehicleTypesForMake` | Vehicle portfolio | Complete vehicle type listings |

## ⚙️ Setup Instructions

### Prerequisites

- GitHub repository with Actions enabled
- GitHub Personal Access Token with `repo` scope
- PowerShell (for triggering workflows)

### Environment Variables

The workflow uses these environment variables:

```yaml
env:
  NHTSA_API_BASE: "https://vpic.nhtsa.dot.gov/api/vehicles"
```

### Required Files

All necessary files are included in this repository:

```
vin-decoder-workflow/
├── .github/workflows/vin-decode.yml    # Main workflow
├── scripts/
│   ├── decode_vin.py                   # Primary decode script
│   ├── enhance_data.py                 # Enhancement script
│   ├── finalize_data.py                # Final processing script
│   ├── utils.py                        # Utility functions
│   └── requirements.txt                # Python dependencies
├── data/schemas/
│   └── vin_data_schema.json           # JSON validation schema
└── README.md                          # This file
```

## 💻 Usage Examples

### Basic VIN Decoding

```powershell
# Decode a 2006 Porsche 911
$vin = "WP0AA29936S715303"
$body = @{
    event_type = "decode_vin"
    client_payload = @{ vin = $vin }
} | ConvertTo-Json

Invoke-RestMethod -Uri $webhookUrl -Method POST -Headers $headers -Body $body
```

### Batch Processing

```powershell
# Process multiple VINs
$vins = @(
    "WP0AA29936S715303",
    "1HGCM82633A123456",
    "5NPE34AF4EH123456"
)

foreach ($vin in $vins) {
    $body = @{
        event_type = "decode_vin"
        client_payload = @{ vin = $vin }
    } | ConvertTo-Json

    Invoke-RestMethod -Uri $webhookUrl -Method POST -Headers $headers -Body $body
    Start-Sleep -Seconds 10  # Prevent rate limiting
}
```

## 📊 Output Format

### Final Report Structure

```json
{
  "report_metadata": {
    "vin": "WP0AA29936S715303",
    "report_type": "Complete VIN Analysis",
    "generated_at": "2025-09-14T15:30:45.123Z",
    "data_sources": ["NHTSA vPIC DecodeVinExtended", "NHTSA vPIC Enhancement APIs"],
    "workflow_version": "1.0"
  },
  "vehicle_summary": {
    "vin": "WP0AA29936S715303",
    "make": "PORSCHE",
    "model": "911",
    "model_year": "2006",
    "manufacturer": "DR. ING. H.C.F. PORSCHE AG",
    "body_class": "Coupe",
    "engine_cylinders": "6",
    "displacement_l": "3.6",
    "fuel_type": "Gasoline",
    "plant_city": "STUTTGART-ZUFFENHAUSEN",
    "plant_country": "GERMANY",
    "drive_type": "4x2"
  },
  "processing_information": {
    "final_processing_timestamp": "2025-09-14T15:33:12.456Z",
    "api_success_rate": "100.0%",
    "data_quality_score": 95.8,
    "successful_api_calls": 6,
    "total_api_calls": 6
  },
  "detailed_data": {
    "basic_decode": { /* Full DecodeVinExtended response */ },
    "enhanced_decode": { /* All enhancement API responses */ }
  },
  "recommendations": {
    "data_completeness": [],
    "vehicle_insights": ["Vehicle is 19 years old - may have limited parts availability"],
    "potential_issues": []
  }
}
```

### Data Quality Scoring

The workflow calculates a data quality score (0-100%) based on:

- **Basic Data Completeness (60%)**: Essential fields from primary decode
- **Enhancement Success (40%)**: Success rate of additional API calls

## 🔧 Troubleshooting

### Common Issues

#### 1. Invalid VIN Error
```
Error: VIN must be exactly 17 characters
```
**Solution**: Ensure VIN is exactly 17 alphanumeric characters (excluding I, O, Q).

#### 2. API Rate Limiting
```
Request failed: HTTP 429 Too Many Requests
```
**Solution**: The workflow includes built-in 3-second delays. For batch processing, add delays between workflow triggers.

#### 3. Authentication Error
```
Error: Bad credentials
```
**Solution**: Verify your GitHub token has `repo` scope and is correctly formatted.

#### 4. Workflow Not Triggering
**Check**:
- Repository has Actions enabled
- Webhook URL is correct
- Token permissions are sufficient
- Event type matches (`decode_vin`)

### Debug Mode

Enable debug logging by setting the `ACTIONS_RUNNER_DEBUG` secret to `true` in repository settings.

### Logs Location

Workflow logs are available in:
- Repository → Actions tab → Select workflow run → View logs

## 📈 Performance

### Typical Execution Times

| Job | Duration | API Calls | Rate Limited |
|-----|----------|-----------|--------------|
| Primary Decode | 30 seconds | 1 | No |
| Enhanced Collection | 2-3 minutes | 5 | Yes (3s delays) |
| Final Processing | 15 seconds | 0 | No |
| **Total** | **3-4 minutes** | **6** | **Yes** |

### Rate Limiting Strategy

- 3-second delays between API calls
- Exponential backoff on failures
- Maximum 3 retry attempts per call

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make changes and test thoroughly
4. Commit changes: `git commit -am 'Add feature'`
5. Push to branch: `git push origin feature-name`
6. Submit a Pull Request

### Development Setup

```bash
# Install dependencies
pip install -r scripts/requirements.txt

# Run tests locally
python scripts/decode_vin.py WP0AA29936S715303
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **NHTSA vPIC API**: Vehicle data provided by the National Highway Traffic Safety Administration
- **GitHub Actions**: Workflow automation platform
- **Python Community**: Libraries and tools used in this project

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/username/vin-decoder-workflow/issues)
- **Discussions**: [GitHub Discussions](https://github.com/username/vin-decoder-workflow/discussions)
- **Documentation**: This README and inline code comments

---

**Note**: This workflow uses free NHTSA government data and respects their API usage guidelines. No API keys or paid services required.
