# Azure VNet Hub-Spoke Peering Management

A comprehensive Python script for managing Azure Virtual Network (VNet) peerings in a hub-spoke architecture across multiple subscriptions and regions.

## Overview

This script automates the creation, repair, and cleanup of VNet peerings between hub and spoke networks in Azure. It's designed for organizations with:
- Hub VNets in specific subscriptions
- Spoke VNets distributed across multiple subscriptions within a tenant
- Multi-region deployments requiring cross-region peering management

## Features

- **Automatic Tenant Discovery**: Discovers all subscriptions in your Azure tenant
- **Selective Subscription Management**: 
  - Hub VNets searched only in specified subscriptions
  - Spoke VNets searched across all tenant subscriptions (with exclusion support)
- **Intelligent Peering Management**:
  - Creates new peerings between hubs and spokes
  - Repairs unhealthy or misconfigured peerings
  - Maintains bidirectional peering connections
- **Orphan Cleanup**: Removes peerings pointing to non-existent VNets
- **Multi-Region Support**: Processes region pairs based on configuration files
- **Comprehensive Reporting**: Generates detailed HTML reports of all operations
- **Dry Run Mode**: Preview changes without making actual modifications

## Prerequisites

### Python Dependencies

```bash
pip install azure-identity azure-mgmt-network azure-mgmt-subscription tabulate
```

### Azure Requirements

- Azure Service Principal with appropriate permissions:
  - `Network Contributor` role on all relevant subscriptions
  - `Reader` role at the tenant level (for subscription discovery)
- Network architecture following hub-spoke topology
- VNets tagged appropriately for identification

### Region Configuration Files

The script expects region configuration files in the following structure:
```
hub/
├── hubUS
├── hubEU
└── hubAPAC

spoke/
├── spokeUS
├── spokeEU
└── spokeAPAC
```

Each file should contain a list of Azure regions (one per line):
```
eastus
westus2
centralus
```

## Installation

1. Clone or download the script
2. Install required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Create region configuration files as described above

## Usage

### Basic Usage

```bash
python vnet_peering_manager.py \
  --hub-subscription-ids sub1,sub2 \
  --tenant-id your-tenant-id \
  --client-id your-client-id \
  --client-secret your-client-secret
```

### Exclude Specific Subscriptions from Spoke Search

```bash
python vnet_peering_manager.py \
  --hub-subscription-ids sub1,sub2 \
  --spoke-exclude-subscription-ids sub3,sub4 \
  --tenant-id your-tenant-id \
  --client-id your-client-id \
  --client-secret your-client-secret
```

### Dry Run Mode

Preview changes without making modifications:
```bash
python vnet_peering_manager.py \
  --hub-subscription-ids sub1 \
  --tenant-id your-tenant-id \
  --client-id your-client-id \
  --client-secret your-client-secret \
  --dry-run
```

### Skip Orphan Cleanup

```bash
python vnet_peering_manager.py \
  --hub-subscription-ids sub1,sub2 \
  --tenant-id your-tenant-id \
  --client-id your-client-id \
  --client-secret your-client-secret \
  --skip-cleanup
```

## Command-Line Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--tenant-id` | Yes | Azure AD tenant ID |
| `--client-id` | Yes | Service Principal client ID |
| `--client-secret` | Yes | Service Principal client secret |
| `--hub-subscription-ids` | Yes | Comma-separated list of subscription IDs containing hub VNets |
| `--spoke-exclude-subscription-ids` | No | Comma-separated list of subscription IDs to exclude from spoke VNet search |
| `--dry-run` | No | Simulate operations without making changes |
| `--skip-cleanup` | No | Skip orphan peering cleanup |

## How It Works

### VNet Discovery

1. **Hub VNets**: Searched only in subscriptions specified by `--hub-subscription-ids`
   - Must have name prefix: `cngfw-az`
   - Must have tag: `appname` containing `hub`

2. **Spoke VNets**: Searched in all tenant subscriptions except those in `--spoke-exclude-subscription-ids`
   - Must have name prefix: `opencti` or `MISP`

### Peering Process

1. **Region Pair Processing**: The script processes predefined region pairs:
   - US: `hub/hubUS` ↔ `spoke/spokeUS`
   - EU: `hub/hubEU` ↔ `spoke/spokeEU`
   - APAC: `hub/hubAPAC` ↔ `spoke/spokeAPAC`

2. **Peering Creation/Repair**:
   - Checks existing peerings for health status
   - Deletes unhealthy peerings
   - Creates new bidirectional peerings
   - Names follow pattern: `cngfw_dnd-{source}-to-{target}`

3. **Orphan Cleanup** (unless skipped):
   - Identifies peerings pointing to non-existent VNets
   - Removes orphaned peerings to maintain clean configuration

### Peering Health Criteria

A peering is considered healthy when:
- State is "Connected"
- Virtual network access is allowed
- Forwarded traffic is allowed

## Output

### Console Output
- Real-time progress updates
- Detailed logging of all operations
- Error messages and warnings
- Summary statistics

### HTML Report
Generated with timestamp, containing:
- Summary of operations
- Successful peerings table
- Failed peerings with error details
- All peerings grouped by region pair
- Deleted orphan peerings

Example: `vnet_peering_report_20240118_143052.html`

## Security Considerations

- **Credentials**: Never commit credentials to version control
- **Service Principal**: Use least-privilege access
  - Minimum required: Network Contributor on relevant subscriptions
  - Reader access at tenant root for subscription discovery
- **Network Security**: Ensure peering aligns with your security policies

## Troubleshooting

### Common Issues

1. **Authentication Failures**
   - Verify Service Principal credentials
   - Check Service Principal has required permissions
   - Ensure tenant ID is correct

2. **Subscription Discovery Fails**
   - Service Principal needs Reader access at tenant level
   - Falls back to hub subscriptions only

3. **Peering Creation Fails**
   - Check Network Contributor role assignment
   - Verify VNet names don't exceed 80 characters
   - Ensure no IP address conflicts between VNets

4. **No VNets Found**
   - Verify region configuration files exist and are correct
   - Check VNet naming conventions and tags
   - Ensure subscriptions contain expected VNets

### Debug Tips

- Use `--dry-run` to preview operations
- Check the HTML report for detailed error messages
- Verify region files contain valid Azure region names
- Ensure VNets are properly tagged

## Best Practices

1. **Run in Dry Mode First**: Always test with `--dry-run` before actual execution
2. **Regular Maintenance**: Schedule regular runs to maintain peering health
3. **Monitor Reports**: Review HTML reports for failed operations
4. **Version Control**: Keep region configuration files in version control
5. **Backup**: Document existing peering configuration before major changes

## Limitations

- Peering names are limited to 80 characters (automatically truncated if needed)
- Gateway transit and remote gateways are disabled by default
- Only processes VNets with specific naming patterns and tags
- Requires appropriate network permissions in all subscriptions

## Contributing

When contributing to this script:
1. Test thoroughly in a non-production environment
2. Update documentation for new features
3. Follow existing code style and patterns
4. Add appropriate error handling

## License

[Your License Here]

## Support

For issues or questions:
- Review the generated HTML report for detailed error information
- Check Azure Activity Logs for peering operations
- Verify Service Principal permissions
- Ensure network configuration allows peering