# 🌍 Global Drone Simulator

## 📋 Features

- 🚁 **195 Drones** - 
- 📡 **MAVLink Protocol** - Real drone protocol ကို simulate လုပ်
- 🌐 **Web Interface** - Real-time telemetry viewing
- 🔄 **Real-time Updates** - Socket.IO နဲ့ live streaming
- 🎯 **Autonomous Flight** - Capital ကနေ random destination 5km
- 📊 **Live Statistics** - Battery, speed, altitude, position

## 🚀 Quick Start

### Using Docker (Recommended)

```bash
# Pull from Docker Hub
docker pull uhtetaungkyaw/global-drone-simulator:latest

# Run with docker-compose
docker-compose up -d

# Or run directly
docker run -d -p 5000:5000 --name drone-simulator uhtetaungkyaw/global-drone-simulator:latest