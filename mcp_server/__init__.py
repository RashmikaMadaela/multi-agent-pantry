"""
mcp_server/__init__.py

Package marker for the MCP (Model Context Protocol) server layer.
The Auditor Agent connects to inventory_server.py via MCPToolset,
discovering available tools at runtime rather than importing them directly.
This decoupling is the key architectural advantage of using MCP.
"""
