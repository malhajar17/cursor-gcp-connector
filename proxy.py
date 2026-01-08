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


def extract_tool_use_ids(message: dict) -> set:
    """Extract all tool_use IDs from an assistant message (either format)."""
    tool_ids = set()
    
    # Check Anthropic format: content array with tool_use items
    content = message.get("content", [])
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                tool_id = item.get("id")
                if tool_id:
                    tool_ids.add(tool_id)
    
    # Check OpenAI format: tool_calls array
    tool_calls = message.get("tool_calls", [])
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if isinstance(tc, dict):
                tool_id = tc.get("id")
                if tool_id:
                    tool_ids.add(tool_id)
    
    return tool_ids


def convert_tool_use_to_openai(tool_use: dict) -> dict:
    """
    Convert Anthropic-style tool_use to OpenAI-style tool_call.
    
    Anthropic: {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
    OpenAI:    {"id": "...", "type": "function", "function": {"name": "...", "arguments": "..."}}
    """
    input_data = tool_use.get("input", {})
    if isinstance(input_data, dict):
        arguments = json.dumps(input_data)
    else:
        arguments = str(input_data)
    
    return {
        "id": tool_use.get("id", ""),
        "type": "function",
        "function": {
            "name": tool_use.get("name", ""),
            "arguments": arguments
        }
    }


def convert_tool_result_to_openai(tool_result: dict) -> dict:
    """
    Convert Anthropic-style tool_result to OpenAI-style tool message.
    
    Anthropic: {"type": "tool_result", "tool_use_id": "...", "content": "..."}
    OpenAI:    {"role": "tool", "tool_call_id": "...", "content": "..."}
    """
    content = tool_result.get("content", "")
    
    # Handle nested content (can be string or list of text blocks)
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif isinstance(item, str):
                text_parts.append(item)
        content = "\n".join(text_parts)
    
    return {
        "role": "tool",
        "tool_call_id": tool_result.get("tool_use_id", ""),
        "content": str(content)
    }


def convert_image_to_openai(item: dict) -> dict:
    """
    Convert Anthropic-style image to OpenAI-style image_url.
    
    Anthropic: {"type": "image", "source": {"type": "base64", "media_type": "...", "data": "..."}}
    OpenAI:    {"type": "image_url", "image_url": {"url": "data:...;base64,..."}}
    
    Also handles URL-based images:
    Anthropic: {"type": "image", "source": {"type": "url", "url": "..."}}
    OpenAI:    {"type": "image_url", "image_url": {"url": "..."}}
    """
    source = item.get("source", {})
    source_type = source.get("type", "")
    
    if source_type == "base64":
        media_type = source.get("media_type", "image/png")
        data = source.get("data", "")
        url = f"data:{media_type};base64,{data}"
        return {
            "type": "image_url",
            "image_url": {"url": url}
        }
    elif source_type == "url":
        return {
            "type": "image_url",
            "image_url": {"url": source.get("url", "")}
        }
    else:
        # Unknown format, try to pass through with type change
        return {
            "type": "image_url",
            "image_url": {"url": item.get("url", source.get("url", ""))}
        }


def clean_messages(messages: list, logger: logging.Logger) -> list:
    """
    Clean messages to be compatible with LiteLLM and Vertex AI Claude.
    
    Key transformations:
    1. Convert Anthropic-style tool_result to OpenAI-style role: "tool" messages
    2. Only keep tool_result blocks that match a tool_use in the preceding assistant message
    3. Remove orphaned tool_result blocks (historical ones without matching tool_use)
    4. Remove cache_control from all content
    
    This preserves the tool calling flow while removing problematic history.
    """
    cleaned = []
    pending_tool_ids = set()  # Tool IDs from the most recent assistant message
    
    for msg in messages:
        if not isinstance(msg, dict):
            cleaned.append(msg)
            continue
        
        role = msg.get("role", "")
        content = msg.get("content")
        
        # If this is an assistant message, extract tool_use IDs and convert to OpenAI format
        if role == "assistant":
            pending_tool_ids = extract_tool_use_ids(msg)
            
            # Convert Anthropic-style tool_use in content to OpenAI-style tool_calls
            if isinstance(content, list):
                tool_calls = []
                other_content = []
                
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "tool_use":
                            tool_calls.append(convert_tool_use_to_openai(item))
                        else:
                            remove_cache_control(item)
                            other_content.append(item)
                    else:
                        other_content.append(item)
                
                # If we found tool_use blocks, convert to OpenAI format
                if tool_calls:
                    logger.debug(f"Converting {len(tool_calls)} tool_use to OpenAI tool_calls format")
                    msg["tool_calls"] = tool_calls
                    # OpenAI format: content can be null or text when there are tool_calls
                    if other_content:
                        # Extract text content if any
                        text_parts = [item.get("text", "") for item in other_content 
                                     if isinstance(item, dict) and item.get("type") == "text"]
                        msg["content"] = " ".join(text_parts) if text_parts else None
                    else:
                        msg["content"] = None
                else:
                    msg["content"] = other_content if other_content else content
            
            if pending_tool_ids:
                logger.debug(f"Assistant made tool calls: {pending_tool_ids}")
            
            cleaned.append(msg)
            continue
        
        # For user messages, handle tool_result blocks and images
        if role == "user" and isinstance(content, list):
            new_content = []
            tool_messages = []  # Collect tool results to add as separate messages
            removed_results = 0
            converted_images = 0
            
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type", "")
                    
                    if item_type == "tool_result":
                        tool_use_id = item.get("tool_use_id", "")
                        
                        # Keep if it matches a pending tool_use from the previous assistant message
                        if tool_use_id in pending_tool_ids:
                            logger.debug(f"Converting tool_result to OpenAI format: {tool_use_id}")
                            tool_messages.append(convert_tool_result_to_openai(item))
                        else:
                            # Orphaned tool_result - remove it
                            logger.debug(f"Removing orphaned tool_result: {tool_use_id}")
                            removed_results += 1
                    elif item_type == "image":
                        # Convert Anthropic-style image to OpenAI-style image_url
                        logger.debug("Converting image to OpenAI image_url format")
                        new_content.append(convert_image_to_openai(item))
                        converted_images += 1
                    else:
                        # Non-tool_result content - keep it
                        remove_cache_control(item)
                        new_content.append(item)
                else:
                    new_content.append(item)
            
            if converted_images > 0:
                logger.info(f"Converted {converted_images} images to OpenAI format")
            
            if tool_messages or removed_results > 0:
                logger.info(f"Tool results: converted {len(tool_messages)}, removed {removed_results} orphaned")
            
            # Clear pending tool IDs after processing user message
            pending_tool_ids = set()
            
            # Add the user message if it has non-tool content
            if new_content:
                msg["content"] = new_content
                cleaned.append(msg)
            
            # Add converted tool messages as separate OpenAI-style messages
            for tool_msg in tool_messages:
                cleaned.append(tool_msg)
                
        else:
            # Simple string content or other role - keep as is
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        remove_cache_control(item)
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
            
            # Log the modified messages for debugging
            if self.debug and "messages" in data:
                self.logger.debug(f"Modified messages being sent to LiteLLM:")
                for i, msg in enumerate(data["messages"]):
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        content_preview = content[:100]
                    else:
                        content_preview = json.dumps(content)[:200]
                    self.logger.debug(f"  [{i}] {role}: {content_preview}")
            
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
