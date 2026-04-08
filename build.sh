#!/bin/bash

echo "========================================="
echo "🌍 Global Drone Simulator Build Script"
echo "========================================="

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed. Please install Docker first.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Docker found${NC}"

# Build the Docker image for AMD64 (for Apple Silicon compatibility)
echo -e "${YELLOW}🔨 Building Docker image for AMD64 architecture...${NC}"
docker build --platform linux/amd64 -t global-drone-simulator:latest .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Build successful!${NC}"
else
    echo -e "${RED}❌ Build failed!${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================="
echo "🎉 Build Complete!"
echo "=========================================${NC}"
echo ""
echo "To run the simulator:"
echo "  docker-compose up -d"
echo ""
echo "To view logs:"
echo "  docker-compose logs -f"
echo ""
echo "To stop:"
echo "  docker-compose down"
echo ""
echo "Access the web interface:"
echo "  http://localhost:5002"
echo "========================================="