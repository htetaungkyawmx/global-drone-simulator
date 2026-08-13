#!/usr/bin/env python3
"""
Drone Simulator Class - MAVLink protocol simulator with telemetry storage
"""

import threading
import time
import random
import math
from datetime import datetime
from pymavlink import mavutil
from geopy.distance import geodesic
from geopy.point import Point
import logging

logger = logging.getLogger(__name__)

# Global telemetry storage
telemetry_store = {}
telemetry_lock = threading.Lock()

class DroneSimulator:
    """Drone simulator for MAVLink telemetry"""

    def __init__(self, drone_id, port, host, country_data, update_interval=0.5,
                 telemetry_callback=None, base_port=15000):
        self.drone_id = drone_id
        self.port = port
        self.host = host
        self.country = country_data['country']
        self.capital = country_data['capital']
        self.update_interval = update_interval
        # Use base_port (derived from START_PORT) instead of a hardcoded 15000
        # so system_id stays unique and valid even if START_PORT is changed.
        self.system_id = max(1, min(255, port - base_port + 1))
        self.connection = None
        self.telemetry_callback = telemetry_callback

        # Location setup
        self.source_lat = country_data['lat'] + random.uniform(-0.05, 0.05)
        self.source_lon = country_data['lon'] + random.uniform(-0.05, 0.05)
        self.bearing = random.uniform(0, 360)

        source_point = Point(latitude=self.source_lat, longitude=self.source_lon)
        destination_point = geodesic(meters=5000).destination(source_point, self.bearing)
        self.dest_lat = destination_point.latitude
        self.dest_lon = destination_point.longitude

        # Flight state
        self.current_lat = self.source_lat
        self.current_lon = self.source_lon
        self.current_alt = 0.0
        self.ground_speed = 5.0
        self.vertical_speed = 0.0
        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = self.bearing

        # Battery
        self.battery_voltage = 12.0
        self.battery_current = 0.0
        self.battery_remaining = 100
        self.ch3out = 1000

        # Time tracking
        self.start_time = time.time()
        self.travel_time = 1000
        self.travel_distance = 5000
        self.wp_dist = self.travel_distance
        self.dist_traveled = 0.0
        self.dist_to_home = 0.0

        # Additional telemetry
        self.airspeed = self.ground_speed * 1.2
        self.wind_speed = random.uniform(0.0, 8.0)
        self.gps_hdop = random.uniform(0.8, 2.5)
        self.satellites_visible = random.randint(8, 20)

        # Mission
        self.waypoints = self._generate_waypoints()
        self.mission_count = len(self.waypoints)
        self.flight_mode = "AUTO"
        self.armed = False
        self.ekf_ok = True
        self.throttle_percent = 0

        logger.info(f"[{self.country}] Drone {self.drone_id} initialized - Port: {self.port}")

    def _generate_waypoints(self):
        """Generate mission waypoints"""
        return [
            {'seq': 0, 'lat': self.source_lat, 'lon': self.source_lon, 'alt': 30.0,
             'command': mavutil.mavlink.MAV_CMD_NAV_WAYPOINT},
            {'seq': 1, 'lat': self.dest_lat, 'lon': self.dest_lon, 'alt': 50.0,
             'command': mavutil.mavlink.MAV_CMD_NAV_WAYPOINT}
        ]

    def connect_udp(self):
        """Connect to GCS via UDP"""
        for attempt in range(3):
            try:
                self.connection = mavutil.mavlink_connection(
                    f'udpout:{self.host}:{self.port}',
                    source_system=self.system_id,
                    source_component=1,
                    dialect='common'
                )
                logger.info(f"[{self.country}] Connected to {self.host}:{self.port}")
                return True
            except Exception as e:
                logger.warning(f"[{self.country}] Connection attempt {attempt+1}/3 failed: {e}")
                time.sleep(1)
        return False

    def send_heartbeat(self):
        """Send MAVLink heartbeat"""
        try:
            if self.connection:
                self.connection.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_QUADROTOR,
                    mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
                    0, 0, 0
                )
        except Exception:
            self.connection = None

    def send_global_position_int(self):
        """Send global position"""
        try:
            if self.connection:
                ground_speed_cms = int(min(max(self.ground_speed * 100, -32767), 32767))
                heading_cdeg = int(min(max(self.yaw * 100, 0), 35999))

                self.connection.mav.global_position_int_send(
                    0,
                    int(self.current_lat * 1e7),
                    int(self.current_lon * 1e7),
                    int(self.current_alt * 1000),
                    int(self.current_alt * 1000),
                    ground_speed_cms, ground_speed_cms, 0,
                    heading_cdeg
                )
        except Exception:
            self.connection = None

    def send_vfr_hud(self):
        """Send VFR HUD data"""
        try:
            if self.connection:
                throttle_percent = int(((self.ch3out - 1000) / 1000.0) * 100)
                self.connection.mav.vfr_hud_send(
                    float(self.airspeed),
                    float(self.ground_speed),
                    int(self.yaw),
                    throttle_percent,
                    float(self.current_alt),
                    float(self.vertical_speed)
                )
        except Exception:
            self.connection = None

    def send_attitude(self):
        """Send attitude data"""
        try:
            if self.connection:
                self.connection.mav.attitude_send(
                    0,
                    float(math.radians(self.roll)),
                    float(math.radians(self.pitch)),
                    float(math.radians(self.yaw)),
                    0, 0, 0
                )
        except Exception:
            self.connection = None

    def send_sys_status(self):
        """Send system status"""
        try:
            if self.connection:
                self.connection.mav.sys_status_send(
                    0, 0, 0,
                    int(self.battery_remaining * 100),
                    int(self.battery_voltage * 1000),
                    int(self.battery_current * 100),
                    -1, 0, 0, 0, 0
                )
        except Exception:
            self.connection = None

    def send_gps_raw_int(self):
        """Send GPS raw data"""
        try:
            if self.connection:
                self.connection.mav.gps_raw_int_send(
                    0, 3,
                    int(self.current_lat * 1e7),
                    int(self.current_lon * 1e7),
                    int(self.current_alt * 1000),
                    int(self.gps_hdop * 100),
                    int(self.ground_speed * 100),
                    int(self.yaw * 100),
                    self.satellites_visible
                )
        except Exception:
            self.connection = None

    def send_mission_current(self):
        """Send current mission item"""
        try:
            if self.connection:
                self.connection.mav.mission_current_send(1)
        except Exception:
            self.connection = None

    def update_position(self):
        """Update drone position based on time"""
        current_time = time.time()
        elapsed_time = current_time - self.start_time

        if elapsed_time >= self.travel_time:
            self.start_time = current_time
            elapsed_time = 0
            self.current_lat = self.source_lat
            self.current_lon = self.source_lon
            self.dist_traveled = 0
            self.ch3out = 1000
            self.armed = False

        fraction = elapsed_time / self.travel_time
        source_point = Point(latitude=self.source_lat, longitude=self.source_lon)
        current_point = geodesic(meters=self.travel_distance * fraction).destination(source_point, self.bearing)

        self.current_lat = current_point.latitude
        self.current_lon = current_point.longitude

        # Altitude simulation
        if self.current_alt < 10.0:
            self.vertical_speed = 1.0
            self.current_alt += self.vertical_speed * self.update_interval
            if self.current_alt >= 10.0:
                self.current_alt = 10.0
                self.vertical_speed = 0.0
                self.armed = True
        else:
            self.vertical_speed = 0.0

        # Throttle
        if self.armed and self.current_alt > 0.9:
            self.ch3out = random.randint(1500, 2000)
            self.throttle_percent = ((self.ch3out - 1000) / 1000.0) * 100
        else:
            self.ch3out = 1000
            self.throttle_percent = 0

        # Distance calculations
        self.dist_traveled = self.travel_distance * fraction
        self.dist_to_home = geodesic(
            (self.current_lat, self.current_lon),
            (self.source_lat, self.source_lon)
        ).meters
        self.wp_dist = self.travel_distance - self.dist_traveled

        # Random variations
        self.roll = random.uniform(-15, 15)
        self.pitch = random.uniform(-10, 10)
        self.yaw = self.bearing + random.uniform(-5, 5)

        # Battery drain
        if self.armed:
            self.battery_voltage -= 0.0001 * self.update_interval
            self.battery_remaining -= 0.01 * self.update_interval
            if self.battery_voltage < 11.5:
                self.battery_voltage = 11.5
            if self.battery_remaining < 0:
                self.battery_remaining = 0

        return {
            'lat': self.current_lat,
            'lon': self.current_lon,
            'alt': self.current_alt,
            'dist_traveled': self.dist_traveled,
            'wp_dist': self.wp_dist,
            'dist_to_home': self.dist_to_home
        }

    def get_telemetry(self):
        """Get current telemetry data"""
        position = self.update_position()

        telemetry = {
            'port': self.port,
            'drone_id': self.drone_id,
            'country': self.country,
            'capital': self.capital,
            'system_id': self.system_id,
            'lat': round(position['lat'], 7),
            'lon': round(position['lon'], 7),
            'alt': round(position['alt'], 1),
            'ground_speed': round(self.ground_speed, 2),
            'airspeed': round(self.airspeed, 2),
            'vertical_speed': round(self.vertical_speed, 2),
            'heading': round(self.yaw, 1),
            'roll': round(self.roll, 1),
            'pitch': round(self.pitch, 1),
            'dist_traveled': round(position['dist_traveled'], 2),
            'wp_dist': round(position['wp_dist'], 2),
            'dist_to_home': round(position['dist_to_home'], 2),
            'status': 'flying' if self.armed else 'landed',
            'flight_mode': self.flight_mode,
            'armed': self.armed,
            'battery_voltage': round(self.battery_voltage, 1),
            'battery_current': round(self.battery_current, 1),
            'battery_remaining': round(self.battery_remaining, 1),
            'throttle': round(self.throttle_percent, 1),
            'ch3out': self.ch3out,
            'ch3percent': round(self.throttle_percent, 1),
            'gps_hdop': round(self.gps_hdop, 2),
            'satellites': self.satellites_visible,
            'wind_speed': round(self.wind_speed, 1),
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'timestamp_full': datetime.now().isoformat(),
            'waypoint_index': 1,
            'waypoints_count': self.mission_count
        }

        # Store in global telemetry store
        with telemetry_lock:
            telemetry_store[self.port] = telemetry

        # Callback if provided
        if self.telemetry_callback:
            self.telemetry_callback(self.port, telemetry)

        return telemetry

    def run(self, stop_event):
        """Main simulation loop"""
        if not self.connect_udp():
            logger.error(f"[{self.country}] Cannot start simulator")
            return

        logger.info(f"[{self.country}] Drone simulator started")

        while not stop_event.is_set():
            try:
                # Get telemetry and store it
                telemetry = self.get_telemetry()

                # Send MAVLink messages if connected
                if self.connection:
                    self.send_heartbeat()
                    self.send_global_position_int()
                    self.send_vfr_hud()
                    self.send_attitude()
                    self.send_sys_status()
                    self.send_gps_raw_int()
                    self.send_mission_current()
                else:
                    self.connect_udp()

                time.sleep(self.update_interval)

            except Exception as e:
                logger.error(f"[{self.country}] Error: {e}")
                self.connection = None
                time.sleep(1)

        # Cleanup
        if self.connection:
            self.connection.close()
            logger.info(f"[{self.country}] Drone simulator stopped")

        # Remove from telemetry store
        with telemetry_lock:
            if self.port in telemetry_store:
                del telemetry_store[self.port]