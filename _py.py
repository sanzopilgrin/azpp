#!/usr/bin/env python3
"""
Enhanced Azure VNet Hub-Spoke Peering Management Script

This script manages VNet peerings between hub and spoke networks across Azure subscriptions.
It creates, repairs, and cleans up peerings while generating comprehensive reports.
"""

import os
import sys
import json
import argparse
import time
import logging
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Tuple, Optional, Set, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
import yaml

from azure.identity import ClientSecretCredential, DefaultAzureCredential, ManagedIdentityCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import VirtualNetwork, VirtualNetworkPeering
from azure.mgmt.subscription import SubscriptionClient
from azure.core.exceptions import ResourceNotFoundError, AzureError
from tabulate import tabulate
import colorama
from colorama import Fore, Style

# Initialize colorama for cross-platform colored output
colorama.init(autoreset=True)


class PeeringState(Enum):
    """Enum for peering states."""
    CONNECTED = "Connected"
    DISCONNECTED = "Disconnected"
    INITIATED = "Initiated"
    FAILED = "Failed"


class PeeringAction(Enum):
    """Enum for peering actions."""
    CREATED = "Created"
    REPAIRED = "Repaired"  
    DELETED = "Deleted"
    NO_CHANGE = "No Change"
    FAILED = "Failed"


