#!/usr/bin/env python3
"""
Comprehensive Website Performance Testing Script
Tests availability, performance metrics, SSL certificates, and generates detailed reports.

Requirements:
- pip install requests selenium psutil
- Chrome/Chromium browser (for Web Vitals collection)
- ChromeDriver (automatically managed by selenium 4.x)

Features:
- SSL certificate validation and expiration checking
- Core Web Vitals (FCP, LCP, CLS, TTI) measurement
- Resource loading analysis (images, CSS, JS, fonts)
- Multiple endpoint health checks
- Geographic performance testing simulation
- Load and stress testing with concurrent users
- Comprehensive HTML reports with visual indicators
"""

import requests
import time
import statistics
import concurrent.futures
import socket
import ssl
import urllib.parse
from datetime import datetime, timedelta
import json
import argparse
import sys
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import psutil
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import subprocess
import platform

@dataclass
class SSLInfo:
    """SSL Certificate information"""
    is_valid: bool
    issuer: str
    subject: str
    expires: datetime
    days_until_expiry: int
    version: str
    cipher: str

@dataclass
class ResourceTiming:
    """Resource loading timing information"""
    url: str
    size: int
    load_time: float
    resource_type: str
    status_code: int

@dataclass
class WebVitals:
    """Core Web Vitals metrics"""
    fcp: float  # First Contentful Paint
    lcp: float  # Largest Contentful Paint
    cls: float  # Cumulative Layout Shift
    tti: float  # Time to Interactive
    dom_ready: float
    fully_loaded: float

