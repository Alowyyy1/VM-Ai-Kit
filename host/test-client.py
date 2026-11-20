#!/usr/bin/env python3
"""Host verification client for AgentKit MCP Server."""
import argparse
import json
import sys
import urllib.request
import urllib.error

def main():
    parser = argparse.ArgumentParser(description="Test AgentKit VM connection from host")
    parser.add_argument("--url", default="http://127.0.0.1:8765", help="Agent endpoint URL")
    parser.add_argument("--token", default="", help="Auth token if required")
    args = parser.parse_args()

    health_url = f"{args.url.rstrip('/')}/healthz"
    print(f"[*] Checking AgentKit at {health_url}...")

    req = urllib.request.Request(health_url)
    if args.token:
        req.add_header("Authorization", f"Bearer {args.token}")

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode('utf-8')
            print(f"[+] Status: {resp.status} OK")
            print(f"[+] Response:\n{data}")
    except urllib.error.HTTPError as e:
        print(f"[-] HTTP Error {e.code}: {e.read().decode('utf-8', errors='ignore')}")
        sys.exit(1)
    except Exception as e:
        print(f"[-] Connection failed: {e}")
        print("[-] Ensure VM is running and port 8765 is forwarded to host.")
        sys.exit(1)

if __name__ == "__main__":
    main()
