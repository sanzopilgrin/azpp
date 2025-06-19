# Azure VNet Hub-Spoke Peering Manager

A robust Python script for managing Azure Virtual Network (VNet) peerings in hub-spoke architectures across multiple subscriptions. The tool automates the creation, repair, and cleanup of VNet peerings while providing comprehensive reporting and monitoring capabilities.

## Table of Contents
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Authentication Methods](#authentication-methods)
- [Region Configuration](#region-configuration)
- [Reports and Logging](#reports-and-logging)
- [Advanced Features](#advanced-features)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

## Features

### Core Functionality
- **Automated Peering Management**: Create, repair, and maintain bidirectional VNet peerings
- **Multi-Subscription Support**: Manage peerings across multiple Azure subscriptions
- **Intelligent Discovery**: Automatically discover VNets based on naming patterns and tags
- **Health Monitoring**: Detect and repair unhealthy peerings automatically
- **Orphan Cleanup**: Remove peerings pointing to non-existent VNets

### Performance & Reliability
- **Parallel Processing**: Concurrent operations for faster execution
- **Retry Logic**: Automatic retry with exponential backoff for transient failures
- **Connection Pooling**: Efficient resource utilization
- **Configurable Threading**: Adjust worker threads based on your environment

### Monitoring & Reporting
- **Comprehensive HTML Reports**: Professional reports with metrics and visualizations
- **JSON Export**: Machine-readable output for integration with other tools
- **Detailed Logging**: Multi-level logging with separate failure tracking
- **Real-time Progress**: Colored console output with progress indicators

### Enterprise Features
- **Multiple Authentication Methods**: Service Principal, Managed Identity, and Default Credential
- **Configuration Files**: YAML-based configuration for repeatable deployments
- **Dry Run Mode**: Test changes before applying them
- **Custom Peering Settings**: Configure gateway transit, forwarded traffic, etc.

## Prerequisites

### System Requirements
- Python 3.7 or higher
- pip (Python package manager)

### Azure Requirements
- Azure subscription(s)
- Appropriate permissions:
  - `Network Contributor` role on all VNets to be managed
  - `Reader` role on all subscriptions for VNet discovery
- Service Principal or Managed Identity (for authentication)

### Required Python Packages
```bash
pip install -r requirements.txt
```

**requirements.txt:**
```
azure-identity>=1.14.0
azure-mgmt-network>=23.0.0
azure-mgmt-subscription>=3.1.0
azure-core>=1.28.0
tabulate>=0.9.0
colorama>=0.4.6
pyyaml>=6.0
```

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/azure-vnet-peering-manager.git
cd azure-vnet-peering-manager
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up region configuration files (see [Region Configuration](#region-configuration))

## Configuration

### Command Line Arguments

| Argument | Required | Description | Default |
|----------|----------|-------------|---------|
| `--hub-subscription-ids` | Yes | Comma-separated list of subscription IDs containing hub VNets | - |
| `--auth-method` | No | Authentication method: `service_principal`, `managed_identity`, or `default` | `default` |
| `--tenant-id` | Conditional | Azure AD tenant ID (required for service_principal) | - |
| `--client-id` | Conditional | Service principal or managed identity client ID | - |
| `--client-secret` | Conditional | Service principal client secret (required for service_principal) | - |
| `--spoke-exclude-subscription-ids` | No | Comma-separated list of subscription IDs to exclude from spoke search | - |
| `--config` | No | Path to YAML configuration file | - |
| `--max-workers` | No | Maximum number of concurrent workers | 10 |
| `--dry-run` | No | Simulate operations without making changes | False |
| `--skip-cleanup` | No | Skip orphan peering cleanup | False |
| `--export-json` | No | Export report in JSON format | False |
| `--log-level` | No | Logging level: DEBUG, INFO, WARNING, ERROR | INFO |

### YAML Configuration File

Create a `config.yaml` file for advanced configuration:

```yaml
# VNet name prefixes to search for
hub_prefixes:
  - cngfw-az
  - hub-vnet
  - hub-

spoke_prefixes:
  - opencti
  - MISP
  - spoke-vnet
  - app-

# Tag filters for VNet discovery
hub_tag_key: appname
hub_tag_value: hub

# Region pair mappings
region_pairs:
  - ["hub/hubUS", "spoke/spokeUS"]
  - ["hub/hubEU", "spoke/spokeEU"]
  - ["hub/hubAPAC", "spoke/spokeAPAC"]
  - ["hub/hubUK", "spoke/spokeUK"]

# Peering configuration settings
peering_config:
  allow_virtual_network_access: true
  allow_forwarded_traffic: true
  allow_gateway_transit: false
  use_remote_gateways: false

# Advanced settings
max_peering_name_length: 79
health_check_timeout: 300
retry_attempts: 3
retry_delay: 5
```

## Usage

### Basic Usage

1. **Service Principal Authentication:**
```bash
python vnet_peering_manager.py \
  --hub-subscription-ids "sub-id-1,sub-id-2" \
  --auth-method service_principal \
  --tenant-id "your-tenant-id" \
  --client-id "your-client-id" \
  --client-secret "your-client-secret"
```

2. **Managed Identity Authentication (when running in Azure):**
```bash
python vnet_peering_manager.py \
  --hub-subscription-ids "sub-id-1" \
  --auth-method managed_identity
```

3. **With Configuration File:**
```bash
python vnet_peering_manager.py \
  --hub-subscription-ids "sub-id-1,sub-id-2" \
  --config config.yaml \
  --auth-method default
```

4. **Dry Run Mode:**
```bash
python vnet_peering_manager.py \
  --hub-subscription-ids "sub-id-1" \
  --dry-run \
  --auth-method default
```

### Advanced Usage

1. **Exclude Specific Subscriptions from Spoke Discovery:**
```bash
python vnet_peering_manager.py \
  --hub-subscription-ids "hub-sub-1,hub-sub-2" \
  --spoke-exclude-subscription-ids "dev-sub-1,test-sub-1" \
  --auth-method default
```

2. **Increase Parallelism for Large Environments:**
```bash
python vnet_peering_manager.py \
  --hub-subscription-ids "sub-id-1,sub-id-2" \
  --max-workers 20 \
  --auth-method default
```

3. **Debug Mode with JSON Export:**
```bash
python vnet_peering_manager.py \
  --hub-subscription-ids "sub-id-1" \
  --log-level DEBUG \
  --export-json \
  --auth-method default
```

## Authentication Methods

### 1. Service Principal
Create a service principal and assign necessary permissions:

```bash
# Create service principal
az ad sp create-for-rbac --name "vnet-peering-manager" --role "Network Contributor"

# Assign additional reader role for subscription discovery
az role assignment create --assignee <app-id> --role "Reader" --scope /subscriptions/<subscription-id>
```

### 2. Managed Identity
When running in Azure (VM, Container Instance, etc.):

```bash
# Enable system-assigned managed identity
az vm identity assign --name <vm-name> --resource-group <rg-name>

# Grant permissions
az role assignment create --assignee <identity-object-id> --role "Network Contributor" --scope <vnet-resource-id>
```

### 3. Default Credential
Uses Azure CLI, environment variables, or managed identity automatically:

```bash
# Login with Azure CLI
az login

# Run the script
python vnet_peering_manager.py --hub-subscription-ids "sub-id" --auth-method default
```

## Region Configuration

Create region files in the following structure:

```
project/
├── hub/
│   ├── hubUS         # List of US hub regions
│   ├── hubEU         # List of EU hub regions
│   └── hubAPAC       # List of APAC hub regions
└── spoke/
    ├── spokeUS       # List of US spoke regions
    ├── spokeEU       # List of EU spoke regions
    └── spokeAPAC     # List of APAC spoke regions
```

### Example Region File (hub/hubUS):
```
eastus
eastus2
westus
westus2
centralus
# Comments are supported
northcentralus
southcentralus
```

### Region Mapping Logic
The script creates peerings between all VNets in corresponding region pairs:
- All hub VNets in `hubUS` regions peer with all spoke VNets in `spokeUS` regions
- All hub VNets in `hubEU` regions peer with all spoke VNets in `spokeEU` regions
- And so on...

## Reports and Logging

### Generated Files

1. **Main Log File**: `vnet_peering_YYYYMMDD_HHMMSS.log`
   - Complete execution log
   - All operations and decisions
   - Debug information (if enabled)

2. **Failure Log File**: `vnet_peering_failures_YYYYMMDD_HHMMSS.log`
   - Only created if critical failures occur
   - Detailed context for failures after max retries
   - Useful for troubleshooting persistent issues

3. **HTML Report**: `vnet_peering_report_YYYYMMDD_HHMMSS.html`
   - Executive summary with metrics
   - Visual representation of operations
   - Grouped by region pairs
   - Success/failure statistics

4. **JSON Report**: `vnet_peering_report_YYYYMMDD_HHMMSS.json` (optional)
   - Machine-readable format
   - Complete operation details
   - Integration with other tools

### Report Sections

#### HTML Report Contents:
- **Executive Summary**: Overview metrics and statistics
- **Performance Metrics**: Operation counts and success rates
- **Successful Operations**: List of created/repaired peerings
- **Failed Operations**: Peerings that couldn't be established
- **All Peerings by Region**: Complete inventory grouped by region pairs
- **Deleted Orphans**: Cleaned up invalid peerings
- **Critical Failures**: Operations that failed after max retries

## Advanced Features

### Parallel Processing
The script uses ThreadPoolExecutor for concurrent operations:
- Subscription scanning
- Peering creation/repair
- Orphan cleanup

Adjust `--max-workers` based on:
- Number of subscriptions
- Number of VNets
- Azure API rate limits

### Retry Logic
Automatic retry with exponential backoff for:
- Transient network failures
- Azure API throttling
- Temporary resource locks

### Health Checks
Peerings are considered healthy when:
- State is "Connected"
- Virtual network access is allowed
- Forwarded traffic is allowed
- Sync level is "FullyInSync" (if available)

### Orphan Detection
Identifies and removes peerings that:
- Point to non-existent VNets
- Reference deleted resources
- Have invalid remote VNet IDs

## Troubleshooting

### Common Issues

1. **Authentication Failures**
   ```
   Error: Authentication failed: Invalid client secret provided
   ```
   - Verify service principal credentials
   - Check tenant ID is correct
   - Ensure client secret hasn't expired

2. **Permission Errors**
   ```
   Error: The client 'xxx' does not have authorization to perform action
   ```
   - Grant Network Contributor role on VNets
   - Grant Reader role on subscriptions
   - Check scope of role assignments

3. **VNet Not Found**
   ```
   Warning: No hub VNets found for regions in hub/hubUS
   ```
   - Verify region files exist and contain valid regions
   - Check VNet naming matches configured prefixes
   - Ensure tags match filter criteria

4. **Peering Failures**
   ```
   Error: Failed to create peering after 3 attempts
   ```
   - Check failure log for details
   - Verify network connectivity between regions
   - Ensure no conflicting peerings exist
   - Check VNet address spaces don't overlap

### Debug Mode
Enable detailed logging for troubleshooting:
```bash
python vnet_peering_manager.py --hub-subscription-ids "sub-id" --log-level DEBUG
```

### Validation Steps
1. List all VNets to verify discovery:
   ```bash
   az network vnet list --subscription <sub-id> --output table
   ```

2. Check existing peerings:
   ```bash
   az network vnet peering list --resource-group <rg> --vnet-name <vnet> --output table
   ```

3. Verify permissions:
   ```bash
   az role assignment list --assignee <service-principal-id> --output table
   ```

## Best Practices

1. **Start with Dry Run**: Always test with `--dry-run` first
2. **Use Configuration Files**: Store settings in YAML for consistency
3. **Monitor Logs**: Check both main and failure logs
4. **Regular Cleanup**: Run periodically to remove orphaned peerings
5. **Incremental Rollout**: Test with a subset of subscriptions first
6. **Backup State**: Export JSON reports before major changes

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Update documentation
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review logs for detailed error messages
3. Open an issue on GitHub with:
   - Script version
   - Error messages
   - Sanitized log excerpts
   - Steps to reproduce