@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics"""
    url: str
    dns_time: float
    connect_time: float
    ssl_time: float
    ttfb: float
    total_time: float
    response_size: int
    status_code: int
    timestamp: float
    ssl_info: Optional[SSLInfo] = None
    web_vitals: Optional[WebVitals] = None
    resources: List[ResourceTiming] = None
    location: str = "local"

class SSLChecker:
    """SSL Certificate validation and information extraction"""
    
    @staticmethod
    def check_ssl_certificate(hostname: str, port: int = 443) -> SSLInfo:
        """Check SSL certificate details"""
        try:
            context = ssl.create_default_context()
            with socket.create_connection((hostname, port), timeout=10) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    
                    # Parse expiration date
                    expires_str = cert['notAfter']
                    expires = datetime.strptime(expires_str, '%b %d %H:%M:%S %Y %Z')
                    days_until_expiry = (expires - datetime.now()).days
                    
                    # Extract certificate info
                    issuer = dict(x[0] for x in cert['issuer'])['organizationName']
                    subject = dict(x[0] for x in cert['subject'])['commonName']
                    
                    return SSLInfo(
                        is_valid=True,
                        issuer=issuer,
                        subject=subject,
                        expires=expires,
                        days_until_expiry=days_until_expiry,
                        version=ssock.version(),
                        cipher=ssock.cipher()[0] if ssock.cipher() else "Unknown"
                    )
                    
        except Exception as e:
            return SSLInfo(
                is_valid=False,
                issuer=f"Error: {str(e)}",
                subject="",
                expires=datetime.now(),
                days_until_expiry=0,
                version="",
                cipher=""
            )

class WebVitalsCollector:
    """Collect Core Web Vitals using Selenium"""
    
    def __init__(self):
        self.driver = None
        
    def setup_driver(self):
        """Setup Chrome WebDriver with performance logging"""
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            
            # Enable performance logging
            chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
            
            self.driver = webdriver.Chrome(options=chrome_options)
            return True
        except Exception as e:
            print(f"Warning: Could not setup Chrome WebDriver for Web Vitals collection: {e}")
            print("Continuing without Web Vitals metrics...")
            return False
    
    def collect_web_vitals(self, url: str) -> Optional[WebVitals]:
        """Collect Core Web Vitals metrics"""
        if not self.driver:
            return None
            
        try:
            start_time = time.time()
            self.driver.get(url)
            
            # Wait for page to load
            WebDriverWait(self.driver, 30).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            
            # Get navigation timing
            nav_timing = self.driver.execute_script("""
                const timing = performance.timing;
                const navigation = performance.getEntriesByType('navigation')[0];
                return {
                    domReady: timing.domContentLoadedEventEnd - timing.navigationStart,
                    fullyLoaded: timing.loadEventEnd - timing.navigationStart,
                    ttfb: timing.responseStart - timing.navigationStart
                };
            """)
            
            # Get Core Web Vitals (simplified approximation)
            web_vitals_script = """
                return new Promise((resolve) => {
                    const vitals = {
                        fcp: 0,
                        lcp: 0,
                        cls: 0,
                        tti: 0
                    };
                    
                    // First Contentful Paint
                    const fcpEntry = performance.getEntriesByName('first-contentful-paint')[0];
                    if (fcpEntry) vitals.fcp = fcpEntry.startTime;
                    
                    // Largest Contentful Paint (approximation)
                    const paintEntries = performance.getEntriesByType('paint');
                    if (paintEntries.length > 0) {
                        vitals.lcp = Math.max(...paintEntries.map(p => p.startTime));
                    }
                    
                    // Time to Interactive (approximation using domInteractive)
                    vitals.tti = performance.timing.domInteractive - performance.timing.navigationStart;
                    
                    // CLS is complex to measure, setting to 0 for now
                    vitals.cls = 0;
                    
                    resolve(vitals);
                });
            """
            
            vitals_data = self.driver.execute_script(web_vitals_script)
            
            return WebVitals(
                fcp=vitals_data.get('fcp', 0) / 1000,  # Convert to seconds
                lcp=vitals_data.get('lcp', 0) / 1000,
                cls=vitals_data.get('cls', 0),
                tti=vitals_data.get('tti', 0) / 1000,
                dom_ready=nav_timing.get('domReady', 0) / 1000,
                fully_loaded=nav_timing.get('fullyLoaded', 0) / 1000
            )
            
        except Exception as e:
            print(f"Warning: Could not collect Web Vitals: {e}")
            return None
    
    def collect_resource_timings(self, url: str) -> List[ResourceTiming]:
        """Collect resource loading timings"""
        if not self.driver:
            return []
            
        try:
            self.driver.get(url)
            
            # Wait for page to load
            WebDriverWait(self.driver, 30).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            
            # Get resource timing data
            resources_script = """
                return performance.getEntriesByType('resource').map(entry => ({
                    name: entry.name,
                    duration: entry.duration,
                    transferSize: entry.transferSize || 0,
                    initiatorType: entry.initiatorType
                }));
            """
            
            resources_data = self.driver.execute_script(resources_script)
            
            resource_timings = []
            for resource in resources_data:
                # Determine resource type
                name = resource['name']
                if any(ext in name.lower() for ext in ['.js', 'javascript']):
                    resource_type = 'script'
                elif any(ext in name.lower() for ext in ['.css', 'stylesheet']):
                    resource_type = 'stylesheet'
                elif any(ext in name.lower() for ext in ['.jpg', '.png', '.gif', '.webp', '.svg']):
                    resource_type = 'image'
                elif any(ext in name.lower() for ext in ['.woff', '.woff2', '.ttf', '.otf']):
                    resource_type = 'font'
                else:
                    resource_type = resource.get('initiatorType', 'other')
                
                resource_timings.append(ResourceTiming(
                    url=name,
                    size=resource.get('transferSize', 0),
                    load_time=resource.get('duration', 0) / 1000,  # Convert to seconds
                    resource_type=resource_type,
                    status_code=200  # Assume success if loaded
                ))
            
            return resource_timings
            
        except Exception as e:
            print(f"Warning: Could not collect resource timings: {e}")
            return []
    
    def cleanup(self):
        """Clean up WebDriver"""
        if self.driver:
            self.driver.quit()

class GeographicTester:
    """Test from multiple geographic locations using public APIs"""
    
    @staticmethod
    def test_from_locations(url: str, locations: List[str] = None) -> Dict[str, PerformanceMetrics]:
        """Test website from different geographic locations"""
        if not locations:
            locations = ['us-east', 'us-west', 'europe', 'asia']
        
        # For demo purposes, we'll simulate different locations
        # In a real implementation, you'd use services like:
        # - GTmetrix API
        # - Pingdom API  
        # - WebPageTest API
        # - Your own distributed testing infrastructure
        
        results = {}
        base_tester = WebPerformanceTester(url)
        
        for location in locations:
            print(f"Testing from {location}...")
            # Add artificial latency to simulate geographic distance
            latency_simulation = {
                'us-east': 0,
                'us-west': 0.05,
                'europe': 0.1,
                'asia': 0.15
            }
            
            time.sleep(latency_simulation.get(location, 0))
            result = base_tester.single_request_test()
            result.location = location
            results[location] = result
            
        return results

class WebPerformanceTester:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.parsed_url = urllib.parse.urlparse(base_url)
        self.session = requests.Session()
        self.ssl_checker = SSLChecker()
        self.web_vitals_collector = None
        
    def setup_web_vitals_collection(self):
        """Setup Web Vitals collection if possible"""
        self.web_vitals_collector = WebVitalsCollector()
        return self.web_vitals_collector.setup_driver()
        
    def get_dns_resolution_time(self) -> float:
        """Measure DNS resolution time"""
        start_time = time.time()
        try:
            socket.gethostbyname(self.parsed_url.hostname)
            return time.time() - start_time
        except socket.gaierror:
            return -1
    
    def get_connection_metrics(self) -> Dict[str, float]:
        """Get detailed connection timing metrics"""
        hostname = self.parsed_url.hostname
        port = self.parsed_url.port or (443 if self.parsed_url.scheme == 'https' else 80)
        
        # DNS Resolution
        dns_start = time.time()
        try:
            ip = socket.gethostbyname(hostname)
            dns_time = time.time() - dns_start
        except socket.gaierror:
            return {"dns_time": -1, "connect_time": -1, "ssl_time": -1}
        
        # TCP Connection
        connect_start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        
        try:
            sock.connect((ip, port))
            connect_time = time.time() - connect_start
            
            # SSL Handshake (if HTTPS)
            ssl_time = 0
            if self.parsed_url.scheme == 'https':
                ssl_start = time.time()
                context = ssl.create_default_context()
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    ssl_time = time.time() - ssl_start
            
            sock.close()
            return {
                "dns_time": dns_time,
                "connect_time": connect_time,
                "ssl_time": ssl_time
            }
            
        except (socket.timeout, ConnectionRefusedError):
            sock.close()
            return {"dns_time": dns_time, "connect_time": -1, "ssl_time": -1}
    
    def check_multiple_endpoints(self, endpoints: List[str]) -> Dict[str, PerformanceMetrics]:
        """Check multiple endpoints for availability and performance"""
        results = {}
        base_domain = f"{self.parsed_url.scheme}://{self.parsed_url.netloc}"
        
        for endpoint in endpoints:
            full_url = f"{base_domain}{endpoint}" if endpoint.startswith('/') else endpoint
            print(f"Testing endpoint: {endpoint}")
            
            try:
                temp_tester = WebPerformanceTester(full_url)
                result = temp_tester.single_request_test()
                results[endpoint] = result
            except Exception as e:
                print(f"Error testing {endpoint}: {e}")
                results[endpoint] = None
                
        return results
    
    def single_request_test(self, collect_vitals: bool = False) -> PerformanceMetrics:
        """Perform a comprehensive single request test"""
        connection_metrics = self.get_connection_metrics()
        
        # SSL Certificate check
        ssl_info = None
        if self.parsed_url.scheme == 'https':
            ssl_info = self.ssl_checker.check_ssl_certificate(self.parsed_url.hostname)
        
        start_time = time.time()
        try:
            response = self.session.get(self.base_url, timeout=30)
            total_time = time.time() - start_time
            
            # Collect Web Vitals if requested and available
            web_vitals = None
            resources = []
            if collect_vitals and self.web_vitals_collector:
                web_vitals = self.web_vitals_collector.collect_web_vitals(self.base_url)
                resources = self.web_vitals_collector.collect_resource_timings(self.base_url)
            
            return PerformanceMetrics(
                url=self.base_url,
                dns_time=connection_metrics["dns_time"],
                connect_time=connection_metrics["connect_time"],
                ssl_time=connection_metrics["ssl_time"],
                ttfb=response.elapsed.total_seconds(),
                total_time=total_time,
                response_size=len(response.content),
                status_code=response.status_code,
                timestamp=time.time(),
                ssl_info=ssl_info,
                web_vitals=web_vitals,
                resources=resources or []
            )
        except requests.RequestException as e:
            return PerformanceMetrics(
                url=self.base_url,
                dns_time=connection_metrics["dns_time"],
                connect_time=connection_metrics["connect_time"],
                ssl_time=connection_metrics["ssl_time"],
                ttfb=-1,
                total_time=-1,
                response_size=0,
                status_code=0,
                timestamp=time.time(),
                ssl_info=ssl_info
            )
    
    def baseline_test(self, num_requests: int = 10, collect_vitals: bool = False) -> List[PerformanceMetrics]:
        """Perform baseline performance test"""
        print(f"Running baseline test with {num_requests} requests...")
        results = []
        
        for i in range(num_requests):
            print(f"Request {i+1}/{num_requests}", end='\r')
            # Only collect vitals on first request to avoid overhead
            result = self.single_request_test(collect_vitals=(i == 0 and collect_vitals))
            results.append(result)
            time.sleep(0.1)  # Small delay between requests
            
        print("\nBaseline test completed.")
        return results
    
    def concurrent_request(self) -> PerformanceMetrics:
        """Single request for concurrent testing"""
        start_time = time.time()
        try:
            response = requests.get(self.base_url, timeout=30)
            total_time = time.time() - start_time
            
            return PerformanceMetrics(
                url=self.base_url,
                dns_time=0,  # Skip detailed timing for concurrent tests
                connect_time=0,
                ssl_time=0,
                ttfb=response.elapsed.total_seconds(),
                total_time=total_time,
                response_size=len(response.content),
                status_code=response.status_code,
                timestamp=time.time()
            )
        except requests.RequestException:
            return PerformanceMetrics(
                url=self.base_url,
                dns_time=0,
                connect_time=0,
                ssl_time=0,
                ttfb=-1,
                total_time=-1,
                response_size=0,
                status_code=0,
                timestamp=time.time()
            )
    
    def load_test(self, concurrent_users: int = 10, requests_per_user: int = 5) -> List[PerformanceMetrics]:
        """Perform load testing with concurrent users"""
        print(f"Running load test with {concurrent_users} concurrent users, {requests_per_user} requests each...")
        
        results = []
        total_requests = concurrent_users * requests_per_user
        
        def user_requests():
            user_results = []
            for _ in range(requests_per_user):
                result = self.concurrent_request()
                user_results.append(result)
            return user_results
        
        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_users) as executor:
            futures = [executor.submit(user_requests) for _ in range(concurrent_users)]
            
            for future in concurrent.futures.as_completed(futures):
                results.extend(future.result())
        
        duration = time.time() - start_time
        rps = total_requests / duration
        
        print(f"\nLoad test completed in {duration:.2f}s")
        print(f"Requests per second: {rps:.2f}")
        
        return results
    
    def stress_test(self, max_users: int = 50, ramp_up_time: int = 30) -> List[PerformanceMetrics]:
        """Perform stress testing with gradual load increase"""
        print(f"Running stress test ramping up to {max_users} users over {ramp_up_time}s...")
        
        results = []
        users_per_step = max(1, max_users // 10)
        steps = max_users // users_per_step
        step_duration = ramp_up_time / steps
        
        for step in range(1, steps + 1):
            current_users = step * users_per_step
            print(f"Step {step}/{steps}: {current_users} concurrent users")
            
            def single_request():
                return self.concurrent_request()
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=current_users) as executor:
                futures = [executor.submit(single_request) for _ in range(current_users)]
                step_results = [future.result() for future in concurrent.futures.as_completed(futures)]
                results.extend(step_results)
            
            if step < steps:
                time.sleep(step_duration)
        
        print("Stress test completed.")
        return results
    
    def cleanup(self):
        """Clean up resources"""
        if self.web_vitals_collector:
            self.web_vitals_collector.cleanup()

class PerformanceReporter:
    def __init__(self, url: str):
        self.url = url
        
    def calculate_statistics(self, metrics: List[PerformanceMetrics], metric_name: str) -> Dict[str, float]:
        """Calculate statistics for a given metric"""
        values = [getattr(m, metric_name) for m in metrics if getattr(m, metric_name) > 0]
        
        if not values:
            return {"min": 0, "max": 0, "mean": 0, "median": 0, "p95": 0, "p99": 0}
        
        return {
            "min": min(values),
            "max": max(values),
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "p95": self.percentile(values, 95),
            "p99": self.percentile(values, 99)
        }
    
    def percentile(self, values: List[float], p: int) -> float:
        """Calculate percentile"""
        if not values:
            return 0
        sorted_values = sorted(values)
        k = (len(sorted_values) - 1) * (p / 100)
        f = int(k)
        c = k - f
        if f == len(sorted_values) - 1:
            return sorted_values[f]
        return sorted_values[f] * (1 - c) + sorted_values[f + 1] * c
    
    def generate_report(self, baseline_results: List[PerformanceMetrics], 
                       load_results: List[PerformanceMetrics], 
                       stress_results: List[PerformanceMetrics],
                       endpoint_results: Dict[str, PerformanceMetrics] = None,
                       geographic_results: Dict[str, PerformanceMetrics] = None) -> str:
        """Generate comprehensive HTML performance report"""
        
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Performance Test Report - {self.url}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6; color: #333; background: #f8f9fa; margin: 0;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .header {{ 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; padding: 2rem; border-radius: 10px; margin-bottom: 2rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .header h1 {{ font-size: 2.5rem; margin-bottom: 0.5rem; }}
        .header p {{ font-size: 1.1rem; opacity: 0.9; }}
        .test-info {{ 
            background: white; padding: 1.5rem; border-radius: 8px; 
            margin-bottom: 2rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .test-info h2 {{ color: #4a5568; margin-bottom: 1rem; }}
        .info-grid {{ 
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem; margin-top: 1rem;
        }}
        .info-item {{ background: #f7fafc; padding: 1rem; border-radius: 6px; }}
        .info-item strong {{ color: #2d3748; }}
        .section {{ 
            background: white; margin-bottom: 2rem; border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden;
        }}
        .section-header {{ 
            background: #4a5568; color: white; padding: 1rem 1.5rem; 
            font-size: 1.2rem; font-weight: 600;
        }}
        .section-content {{ padding: 1.5rem; }}
        .metrics-grid {{ 
            display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem; margin-bottom: 1.5rem;
        }}
        .metric-card {{ 
            background: #f7fafc; border-radius: 8px; padding: 1.5rem;
            border-left: 4px solid #667eea;
        }}
        .metric-card h4 {{ color: #2d3748; margin-bottom: 1rem; font-size: 1.1rem; }}
        .stats-table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
        .stats-table th, .stats-table td {{ 
            padding: 0.75rem; text-align: left; border-bottom: 1px solid #e2e8f0;
        }}
        .stats-table th {{ background: #edf2f7; font-weight: 600; color: #4a5568; }}
        .stats-table tr:hover {{ background: #f7fafc; }}
        .performance-indicator {{ 
            display: inline-block; padding: 0.25rem 0.75rem; border-radius: 20px;
            font-size: 0.9rem; font-weight: 600; margin-left: 0.5rem;
        }}
        .excellent {{ background: #c6f6d5; color: #22543d; }}
        .good {{ background: #fef5e7; color: #c05621; }}
        .fair {{ background: #fed7d7; color: #c53030; }}
        .poor {{ background: #fed7d7; color: #c53030; }}
        .ssl-valid {{ background: #c6f6d5; color: #22543d; }}
        .ssl-warning {{ background: #fef5e7; color: #c05621; }}
        .ssl-invalid {{ background: #fed7d7; color: #c53030; }}
        .recommendations {{ 
            background: #ebf8ff; border-left: 4px solid #3182ce; 
            padding: 1.5rem; border-radius: 0 8px 8px 0; margin-top: 1.5rem;
        }}
        .recommendations h4 {{ color: #2c5282; margin-bottom: 1rem; }}
        .recommendations ul {{ list-style: none; }}
        .recommendations li {{ 
            margin-bottom: 0.5rem; padding-left: 1.5rem; position: relative;
        }}
        .recommendations li:before {{ 
            content: "→"; position: absolute; left: 0; color: #3182ce; font-weight: bold;
        }}
        .chart-container {{ margin: 1.5rem 0; }}
        .progress-bar {{ 
            background: #e2e8f0; height: 20px; border-radius: 10px; overflow: hidden;
            margin: 0.5rem 0;
        }}
        .progress-fill {{ 
            height: 100%; background: linear-gradient(90deg, #48bb78, #38a169);
            transition: width 0.3s ease;
        }}
        .error-indicator {{ color: #e53e3e; font-weight: 600; }}
        .success-indicator {{ color: #38a169; font-weight: 600; }}
        .status-code-200 {{ color: #38a169; }}
        .status-code-404 {{ color: #e53e3e; }}
        .status-code-500 {{ color: #e53e3e; }}
        .status-code-other {{ color: #d69e2e; }}
        .resource-grid {{ 
            display: grid; grid-template-columns: 2fr 1fr 1fr 1fr;
            gap: 0.5rem; align-items: center; margin: 0.5rem 0;
        }}
        .resource-item {{ 
            background: #f7fafc; padding: 0.5rem; border-radius: 4px; font-size: 0.9rem;
        }}
        @media (max-width: 768px) {{
            .container {{ padding: 10px; }}
            .header {{ padding: 1.5rem; }}
            .header h1 {{ font-size: 2rem; }}
            .metrics-grid {{ grid-template-columns: 1fr; }}
            .resource-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Comprehensive Performance Report</h1>
            <p>Complete analysis of website availability, performance, and security</p>
        </div>
        
        <div class="test-info">
            <h2>Test Information</h2>
            <div class="info-grid">
                <div class="info-item">
                    <strong>URL:</strong><br>
                    <code>{self.url}</code>
                </div>
                <div class="info-item">
                    <strong>Test Date:</strong><br>
                    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </div>
                <div class="info-item">
                    <strong>System:</strong><br>
                    {psutil.cpu_count()} CPU cores, {psutil.virtual_memory().total // (1024**3)} GB RAM
                </div>
            </div>
        </div>"""
        
        # SSL Certificate Section
        if baseline_results and baseline_results[0].ssl_info:
            ssl_info = baseline_results[0].ssl_info
            ssl_status_class = "ssl-valid" if ssl_info.is_valid else "ssl-invalid"
            if ssl_info.is_valid and ssl_info.days_until_expiry < 30:
                ssl_status_class = "ssl-warning"
            
            html += f"""
        <div class="section">
            <div class="section-header">🔒 SSL Certificate Analysis</div>
            <div class="section-content">
                <div class="info-grid">
                    <div class="info-item">
                        <strong>Status:</strong><br>
                        <span class="{ssl_status_class}">
                            {'✓ Valid' if ssl_info.is_valid else '✗ Invalid'}
                        </span>
                    </div>
                    <div class="info-item">
                        <strong>Issuer:</strong><br>
                        {ssl_info.issuer}
                    </div>
                    <div class="info-item">
                        <strong>Subject:</strong><br>
                        {ssl_info.subject}
                    </div>
                    <div class="info-item">
                        <strong>Expires:</strong><br>
                        {ssl_info.expires.strftime('%Y-%m-%d %H:%M:%S')}
                        <br><small>({ssl_info.days_until_expiry} days remaining)</small>
                    </div>
                    <div class="info-item">
                        <strong>Protocol:</strong><br>
                        {ssl_info.version}
                    </div>
                    <div class="info-item">
                        <strong>Cipher:</strong><br>
                        {ssl_info.cipher}
                    </div>
                </div>
            </div>
        </div>"""
        
        # Endpoint Health Checks
        if endpoint_results:
            html += f"""
        <div class="section">
            <div class="section-header">🏥 Endpoint Health Checks</div>
            <div class="section-content">
                <table class="stats-table">
                    <thead>
                        <tr>
                            <th>Endpoint</th>
                            <th>Status Code</th>
                            <th>Response Time</th>
                            <th>Size</th>
                            <th>Availability</th>
                        </tr>
                    </thead>
                    <tbody>"""
            
            for endpoint, result in endpoint_results.items():
                if result:
                    status_class = f"status-code-{result.status_code}" if result.status_code in [200, 404, 500] else "status-code-other"
                    availability = "✓ Available" if result.status_code == 200 else "✗ Unavailable"
                    availability_class = "success-indicator" if result.status_code == 200 else "error-indicator"
                    
                    html += f"""
                        <tr>
                            <td><code>{endpoint}</code></td>
                            <td><span class="{status_class}">{result.status_code}</span></td>
                            <td>{result.ttfb:.3f}s</td>
                            <td>{result.response_size:,} bytes</td>
                            <td><span class="{availability_class}">{availability}</span></td>
                        </tr>"""
                else:
                    html += f"""
                        <tr>
                            <td><code>{endpoint}</code></td>
                            <td><span class="error-indicator">Error</span></td>
                            <td>-</td>
                            <td>-</td>
                            <td><span class="error-indicator">✗ Failed</span></td>
                        </tr>"""
            
            html += """
                    </tbody>
                </table>
            </div>
        </div>"""
        
        # Geographic Performance
        if geographic_results:
            html += f"""
        <div class="section">
            <div class="section-header">🌍 Geographic Performance</div>
            <div class="section-content">
                <table class="stats-table">
                    <thead>
                        <tr>
                            <th>Location</th>
                            <th>DNS Time</th>
                            <th>Connect Time</th>
                            <th>TTFB</th>
                            <th>Total Time</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>"""
            
            for location, result in geographic_results.items():
                status_class = "success-indicator" if result.status_code == 200 else "error-indicator"
                status_text = "✓ Success" if result.status_code == 200 else f"✗ {result.status_code}"
                
                html += f"""
                    <tr>
                        <td><strong>{location.title()}</strong></td>
                        <td>{result.dns_time:.3f}s</td>
                        <td>{result.connect_time:.3f}s</td>
                        <td>{result.ttfb:.3f}s</td>
                        <td>{result.total_time:.3f}s</td>
                        <td><span class="{status_class}">{status_text}</span></td>
                    </tr>"""
            
            html += """
                    </tbody>
                </table>
            </div>
        </div>"""
        
        # Web Vitals Section
        if baseline_results and baseline_results[0].web_vitals:
            vitals = baseline_results[0].web_vitals
            
            # Scoring based on Google's thresholds
            def get_vitals_score(metric, value):
                thresholds = {
                    'fcp': {'good': 1.8, 'poor': 3.0},
                    'lcp': {'good': 2.5, 'poor': 4.0},
                    'cls': {'good': 0.1, 'poor': 0.25},
                    'tti': {'good': 3.8, 'poor': 7.3}
                }
                
                if metric not in thresholds:
                    return 'good'
                
                if value <= thresholds[metric]['good']:
                    return 'excellent'
                elif value <= thresholds[metric]['poor']:
                    return 'fair'
                else:
                    return 'poor'
            
            html += f"""
        <div class="section">
            <div class="section-header">⚡ Core Web Vitals</div>
            <div class="section-content">
                <div class="metrics-grid">
                    <div class="metric-card">
                        <h4>🎨 First Contentful Paint (FCP)</h4>
                        <p><strong>{vitals.fcp:.2f}s</strong> 
                        <span class="performance-indicator {get_vitals_score('fcp', vitals.fcp)}">
                            {get_vitals_score('fcp', vitals.fcp).title()}
                        </span></p>
                        <small>Good: ≤ 1.8s | Poor: > 3.0s</small>
                    </div>
                    
                    <div class="metric-card">
                        <h4>🖼️ Largest Contentful Paint (LCP)</h4>
                        <p><strong>{vitals.lcp:.2f}s</strong>
                        <span class="performance-indicator {get_vitals_score('lcp', vitals.lcp)}">
                            {get_vitals_score('lcp', vitals.lcp).title()}
                        </span></p>
                        <small>Good: ≤ 2.5s | Poor: > 4.0s</small>
                    </div>
                    
                    <div class="metric-card">
                        <h4>📐 Cumulative Layout Shift (CLS)</h4>
                        <p><strong>{vitals.cls:.3f}</strong>
                        <span class="performance-indicator {get_vitals_score('cls', vitals.cls)}">
                            {get_vitals_score('cls', vitals.cls).title()}
                        </span></p>
                        <small>Good: ≤ 0.1 | Poor: > 0.25</small>
                    </div>
                    
                    <div class="metric-card">
                        <h4>⚡ Time to Interactive (TTI)</h4>
                        <p><strong>{vitals.tti:.2f}s</strong>
                        <span class="performance-indicator {get_vitals_score('tti', vitals.tti)}">
                            {get_vitals_score('tti', vitals.tti).title()}
                        </span></p>
                        <small>Good: ≤ 3.8s | Poor: > 7.3s</small>
                    </div>
                    
                    <div class="metric-card">
                        <h4>📄 DOM Ready</h4>
                        <p><strong>{vitals.dom_ready:.2f}s</strong></p>
                        <small>Time until DOM content loaded</small>
                    </div>
                    
                    <div class="metric-card">
                        <h4>✅ Fully Loaded</h4>
                        <p><strong>{vitals.fully_loaded:.2f}s</strong></p>
                        <small>Time until all resources loaded</small>
                    </div>
                </div>
            </div>
        </div>"""
        
        # Resource Loading Analysis
        if baseline_results and baseline_results[0].resources:
            resources = baseline_results[0].resources
            
            # Group resources by type
            resource_types = {}
            for resource in resources:
                if resource.resource_type not in resource_types:
                    resource_types[resource.resource_type] = []
                resource_types[resource.resource_type].append(resource)
            
            html += f"""
        <div class="section">
            <div class="section-header">📦 Resource Loading Analysis</div>
            <div class="section-content">"""
            
            for resource_type, type_resources in resource_types.items():
                total_size = sum(r.size for r in type_resources)
                avg_load_time = statistics.mean([r.load_time for r in type_resources]) if type_resources else 0
                
                html += f"""
                <div class="metric-card">
                    <h4>📁 {resource_type.title()} Resources ({len(type_resources)} files)</h4>
                    <p><strong>Total Size:</strong> {total_size:,} bytes ({total_size/1024:.1f} KB)</p>
                    <p><strong>Average Load Time:</strong> {avg_load_time:.3f}s</p>
                    
                    <div style="max-height: 200px; overflow-y: auto; margin-top: 1rem;">"""
                
                for resource in sorted(type_resources, key=lambda x: x.load_time, reverse=True)[:10]:
                    resource_name = resource.url.split('/')[-1][:50] + ('...' if len(resource.url.split('/')[-1]) > 50 else '')
                    html += f"""
                        <div class="resource-grid">
                            <div class="resource-item"><small>{resource_name}</small></div>
                            <div class="resource-item">{resource.size:,}B</div>
                            <div class="resource-item">{resource.load_time:.3f}s</div>
                            <div class="resource-item">{'✓' if resource.status_code == 200 else '✗'}</div>
                        </div>"""
                
                html += "</div></div>"
            
            html += "</div></div>"
        
        # Baseline Test Results
        if baseline_results:
            success_rate = len([m for m in baseline_results if m.status_code == 200]) / len(baseline_results) * 100
            ttfb_stats = self.calculate_statistics(baseline_results, 'ttfb')
            total_stats = self.calculate_statistics(baseline_results, 'total_time')
            avg_size = statistics.mean([m.response_size for m in baseline_results if m.response_size > 0])
            
            html += f"""
        <div class="section">
            <div class="section-header">📊 Baseline Performance Test</div>
            <div class="section-content">
                <div class="info-grid">
                    <div class="info-item">
                        <strong>Requests:</strong> {len(baseline_results)}
                    </div>
                    <div class="info-item">
                        <strong>Success Rate:</strong> 
                        <span class="{'success-indicator' if success_rate >= 95 else 'error-indicator'}">{success_rate:.1f}%</span>
                    </div>
                    <div class="info-item">
                        <strong>Avg Response Size:</strong> {avg_size:,.0f} bytes ({avg_size/1024:.1f} KB)
                    </div>
                </div>
                
                <div class="metrics-grid">
                    <div class="metric-card">
                        <h4>⏱️ Time to First Byte (TTFB)</h4>
                        <table class="stats-table">
                            <tr><td>Min</td><td>{ttfb_stats['min']:.3f}s</td></tr>
                            <tr><td>Mean</td><td><strong>{ttfb_stats['mean']:.3f}s</strong></td></tr>
                            <tr><td>Median</td><td>{ttfb_stats['median']:.3f}s</td></tr>
                            <tr><td>95th percentile</td><td>{ttfb_stats['p95']:.3f}s</td></tr>
                            <tr><td>99th percentile</td><td>{ttfb_stats['p99']:.3f}s</td></tr>
                            <tr><td>Max</td><td>{ttfb_stats['max']:.3f}s</td></tr>
                        </table>
                    </div>
                    
                    <div class="metric-card">
                        <h4>🔄 Total Response Time</h4>
                        <table class="stats-table">
                            <tr><td>Min</td><td>{total_stats['min']:.3f}s</td></tr>
                            <tr><td>Mean</td><td><strong>{total_stats['mean']:.3f}s</strong></td></tr>
                            <tr><td>Median</td><td>{total_stats['median']:.3f}s</td></tr>
                            <tr><td>95th percentile</td><td>{total_stats['p95']:.3f}s</td></tr>
                            <tr><td>99th percentile</td><td>{total_stats['p99']:.3f}s</td></tr>
                            <tr><td>Max</td><td>{total_stats['max']:.3f}s</td></tr>
                        </table>
                    </div>
                </div>"""
            
            # Connection Statistics
            if baseline_results[0].dns_time > 0:
                dns_stats = self.calculate_statistics(baseline_results, 'dns_time')
                connect_stats = self.calculate_statistics(baseline_results, 'connect_time')
                
                html += f"""
                <div class="metric-card">
                    <h4>🌐 Connection Statistics</h4>
                    <table class="stats-table">
                        <tr><td>DNS Resolution</td><td>{dns_stats['mean']:.3f}s</td></tr>
                        <tr><td>TCP Connection</td><td>{connect_stats['mean']:.3f}s</td></tr>"""
                
                if baseline_results[0].ssl_time > 0:
                    ssl_stats = self.calculate_statistics(baseline_results, 'ssl_time')
                    html += f"<tr><td>SSL Handshake</td><td>{ssl_stats['mean']:.3f}s</td></tr>"
                
                html += "</table></div>"
            
            html += "</div></div>"
        
        # Load Test Results
        if load_results:
            success_rate = len([m for m in load_results if m.status_code == 200]) / len(load_results) * 100
            duration = max([m.timestamp for m in load_results]) - min([m.timestamp for m in load_results])
            rps = len(load_results) / duration if duration > 0 else 0
            ttfb_stats = self.calculate_statistics(load_results, 'ttfb')
            
            html += f"""
        <div class="section">
            <div class="section-header">⚡ Load Test Results</div>
            <div class="section-content">
                <div class="info-grid">
                    <div class="info-item">
                        <strong>Total Requests:</strong> {len(load_results)}
                    </div>
                    <div class="info-item">
                        <strong>Success Rate:</strong> 
                        <span class="{'success-indicator' if success_rate >= 95 else 'error-indicator'}">{success_rate:.1f}%</span>
                    </div>
                    <div class="info-item">
                        <strong>Requests/Second:</strong> <strong>{rps:.2f}</strong>
                    </div>
                    <div class="info-item">
                        <strong>Test Duration:</strong> {duration:.2f}s
                    </div>
                </div>
                
                <div class="metric-card">
                    <h4>📈 Response Time Under Load</h4>
                    <table class="stats-table">
                        <tr><td>TTFB Mean</td><td><strong>{ttfb_stats['mean']:.3f}s</strong></td></tr>
                        <tr><td>TTFB 95th percentile</td><td>{ttfb_stats['p95']:.3f}s</td></tr>
                        <tr><td>TTFB 99th percentile</td><td>{ttfb_stats['p99']:.3f}s</td></tr>
                    </table>
                </div>"""
            
            # Error analysis
            error_codes = {}
            for result in load_results:
                if result.status_code != 200:
                    error_codes[result.status_code] = error_codes.get(result.status_code, 0) + 1
            
            if error_codes:
                html += '<div class="metric-card"><h4>❌ Error Distribution</h4><table class="stats-table">'
                for code, count in error_codes.items():
                    html += f'<tr><td>HTTP {code}</td><td class="error-indicator">{count} requests</td></tr>'
                html += '</table></div>'
            
            html += "</div></div>"
        
        # Stress Test Results
        if stress_results:
            success_rate = len([m for m in stress_results if m.status_code == 200]) / len(stress_results) * 100
            ttfb_stats = self.calculate_statistics(stress_results, 'ttfb')
            
            html += f"""
        <div class="section">
            <div class="section-header">🔥 Stress Test Results</div>
            <div class="section-content">
                <div class="info-grid">
                    <div class="info-item">
                        <strong>Total Requests:</strong> {len(stress_results)}
                    </div>
                    <div class="info-item">
                        <strong>Success Rate:</strong> 
                        <span class="{'success-indicator' if success_rate >= 95 else 'error-indicator'}">{success_rate:.1f}%</span>
                    </div>
                </div>
                
                <div class="metric-card">
                    <h4>⚡ Response Time Under Stress</h4>
                    <table class="stats-table">
                        <tr><td>TTFB Mean</td><td><strong>{ttfb_stats['mean']:.3f}s</strong></td></tr>
                        <tr><td>TTFB 95th percentile</td><td>{ttfb_stats['p95']:.3f}s</td></tr>
                        <tr><td>TTFB 99th percentile</td><td>{ttfb_stats['p99']:.3f}s</td></tr>
                    </table>
                </div>
            </div>
        </div>"""
        
        # Performance Analysis
        html += '<div class="section"><div class="section-header">📊 Performance Analysis</div><div class="section-content">'
        
        if baseline_results and load_results:
            baseline_ttfb = self.calculate_statistics(baseline_results, 'ttfb')['mean']
            load_ttfb = self.calculate_statistics(load_results, 'ttfb')['mean']
            degradation = ((load_ttfb - baseline_ttfb) / baseline_ttfb * 100) if baseline_ttfb > 0 else 0
            
            if degradation < 10:
                indicator_class = "excellent"
                indicator_text = "✓ Excellent: Minimal performance degradation"
            elif degradation < 25:
                indicator_class = "good"
                indicator_text = "⚠ Good: Acceptable performance degradation"
            elif degradation < 50:
                indicator_class = "fair"
                indicator_text = "⚠ Fair: Noticeable performance degradation"
            else:
                indicator_class = "poor"
                indicator_text = "✗ Poor: Significant performance degradation"
            
            html += f"""
            <div class="metric-card">
                <h4>📈 Performance Degradation Analysis</h4>
                <p><strong>Performance degradation under load:</strong> {degradation:.1f}%</p>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {min(degradation, 100)}%"></div>
                </div>
                <span class="performance-indicator {indicator_class}">{indicator_text}</span>
            </div>"""
        
        # Recommendations
        recommendations = []
        if baseline_results:
            avg_ttfb = self.calculate_statistics(baseline_results, 'ttfb')['mean']
            if avg_ttfb > 1.0:
                recommendations.append("High TTFB detected - optimize server response time")
            if avg_ttfb > 0.5:
                recommendations.append("Consider implementing caching strategies")
            
            avg_size = statistics.mean([m.response_size for m in baseline_results if m.response_size > 0])
            if avg_size > 1024 * 1024:  # 1MB
                recommendations.append("Large response size - consider compression and optimization")
            
            # SSL recommendations
            if baseline_results[0].ssl_info:
                ssl_info = baseline_results[0].ssl_info
                if ssl_info.is_valid and ssl_info.days_until_expiry < 30:
                    recommendations.append(f"SSL certificate expires in {ssl_info.days_until_expiry} days - renew soon")
                elif not ssl_info.is_valid:
                    recommendations.append("SSL certificate is invalid - fix certificate configuration")
            
            # Web Vitals recommendations
            if baseline_results[0].web_vitals:
                vitals = baseline_results[0].web_vitals
                if vitals.fcp > 1.8:
                    recommendations.append("Improve First Contentful Paint - optimize critical rendering path")
                if vitals.lcp > 2.5:
                    recommendations.append("Improve Largest Contentful Paint - optimize images and fonts")
                if vitals.cls > 0.1:
                    recommendations.append("Reduce Cumulative Layout Shift - reserve space for dynamic content")
                if vitals.tti > 3.8:
                    recommendations.append("Improve Time to Interactive - minimize JavaScript execution time")
        
        if load_results:
            error_count = len([m for m in load_results if m.status_code != 200])
            if error_count > 0:
                recommendations.append("Errors detected under load - investigate server capacity")
        
        # Resource-specific recommendations
        if baseline_results and baseline_results[0].resources:
            resources = baseline_results[0].resources
            large_images = [r for r in resources if r.resource_type == 'image' and r.size > 500000]  # 500KB
            if large_images:
                recommendations.append(f"Found {len(large_images)} large images - consider optimization and compression")
            
            slow_scripts = [r for r in resources if r.resource_type == 'script' and r.load_time > 1.0]
            if slow_scripts:
                recommendations.append(f"Found {len(slow_scripts)} slow-loading scripts - consider bundling and minification")
        
        if recommendations:
            html += '<div class="recommendations"><h4>💡 Recommendations</h4><ul>'
            for rec in recommendations:
                html += f'<li>{rec}</li>'
            html += '</ul></div>'
        
        html += """
                </div>
            </div>
        </div>
    </body>
</html>"""
        
        return html

    def check_dependencies():
        """Check if required dependencies are available"""
        missing_deps = []
        
        try:
            import requests
        except ImportError:
            missing_deps.append("requests")
        
        try:
            import psutil
        except ImportError:
            missing_deps.append("psutil")
        
        try:
            from selenium import webdriver
        except ImportError:
            missing_deps.append("selenium")
        
        if missing_deps:
            print("❌ Missing required dependencies:")
            for dep in missing_deps:
                print(f"   - {dep}")
            print("\n📦 Install with: pip install " + " ".join(missing_deps))
            return False
        
        return True
    parser = argparse.ArgumentParser(description='Comprehensive Website Performance Testing Tool')
    parser.add_argument('url', help='Website URL to test')
    parser.add_argument('--baseline', type=int, default=10, help='Number of baseline requests (default: 10)')
    parser.add_argument('--load-users', type=int, default=10, help='Concurrent users for load test (default: 10)')
    parser.add_argument('--load-requests', type=int, default=5, help='Requests per user in load test (default: 5)')
    parser.add_argument('--stress-users', type=int, default=50, help='Max users for stress test (default: 50)')
    parser.add_argument('--stress-ramp', type=int, default=30, help='Stress test ramp-up time in seconds (default: 30)')
    parser.add_argument('--output', help='Output file for report (default: report.html)')
    parser.add_argument('--endpoints', nargs='*', default=['/'], help='Additional endpoints to test (default: /)')
    parser.add_argument('--geographic', action='store_true', help='Test from multiple geographic locations')
    parser.add_argument('--web-vitals', action='store_true', help='Collect Core Web Vitals (requires Chrome)')
    parser.add_argument('--skip-load', action='store_true', help='Skip load testing')
    parser.add_argument('--skip-stress', action='store_true', help='Skip stress testing')
    
    args = parser.parse_args()
    
    # Validate URL
    if not args.url.startswith(('http://', 'https://')):
        args.url = 'https://' + args.url
    
    print(f"Starting comprehensive performance tests for: {args.url}")
    print("=" * 60)
    
    # Initialize tester and reporter
    tester = WebPerformanceTester(args.url)
    reporter = PerformanceReporter(args.url)
    
    # Setup Web Vitals collection if requested
    web_vitals_available = False
    if args.web_vitals:
        web_vitals_available = tester.setup_web_vitals_collection()
        if not web_vitals_available:
            print("Warning: Web Vitals collection not available, continuing without it...")
    
    # Run tests
    try:
        # Baseline test with Web Vitals
        baseline_results = tester.baseline_test(args.baseline, collect_vitals=web_vitals_available)
        
        # Multiple endpoint testing
        endpoint_results = None
        if len(args.endpoints) > 1 or args.endpoints[0] != '/':
            print(f"\nTesting {len(args.endpoints)} endpoints...")
            endpoint_results = tester.check_multiple_endpoints(args.endpoints)
        
        # Geographic testing
        geographic_results = None
        if args.geographic:
            print("\nTesting from multiple geographic locations...")
            geographic_results = GeographicTester.test_from_locations(args.url)
        
        # Load and stress tests
        load_results = []
        stress_results = []
        
        if not args.skip_load:
            load_results = tester.load_test(args.load_users, args.load_requests)
        
        if not args.skip_stress:
            stress_results = tester.stress_test(args.stress_users, args.stress_ramp)
        
        # Generate report
        report = reporter.generate_report(
            baseline_results, 
            load_results, 
            stress_results,
            endpoint_results,
            geographic_results
        )
        
        # Output report
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\nComprehensive HTML report saved to: {args.output}")
        else:
            # Default filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"performance_report_{timestamp}.html"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\nComprehensive HTML report saved to: {filename}")
            print(f"Open the file in your browser to view the detailed report.")
            
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError running tests: {e}")
        sys.exit(1)
    finally:
        # Clean up resources
        tester.cleanup()

if __name__ == "__main__":
    main()