@dataclass
class PeeringConfig:
    """Configuration for VNet peering."""
    allow_virtual_network_access: bool = True
    allow_forwarded_traffic: bool = True
    allow_gateway_transit: bool = False
    use_remote_gateways: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Azure API."""
        return {
            "allow_virtual_network_access": self.allow_virtual_network_access,
            "allow_forwarded_traffic": self.allow_forwarded_traffic,
            "allow_gateway_transit": self.allow_gateway_transit,
            "use_remote_gateways": self.use_remote_gateways,
        }


@dataclass
class PeeringResult:
    """Result of a peering operation."""
    hub_vnet: str
    spoke_vnet: str
    status: PeeringState
    action: PeeringAction
    region_pair: str
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


class VNetPeeringManager:
    """Manages Azure VNet peering operations."""
    
    def __init__(self, hub_subscription_ids: List[str], spoke_exclude_subscription_ids: List[str], 
                 credential: Any, max_workers: int = 10, config_file: Optional[str] = None):
        """Initialize the peering manager with hub subscriptions and spoke exclusions."""
        self.hub_subscription_ids = hub_subscription_ids
        self.spoke_exclude_subscription_ids = spoke_exclude_subscription_ids or []
        self.credential = credential
        self.max_workers = max_workers
        
        # Setup logging
        self._setup_logging()
        
        # Load configuration
        self.config = self._load_config(config_file) if config_file else {}
        
        # Get all subscriptions in the tenant for spoke VNets
        self.all_subscription_ids = self._get_all_tenant_subscriptions()
        
        # Determine spoke subscriptions (all except excluded)
        self.spoke_subscription_ids = [
            sub_id for sub_id in self.all_subscription_ids 
            if sub_id not in self.spoke_exclude_subscription_ids
        ]
        
        # Create clients for all subscriptions we'll need
        all_needed_subs = set(self.hub_subscription_ids + self.spoke_subscription_ids)
        self.clients = self._create_clients(all_needed_subs)
        
        # Report data structure
        self.report_data = {
            "successful_peerings": [],
            "failed_peerings": [],
            "all_peerings": [],
            "deleted_orphans": [],
            "metrics": {
                "total_vnets_scanned": 0,
                "total_peerings_checked": 0,
                "total_operations": 0,
                "start_time": datetime.utcnow(),
                "end_time": None
            }
        }
        
        self.logger.info(f"📊 Subscription Configuration:")
        self.logger.info(f"   Hub Subscriptions: {len(self.hub_subscription_ids)}")
        self.logger.info(f"   Total Tenant Subscriptions: {len(self.all_subscription_ids)}")
        self.logger.info(f"   Excluded from Spokes: {len(self.spoke_exclude_subscription_ids)}")
        self.logger.info(f"   Spoke Subscriptions: {len(self.spoke_subscription_ids)}")
    
    def _setup_logging(self):
        """Setup logging configuration."""
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        logging.basicConfig(level=logging.INFO, format=log_format)
        self.logger = logging.getLogger(__name__)
        
        # Create timestamp for log files
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Main log file handler
        file_handler = logging.FileHandler(f'vnet_peering_{timestamp}.log')
        file_handler.setFormatter(logging.Formatter(log_format))
        self.logger.addHandler(file_handler)
        
        # Create a separate logger for critical failures
        self.failure_logger = logging.getLogger(f"{__name__}.failures")
        self.failure_logger.setLevel(logging.ERROR)
        
        # Failed peerings log file handler
        self.failure_log_path = f'vnet_peering_failures_{timestamp}.log'
        failure_handler = logging.FileHandler(self.failure_log_path)
        failure_format = logging.Formatter(
            '%(asctime)s - CRITICAL FAILURE - %(message)s\n' + '-' * 80
        )
        failure_handler.setFormatter(failure_format)
        self.failure_logger.addHandler(failure_handler)
        
        # Store the handler for potential cleanup
        self.failure_handler = failure_handler
        
        # Write header to failure log
        self.failure_logger.error(
            f"Failed Peerings Log - Session Started at {datetime.utcnow().isoformat()}"
        )
    
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        try:
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
                self.logger.info(f"✅ Loaded configuration from {config_file}")
                return config
        except Exception as e:
            self.logger.warning(f"⚠️ Failed to load config file {config_file}: {e}")
            return {}
    
    def _create_clients(self, subscription_ids: Set[str]) -> Dict[str, NetworkManagementClient]:
        """Create network management clients for subscriptions with retry logic."""
        clients = {}
        max_retries = 3
        
        for sub_id in subscription_ids:
            for attempt in range(max_retries):
                try:
                    clients[sub_id] = NetworkManagementClient(self.credential, sub_id)
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        self.logger.error(f"❌ Failed to create client for subscription {sub_id} after {max_retries} attempts: {e}")
                    else:
                        time.sleep(2 ** attempt)  # Exponential backoff
        
        return clients
    
    def _get_all_tenant_subscriptions(self) -> List[str]:
        """Get all subscription IDs in the tenant."""
        try:
            subscription_client = SubscriptionClient(self.credential)
            subscriptions = []
            
            self.logger.info("🔍 Discovering all subscriptions in tenant...")
            for sub in subscription_client.subscriptions.list():
                if sub.state == "Enabled":
                    subscriptions.append(sub.subscription_id)
                    self.logger.debug(f"   Found: {sub.display_name} ({sub.subscription_id})")
            
            return subscriptions
        except Exception as e:
            self.logger.error(f"❌ Failed to list tenant subscriptions: {e}")
            self.logger.info("   Falling back to using only explicitly provided subscriptions")
            return self.hub_subscription_ids
    
    def load_regions(self, filename: str) -> List[str]:
        """Load region list from file with validation."""
        if not os.path.exists(filename):
            self.logger.warning(f"⚠️  Region file '{filename}' not found.")
            return []
        
        try:
            with open(filename, 'r') as f:
                regions = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            
            # Validate regions against known Azure regions (basic validation)
            valid_regions = []
            for region in regions:
                if region.replace(' ', '').isalnum():
                    valid_regions.append(region)
                else:
                    self.logger.warning(f"⚠️ Invalid region format: {region}")
            
            self.logger.info(f"📍 Loaded {len(valid_regions)} valid regions from {filename}")
            return valid_regions
        except Exception as e:
            self.logger.error(f"❌ Failed to load regions from {filename}: {e}")
            return []
    
    def extract_resource_group(self, resource_id: str) -> Optional[str]:
        """Extract resource group name from Azure resource ID."""
        try:
            parts = resource_id.split('/')
            if len(parts) > 4 and 'resourceGroups' in parts:
                rg_index = parts.index('resourceGroups') + 1
                return parts[rg_index]
            return None
        except (IndexError, AttributeError, ValueError):
            return None
    
    def get_vnets_by_criteria(self, regions: List[str], prefixes: List[str], 
                             tag_key: Optional[str] = None, 
                             tag_value_contains: Optional[str] = None,
                             subscription_ids: Optional[List[str]] = None) -> List[VirtualNetwork]:
        """Get VNets matching specified criteria across specified subscriptions with parallel processing."""
        vnets = []
        region_lower = [r.lower() for r in regions]
        
        # Use provided subscription list or default to all clients
        target_subscriptions = subscription_ids if subscription_ids else list(self.clients.keys())
        
        def scan_subscription(sub_id: str) -> List[VirtualNetwork]:
            """Scan a single subscription for matching VNets."""
            sub_vnets = []
            if sub_id not in self.clients:
                self.logger.warning(f"⚠️  Skipping subscription {sub_id} - no client available")
                return sub_vnets
            
            client = self.clients[sub_id]
            try:
                self.logger.debug(f"🔍 Scanning subscription: {sub_id}")
                for vnet in client.virtual_networks.list_all():
                    self.report_data["metrics"]["total_vnets_scanned"] += 1
                    
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
                    
                    sub_vnets.append(vnet)
                    
            except Exception as e:
                self.logger.error(f"⚠️  Failed to scan subscription {sub_id}: {e}")
            
            return sub_vnets
        
        # Use thread pool for parallel scanning
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(target_subscriptions))) as executor:
            future_to_sub = {executor.submit(scan_subscription, sub_id): sub_id 
                           for sub_id in target_subscriptions}
            
            for future in as_completed(future_to_sub):
                try:
                    vnets.extend(future.result())
                except Exception as e:
                    sub_id = future_to_sub[future]
                    self.logger.error(f"❌ Failed to process subscription {sub_id}: {e}")
        
        self.logger.info(f"✅ Found {len(vnets)} VNets matching criteria in {len(target_subscriptions)} subscriptions")
        return vnets
    
    def generate_peering_name(self, vnet_a_name: str, vnet_b_name: str, max_length: int = 79) -> str:
        """Generate peering name with length constraints and validation."""
        base_name = f"cngfw_dnd-{vnet_a_name}-to-{vnet_b_name}"
        
        if len(base_name) <= max_length:
            return base_name
        
        # Truncate proportionally if too long
        prefix_length = len("cngfw_dnd--to-")
        max_each = (max_length - prefix_length) // 2
        
        # Use a hash suffix to ensure uniqueness
        import hashlib
        hash_suffix = hashlib.md5(base_name.encode()).hexdigest()[:4]
        
        short_a = vnet_a_name[:max_each - 2]  # Leave room for hash
        short_b = vnet_b_name[:max_each - 2]
        truncated_name = f"cngfw_dnd-{short_a}-to-{short_b}-{hash_suffix}"
        
        self.logger.debug(f"⚠️  Peering name truncated: {base_name} -> {truncated_name}")
        return truncated_name
    
    def is_healthy_peering(self, peering: VirtualNetworkPeering) -> bool:
        """Check if peering is in healthy state with comprehensive checks."""
        if not peering:
            return False
        
        basic_health = (
            peering.peering_state == "Connected" and
            peering.allow_virtual_network_access and
            peering.allow_forwarded_traffic
        )
        
        # Additional health checks
        if hasattr(peering, 'peering_sync_level'):
            sync_healthy = peering.peering_sync_level == "FullyInSync"
        else:
            sync_healthy = True
        
        return basic_health and sync_healthy
    
    def get_existing_peering(self, vnet: VirtualNetwork, peer_name: str) -> Optional[VirtualNetworkPeering]:
        """Get existing peering by name with caching."""
        try:
            rg = self.extract_resource_group(vnet.id)
            sub_id = vnet.id.split("/")[2]
            client = self.clients[sub_id]
            
            peering = client.virtual_network_peerings.get(rg, vnet.name, peer_name)
            self.report_data["metrics"]["total_peerings_checked"] += 1
            return peering
            
        except ResourceNotFoundError:
            return None
        except Exception as e:
            self.logger.warning(f"⚠️  Error checking peering '{peer_name}' in VNet '{vnet.name}': {e}")
            return None
    
    def create_peering(self, source_vnet: VirtualNetwork, target_vnet: VirtualNetwork, 
                      peering_name: str, config: Optional[PeeringConfig] = None) -> bool:
        """Create a single peering connection with retry logic."""
        max_retries = 3
        retry_delay = 5
        
        if config is None:
            config = PeeringConfig()
        
        for attempt in range(max_retries):
            try:
                rg = self.extract_resource_group(source_vnet.id)
                sub_id = source_vnet.id.split("/")[2]
                client = self.clients[sub_id]
                
                peering_params = {
                    "remote_virtual_network": {"id": target_vnet.id},
                    **config.to_dict()
                }
                
                operation = client.virtual_network_peerings.begin_create_or_update(
                    rg, source_vnet.name, peering_name, peering_params
                )
                
                # Wait for operation with timeout
                operation.result(timeout=300)  # 5 minutes timeout
                
                self.report_data["metrics"]["total_operations"] += 1
                self.logger.info(f"{Fore.GREEN}✅ Created peering '{peering_name}'{Style.RESET_ALL}")
                return True
                
            except Exception as e:
                if attempt < max_retries - 1:
                    self.logger.warning(f"⚠️  Attempt {attempt + 1} failed for peering '{peering_name}': {e}")
                    time.sleep(retry_delay * (attempt + 1))
                else:
                    self.logger.error(f"{Fore.RED}❌ Failed to create peering '{peering_name}' after {max_retries} attempts: {e}{Style.RESET_ALL}")
                    
                    # Log to critical failures file with detailed context
                    self.failure_logger.error(
                        f"Peering Creation Failed After {max_retries} Attempts\n"
                        f"Peering Name: {peering_name}\n"
                        f"Source VNet: {source_vnet.name} (ID: {source_vnet.id})\n"
                        f"Target VNet: {target_vnet.name} (ID: {target_vnet.id})\n"
                        f"Resource Group: {rg}\n"
                        f"Subscription: {sub_id}\n"
                        f"Configuration: {config.to_dict()}\n"
                        f"Final Error: {type(e).__name__}: {str(e)}\n"
                        f"Timestamp: {datetime.utcnow().isoformat()}"
                    )
                    
                    # Also add to report data for tracking
                    if "critical_failures" not in self.report_data:
                        self.report_data["critical_failures"] = []
                    
                    self.report_data["critical_failures"].append({
                        "peering_name": peering_name,
                        "source_vnet": source_vnet.name,
                        "target_vnet": target_vnet.name,
                        "error": str(e),
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    
                    return False
        
        return False
    
    def delete_peering(self, vnet: VirtualNetwork, peering_name: str) -> bool:
        """Delete a peering connection with confirmation."""
        try:
            rg = self.extract_resource_group(vnet.id)
            sub_id = vnet.id.split("/")[2]
            client = self.clients[sub_id]
            
            operation = client.virtual_network_peerings.begin_delete(rg, vnet.name, peering_name)
            operation.result(timeout=300)
            
            self.report_data["metrics"]["total_operations"] += 1
            self.logger.info(f"{Fore.YELLOW}🗑️  Deleted peering '{peering_name}'{Style.RESET_ALL}")
            return True
            
        except Exception as e:
            self.logger.error(f"{Fore.RED}❌ Failed to delete peering '{peering_name}': {e}{Style.RESET_ALL}")
            return False
    
    def create_or_repair_peering_pair(self, hub_vnet: VirtualNetwork, spoke_vnet: VirtualNetwork, 
                                     region_pair: str, config: Optional[PeeringConfig] = None) -> PeeringResult:
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
            self.logger.info(f"✅ Peerings between {hub_vnet.name} and {spoke_vnet.name} are healthy")
            result = PeeringResult(
                hub_vnet=hub_vnet.name,
                spoke_vnet=spoke_vnet.name,
                status=PeeringState.CONNECTED,
                action=PeeringAction.NO_CHANGE,
                region_pair=region_pair
            )
            self.report_data["all_peerings"].append(result)
            return result
        
        self.logger.info(f"🔧 {'Repairing' if (existing_hub_to_spoke or existing_spoke_to_hub) else 'Creating'} "
                        f"peerings between {hub_vnet.name} and {spoke_vnet.name}")
        
        # Delete BOTH peerings if EITHER is unhealthy to ensure clean state
        if (existing_hub_to_spoke or existing_spoke_to_hub) and (not hub_healthy or not spoke_healthy):
            self.logger.info(f"🧹 One or both peerings are unhealthy - deleting both sides for clean recreation")
            
            if existing_hub_to_spoke:
                self.logger.info(f"   Deleting hub->spoke peering (was {'healthy' if hub_healthy else 'unhealthy'})")
                self.delete_peering(hub_vnet, hub_to_spoke_name)
            
            if existing_spoke_to_hub:
                self.logger.info(f"   Deleting spoke->hub peering (was {'healthy' if spoke_healthy else 'unhealthy'})")
                self.delete_peering(spoke_vnet, spoke_to_hub_name)
        
        # Create new peerings
        hub_success = self.create_peering(hub_vnet, spoke_vnet, hub_to_spoke_name, config)
        spoke_success = self.create_peering(spoke_vnet, hub_vnet, spoke_to_hub_name, config)
        
        # Record results
        if hub_success and spoke_success:
            action = PeeringAction.REPAIRED if (existing_hub_to_spoke or existing_spoke_to_hub) else PeeringAction.CREATED
            self.logger.info(f"{Fore.GREEN}✅ Successfully {action.value.lower()} peerings between {hub_vnet.name} and {spoke_vnet.name}{Style.RESET_ALL}")
            
            self.report_data["successful_peerings"].append((
                hub_vnet.name, "Hub", hub_to_spoke_name, 
                spoke_vnet.name, "Spoke", action.value
            ))
            
            result = PeeringResult(
                hub_vnet=hub_vnet.name,
                spoke_vnet=spoke_vnet.name,
                status=PeeringState.CONNECTED,
                action=action,
                region_pair=region_pair
            )
        else:
            error_msg = f"Hub->Spoke: {'Failed' if not hub_success else 'OK'}, " \
                       f"Spoke->Hub: {'Failed' if not spoke_success else 'OK'}"
            
            self.report_data["failed_peerings"].append({
                "hub_vnet": hub_vnet.name,
                "spoke_vnet": spoke_vnet.name,
                "error": error_msg
            })
            
            result = PeeringResult(
                hub_vnet=hub_vnet.name,
                spoke_vnet=spoke_vnet.name,
                status=PeeringState.FAILED,
                action=PeeringAction.FAILED,
                region_pair=region_pair,
                error=error_msg
            )
        
        self.report_data["all_peerings"].append(result)
        return result
    
    def cleanup_failure_log(self):
        """Remove failure log file if no failures occurred."""
        try:
            # Check if there were any critical failures
            has_failures = (
                self.report_data.get("critical_failures") or 
                any("Deletion Failed" in str(record.msg) for record in self.failure_logger.handlers[0].buffer if hasattr(self.failure_logger.handlers[0], 'buffer'))
            )
            
            if not has_failures:
                # Close the handler and remove the file
                self.failure_handler.close()
                self.failure_logger.removeHandler(self.failure_handler)
                
                if os.path.exists(self.failure_log_path):
                    os.remove(self.failure_log_path)
                    self.logger.info(f"🧹 Removed empty failure log file: {self.failure_log_path}")
            else:
                self.logger.warning(f"⚠️  Critical failures logged to: {self.failure_log_path}")
        except Exception as e:
            self.logger.debug(f"Could not cleanup failure log: {e}")
        """Clean up orphaned peerings that point to non-existent VNets with parallel processing."""
        self.logger.info(f"\n🧹 Cleaning up orphaned peerings {'(DRY RUN)' if dry_run else ''}")
        
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
                self.logger.error(f"⚠️  Failed to list VNets in subscription {sub_id}: {e}")
        
        self.logger.info(f"📊 Found {len(valid_vnet_ids)} valid VNets in {len(valid_regions)} regions")
        
        # Find and delete orphaned peerings
        def process_subscription_orphans(sub_id: str, client: NetworkManagementClient):
            """Process orphans in a single subscription."""
            try:
                for vnet in client.virtual_networks.list_all():
                    if vnet.location.lower() not in valid_region_lower:
                        continue
                    
                    rg = self.extract_resource_group(vnet.id)
                    try:
                        peerings = list(client.virtual_network_peerings.list(rg, vnet.name))
                    except Exception as e:
                        self.logger.warning(f"⚠️  Failed to list peerings for {vnet.name}: {e}")
                        continue
                    
                    for peering in peerings:
                        if not peering.name.startswith("cngfw_dnd"):
                            continue
                        
                        remote_id = peering.remote_virtual_network.id.lower()
                        if remote_id not in valid_vnet_ids:
                            self.logger.info(f"🗑️  {'Would delete' if dry_run else 'Deleting'} orphaned peering: "
                                           f"{vnet.name} -> {peering.name}")
                            
                            if not dry_run:
                                if self.delete_peering(vnet, peering.name):
                                    self.report_data["deleted_orphans"].append({
                                        "vnet": vnet.name,
                                        "peering_name": peering.name,
                                        "remote_id": remote_id
                                    })
                            
            except Exception as e:
                self.logger.error(f"⚠️  Failed to process subscription {sub_id}: {e}")
        
        # Process subscriptions in parallel
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(self.clients))) as executor:
            futures = [executor.submit(process_subscription_orphans, sub_id, client) 
                      for sub_id, client in self.clients.items()]
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    self.logger.error(f"❌ Failed to process orphans: {e}")
    
    def process_region_pair(self, hub_regions_file: str, spoke_regions_file: str, 
                           config: Optional[PeeringConfig] = None) -> None:
        """Process peering for a specific hub-spoke region pair with parallel processing."""
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"🌍 Processing region pair: {hub_regions_file} <-> {spoke_regions_file}")
        self.logger.info(f"{'='*60}")
        
        hub_regions = self.load_regions(hub_regions_file)
        spoke_regions = self.load_regions(spoke_regions_file)
        
        if not hub_regions or not spoke_regions:
            self.logger.warning("⚠️  Skipping region pair due to missing regions")
            return
        
        # Get hub VNets (cngfw-az with hub tag) - ONLY from hub subscriptions
        self.logger.info(f"\n🔍 Searching for hub VNets in {len(self.hub_subscription_ids)} hub subscriptions...")
        hub_vnets = self.get_vnets_by_criteria(
            regions=hub_regions,
            prefixes=self.config.get('hub_prefixes', ["cngfw-az"]),
            tag_key=self.config.get('hub_tag_key', "appname"),
            tag_value_contains=self.config.get('hub_tag_value', "hub"),
            subscription_ids=self.hub_subscription_ids
        )
        
        # Get spoke VNets (opencti, MISP) - from all subscriptions except excluded
        self.logger.info(f"\n🔍 Searching for spoke VNets in {len(self.spoke_subscription_ids)} spoke subscriptions...")
        spoke_vnets = self.get_vnets_by_criteria(
            regions=spoke_regions,
            prefixes=self.config.get('spoke_prefixes', ["opencti", "MISP"]),
            subscription_ids=self.spoke_subscription_ids
        )
        
        if not hub_vnets:
            self.logger.warning(f"⚠️  No hub VNets found for regions in {hub_regions_file}")
            return
        if not spoke_vnets:
            self.logger.warning(f"⚠️  No spoke VNets found for regions in {spoke_regions_file}")
            return
        
        region_label = f"{os.path.basename(hub_regions_file)} <-> {os.path.basename(spoke_regions_file)}"
        
        # Create peerings between all hub-spoke pairs
        total_pairs = len(hub_vnets) * len(spoke_vnets)
        self.logger.info(f"🔗 Processing {total_pairs} hub-spoke peering pairs")
        
        # Process peerings in parallel
        with ThreadPoolExecutor(max_workers=min(self.max_workers, total_pairs)) as executor:
            futures = []
            
            for i, hub_vnet in enumerate(hub_vnets, 1):
                for j, spoke_vnet in enumerate(spoke_vnets, 1):
                    pair_num = (i-1) * len(spoke_vnets) + j
                    self.logger.info(f"\n[{pair_num}/{total_pairs}] Submitting: {hub_vnet.name} <-> {spoke_vnet.name}")
                    
                    future = executor.submit(
                        self.create_or_repair_peering_pair,
                        hub_vnet, spoke_vnet, region_label, config
                    )
                    futures.append(future)
            
            # Wait for all futures to complete
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result.status == PeeringState.FAILED:
                        self.logger.error(f"❌ Failed peering: {result.hub_vnet} <-> {result.spoke_vnet}")
                except Exception as e:
                    self.logger.error(f"❌ Peering operation failed: {e}")
    
    def generate_html_report(self, filename: str = "vnet_peering_report.html") -> None:
        """Generate comprehensive HTML report with enhanced styling and metrics."""
        def html_table(rows: List, headers: List[str]) -> str:
            if not rows:
                return "<p class='no-data'>No data available.</p>"
            
            table = """<table class='data-table'>
                      <thead><tr>"""
            table += "".join(f"<th>{h}</th>" for h in headers)
            table += "</tr></thead><tbody>"
            
            for i, row in enumerate(rows):
                row_class = "even" if i % 2 == 0 else "odd"
                table += f"<tr class='{row_class}'>"
                table += "".join(f"<td>{c}</td>" for c in row)
                table += "</tr>"
            
            table += "</tbody></table>"
            return table
        
        # Calculate metrics
        self.report_data["metrics"]["end_time"] = datetime.utcnow()
        duration = self.report_data["metrics"]["end_time"] - self.report_data["metrics"]["start_time"]
        
        # Generate HTML report
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Azure VNet Peering Report</title>
            <style>
                body {{ 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    margin: 0;
                    padding: 0;
                    background-color: #f5f5f5;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                h1, h2, h3 {{ 
                    color: #0078d4;
                    margin-top: 30px;
                }}
                h1 {{
                    border-bottom: 3px solid #0078d4;
                    padding-bottom: 10px;
                }}
                .summary {{ 
                    background: linear-gradient(135deg, #e8f4f8 0%, #d4e9f7 100%);
                    padding: 20px;
                    border-radius: 10px;
                    margin: 20px 0;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }}
                .metrics {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 15px;
                    margin: 20px 0;
                }}
                .metric-card {{
                    background: white;
                    padding: 15px;
                    border-radius: 8px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                    text-align: center;
                }}
                .metric-value {{
                    font-size: 2em;
                    font-weight: bold;
                    color: #0078d4;
                }}
                .metric-label {{
                    color: #666;
                    margin-top: 5px;
                }}
                .data-table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                    background: white;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                }}
                .data-table th {{
                    background-color: #0078d4;
                    color: white;
                    padding: 12px;
                    text-align: left;
                    font-weight: 600;
                }}
                .data-table td {{
                    padding: 12px;
                    border-bottom: 1px solid #ddd;
                }}
                .data-table tr.even {{
                    background-color: #f9f9f9;
                }}
                .data-table tr:hover {{
                    background-color: #e8f4f8;
                }}
                .status-badge {{
                    display: inline-block;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-size: 0.85em;
                    font-weight: 600;
                }}
                .status-success {{
                    background-color: #107c10;
                    color: white;
                }}
                .status-failed {{
                    background-color: #d13438;
                    color: white;
                }}
                .status-warning {{
                    background-color: #ff8c00;
                    color: white;
                }}
                .no-data {{
                    text-align: center;
                    color: #666;
                    padding: 20px;
                    font-style: italic;
                }}
                .footer {{
                    margin-top: 50px;
                    padding: 20px;
                    text-align: center;
                    color: #666;
                    border-top: 1px solid #ddd;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🔗 Azure VNet Peering Report</h1>
                
                <div class="summary">
                    <h2>Executive Summary</h2>
                    <strong>Report Generated:</strong> {timestamp}<br>
                    <strong>Duration:</strong> {duration}<br>
                    <strong>Environment:</strong> {len(self.all_subscription_ids)} subscriptions across tenant
                </div>
                
                <div class="metrics">
                    <div class="metric-card">
                        <div class="metric-value">{len(self.hub_subscription_ids)}</div>
                        <div class="metric-label">Hub Subscriptions</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">{len(self.spoke_subscription_ids)}</div>
                        <div class="metric-label">Spoke Subscriptions</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">{self.report_data['metrics']['total_vnets_scanned']}</div>
                        <div class="metric-label">VNets Scanned</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">{self.report_data['metrics']['total_peerings_checked']}</div>
                        <div class="metric-label">Peerings Checked</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">{len(self.report_data['successful_peerings'])}</div>
                        <div class="metric-label">Successful Operations</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">{len(self.report_data['failed_peerings'])}</div>
                        <div class="metric-label">Failed Operations</div>
                    </div>
                </div>
        """
        
        # Successful peerings
        html += "<h2>✅ Successful Peering Operations</h2>"
        if self.report_data["successful_peerings"]:
            html += html_table(
                self.report_data["successful_peerings"],
                ["Hub VNet", "Role", "Peering Name", "Spoke VNet", "Role", "Action"]
            )
        else:
            html += "<p class='no-data'>No successful peering operations.</p>"
        
        # Failed peerings
        html += "<h2>❌ Failed Peering Operations</h2>"
        if self.report_data["failed_peerings"]:
            failed_rows = [
                (entry["hub_vnet"], entry["spoke_vnet"], 
                 f"<span class='status-badge status-failed'>{entry['error']}</span>")
                for entry in self.report_data["failed_peerings"]
            ]
            html += html_table(failed_rows, ["Hub VNet", "Spoke VNet", "Error"])
        else:
            html += "<p class='no-data'>No peering failures encountered.</p>"
        
        # All peerings grouped by region
        html += "<h2>📊 All Peerings by Region Pair</h2>"
        if self.report_data["all_peerings"]:
            grouped = defaultdict(list)
            for peering in self.report_data["all_peerings"]:
                region = peering.region_pair
                status_class = "status-success" if peering.status == PeeringState.CONNECTED else "status-failed"
                status_badge = f"<span class='status-badge {status_class}'>{peering.status.value}</span>"
                
                grouped[region].append((
                    peering.hub_vnet,
                    peering.spoke_vnet,
                    status_badge,
                    peering.action.value,
                    peering.error or "-"
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
                (entry["vnet"], entry["peering_name"], 
                 f"<code style='font-size: 0.85em;'>{entry['remote_id']}</code>")
                for entry in self.report_data["deleted_orphans"]
            ]
            html += html_table(orphan_rows, ["VNet", "Peering Name", "Remote VNet ID"])
        else:
            html += "<p class='no-data'>No orphan peerings were deleted.</p>"
        
        # Critical failures section
        if self.report_data.get("critical_failures"):
            html += """<h2>🚨 Critical Failures (Max Retries Exceeded)</h2>
                      <div class='summary' style='background: #ffe6e6; border-left: 5px solid #d13438;'>
                      <strong>⚠️ These peerings failed after maximum retry attempts and require manual investigation.</strong><br>
                      Check the detailed failure log: vnet_peering_failures_*.log
                      </div>"""
            
            critical_rows = [
                (
                    entry["peering_name"],
                    entry["source_vnet"],
                    entry["target_vnet"],
                    f"<span class='status-badge status-failed'>{entry['error'][:100]}...</span>",
                    entry["timestamp"]
                )
                for entry in self.report_data["critical_failures"]
            ]
            html += html_table(
                critical_rows,
                ["Peering Name", "Source VNet", "Target VNet", "Error", "Timestamp"]
            )
        
        # Performance metrics
        html += f"""
                <h2>📈 Performance Metrics</h2>
                <div class="summary">
                    <strong>Total Operations:</strong> {self.report_data['metrics']['total_operations']}<br>
                    <strong>Success Rate:</strong> {len(self.report_data['successful_peerings']) / max(1, len(self.report_data['successful_peerings']) + len(self.report_data['failed_peerings'])) * 100:.1f}%<br>
                    <strong>Average Operation Time:</strong> {duration.total_seconds() / max(1, self.report_data['metrics']['total_operations']):.2f} seconds
                </div>
                
                <div class="footer">
                    <p>Generated by Azure VNet Peering Manager | {timestamp}</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        with open(filename, "w", encoding='utf-8') as f:
            f.write(html)
        
        self.logger.info(f"\n📄 HTML report generated: {filename}")
    
    def export_json_report(self, filename: str = "vnet_peering_report.json") -> None:
        """Export report data as JSON for programmatic access."""
        json_data = {
            "metadata": {
                "generated_at": datetime.utcnow().isoformat(),
                "duration_seconds": (self.report_data["metrics"]["end_time"] - 
                                   self.report_data["metrics"]["start_time"]).total_seconds(),
                "hub_subscriptions": self.hub_subscription_ids,
                "spoke_subscriptions": self.spoke_subscription_ids,
                "excluded_subscriptions": self.spoke_exclude_subscription_ids
            },
            "metrics": self.report_data["metrics"],
            "results": {
                "successful_peerings": self.report_data["successful_peerings"],
                "failed_peerings": self.report_data["failed_peerings"],
                "all_peerings": [
                    {
                        "hub_vnet": p.hub_vnet,
                        "spoke_vnet": p.spoke_vnet,
                        "status": p.status.value,
                        "action": p.action.value,
                        "region_pair": p.region_pair,
                        "error": p.error,
                        "timestamp": p.timestamp.isoformat()
                    }
                    for p in self.report_data["all_peerings"]
                ],
                "deleted_orphans": self.report_data["deleted_orphans"]
            }
        }
        
        with open(filename, "w", encoding='utf-8') as f:
            json.dump(json_data, f, indent=2)
        
        self.logger.info(f"📄 JSON report exported: {filename}")


def get_credential(auth_method: str, **kwargs) -> Any:
    """Get Azure credential based on authentication method."""
    if auth_method == "service_principal":
        return ClientSecretCredential(
            tenant_id=kwargs['tenant_id'],
            client_id=kwargs['client_id'],
            client_secret=kwargs['client_secret']
        )
    elif auth_method == "managed_identity":
        return ManagedIdentityCredential(
            client_id=kwargs.get('client_id')  # Optional for user-assigned
        )
    elif auth_method == "default":
        return DefaultAzureCredential()
    else:
        raise ValueError(f"Unknown authentication method: {auth_method}")


def main():
    """Main function to orchestrate the peering process."""
    parser = argparse.ArgumentParser(
        description="Enhanced Azure VNet Hub-Spoke Peering Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Service Principal authentication
  python script.py --hub-subscription-ids sub1,sub2 --auth-method service_principal \\
    --tenant-id xxx --client-id yyy --client-secret zzz
  
  # Managed Identity authentication
  python script.py --hub-subscription-ids sub1 --auth-method managed_identity
  
  # With configuration file
  python script.py --hub-subscription-ids sub1 --config config.yaml \\
    --auth-method default
  
  # Exclude specific subscriptions and set worker threads
  python script.py --hub-subscription-ids sub1 --spoke-exclude-subscription-ids sub3,sub4 \\
    --max-workers 20 --auth-method default
        """
    )
    
    # Required arguments
    parser.add_argument(
        "--hub-subscription-ids",
        required=True,
        help="Comma-separated list of subscription IDs containing hub VNets"
    )
    
    # Authentication arguments
    parser.add_argument(
        "--auth-method",
        choices=["service_principal", "managed_identity", "default"],
        default="default",
        help="Authentication method to use (default: default)"
    )
    parser.add_argument(
        "--tenant-id",
        help="Azure AD tenant ID (required for service_principal auth)"
    )
    parser.add_argument(
        "--client-id",
        help="Service principal or managed identity client ID"
    )
    parser.add_argument(
        "--client-secret",
        help="Service principal client secret (required for service_principal auth)"
    )
    
    # Optional arguments
    parser.add_argument(
        "--spoke-exclude-subscription-ids",
        default="",
        help="Comma-separated list of subscription IDs to exclude from spoke VNet search"
    )
    parser.add_argument(
        "--config",
        help="Path to YAML configuration file"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=10,
        help="Maximum number of concurrent workers (default: 10)"
    )
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
    parser.add_argument(
        "--export-json",
        action="store_true",
        help="Export report in JSON format"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level (default: INFO)"
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Set logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # Validate authentication arguments
    if args.auth_method == "service_principal":
        if not all([args.tenant_id, args.client_id, args.client_secret]):
            parser.error("Service principal authentication requires --tenant-id, --client-id, and --client-secret")
    
    # Parse subscription IDs
    hub_subscriptions = [sub.strip() for sub in args.hub_subscription_ids.split(",") if sub.strip()]
    if not hub_subscriptions:
        print(f"{Fore.RED}❌ No valid hub subscription IDs provided{Style.RESET_ALL}")
        sys.exit(1)
    
    # Parse excluded subscription IDs
    spoke_exclude_subscriptions = []
    if args.spoke_exclude_subscription_ids:
        spoke_exclude_subscriptions = [
            sub.strip() for sub in args.spoke_exclude_subscription_ids.split(",") if sub.strip()
        ]
    
    print(f"{Fore.CYAN}🎯 Configuration:{Style.RESET_ALL}")
    print(f"   Hub Subscriptions: {len(hub_subscriptions)}")
    print(f"   Excluded from Spokes: {len(spoke_exclude_subscriptions)}")
    print(f"   Max Workers: {args.max_workers}")
    print(f"   Authentication Method: {args.auth_method}")
    
    # Get credential
    try:
        credential = get_credential(
            args.auth_method,
            tenant_id=args.tenant_id,
            client_id=args.client_id,
            client_secret=args.client_secret
        )
        print(f"{Fore.GREEN}✅ Successfully authenticated with Azure{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}❌ Authentication failed: {e}{Style.RESET_ALL}")
        sys.exit(1)
    
    # Initialize peering manager
    try:
        manager = VNetPeeringManager(
            hub_subscription_ids=hub_subscriptions,
            spoke_exclude_subscription_ids=spoke_exclude_subscriptions,
            credential=credential,
            max_workers=args.max_workers,
            config_file=args.config
        )
    except Exception as e:
        print(f"{Fore.RED}❌ Failed to initialize peering manager: {e}{Style.RESET_ALL}")
        sys.exit(1)
    
    # Load peering configuration if provided
    peering_config = None
    if args.config and 'peering_config' in manager.config:
        peering_config = PeeringConfig(**manager.config['peering_config'])
    
    # Define region pairs (can be overridden by config)
    region_pairs = manager.config.get('region_pairs', [
        ("hub/hubUS", "spoke/spokeUS"),
        ("hub/hubEU", "spoke/spokeEU"),
        ("hub/hubAPAC", "spoke/spokeAPAC")
    ])
    
    # Process each region pair
    for hub_file, spoke_file in region_pairs:
        try:
            manager.process_region_pair(hub_file, spoke_file, peering_config)
        except Exception as e:
            print(f"{Fore.RED}❌ Failed to process region pair {hub_file} <-> {spoke_file}: {e}{Style.RESET_ALL}")
            continue
    
    # Cleanup orphaned peerings if not skipped
    if not args.skip_cleanup:
        valid_regions = set()
        for hub_file, spoke_file in region_pairs:
            valid_regions.update(manager.load_regions(hub_file))
            valid_regions.update(manager.load_regions(spoke_file))
        
        manager.cleanup_orphan_peerings(valid_regions, dry_run=args.dry_run)
    
    # Set end time for metrics
    manager.report_data["metrics"]["end_time"] = datetime.utcnow()
    
    # Generate reports
    report_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    html_filename = f"vnet_peering_report_{report_timestamp}.html"
    manager.generate_html_report(html_filename)
    
    if args.export_json:
        json_filename = f"vnet_peering_report_{report_timestamp}.json"
        manager.export_json_report(json_filename)
    
    # Cleanup failure log if no failures occurred
    manager.cleanup_failure_log()
    
    print(f"\n{Fore.GREEN}🎉 Peering management completed!{Style.RESET_ALL}")
    print(f"📊 Summary:")
    print(f"   - Successful operations: {len(manager.report_data['successful_peerings'])}")
    print(f"   - Failed operations: {len(manager.report_data['failed_peerings'])}")
    print(f"   - Orphans cleaned: {len(manager.report_data['deleted_orphans'])}")
    print(f"   - Report: {html_filename}")


if __name__ == "__main__":
    main()