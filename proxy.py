#!/usr/bin/env python3
"""
Cursor-GCP Connector Proxy

A proxy that transforms Cursor IDE requests to be compatible with Claude on Vertex AI
via LiteLLM. It handles incompatibilities between Cursor's OpenAI-compatible requests
and Vertex AI's Claude API.

Key transformations:
- Removes unsupported beta features (cache_control, thinking, etc.)
- Filters orphaned tool_result messages
- Removes problematic headers
"""

import json
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.error

# Configure logging
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
LITELLM_URL = os.environ.get('LITELLM_URL', 'http://localhost:4000')
PROXY_PORT = int(os.environ.get('PROXY_PORT', '4001'))

class ProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # Read request body
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            
            # Parse JSON
            data = json.loads(body) if body else {}
            
            logger.debug(f"Incoming request to {self.path}")
            
            # Remove tool_choice (not supported properly by Vertex AI)
            if "tool_choice" in data:
                logger.info(f"Removing tool_choice: {data['tool_choice']}")
                del data["tool_choice"]
            
            # Remove beta features not supported by Vertex AI
            if "system" in data:
                self._remove_cache_control(data["system"], "system")
            
            # Remove metadata (beta feature)
            if "metadata" in data:
                logger.info("Removing metadata")
                del data["metadata"]
            
            # Remove stream_options
            if "stream_options" in data:
                logger.info("Removing stream_options")
                del data["stream_options"]
            
            # Remove parameters that trigger beta headers
            beta_params = ["thinking", "reasoning_effort", "extended_thinking", "budget_tokens"]
            for param in beta_params:
                if param in data:
                    logger.info(f"Removing beta param: {param}")
                    del data[param]
            
            # Fix messages
            if "messages" in data:
                data["messages"] = self._fix_messages(data["messages"])
            
            # Forward to LiteLLM
            modified_body = json.dumps(data).encode('utf-8')
            
            req = urllib.request.Request(
                f"{LITELLM_URL}{self.path}",
                data=modified_body,
                method='POST'
            )
            
            # Copy headers but filter problematic ones
            blocked_headers = ['host', 'content-length', 'anthropic-beta', 'x-anthropic-beta']
            for key, value in self.headers.items():
                if key.lower() not in blocked_headers:
                    req.add_header(key, value)
            req.add_header('Content-Type', 'application/json')
            
            # Make request to LiteLLM
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
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
                logger.error(f"LiteLLM error: {error_body.decode()}")
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(error_body))
                self.end_headers()
                self.wfile.write(error_body)
                
        except Exception as e:
            logger.exception(f"Proxy error: {e}")
            error_response = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(error_response))
            self.end_headers()
            self.wfile.write(error_response)
    
    def _remove_cache_control(self, obj, location):
        """Recursively remove cache_control from objects"""
        if isinstance(obj, list):
            for item in obj:
                self._remove_cache_control(item, location)
        elif isinstance(obj, dict):
            if "cache_control" in obj:
                logger.info(f"Removing cache_control from {location}")
                del obj["cache_control"]
    
    def _fix_messages(self, messages):
        """Fix message format for Vertex AI compatibility.
        
        Key transformations:
        1. Remove ALL tool_result blocks from user messages (they're conversation history)
        2. Remove cache_control from all content
        3. Convert tool_use in assistant messages to tool_calls format
        """
        fixed_messages = []
        
        for i, msg in enumerate(messages):
            role = msg.get("role", "")
            content = msg.get("content")
            
            if isinstance(content, list):
                new_content = []
                
                for item in content:
                    if isinstance(item, dict):
                        # Remove cache_control
                        if "cache_control" in item:
                            logger.info("Removing cache_control from content")
                            item = {k: v for k, v in item.items() if k != "cache_control"}
                        
                        item_type = item.get("type", "")
                        
                        # REMOVE tool_result from user messages entirely
                        if item_type == "tool_result":
                            logger.info(f"Removing tool_result from message (tool_use_id: {item.get('tool_use_id', 'unknown')})")
                            continue
                        
                        # Keep tool_use in assistant messages but also create tool_calls
                        if item_type == "tool_use" and role == "assistant":
                            # LiteLLM expects tool_calls format, keep tool_use too for compatibility
                            new_content.append(item)
                        else:
                            new_content.append(item)
                    else:
                        new_content.append(item)
                
                # Only add message if it has content
                if new_content:
                    msg = dict(msg)  # Copy to avoid mutation
                    msg["content"] = new_content
                    fixed_messages.append(msg)
                elif role == "assistant" and "tool_calls" in msg:
                    # Keep assistant messages with tool_calls even if content is empty
                    fixed_messages.append(msg)
            else:
                fixed_messages.append(msg)
        
        logger.info(f"Processed {len(messages)} messages -> {len(fixed_messages)} messages")
        return fixed_messages
    
    def do_GET(self):
        if self.path == '/health':
            response = json.dumps({
                "status": "healthy",
                "proxy": "cursor-gcp-connector",
                "litellm_url": LITELLM_URL
            }).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(response))
            self.end_headers()
            self.wfile.write(response)
        else:
            # Forward GET requests
            try:
                req = urllib.request.Request(f"{LITELLM_URL}{self.path}")
                for key, value in self.headers.items():
                    if key.lower() not in ['host']:
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
                logger.error(f"GET request error: {e}")
                self.send_response(500)
                self.end_headers()

    def log_message(self, format, *args):
        logger.debug(f"HTTP: {args}")


def main():
    server = HTTPServer(('0.0.0.0', PROXY_PORT), ProxyHandler)
    logger.info(f"Starting Cursor-GCP Connector on port {PROXY_PORT}")
    logger.info(f"Forwarding to LiteLLM at {LITELLM_URL}")
    server.serve_forever()


if __name__ == "__main__":
    main()

