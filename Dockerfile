# Use stable Python release (compatible with langchain-mcp-adapters)
FROM python:3.12-slim

# Install Node.js + npm so we can run npx for MCP server
RUN apt-get update && \
    apt-get install -y nodejs npm && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Render-managed port
ENV PORT=8000
EXPOSE 8000

# Start FastAPI app
CMD ["sh", "-c", "uvicorn github_mcp:app --host 0.0.0.0 --port ${PORT}"]
