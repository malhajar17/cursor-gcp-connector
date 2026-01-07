#!/usr/bin/env python3
"""
Cursor GCP Connector - Compatibility Proxy

This proxy sits between Cursor IDE and LiteLLM, fixing compatibility issues
between Cursor's OpenAI-style requests and Vertex AI's Claude API.

Key fixes:
1. Removes `cache_control` from messages (Vertex AI beta feature not supported)
2. Removes orphaned `tool_result` blocks (Cursor sends conversation history)
3. Removes `tool_choice` parameter (format incompatible with Vertex AI)
4. Filters `Anthropic-Beta` headers
5. Removes thinking/reasoning parameters that trigger beta features

Usage:
    python proxy.py [--port PORT] [--litellm-url URL] [--log-file PATH]

Environment Variables:
    PROXY_PORT          - Port to listen on (default: 4001)
    LITELLM_URL         - LiteLLM backend URL (default: http://localhost:4000)
    PROXY_LOG_FILE      - Log file path (default: /tmp/cursor-proxy.log)
    PROXY_DEBUG         - Enable debug logging (default: false)
"""

import json
import logging
import os
import sys
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.error
from datetime import datetime

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_PORT = 4001
DEFAULT_LITELLM_URL = "http://localhost:4000"
DEFAULT_LOG_FILE = "/tmp/cursor-proxy.log"

# Parameters to remove from requests (incompatible with Vertex AI)
BLOCKED_PARAMS = [
    "tool_choice",
    "thinking", 
    "reasoning_effort",
    "extended_thinking",
    "budget_tokens",
    "metadata",
    "stream_options",
]

# Headers to filter out
BLOCKED_HEADERS = [
    "host",
    "content-length", 
    "anthropic-beta",
]

# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging(log_file: str, debug: bool = False) -> logging.Logger:
    """Configure logging with file and console handlers."""
    logger = logging.getLogger("cursor-proxy")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    
    # File handler
    file_handler = logging.FileHandler(log_file, mode='a')
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(file_handler)
    
    # Console handler (for systemd/docker logs)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(console_handler)
    
    return logger

# =============================================================================
# Request Processing
# =============================================================================

def remove_cache_control(obj):
    """Recursively remove cache_control from any nested structure."""
    if isinstance(obj, dict):
        # Remove cache_control key if present
        obj.pop("cache_control", None)
        # Recurse into values
        for value in obj.values():
            remove_cache_control(value)
    elif isinstance(obj, list):
        for item in obj:
            remove_cache_control(item)
    return obj


def clean_messages(messages: list, logger: logging.Logger) -> list:
    """
    Clean messages to be compatible with Vertex AI Claude.
    
    Main issue: Cursor sends conversation history with `tool_result` blocks
    embedded in user messages, but Vertex AI requires tool_result to immediately
    follow the assistant's tool_use message. Solution: remove tool_result blocks.
    """
    cleaned = []
    
    for msg in messages:
        if not isinstance(msg, dict):
            cleaned.append(msg)
            continue
            
        content = msg.get("content")
        
        if isinstance(content, list):
            # Filter out tool_result blocks from content array
            new_content = []
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type", "")
                    
                    # Skip tool_result blocks entirely
                    if item_type == "tool_result":
                        logger.debug(f"Removing tool_result block: {item.get('tool_use_id', 'unknown')}")
                        continue
                    
                    # Remove cache_control from item
                    remove_cache_control(item)
                    new_content.append(item)
                else:
                    new_content.append(item)
            
            # Only add message if it has content left
            if new_content:
                msg["content"] = new_content
                cleaned.append(msg)
            else:
                logger.debug(f"Dropping empty message after cleaning")
        else:
            # Simple string content - keep as is
            cleaned.append(msg)
    
    return cleaned


def process_request_body(data: dict, logger: logging.Logger) -> dict:
    """
    Process and clean the request body for Vertex AI compatibility.
    
    Returns the modified request data.
    """
    # Remove blocked parameters
    for param in BLOCKED_PARAMS:
        if param in data:
            logger.info(f"Removing parameter: {param}")
            del data[param]
    
    # Remove cache_control from system messages
    if "system" in data:
        remove_cache_control(data["system"])
    
    # Clean messages
    if "messages" in data:
        original_count = len(data["messages"])
        data["messages"] = clean_messages(data["messages"], logger)
        new_count = len(data["messages"])
        if original_count != new_count:
            logger.info(f"Cleaned messages: {original_count} -> {new_count}")
    
    return data

# =============================================================================
# HTTP Handler
# =============================================================================

