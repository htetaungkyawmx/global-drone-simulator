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
DEFAULT_HOST = os.environ.get('DRONE_HOST', '127.0.0.1')
UPDATE_INTERVAL = float(os.environ.get('UPDATE_INTERVAL', 0.5))

# Optional: comma-separated list of "start-end" or single ports, e.g.
#   PORT_RANGES=15001-15035,15091-15100
# If set, the simulation auto-starts for these ports as soon as the
# container boots -- no need to call /api/start manually.
PORT_RANGES = os.environ.get('PORT_RANGES', '')


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


def parse_port_ranges(spec):
    """Parse a string like '15001-15035,15091-15100' into a sorted list of ints.

    Also accepts single ports, e.g. '15001-15035,15200'.
    Invalid or empty input returns an empty list rather than raising, so a
    bad env var never crashes the app on boot.
    """
    ports = []
    if not spec:
        return ports

    for chunk in spec.split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            if '-' in chunk:
                start_s, end_s = chunk.split('-', 1)
                start, end = int(start_s.strip()), int(end_s.strip())
                if start > end:
                    start, end = end, start
                ports.extend(range(start, end + 1))
            else:
                ports.append(int(chunk))
        except ValueError:
            logger.warning(f"Ignoring invalid PORT_RANGES chunk: '{chunk}'")

    # De-duplicate while preserving order
    seen = set()
    unique_ports = []
    for p in ports:
        if p not in seen:
            seen.add(p)
            unique_ports.append(p)
    return unique_ports


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


def _stop_all_locked():
    """Stop every running drone thread. Caller does not need to hold simulation_lock."""
    global simulation_threads, stop_events

    for thread, stop_event in simulation_threads:
        stop_event.set()

    for thread, stop_event in simulation_threads:
        thread.join(timeout=2.0)

    with simulation_lock:
        simulation_threads = []
        stop_events = []

    with telemetry_lock:
        telemetry_store.clear()

    socketio.emit('telemetry_update', {})


def start_drones(ports, host):
    """Core logic to (re)start the simulation for a given list of ports.

    Shared by the /api/start HTTP route and the auto-start-on-boot path so
    behavior is identical whether triggered by a request or by PORT_RANGES.

    Country indexing uses modulo so that ports beyond len(COUNTRIES) still
    get a valid (reused) country instead of being silently skipped -- this
    matters if countries.json has fewer than 100 entries but you still want
    to spin up drones on ports like 15091-15100.
    """
    global simulation_threads, stop_events

    if not COUNTRIES:
        raise RuntimeError("No countries loaded; cannot start simulation")

    logger.info(f"Starting simulation for {len(ports)} drones on {host}")

    # Stop any existing simulation first
    _stop_all_locked()

    def telemetry_callback(port, data):
        with telemetry_lock:
            telemetry_store[port] = data

    new_threads = []
    started_ports = []

    for port in ports:
        port_index = port - START_PORT
        if port_index < 0:
            logger.warning(f"Skipping port {port}: below START_PORT ({START_PORT})")
            continue

        # Reuse countries cyclically instead of dropping ports that fall
        # outside len(COUNTRIES) -- this is what made 15091-15100 vanish
        # before when countries.json had under 100 entries.
        country = COUNTRIES[port_index % len(COUNTRIES)]

        drone = DroneSimulator(
            drone_id=port_index + 1,
            port=port,
            host=host,
            country_data=country,
            update_interval=UPDATE_INTERVAL,
            telemetry_callback=telemetry_callback,
            base_port=START_PORT
        )

        stop_event = threading.Event()
        thread = threading.Thread(
            target=drone.run,
            args=(stop_event,),
            daemon=True,
            name=f"Drone-{country['country']}-{port}"
        )

        new_threads.append((thread, stop_event))
        thread.start()
        started_ports.append(port)
        time.sleep(0.01)

    with simulation_lock:
        simulation_threads = new_threads
        stop_events = [se for _, se in new_threads]

    logger.info(f"Started {len(simulation_threads)} drone simulators")

    return {
        'status': 'started',
        'num_drones': len(simulation_threads),
        'host': host,
        'ports': started_ports
    }


@app.route('/')
def index():
    return render_template('index.html', total_countries=len(COUNTRIES))


@app.route('/api/countries')
def get_countries():
    return jsonify(COUNTRIES)


@app.route('/api/start', methods=['POST'])
def start_simulation():
    try:
        data = request.get_json(silent=True) or {}
        host = data.get('host', DEFAULT_HOST)
        ports = data.get('ports', [])

        if not ports and COUNTRIES:
            ports = [START_PORT + i for i in range(min(len(COUNTRIES), 100))]

        result = start_drones(ports, host)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error starting simulation: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/stop', methods=['POST'])
def stop_simulation():
    logger.info("Stopping all simulators...")
    try:
        _stop_all_locked()
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

    # Auto-start the simulation on boot if PORT_RANGES is set, so opening
    # the browser right after `docker compose up` shows drones immediately
    # without needing a manual POST to /api/start.
    auto_ports = parse_port_ranges(PORT_RANGES)
    if auto_ports and COUNTRIES:
        logger.info(f"PORT_RANGES set -- auto-starting {len(auto_ports)} drones: "
                     f"{auto_ports[0]}..{auto_ports[-1]}")

        def _delayed_autostart():
            # Small delay so the Flask/SocketIO server is fully up before
            # the first telemetry broadcasts go out.
            time.sleep(1.0)
            try:
                start_drones(auto_ports, DEFAULT_HOST)
            except Exception as e:
                logger.error(f"Auto-start failed: {e}")

        threading.Thread(target=_delayed_autostart, daemon=True).start()
    elif PORT_RANGES and not COUNTRIES:
        logger.error("PORT_RANGES set but no countries loaded -- skipping auto-start")

    # Run Flask app
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)