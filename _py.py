#!/usr/bin/env python3
"""
Enhanced Azure VNet Hub-Spoke Peering Management Script

This script manages VNet peerings between hub and spoke networks across Azure subscriptions.
It creates, repairs, and cleans up peerings while generating comprehensive reports.
"""

import os
import sys
import argparse
import time
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Tuple, Optional, Set

from azure.identity import ClientSecretCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import VirtualNetwork, VirtualNetworkPeering
from azure.mgmt.subscription import SubscriptionClient
from tabulate import tabulate


class VNetPeeringManager:
    """Manages Azure VNet peering operations."""
    
    def __init__(self, hub_subscription_ids: List[str], spoke_exclude_subscription_ids: List[str], 
                 tenant_id: str, client_id: str, client_secret: str):
        """Initialize the peering manager with hub subscriptions and spoke exclusions."""
        self.hub_subscription_ids = hub_subscription_ids
        self.spoke_exclude_subscription_ids = spoke_exclude_subscription_ids or []
        self.tenant_id = tenant_id
        self.credential = self._get_credential(tenant_id, client_id, client_secret)
        
        # Get all subscriptions in the tenant for spoke VNets
        self.all_subscription_ids = self._get_all_tenant_subscriptions()
        
        # Determine spoke subscriptions (all except excluded)
        self.spoke_subscription_ids = [
            sub_id for sub_id in self.all_subscription_ids 
            if sub_id not in self.spoke_exclude_subscription_ids
        ]
        
        # Create clients for all subscriptions we'll need
        all_needed_subs = set(self.hub_subscription_ids + self.spoke_subscription_ids)
        self.clients = {
            sub_id: NetworkManagementClient(self.credential, sub_id)
            for sub_id in all_needed_subs
        }
        
        # Report data structure
        self.report_data = {
            "successful_peerings": [],
            "failed_peerings": [],
            "all_peerings": [],
            "deleted_orphans": []
        }
        
        print(f"📊 Subscription Configuration:")
        print(f"   Hub Subscriptions: {len(self.hub_subscription_ids)}")
        print(f"   Total Tenant Subscriptions: {len(self.all_subscription_ids)}")
        print(f"   Excluded from Spokes: {len(self.spoke_exclude_subscription_ids)}")
        print(f"   Spoke Subscriptions: {len(self.spoke_subscription_ids)}")
    
    def _get_credential(self, tenant_id: str, client_id: str, client_secret: str) -> ClientSecretCredential:
        """Get Azure credentials using Client Secret."""
        if not all([tenant_id, client_id, client_secret]):
            missing = []
            if not tenant_id:
                missing.append("tenant_id")
            if not client_id:
                missing.append("client_id")
            if not client_secret:
                missing.append("client_secret")
            raise ValueError(f"Missing required credentials: {', '.join(missing)}")
        
        return ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
    
    def _get_all_tenant_subscriptions(self) -> List[str]:
        """Get all subscription IDs in the tenant."""
        try:
            subscription_client = SubscriptionClient(self.credential)
            subscriptions = []
            
            print("🔍 Discovering all subscriptions in tenant...")
            for sub in subscription_client.subscriptions.list():
                if sub.state == "Enabled":
                    subscriptions.append(sub.subscription_id)
                    print(f"   Found: {sub.display_name} ({sub.subscription_id})")
            
            return subscriptions
        except Exception as e:
            print(f"❌ Failed to list tenant subscriptions: {e}")
            print("   Falling back to using only explicitly provided subscriptions")
            return self.hub_subscription_ids
    
    def load_regions(self, filename: str) -> List[str]:
        """Load region list from file."""
        if not os.path.exists(filename):
            print(f"⚠️  Region file '{filename}' not found.")
            return []
        
        try:
            with open(filename, 'r') as f:
                regions = [line.strip() for line in f if line.strip()]
            print(f"📍 Loaded {len(regions)} regions from {filename}")
            return regions
        except Exception as e:
            print(f"❌ Failed to load regions from {filename}: {e}")
            return []
    
    def extract_resource_group(self, resource_id: str) -> Optional[str]:
        """Extract resource group name from Azure resource ID."""
        try:
            parts = resource_id.split('/')
            return parts[4] if len(parts) > 4 and 'resourceGroups' in parts else None
        except (IndexError, AttributeError):
            return None
    
    def get_vnets_by_criteria(self, regions: List[str], prefixes: List[str], 
                             tag_key: Optional[str] = None, 
                             tag_value_contains: Optional[str] = None,
                             subscription_ids: Optional[List[str]] = None) -> List[VirtualNetwork]:
        """Get VNets matching specified criteria across specified subscriptions."""
        vnets = []
        region_lower = [r.lower() for r in regions]
        
        # Use provided subscription list or default to all clients
        target_subscriptions = subscription_ids if subscription_ids else list(self.clients.keys())
        
        for sub_id in target_subscriptions:
            if sub_id not in self.clients:
                print(f"⚠️  Skipping subscription {sub_id} - no client available")
                continue
                
            client = self.clients[sub_id]
            try:
                print(f"🔍 Scanning subscription: {sub_id}")
                for vnet in client.virtual_networks.list_all():
                    # Filter by region
                    if vnet.location.lower() not in region_lower:
                        continue
                    
                    # Filter by name prefix
                    if not any(vnet.name.startswith(pfx) for pfx in prefixes):
                        continue
                    
                    # Filter by tags if specified
                    if tag_key and tag_value_contains:
                        tags = vnet.tags or {}
                        tag_val = tags.get(tag_key, "").lower()
                        if tag_value_contains.lower() not in tag_val:
                            continue
                    
                    vnets.append(vnet)
                    
            except Exception as e:
                print(f"⚠️  Failed to scan subscription {sub_id}: {e}")
                continue
        
        print(f"✅ Found {len(vnets)} VNets matching criteria in {len(target_subscriptions)} subscriptions")
        return vnets
    
    def generate_peering_name(self, vnet_a_name: str, vnet_b_name: str, max_length: int = 79) -> str:
        """Generate peering name with length constraints."""
        base_name = f"cngfw_dnd-{vnet_a_name}-to-{vnet_b_name}"
        
        if len(base_name) <= max_length:
            return base_name
        
        # Truncate proportionally if too long
        prefix_length = len("cngfw_dnd--to-")
        max_each = (max_length - prefix_length) // 2
        short_a = vnet_a_name[:max_each]
        short_b = vnet_b_name[:max_each]
        truncated_name = f"cngfw_dnd-{short_a}-to-{short_b}"
        
        print(f"⚠️  Peering name truncated: {base_name} -> {truncated_name}")
        return truncated_name
    
    def is_healthy_peering(self, peering: VirtualNetworkPeering) -> bool:
        """Check if peering is in healthy state."""
        return (
            peering and
            peering.peering_state == "Connected" and
            peering.allow_virtual_network_access and
            peering.allow_forwarded_traffic
        )
    
    def get_existing_peering(self, vnet: VirtualNetwork, peer_name: str) -> Optional[VirtualNetworkPeering]:
        """Get existing peering by name."""
        try:
            rg = self.extract_resource_group(vnet.id)
            sub_id = vnet.id.split("/")[2]
            client = self.clients[sub_id]
            
            peerings = list(client.virtual_network_peerings.list(rg, vnet.name))
            return next((p for p in peerings if p.name == peer_name), None)
            
        except Exception as e:
            print(f"⚠️  Error checking peering '{peer_name}' in VNet '{vnet.name}': {e}")
            return None
    
    def create_peering(self, source_vnet: VirtualNetwork, target_vnet: VirtualNetwork, 
                      peering_name: str) -> bool:
        """Create a single peering connection."""
        try:
            rg = self.extract_resource_group(source_vnet.id)
            sub_id = source_vnet.id.split("/")[2]
            client = self.clients[sub_id]
            
            peering_params = {
                "remote_virtual_network": {"id": target_vnet.id},
                "allow_virtual_network_access": True,
                "allow_forwarded_traffic": True,
                "allow_gateway_transit": False,
                "use_remote_gateways": False,
            }
            
            client.virtual_network_peerings.begin_create_or_update(
                rg, source_vnet.name, peering_name, peering_params
            ).result()
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to create peering '{peering_name}': {e}")
            return False
    
    def delete_peering(self, vnet: VirtualNetwork, peering_name: str) -> bool:
        """Delete a peering connection."""
        try:
            rg = self.extract_resource_group(vnet.id)
            sub_id = vnet.id.split("/")[2]
            client = self.clients[sub_id]
            
            client.virtual_network_peerings.begin_delete(rg, vnet.name, peering_name).result()
            return True
            
        except Exception as e:
            print(f"❌ Failed to delete peering '{peering_name}': {e}")
            return False
    
    def create_or_repair_peering_pair(self, hub_vnet: VirtualNetwork, spoke_vnet: VirtualNetwork, 
                                     region_pair: str) -> None:
        """Create or repair bidirectional peering between hub and spoke."""
        # Generate peering names
        hub_to_spoke_name = self.generate_peering_name(hub_vnet.name, spoke_vnet.name)
        spoke_to_hub_name = self.generate_peering_name(spoke_vnet.name, hub_vnet.name)
        
        # Check existing peerings
        existing_hub_to_spoke = self.get_existing_peering(hub_vnet, hub_to_spoke_name)
        existing_spoke_to_hub = self.get_existing_peering(spoke_vnet, spoke_to_hub_name)
        
        # Determine if repair is needed
        hub_healthy = self.is_healthy_peering(existing_hub_to_spoke)
        spoke_healthy = self.is_healthy_peering(existing_spoke_to_hub)
        
        if hub_healthy and spoke_healthy:
            print(f"✅ Peerings between {hub_vnet.name} and {spoke_vnet.name} are healthy")
            self.report_data["all_peerings"].append({
                "hub_vnet": hub_vnet.name,
                "spoke_vnet": spoke_vnet.name,
                "status": "Healthy",
                "action": "No Change",
                "region_pair": region_pair,
                "error": None
            })
            return
        
        print(f"🔧 {'Repairing' if (existing_hub_to_spoke or existing_spoke_to_hub) else 'Creating'} "
              f"peerings between {hub_vnet.name} and {spoke_vnet.name}")
        
        # Delete unhealthy peerings
        if existing_hub_to_spoke and not hub_healthy:
            print(f"🧹 Deleting unhealthy hub->spoke peering")
            self.delete_peering(hub_vnet, hub_to_spoke_name)
        
        if existing_spoke_to_hub and not spoke_healthy:
            print(f"🧹 Deleting unhealthy spoke->hub peering")
            self.delete_peering(spoke_vnet, spoke_to_hub_name)
        
        # Create new peerings
        hub_success = self.create_peering(hub_vnet, spoke_vnet, hub_to_spoke_name)
        spoke_success = self.create_peering(spoke_vnet, hub_vnet, spoke_to_hub_name)
        
        # Record results
        if hub_success and spoke_success:
            action = "Repaired" if (existing_hub_to_spoke or existing_spoke_to_hub) else "Created"
            print(f"✅ Successfully {action.lower()} peerings between {hub_vnet.name} and {spoke_vnet.name}")
            
            self.report_data["successful_peerings"].append((
                hub_vnet.name, "Hub", hub_to_spoke_name, 
                spoke_vnet.name, "Spoke", action
            ))
            self.report_data["all_peerings"].append({
                "hub_vnet": hub_vnet.name,
                "spoke_vnet": spoke_vnet.name,
                "status": "Connected",
                "action": action,
                "region_pair": region_pair,
                "error": None
            })
        else:
            error_msg = f"Hub->Spoke: {'Failed' if not hub_success else 'OK'}, " \
                       f"Spoke->Hub: {'Failed' if not spoke_success else 'OK'}"
            
            self.report_data["failed_peerings"].append({
                "hub_vnet": hub_vnet.name,
                "spoke_vnet": spoke_vnet.name,
                "error": error_msg
            })
            self.report_data["all_peerings"].append({
                "hub_vnet": hub_vnet.name,
                "spoke_vnet": spoke_vnet.name,
                "status": "Failed",
                "action": "Failed",
                "region_pair": region_pair,
                "error": error_msg
            })
    
    def cleanup_orphan_peerings(self, valid_regions: Set[str], dry_run: bool = False) -> None:
        """Clean up orphaned peerings that point to non-existent VNets."""
        print(f"\n🧹 Cleaning up orphaned peerings {'(DRY RUN)' if dry_run else ''}")
        
        # Build set of all valid VNet IDs across all subscriptions
        valid_vnet_ids = set()
        valid_region_lower = {r.lower() for r in valid_regions}
        
        # Check all subscriptions for valid VNets
        for sub_id, client in self.clients.items():
            try:
                for vnet in client.virtual_networks.list_all():
                    if vnet.location.lower() in valid_region_lower:
                        valid_vnet_ids.add(vnet.id.lower())
            except Exception as e:
                print(f"⚠️  Failed to list VNets in subscription {sub_id}: {e}")
        
        # Find and delete orphaned peerings in all subscriptions
        for sub_id, client in self.clients.items():
            try:
                for vnet in client.virtual_networks.list_all():
                    if vnet.location.lower() not in valid_region_lower:
                        continue
                    
                    rg = self.extract_resource_group(vnet.id)
                    peerings = list(client.virtual_network_peerings.list(rg, vnet.name))
                    
                    for peering in peerings:
                        if not peering.name.startswith("cngfw_dnd"):
                            continue
                        
                        remote_id = peering.remote_virtual_network.id.lower()
                        if remote_id not in valid_vnet_ids:
                            print(f"🗑️  {'Would delete' if dry_run else 'Deleting'} orphaned peering: "
                                  f"{vnet.name} -> {peering.name}")
                            
                            if not dry_run:
                                if self.delete_peering(vnet, peering.name):
                                    self.report_data["deleted_orphans"].append({
                                        "vnet": vnet.name,
                                        "peering_name": peering.name,
                                        "remote_id": remote_id
                                    })
                            
            except Exception as e:
                print(f"⚠️  Failed to process subscription {sub_id}: {e}")
    
    def process_region_pair(self, hub_regions_file: str, spoke_regions_file: str) -> None:
        """Process peering for a specific hub-spoke region pair."""
        print(f"\n{'='*60}")
        print(f"🌍 Processing region pair: {hub_regions_file} <-> {spoke_regions_file}")
        print(f"{'='*60}")
        
        hub_regions = self.load_regions(hub_regions_file)
        spoke_regions = self.load_regions(spoke_regions_file)
        
        if not hub_regions or not spoke_regions:
            print("⚠️  Skipping region pair due to missing regions")
            return
        
        # Get hub VNets (cngfw-az with hub tag) - ONLY from hub subscriptions
        print(f"\n🔍 Searching for hub VNets in {len(self.hub_subscription_ids)} hub subscriptions...")
        hub_vnets = self.get_vnets_by_criteria(
            regions=hub_regions,
            prefixes=["cngfw-az"],
            tag_key="appname",
            tag_value_contains="hub",
            subscription_ids=self.hub_subscription_ids  # Only search in hub subscriptions
        )
        
        # Get spoke VNets (opencti, MISP) - from all subscriptions except excluded
        print(f"\n🔍 Searching for spoke VNets in {len(self.spoke_subscription_ids)} spoke subscriptions...")
        spoke_vnets = self.get_vnets_by_criteria(
            regions=spoke_regions,
            prefixes=["opencti", "MISP"],
            subscription_ids=self.spoke_subscription_ids  # Search in all non-excluded subscriptions
        )
        
        if not hub_vnets:
            print(f"⚠️  No hub VNets found for regions in {hub_regions_file}")
            return
        if not spoke_vnets:
            print(f"⚠️  No spoke VNets found for regions in {spoke_regions_file}")
            return
        
        region_label = f"{os.path.basename(hub_regions_file)} <-> {os.path.basename(spoke_regions_file)}"
        
        # Create peerings between all hub-spoke pairs
        total_pairs = len(hub_vnets) * len(spoke_vnets)
        print(f"🔗 Processing {total_pairs} hub-spoke peering pairs")
        
        for i, hub_vnet in enumerate(hub_vnets, 1):
            for j, spoke_vnet in enumerate(spoke_vnets, 1):
                pair_num = (i-1) * len(spoke_vnets) + j
                print(f"\n[{pair_num}/{total_pairs}] Processing: {hub_vnet.name} <-> {spoke_vnet.name}")
                self.create_or_repair_peering_pair(hub_vnet, spoke_vnet, region_label)
    
    def generate_html_report(self, filename: str = "vnet_peering_report.html") -> None:
        """Generate comprehensive HTML report."""
        def html_table(rows: List, headers: List[str]) -> str:
            if not rows:
                return "<p>No data available.</p>"
            
            table = "<table border='1' cellspacing='0' cellpadding='8' style='border-collapse: collapse; width: 100%;'>"
            table += "<thead><tr style='background-color: #f0f0f0;'>"
            table += "".join(f"<th style='text-align: left; padding: 8px;'>{h}</th>" for h in headers)
            table += "</tr></thead><tbody>"
            
            for i, row in enumerate(rows):
                bg_color = "#f9f9f9" if i % 2 == 0 else "#ffffff"
                table += f"<tr style='background-color: {bg_color};'>"
                table += "".join(f"<td style='padding: 8px;'>{c}</td>" for c in row)
                table += "</tr>"
            
            table += "</tbody></table>"
            return table
        
        # Generate HTML report
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Azure VNet Peering Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1, h2, h3 {{ color: #333; }}
                table {{ margin: 20px 0; }}
                .summary {{ background-color: #e8f4f8; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <h1>🔗 Azure VNet Peering Report</h1>
            <div class="summary">
                <strong>Generated:</strong> {timestamp}<br>
                <strong>Hub Subscriptions:</strong> {len(self.hub_subscription_ids)}<br>
                <strong>Spoke Subscriptions:</strong> {len(self.spoke_subscription_ids)} (from {len(self.all_subscription_ids)} total tenant subscriptions)<br>
                <strong>Excluded Subscriptions:</strong> {len(self.spoke_exclude_subscription_ids)}<br>
                <strong>Successful Peerings:</strong> {len(self.report_data['successful_peerings'])}<br>
                <strong>Failed Peerings:</strong> {len(self.report_data['failed_peerings'])}<br>
                <strong>Deleted Orphans:</strong> {len(self.report_data['deleted_orphans'])}
            </div>
        """
        
        # Successful peerings
        html += "<h2>✅ Successful Peerings</h2>"
        if self.report_data["successful_peerings"]:
            html += html_table(
                self.report_data["successful_peerings"],
                ["Hub VNet", "Role", "Peering Name", "Spoke VNet", "Role", "Action"]
            )
        else:
            html += "<p>No successful peering operations.</p>"
        
        # Failed peerings
        html += "<h2>❌ Failed Peerings</h2>"
        if self.report_data["failed_peerings"]:
            failed_rows = [
                (entry["hub_vnet"], entry["spoke_vnet"], entry["error"])
                for entry in self.report_data["failed_peerings"]
            ]
            html += html_table(failed_rows, ["Hub VNet", "Spoke VNet", "Error"])
        else:
            html += "<p>No peering failures encountered.</p>"
        
        # All peerings grouped by region
        html += "<h2>📊 All Peerings by Region Pair</h2>"
        if self.report_data["all_peerings"]:
            grouped = defaultdict(list)
            for peering in self.report_data["all_peerings"]:
                region = peering.get("region_pair", "Unknown")
                grouped[region].append((
                    peering["hub_vnet"],
                    peering["spoke_vnet"],
                    peering["status"],
                    peering["action"],
                    peering.get("error", "-") or "-"
                ))
            
            for region, peerings in grouped.items():
                html += f"<h3>🌍 {region}</h3>"
                html += html_table(
                    peerings,
                    ["Hub VNet", "Spoke VNet", "Status", "Action", "Error"]
                )
        
        # Deleted orphans
        html += "<h2>🗑️ Deleted Orphan Peerings</h2>"
        if self.report_data["deleted_orphans"]:
            orphan_rows = [
                (entry["vnet"], entry["peering_name"], entry["remote_id"])
                for entry in self.report_data["deleted_orphans"]
            ]
            html += html_table(orphan_rows, ["VNet", "Peering Name", "Remote VNet ID"])
        else:
            html += "<p>No orphan peerings were deleted.</p>"
        
        html += "</body></html>"
        
        with open(filename, "w") as f:
            f.write(html)
        
        print(f"\n📄 HTML report generated: {filename}")


def main():
    """Main function to orchestrate the peering process."""
    parser = argparse.ArgumentParser(
        description="Enhanced Azure VNet Hub-Spoke Peering Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with hub subscriptions only
  python script.py --hub-subscription-ids sub1,sub2 --tenant-id xxx --client-id yyy --client-secret zzz
  
  # Exclude specific subscriptions from spoke search
  python script.py --hub-subscription-ids sub1 --spoke-exclude-subscription-ids sub3,sub4 --tenant-id xxx --client-id yyy --client-secret zzz
  
  # Dry run mode
  python script.py --hub-subscription-ids sub1 --tenant-id xxx --client-id yyy --client-secret zzz --dry-run
        """
    )
    
    # Azure credential arguments
    parser.add_argument(
        "--tenant-id",
        required=True,
        help="Azure AD tenant ID"
    )
    parser.add_argument(
        "--client-id",
        required=True,
        help="Service principal client ID"
    )
    parser.add_argument(
        "--client-secret",
        required=True,
        help="Service principal client secret"
    )
    parser.add_argument(
        "--hub-subscription-ids",
        required=True,
        help="Comma-separated list of subscription IDs containing hub VNets"
    )
    parser.add_argument(
        "--spoke-exclude-subscription-ids",
        default="",
        help="Comma-separated list of subscription IDs to exclude from spoke VNet search (optional)"
    )
    
    # Optional arguments
    parser.add_argument(
        "--dry-run", 
        action="store_true", 
        help="Simulate operations without making changes"
    )
    parser.add_argument(
        "--skip-cleanup", 
        action="store_true", 
        help="Skip orphan peering cleanup"
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Parse subscription IDs
    hub_subscriptions = [sub.strip() for sub in args.hub_subscription_ids.split(",") if sub.strip()]
    if not hub_subscriptions:
        print("❌ No valid hub subscription IDs provided")
        sys.exit(1)
    
    # Parse excluded subscription IDs (can be empty)
    spoke_exclude_subscriptions = []
    if args.spoke_exclude_subscription_ids:
        spoke_exclude_subscriptions = [
            sub.strip() for sub in args.spoke_exclude_subscription_ids.split(",") if sub.strip()
        ]
    
    print(f"🎯 Configuration:")
    print(f"   Hub Subscriptions: {len(hub_subscriptions)}")
    print(f"   Excluded from Spokes: {len(spoke_exclude_subscriptions)}")
    
    # Initialize peering manager with command-line arguments
    try:
        manager = VNetPeeringManager(
            hub_subscription_ids=hub_subscriptions,
            spoke_exclude_subscription_ids=spoke_exclude_subscriptions,
            tenant_id=args.tenant_id,
            client_id=args.client_id,
            client_secret=args.client_secret
        )
        print(f"✅ Successfully authenticated with Azure using Service Principal")
    except ValueError as e:
        print(f"❌ Authentication failed: {e}")
        print("\n📋 Required arguments:")
        print("   --tenant-id: Azure AD tenant ID") 
        print("   --client-id: Service principal client ID")
        print("   --client-secret: Service principal client secret")
        print("   --hub-subscription-ids: Comma-separated list of hub subscription IDs")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to initialize peering manager: {e}")
        sys.exit(1)
    
    # Define region pairs
    region_pairs = [
        ("hub/hubUS", "spoke/spokeUS"),
        ("hub/hubEU", "spoke/spokeEU"),
        ("hub/hubAPAC", "spoke/spokeAPAC")
    ]
    
    # Process each region pair
    for hub_file, spoke_file in region_pairs:
        try:
            manager.process_region_pair(hub_file, spoke_file)
        except Exception as e:
            print(f"❌ Failed to process region pair {hub_file} <-> {spoke_file}: {e}")
            continue
    
    # Cleanup orphaned peerings if not skipped
    if not args.skip_cleanup:
        valid_regions = set()
        for hub_file, spoke_file in region_pairs:
            valid_regions.update(manager.load_regions(hub_file))
            valid_regions.update(manager.load_regions(spoke_file))
        
        manager.cleanup_orphan_peerings(valid_regions, dry_run=args.dry_run)
    
    # Generate final report
    report_filename = f"vnet_peering_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    manager.generate_html_report(report_filename)
    
    print(f"\n🎉 Peering management completed! Check {report_filename} for details.") pair {hub_file} <-> {spoke_file}: {e}")
            continue
    
    # Cleanup orphaned peerings if not skipped
    if not args.skip_cleanup:
        valid_regions = set()
        for hub_file, spoke_file in region_pairs:
            valid_regions.update(manager.load_regions(hub_file))
            valid_regions.update(manager.load_regions(spoke_file))
        
        manager.cleanup_orphan_peerings(valid_regions, dry_run=args.dry_run)
    
    # Generate final report
    report_filename = f"vnet_peering_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    manager.generate_html_report(report_filename)
    
    print(f"\n🎉 Peering management completed! Check {report_filename} for details.")


if __name__ == "__main__":
    main()