class ProxyHandler(BaseHTTPRequestHandler):
    """HTTP request handler that proxies to LiteLLM with fixes."""
    
    # Class-level config (set before server starts)
    litellm_url = DEFAULT_LITELLM_URL
    logger = None
    debug = False
    
    def do_POST(self):
        """Handle POST requests (chat completions)."""
        try:
            # Read request body
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            
            # Parse JSON
            data = json.loads(body) if body else {}
            
            if self.debug:
                self.logger.debug(f"Incoming request: {json.dumps(data, indent=2)[:2000]}")
            
            # Process and clean the request
            data = process_request_body(data, self.logger)
            
            # Forward to LiteLLM
            modified_body = json.dumps(data).encode('utf-8')
            
            req = urllib.request.Request(
                f"{self.litellm_url}{self.path}",
                data=modified_body,
                method='POST'
            )
            
            # Copy headers, filtering blocked ones
            for key, value in self.headers.items():
                if key.lower() not in BLOCKED_HEADERS:
                    req.add_header(key, value)
            req.add_header('Content-Type', 'application/json')
            
            # Make request to LiteLLM
            try:
                with urllib.request.urlopen(req, timeout=300) as response:
                    response_body = response.read()
                    
                    self.send_response(response.status)
                    for key, value in response.getheaders():
                        if key.lower() not in ['transfer-encoding', 'content-encoding']:
                            self.send_header(key, value)
                    self.send_header('Content-Length', len(response_body))
                    self.end_headers()
                    self.wfile.write(response_body)
                    
            except urllib.error.HTTPError as e:
                error_body = e.read()
                self.logger.error(f"LiteLLM error ({e.code}): {error_body[:500]}")
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(error_body))
                self.end_headers()
                self.wfile.write(error_body)
                
        except Exception as e:
            self.logger.exception(f"Proxy error: {e}")
            error_response = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(error_response))
            self.end_headers()
            self.wfile.write(error_response)
    
    def do_GET(self):
        """Handle GET requests (health check, models list)."""
        if self.path == '/health':
            response = json.dumps({
                "status": "healthy",
                "service": "cursor-gcp-connector",
                "timestamp": datetime.utcnow().isoformat()
            }).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(response))
            self.end_headers()
            self.wfile.write(response)
        else:
            # Forward GET requests to LiteLLM
            try:
                req = urllib.request.Request(f"{self.litellm_url}{self.path}")
                for key, value in self.headers.items():
                    if key.lower() not in BLOCKED_HEADERS:
                        req.add_header(key, value)
                
                with urllib.request.urlopen(req, timeout=30) as response:
                    response_body = response.read()
                    self.send_response(response.status)
                    for key, value in response.getheaders():
                        if key.lower() not in ['transfer-encoding']:
                            self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(response_body)
            except Exception as e:
                self.logger.error(f"GET error: {e}")
                self.send_response(500)
                self.end_headers()
    
    def log_message(self, format, *args):
        """Override to use our logger."""
        if self.logger:
            self.logger.debug(f"HTTP: {args[0]}")

# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Cursor GCP Connector - Compatibility proxy for Vertex AI Claude"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=int(os.environ.get("PROXY_PORT", DEFAULT_PORT)),
        help=f"Port to listen on (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--litellm-url", "-u",
        default=os.environ.get("LITELLM_URL", DEFAULT_LITELLM_URL),
        help=f"LiteLLM backend URL (default: {DEFAULT_LITELLM_URL})"
    )
    parser.add_argument(
        "--log-file", "-l",
        default=os.environ.get("PROXY_LOG_FILE", DEFAULT_LOG_FILE),
        help=f"Log file path (default: {DEFAULT_LOG_FILE})"
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        default=os.environ.get("PROXY_DEBUG", "").lower() in ("true", "1", "yes"),
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.log_file, args.debug)
    
    # Configure handler
    ProxyHandler.litellm_url = args.litellm_url
    ProxyHandler.logger = logger
    ProxyHandler.debug = args.debug
    
    # Start server
    server = HTTPServer(('0.0.0.0', args.port), ProxyHandler)
    
    logger.info("=" * 60)
    logger.info("Cursor GCP Connector starting")
    logger.info(f"  Listening on: http://0.0.0.0:{args.port}")
    logger.info(f"  Forwarding to: {args.litellm_url}")
    logger.info(f"  Log file: {args.log_file}")
    logger.info(f"  Debug mode: {args.debug}")
    logger.info("=" * 60)
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           Cursor GCP Connector - Running                     ║
╠══════════════════════════════════════════════════════════════╣
║  Proxy URL:    http://localhost:{args.port:<25}       ║
║  LiteLLM URL:  {args.litellm_url:<43} ║
║  Health check: http://localhost:{args.port}/health{' ' * 19}║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
