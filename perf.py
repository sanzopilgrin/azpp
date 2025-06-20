#!/usr/bin/env python3
"""
Website Performance Testing Script
Tests latency, throughput, response times, and generates comprehensive reports.
"""

import requests
import time
import statistics
import concurrent.futures
import socket
import ssl
import urllib.parse
from datetime import datetime
import json
import argparse
import sys
from dataclasses import dataclass
from typing import List, Dict, Any
import psutil

@dataclass
class PerformanceMetrics:
    """Data class to store performance metrics"""
    url: str
    dns_time: float
    connect_time: float
    ssl_time: float
    ttfb: float
    total_time: float
    response_size: int
    status_code: int
    timestamp: float

class WebPerformanceTester:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.parsed_url = urllib.parse.urlparse(base_url)
        self.session = requests.Session()
        
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
    
    def single_request_test(self) -> PerformanceMetrics:
        """Perform a single request and measure all metrics"""
        connection_metrics = self.get_connection_metrics()
        
        start_time = time.time()
        try:
            response = self.session.get(self.base_url, timeout=30)
            total_time = time.time() - start_time
            
            return PerformanceMetrics(
                url=self.base_url,
                dns_time=connection_metrics["dns_time"],
                connect_time=connection_metrics["connect_time"],
                ssl_time=connection_metrics["ssl_time"],
                ttfb=response.elapsed.total_seconds(),
                total_time=total_time,
                response_size=len(response.content),
                status_code=response.status_code,
                timestamp=time.time()
            )
        except requests.RequestException:
            return PerformanceMetrics(
                url=self.base_url,
                dns_time=connection_metrics["dns_time"],
                connect_time=connection_metrics["connect_time"],
                ssl_time=connection_metrics["ssl_time"],
                ttfb=-1,
                total_time=-1,
                response_size=0,
                status_code=0,
                timestamp=time.time()
            )
    
    def baseline_test(self, num_requests: int = 10) -> List[PerformanceMetrics]:
        """Perform baseline performance test"""
        print(f"Running baseline test with {num_requests} requests...")
        results = []
        
        for i in range(num_requests):
            print(f"Request {i+1}/{num_requests}", end='\r')
            result = self.single_request_test()
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
                       stress_results: List[PerformanceMetrics]) -> str:
        """Generate comprehensive performance report"""
        
        report = []
        report.append("=" * 80)
        report.append("WEBSITE PERFORMANCE TEST REPORT")
        report.append("=" * 80)
        report.append(f"URL: {self.url}")
        report.append(f"Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"System: {psutil.cpu_count()} CPU cores, {psutil.virtual_memory().total // (1024**3)} GB RAM")
        report.append("")
        
        # Baseline Test Results
        report.append("BASELINE PERFORMANCE TEST")
        report.append("-" * 40)
        if baseline_results:
            success_rate = len([m for m in baseline_results if m.status_code == 200]) / len(baseline_results) * 100
            report.append(f"Requests: {len(baseline_results)}")
            report.append(f"Success Rate: {success_rate:.1f}%")
            
            # Response Time Statistics
            ttfb_stats = self.calculate_statistics(baseline_results, 'ttfb')
            total_stats = self.calculate_statistics(baseline_results, 'total_time')
            
            report.append("\nResponse Time Statistics (seconds):")
            report.append(f"  Time to First Byte (TTFB):")
            report.append(f"    Min: {ttfb_stats['min']:.3f}s | Max: {ttfb_stats['max']:.3f}s")
            report.append(f"    Mean: {ttfb_stats['mean']:.3f}s | Median: {ttfb_stats['median']:.3f}s")
            report.append(f"    95th percentile: {ttfb_stats['p95']:.3f}s | 99th percentile: {ttfb_stats['p99']:.3f}s")
            
            report.append(f"  Total Response Time:")
            report.append(f"    Min: {total_stats['min']:.3f}s | Max: {total_stats['max']:.3f}s")
            report.append(f"    Mean: {total_stats['mean']:.3f}s | Median: {total_stats['median']:.3f}s")
            report.append(f"    95th percentile: {total_stats['p95']:.3f}s | 99th percentile: {total_stats['p99']:.3f}s")
            
            # Connection Statistics
            if baseline_results[0].dns_time > 0:
                dns_stats = self.calculate_statistics(baseline_results, 'dns_time')
                connect_stats = self.calculate_statistics(baseline_results, 'connect_time')
                
                report.append("\nConnection Statistics:")
                report.append(f"  DNS Resolution: {dns_stats['mean']:.3f}s (avg)")
                report.append(f"  TCP Connection: {connect_stats['mean']:.3f}s (avg)")
                
                if baseline_results[0].ssl_time > 0:
                    ssl_stats = self.calculate_statistics(baseline_results, 'ssl_time')
                    report.append(f"  SSL Handshake: {ssl_stats['mean']:.3f}s (avg)")
            
            # Response Size
            avg_size = statistics.mean([m.response_size for m in baseline_results if m.response_size > 0])
            report.append(f"\nAverage Response Size: {avg_size:,.0f} bytes ({avg_size/1024:.1f} KB)")
        
        report.append("")
        
        # Load Test Results
        report.append("LOAD TEST RESULTS")
        report.append("-" * 40)
        if load_results:
            success_rate = len([m for m in load_results if m.status_code == 200]) / len(load_results) * 100
            duration = max([m.timestamp for m in load_results]) - min([m.timestamp for m in load_results])
            rps = len(load_results) / duration if duration > 0 else 0
            
            report.append(f"Total Requests: {len(load_results)}")
            report.append(f"Success Rate: {success_rate:.1f}%")
            report.append(f"Requests per Second: {rps:.2f}")
            report.append(f"Test Duration: {duration:.2f}s")
            
            ttfb_stats = self.calculate_statistics(load_results, 'ttfb')
            report.append(f"\nResponse Time Under Load:")
            report.append(f"  TTFB Mean: {ttfb_stats['mean']:.3f}s | 95th: {ttfb_stats['p95']:.3f}s | 99th: {ttfb_stats['p99']:.3f}s")
            
            # Error analysis
            error_codes = {}
            for result in load_results:
                if result.status_code != 200:
                    error_codes[result.status_code] = error_codes.get(result.status_code, 0) + 1
            
            if error_codes:
                report.append(f"\nError Distribution:")
                for code, count in error_codes.items():
                    report.append(f"  HTTP {code}: {count} requests")
        
        report.append("")
        
        # Stress Test Results
        report.append("STRESS TEST RESULTS")
        report.append("-" * 40)
        if stress_results:
            success_rate = len([m for m in stress_results if m.status_code == 200]) / len(stress_results) * 100
            report.append(f"Total Requests: {len(stress_results)}")
            report.append(f"Success Rate: {success_rate:.1f}%")
            
            ttfb_stats = self.calculate_statistics(stress_results, 'ttfb')
            report.append(f"\nResponse Time Under Stress:")
            report.append(f"  TTFB Mean: {ttfb_stats['mean']:.3f}s | 95th: {ttfb_stats['p95']:.3f}s | 99th: {ttfb_stats['p99']:.3f}s")
        
        report.append("")
        
        # Performance Analysis
        report.append("PERFORMANCE ANALYSIS")
        report.append("-" * 40)
        
        if baseline_results and load_results:
            baseline_ttfb = self.calculate_statistics(baseline_results, 'ttfb')['mean']
            load_ttfb = self.calculate_statistics(load_results, 'ttfb')['mean']
            degradation = ((load_ttfb - baseline_ttfb) / baseline_ttfb * 100) if baseline_ttfb > 0 else 0
            
            report.append(f"Performance degradation under load: {degradation:.1f}%")
            
            if degradation < 10:
                report.append("✓ Excellent: Minimal performance degradation under load")
            elif degradation < 25:
                report.append("⚠ Good: Acceptable performance degradation")
            elif degradation < 50:
                report.append("⚠ Fair: Noticeable performance degradation")
            else:
                report.append("✗ Poor: Significant performance degradation")
        
        # Recommendations
        report.append("\nRECOMMendations:")
        if baseline_results:
            avg_ttfb = self.calculate_statistics(baseline_results, 'ttfb')['mean']
            if avg_ttfb > 1.0:
                report.append("• High TTFB detected - optimize server response time")
            if avg_ttfb > 0.5:
                report.append("• Consider implementing caching strategies")
            
            avg_size = statistics.mean([m.response_size for m in baseline_results if m.response_size > 0])
            if avg_size > 1024 * 1024:  # 1MB
                report.append("• Large response size - consider compression and optimization")
        
        if load_results:
            error_count = len([m for m in load_results if m.status_code != 200])
            if error_count > 0:
                report.append("• Errors detected under load - investigate server capacity")
        
        report.append("")
        report.append("=" * 80)
        
        return "\n".join(report)

def main():
    parser = argparse.ArgumentParser(description='Website Performance Testing Tool')
    parser.add_argument('url', help='Website URL to test')
    parser.add_argument('--baseline', type=int, default=10, help='Number of baseline requests (default: 10)')
    parser.add_argument('--load-users', type=int, default=10, help='Concurrent users for load test (default: 10)')
    parser.add_argument('--load-requests', type=int, default=5, help='Requests per user in load test (default: 5)')
    parser.add_argument('--stress-users', type=int, default=50, help='Max users for stress test (default: 50)')
    parser.add_argument('--stress-ramp', type=int, default=30, help='Stress test ramp-up time in seconds (default: 30)')
    parser.add_argument('--output', help='Output file for report (default: stdout)')
    
    args = parser.parse_args()
    
    # Validate URL
    if not args.url.startswith(('http://', 'https://')):
        args.url = 'https://' + args.url
    
    print(f"Starting performance tests for: {args.url}")
    print("=" * 60)
    
    # Initialize tester and reporter
    tester = WebPerformanceTester(args.url)
    reporter = PerformanceReporter(args.url)
    
    # Run tests
    try:
        baseline_results = tester.baseline_test(args.baseline)
        load_results = tester.load_test(args.load_users, args.load_requests)
        stress_results = tester.stress_test(args.stress_users, args.stress_ramp)
        
        # Generate report
        report = reporter.generate_report(baseline_results, load_results, stress_results)
        
        # Output report
        if args.output:
            with open(args.output, 'w') as f:
                f.write(report)
            print(f"\nReport saved to: {args.output}")
        else:
            print("\n" + report)
            
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError running tests: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()