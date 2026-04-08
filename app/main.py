#!/usr/bin/env python3
"""
Global Drone Simulator - Main Application
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import threading
import time
import json
import logging
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from drone_simulator import DroneSimulator, telemetry_store, telemetry_lock

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key')
socketio = SocketIO(app, cors_allowed_origins="*", logger=False, engineio_logger=False)

simulation_threads = []
stop_events = []
simulation_lock = threading.Lock()

START_PORT = int(os.environ.get('START_PORT', 15001))
DEFAULT_HOST = '127.0.0.1'
UPDATE_INTERVAL = 0.5

def load_countries():
    countries_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'countries.json')
    
    if not os.path.exists(countries_path):
        logger.error(f"Countries file not found: {countries_path}")
        return []
    
    with open(countries_path, 'r', encoding='utf-8') as f:
        countries = json.load(f)
        logger.info(f"Loaded {len(countries)} countries")
        return countries

COUNTRIES = load_countries()

def broadcast_telemetry():
    """Background thread to broadcast telemetry data to all clients"""
    while True:
        try:
            with telemetry_lock:
                if telemetry_store:
                    # Create a copy to avoid modification during iteration
                    telemetry_copy = dict(telemetry_store)
                    socketio.emit('telemetry_update', telemetry_copy)
            time.sleep(0.3)  # Broadcast every 300ms
        except Exception as e:
            logger.error(f"Broadcast error: {e}")
            time.sleep(1)

@app.route('/')
def index():
    return render_template('index.html', total_countries=len(COUNTRIES))

@app.route('/api/countries')
def get_countries():
    return jsonify(COUNTRIES)

@app.route('/api/start', methods=['POST'])
def start_simulation():
    global simulation_threads, stop_events
    
    try:
        data = request.get_json() or {}
        host = data.get('host', DEFAULT_HOST)
        ports = data.get('ports', [])
        
        if not ports and COUNTRIES:
            ports = [START_PORT + i for i in range(min(len(COUNTRIES), 100))]
        
        logger.info(f"Starting simulation for {len(ports)} drones on {host}")
        
        # Stop existing simulation
        stop_simulation()
        
        with simulation_lock:
            simulation_threads = []
            stop_events = []
        
        # Clear telemetry store
        with telemetry_lock:
            telemetry_store.clear()
        
        # Define callback to update telemetry
        def telemetry_callback(port, data):
            with telemetry_lock:
                telemetry_store[port] = data
        
        # Start drones
        for idx, port in enumerate(ports):
            port_index = port - START_PORT
            if port_index < 0 or port_index >= len(COUNTRIES):
                continue
                
            country = COUNTRIES[port_index]
            
            drone = DroneSimulator(
                drone_id=port_index + 1,
                port=port,
                host=host,
                country_data=country,
                update_interval=UPDATE_INTERVAL,
                telemetry_callback=telemetry_callback
            )
            
            stop_event = threading.Event()
            thread = threading.Thread(
                target=drone.run, 
                args=(stop_event,),
                daemon=True,
                name=f"Drone-{country['country']}"
            )
            
            simulation_threads.append((thread, stop_event))
            thread.start()
            time.sleep(0.01)
        
        logger.info(f"Started {len(simulation_threads)} drone simulators")
        
        return jsonify({
            'status': 'started',
            'num_drones': len(simulation_threads),
            'host': host,
            'ports': ports
        })
        
    except Exception as e:
        logger.error(f"Error starting simulation: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_simulation():
    global simulation_threads, stop_events
    
    logger.info("Stopping all simulators...")
    
    try:
        # Signal all threads to stop
        for thread, stop_event in simulation_threads:
            stop_event.set()
        
        # Wait for threads to finish
        for thread, stop_event in simulation_threads:
            thread.join(timeout=2.0)
        
        with simulation_lock:
            simulation_threads = []
            stop_events = []
        
        # Clear telemetry store
        with telemetry_lock:
            telemetry_store.clear()
        
        # Broadcast empty telemetry
        socketio.emit('telemetry_update', {})
        
        logger.info("All simulators stopped")
        
        return jsonify({'status': 'stopped', 'message': 'All simulators stopped'})
        
    except Exception as e:
        logger.error(f"Error stopping simulation: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/status')
def get_status():
    with telemetry_lock:
        return jsonify({
            'running': len(simulation_threads) > 0,
            'num_drones': len(telemetry_store),
            'total_countries': len(COUNTRIES)
        })

@app.route('/api/telemetry')
def get_telemetry():
    with telemetry_lock:
        return jsonify(dict(telemetry_store))

@socketio.on('connect')
def handle_connect():
    logger.info(f"Client connected: {request.sid}")
    # Send current telemetry immediately
    with telemetry_lock:
        if telemetry_store:
            socketio.emit('telemetry_update', dict(telemetry_store), to=request.sid)

@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"Client disconnected: {request.sid}")

if __name__ == '__main__':
    port = int(os.environ.get('FLASK_PORT', 5000))
    logger.info("=" * 50)
    logger.info("Global Drone Simulator v1.0.0")
    logger.info(f"Total Countries: {len(COUNTRIES)}")
    logger.info(f"Starting Port: {START_PORT}")
    logger.info(f"Web Interface: http://0.0.0.0:{port}")
    logger.info("=" * 50)
    
    # Start telemetry broadcast thread
    broadcast_thread = threading.Thread(target=broadcast_telemetry, daemon=True)
    broadcast_thread.start()
    
    # Run Flask app
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
