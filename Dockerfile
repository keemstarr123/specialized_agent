# Base image with Node (for npx) + Debian so we can add Python
FROM node:20-bullseye

# Install Python and pip
RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Render will set PORT env; default to 8000 for local runs
ENV PORT=8000

# Expose the port for local testing (Render ignores EXPOSE but it's fine)
EXPOSE 8000

# Start FastAPI using uvicorn; MCP server will be spawned via subprocess (npx) from Python
CMD ["sh", "-c", "uvicorn file:app --host 0.0.0.0 --port ${PORT}"]