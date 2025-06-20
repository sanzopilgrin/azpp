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
        @media (max-width: 768px) {{
            .container {{ padding: 10px; }}
            .header {{ padding: 1.5rem; }}
            .header h1 {{ font-size: 2rem; }}
            .metrics-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Performance Test Report</h1>
            <p>Comprehensive analysis of website performance metrics</p>
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
        
        if load_results:
            error_count = len([m for m in load_results if m.status_code != 200])
            if error_count > 0:
                recommendations.append("Errors detected under load - investigate server capacity")
        
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

def main():
    parser = argparse.ArgumentParser(description='Website Performance Testing Tool')
    parser.add_argument('url', help='Website URL to test')
    parser.add_argument('--baseline', type=int, default=10, help='Number of baseline requests (default: 10)')
    parser.add_argument('--load-users', type=int, default=10, help='Concurrent users for load test (default: 10)')
    parser.add_argument('--load-requests', type=int, default=5, help='Requests per user in load test (default: 5)')
    parser.add_argument('--stress-users', type=int, default=50, help='Max users for stress test (default: 50)')
    parser.add_argument('--stress-ramp', type=int, default=30, help='Stress test ramp-up time in seconds (default: 30)')
    parser.add_argument('--output', help='Output file for report (default: report.html)')
    parser.add_argument('--format', choices=['html', 'text'], default='html', help='Report format (default: html)')
    
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
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\nHTML report saved to: {args.output}")
        else:
            # Default filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"performance_report_{timestamp}.html"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\nHTML report saved to: {filename}")
            print(f"Open the file in your browser to view the report.")
            
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError running tests: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()