#!/usr/bin/env python3
"""
Quick test script for GetME! API
Tests basic processing and polling functionality.

Usage:
    python test_api.py --drive-link "YOUR_DRIVE_LINK" --admin-token "YOUR_TOKEN"
"""
import argparse
import sys
import time
import requests
from typing import Optional


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_success(msg: str):
    print(f"{Colors.GREEN}✓{Colors.RESET} {msg}")


def print_error(msg: str):
    print(f"{Colors.RED}✗{Colors.RESET} {msg}")


def print_info(msg: str):
    print(f"{Colors.BLUE}ℹ{Colors.RESET} {msg}")


def print_section(msg: str):
    print(f"\n{Colors.BOLD}{msg}{Colors.RESET}")


class GetMEAPITester:
    def __init__(self, base_url: str, admin_token: str, drive_link: str):
        self.base_url = base_url
        self.admin_token = admin_token
        self.drive_link = drive_link
        self.headers = {"x-admin-token": admin_token}
    
    def test_health(self) -> bool:
        """Test the health endpoint"""
        print_section("Testing Health Endpoint")
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            print_success(f"Health check passed: {data}")
            return True
        except Exception as e:
            print_error(f"Health check failed: {e}")
            return False
    
    def test_full_processing(self) -> Optional[str]:
        """Test full processing job"""
        print_section("Testing Full Processing")
        try:
            print_info("Starting full processing job...")
            resp = requests.post(
                f"{self.base_url}/api/drive/process",
                headers=self.headers,
                json={"drive_link": self.drive_link, "incremental": False},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            job_id = data["job_id"]
            print_success(f"Job started: {job_id}")
            
            # Poll job status
            print_info("Monitoring job progress...")
            while True:
                status_resp = requests.get(
                    f"{self.base_url}/api/drive/status/{job_id}",
                    timeout=10
                )
                status_resp.raise_for_status()
                status = status_resp.json()
                
                progress = f"{status['processed_files']}/{status['total_files']}"
                faces = status['faces_found']
                print_info(f"  Status: {status['status']} | Files: {progress} | Faces: {faces}")
                
                if status["status"] == "done":
                    print_success(f"Processing completed! Clusters: {status['clusters']}")
                    return job_id
                elif status["status"] == "error":
                    print_error(f"Processing failed: {status.get('error')}")
                    return None
                
                time.sleep(5)
                
        except Exception as e:
            print_error(f"Full processing test failed: {e}")
            return None
    
    def test_incremental_processing(self) -> bool:
        """Test incremental processing"""
        print_section("Testing Incremental Processing")
        print_info("Note: This will only find new images. Add new photos to test fully.")
        try:
            resp = requests.post(
                f"{self.base_url}/api/drive/process",
                headers=self.headers,
                json={"drive_link": self.drive_link, "incremental": True},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            job_id = data["job_id"]
            print_success(f"Incremental job started: {job_id}")
            
            # Wait a bit and check status
            time.sleep(3)
            status_resp = requests.get(
                f"{self.base_url}/api/drive/status/{job_id}",
                timeout=10
            )
            status_resp.raise_for_status()
            status = status_resp.json()
            
            if status["total_files"] == 0:
                print_info("No new images to process (expected if no new photos added)")
            else:
                print_success(f"Found {status['total_files']} new images")
            
            return True
            
        except Exception as e:
            print_error(f"Incremental processing test failed: {e}")
            return False
    
    def test_polling_start(self) -> bool:
        """Test starting polling"""
        print_section("Testing Polling Start")
        try:
            resp = requests.post(
                f"{self.base_url}/api/drive/polling/start",
                headers=self.headers,
                json={"drive_link": self.drive_link, "interval_seconds": 120},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("success"):
                print_success(f"Polling started: {data.get('message')}")
                return True
            else:
                print_error(f"Polling start failed: {data.get('error')}")
                return False
                
        except Exception as e:
            print_error(f"Polling start test failed: {e}")
            return False
    
    def test_polling_status(self) -> bool:
        """Test polling status check"""
        print_section("Testing Polling Status")
        try:
            resp = requests.get(
                f"{self.base_url}/api/drive/polling/status",
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("active"):
                print_success(f"Polling is active. Folder: {data.get('folder_id')}")
            else:
                print_info("Polling is not active")
            
            return True
            
        except Exception as e:
            print_error(f"Polling status test failed: {e}")
            return False
    
    def test_polling_stop(self) -> bool:
        """Test stopping polling"""
        print_section("Testing Polling Stop")
        try:
            resp = requests.post(
                f"{self.base_url}/api/drive/polling/stop",
                headers=self.headers,
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("success"):
                print_success(f"Polling stopped: {data.get('message')}")
                return True
            else:
                print_error(f"Polling stop failed: {data.get('error')}")
                return False
                
        except Exception as e:
            print_error(f"Polling stop test failed: {e}")
            return False
    
    def run_all_tests(self):
        """Run all tests"""
        print(f"{Colors.BOLD}GetME! API Test Suite{Colors.RESET}")
        print(f"Base URL: {self.base_url}")
        print(f"Drive Link: {self.drive_link[:50]}...")
        
        results = []
        
        # Test 1: Health
        results.append(("Health", self.test_health()))
        
        # Test 2: Full processing (this takes time)
        job_id = self.test_full_processing()
        results.append(("Full Processing", job_id is not None))
        
        if job_id:
            # Test 3: Incremental processing
            results.append(("Incremental Processing", self.test_incremental_processing()))
            
            # Test 4: Polling
            results.append(("Polling Start", self.test_polling_start()))
            results.append(("Polling Status", self.test_polling_status()))
            results.append(("Polling Stop", self.test_polling_stop()))
        else:
            print_error("Skipping remaining tests due to processing failure")
        
        # Summary
        print_section("Test Summary")
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = f"{Colors.GREEN}PASS{Colors.RESET}" if result else f"{Colors.RED}FAIL{Colors.RESET}"
            print(f"  {test_name}: {status}")
        
        print(f"\n{Colors.BOLD}Total: {passed}/{total} tests passed{Colors.RESET}")
        
        if passed == total:
            print_success("All tests passed!")
            return 0
        else:
            print_error(f"{total - passed} test(s) failed")
            return 1


def main():
    parser = argparse.ArgumentParser(
        description="Test GetME! API functionality"
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--admin-token",
        required=True,
        help="Admin token for authentication"
    )
    parser.add_argument(
        "--drive-link",
        required=True,
        help="Google Drive folder link or ID to test with"
    )
    
    args = parser.parse_args()
    
    # Create tester and run
    tester = GetMEAPITester(args.base_url, args.admin_token, args.drive_link)
    exit_code = tester.run_all_tests()
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
