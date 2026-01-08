#!/usr/bin/env python3
"""
Cursor GCP Connector CLI

Commands:
    start   - Start the proxy and LiteLLM
    test    - Test connectivity to proxy and LiteLLM
    config  - Show current configuration
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


def find_config():
    """Find litellm config file."""
    candidates = [
        Path("litellm-config.yaml"),
        Path("config.yaml"),
        Path.home() / ".cursor-gcp-connector" / "config.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def check_health(url, name):
    """Check health of a service."""
    try:
        req = urllib.request.Request(f"{url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                print(f"  {name}: OK")
                return True
    except Exception as e:
        print(f"  {name}: FAILED - {e}")
    return False


def cmd_start(args):
    """Start proxy and LiteLLM."""
    config_path = args.config or find_config()
    if not config_path or not Path(config_path).exists():
        print(f"Error: Config file not found. Specify with --config")
        return 1

    # Check for credentials
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print("Warning: GOOGLE_APPLICATION_CREDENTIALS not set")

    proxy_port = args.proxy_port
    litellm_port = args.litellm_port

    print(f"Starting Cursor GCP Connector")
    print(f"  Config: {config_path}")
    print(f"  LiteLLM port: {litellm_port}")
    print(f"  Proxy port: {proxy_port}")
    print()

    # Kill existing processes
    subprocess.run(["pkill", "-f", "litellm --config"], capture_output=True)
    subprocess.run(["pkill", "-f", "cursor_gcp_connector"], capture_output=True)
    time.sleep(1)

    if not args.proxy_only:
        # Start LiteLLM
        print("Starting LiteLLM...")
        litellm_cmd = ["litellm", "--config", str(config_path), "--port", str(litellm_port)]
        litellm_log = open("/tmp/litellm.log", "w")
        subprocess.Popen(litellm_cmd, stdout=litellm_log, stderr=litellm_log)

        # Wait for LiteLLM
        print("Waiting for LiteLLM to start", end="", flush=True)
        for _ in range(30):
            try:
                req = urllib.request.Request(f"http://localhost:{litellm_port}/health")
                with urllib.request.urlopen(req, timeout=2):
                    print(" OK")
                    break
            except:
                print(".", end="", flush=True)
                time.sleep(1)
        else:
            print(" FAILED")
            print("Check /tmp/litellm.log for errors")
            return 1

    # Start proxy
    print("Starting proxy...")
    proxy_module = Path(__file__).parent / "proxy.py"
    if not proxy_module.exists():
        # Fall back to repo root
        proxy_module = Path(__file__).parent.parent / "proxy.py"
    
    env = os.environ.copy()
    env["LITELLM_URL"] = f"http://localhost:{litellm_port}"
    env["PROXY_PORT"] = str(proxy_port)
    
    proxy_log = open("/tmp/proxy.log", "w")
    subprocess.Popen([sys.executable, str(proxy_module)], stdout=proxy_log, stderr=proxy_log, env=env)
    
    time.sleep(2)

    # Verify
    print()
    print("Checking services...")
    proxy_ok = check_health(f"http://localhost:{proxy_port}", "Proxy")
    litellm_ok = check_health(f"http://localhost:{litellm_port}", "LiteLLM")

    if proxy_ok and litellm_ok:
        print()
        print("=" * 50)
        print("Cursor GCP Connector is running")
        print("=" * 50)
        print()
        print(f"Proxy endpoint: http://localhost:{proxy_port}")
        print()
        print("Next: Expose via tunnel for Cursor:")
        print(f"  cloudflared tunnel --url http://localhost:{proxy_port}")
        print()
        print("Logs:")
        print("  tail -f /tmp/litellm.log")
        print("  tail -f /tmp/proxy.log")
        return 0
    else:
        print()
        print("Some services failed to start. Check logs.")
        return 1


def cmd_test(args):
    """Test connectivity."""
    print("Testing services...")
    proxy_ok = check_health(f"http://localhost:{args.proxy_port}", "Proxy")
    litellm_ok = check_health(f"http://localhost:{args.litellm_port}", "LiteLLM")
    
    if proxy_ok and litellm_ok:
        print()
        print("All services healthy")
        return 0
    return 1


def cmd_config(args):
    """Show configuration."""
    config_path = args.config or find_config()
    
    print("Configuration")
    print("=" * 40)
    print(f"Config file: {config_path or 'Not found'}")
    print(f"Proxy port: {args.proxy_port}")
    print(f"LiteLLM port: {args.litellm_port}")
    print(f"GOOGLE_APPLICATION_CREDENTIALS: {os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'Not set')}")
    
    if config_path and Path(config_path).exists():
        print()
        print("Config contents:")
        print("-" * 40)
        print(Path(config_path).read_text())


def main():
    parser = argparse.ArgumentParser(
        prog="cursor-gcp-connector",
        description="Bridge Cursor IDE to Vertex AI Claude"
    )
    parser.add_argument("--config", "-c", help="Path to litellm config file")
    parser.add_argument("--proxy-port", type=int, default=4001, help="Proxy port (default: 4001)")
    parser.add_argument("--litellm-port", type=int, default=4000, help="LiteLLM port (default: 4000)")
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # start command
    start_parser = subparsers.add_parser("start", help="Start proxy and LiteLLM")
    start_parser.add_argument("--proxy-only", action="store_true", help="Start only the proxy")
    
    # test command
    subparsers.add_parser("test", help="Test service connectivity")
    
    # config command
    subparsers.add_parser("config", help="Show configuration")
    
    args = parser.parse_args()
    
    if args.command == "start":
        return cmd_start(args)
    elif args.command == "test":
        return cmd_test(args)
    elif args.command == "config":
        return cmd_config(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())



