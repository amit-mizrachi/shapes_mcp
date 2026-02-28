# `Dockerfile` -- MCP Server Container Image

## Overview

Single-stage Dockerfile that packages the `mcp-server` Python application into a lightweight container. It installs Python dependencies, copies the shared library and server source code, creates a non-root user for runtime security, and exposes the MCP server on port 3001.

**Location:** `mcp-server/Dockerfile`

## Base Image

| Property | Value |
|----------|-------|
| Image | `python:3.12-slim` |
| Description | Minimal Debian-based Python 3.12 image with a reduced footprint compared to the full `python:3.12` image. |

## Build Steps

### 1. Create a non-root application user

```dockerfile
RUN groupadd -r appuser && useradd -r -g appuser appuser
```

Creates a system group and user named `appuser`. The container process runs as this user instead of root, following the principle of least privilege.

### 2. Set the working directory

```dockerfile
WORKDIR /app
```

All subsequent `COPY` and `RUN` instructions operate relative to `/app`.

### 3. Install Python dependencies

```dockerfile
COPY mcp-server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

Copies `requirements.txt` first and installs dependencies in a separate layer. This leverages Docker layer caching so dependencies are only reinstalled when the requirements file changes. The `--no-cache-dir` flag keeps the image size small by skipping pip's download cache.

**Dependencies installed:**

| Package | Version | Purpose |
|---------|---------|---------|
| `mcp[cli]` | 1.20.0 | MCP (Model Context Protocol) server framework with CLI extras |
| `aiosqlite` | 0.20.0 | Async SQLite driver for Python |

### 4. Copy application source code

```dockerfile
COPY shared/ ./shared/
COPY mcp-server/src/ ./mcp-server/src/
```

Copies two directories into the image:

- `shared/` -- Shared library modules used across the project (data store, ingestion, parsing).
- `mcp-server/src/` -- The MCP server source code, including the main entry point.

### 5. Prepare the data directory

```dockerfile
RUN mkdir -p /app/db && chown -R appuser:appuser /app
```

Creates a `/app/db` directory for SQLite database files at runtime and grants ownership of the entire `/app` tree to `appuser`.

### 6. Switch to non-root user

```dockerfile
USER appuser
```

All subsequent instructions and the container's runtime process execute as `appuser`.

## Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `PYTHONPATH` | `/app` | Allows Python to resolve imports from the project root, so both `shared` and `mcp-server` packages are importable. |

## Exposed Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 3001 | TCP | MCP server listening port |

## Entry Point / CMD

```dockerfile
CMD ["python", "/app/mcp-server/src/server.py"]
```

Starts the MCP server by running `server.py` directly with the Python interpreter. Uses the exec form (JSON array) so the Python process receives signals (SIGTERM, SIGINT) directly, enabling graceful shutdown.

## Build Args

This Dockerfile does not define any `ARG` instructions.

## Usage

The Dockerfile expects to be built from the **project root** (not from `mcp-server/`), because the `COPY` instructions reference `shared/` and `mcp-server/` as sibling directories.

**Build the image:**

```bash
docker build -f mcp-server/Dockerfile -t shapes-mcp-server .
```

**Run the container:**

```bash
docker run -p 3001:3001 shapes-mcp-server
```

**Run with a persistent database volume:**

```bash
docker run -p 3001:3001 -v shapes_db:/app/db shapes-mcp-server
```
