#!/usr/bin/env python3
## author: l0g
## borrowed code from https://github.com/alphafox02/

import zmq
import json
import argparse
import signal
import sys
import datetime
import time
import logging
from collections import deque

logger = logging.getLogger(__name__)

def iso_timestamp_now() -> str:
    """Return current time as an ISO8601 string with 'Z' for UTC."""
    return datetime.datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'

def parse_float(value: str) -> float:
    """Parses a string to a float, ignoring any extraneous characters."""
    try:
        return float(value.split()[0])
    except (ValueError, AttributeError):
        return 0.0

def JSONWriter(file, data: list):
    """Sets up the JSON writer for writing drone data to file"""
    try:
        with open(file, 'w', encoding='utf-8') as json_file:
            json.dump(data, json_file, indent=4)
    except (IOError, TypeError) as e:
        print(f"An error occurred while writing to the file: {e}")

def is_valid_latlon(lat: float, lon: float) -> bool:
    """Check if lat/lon is valid."""
    if (lat < -90.0 or lat > 90.0) or (lat == 0.0):
        return False
    if (lon < -180.0 or lon > 180.0) or (lon == 0.0):
        return False
    return True

class Drone:
    """Represents a drone and its telemetry data."""
    def __init__(self, id: str, lat: float, lon: float, speed: float, vspeed: float, alt: float, height: float, pilot_lat: float, pilot_lon: float, description: str, time_str: str):
        self.id = id
        self.lat = lat
        self.lon = lon
        self.speed = speed
        self.vspeed = vspeed
        self.alt = alt
        self.height = height
        self.pilot_lat = pilot_lat
        self.pilot_lon = pilot_lon
        self.description = description
        self.time = time_str

    def update(self, lat: float, lon: float, speed: float, vspeed: float, alt: float, height: float, pilot_lat: float, pilot_lon: float, description: str, time_str: str):
        """Updates the drone's telemetry data and last seen time"""
        self.lat = lat
        self.lon = lon
        self.speed = speed
        self.vspeed = vspeed
        self.alt = alt
        self.height = height
        self.pilot_lat = pilot_lat
        self.pilot_lon = pilot_lon
        self.description = description
        self.time = time_str

    def to_dict(self) -> dict[str, any]:
        """Convert the Drone instance to a dictionary."""
        return {
            "id": self.id,
            "time": self.time,
            "lat": self.lat,
            "lon": self.lon,
            "speed": self.speed,
            "vspeed": self.vspeed,
            "alt": self.alt,
            "height": self.height,
            "pilot_lat": self.pilot_lat,
            "pilot_lon": self.pilot_lon,
            "description": self.description
        }

class DroneManager:
    """Manages a collection of drones and handles their updates."""    
    def __init__(self, max_drones=30):
        self.drones = deque(maxlen=max_drones)
        self.drone_dict = {}

    def update_or_add_drone(self, drone_id: str, new_drone_data: Drone):
        """Updates an existing drone or adds a new one to the collection."""
        if drone_id not in self.drone_dict:
            if len(self.drones) >= self.drones.maxlen:
                oldest_id = self.drones.popleft()
                del self.drone_dict[oldest_id]
            self.drones.append(drone_id)
            self.drone_dict[drone_id] = new_drone_data
        else:
            # Update existing
            self.drone_dict[drone_id].update(
                lat=new_drone_data.lat,
                lon=new_drone_data.lon,
                speed=new_drone_data.speed,
                vspeed=new_drone_data.vspeed,
                alt=new_drone_data.alt,
                height=new_drone_data.height,
                pilot_lat=new_drone_data.pilot_lat,
                pilot_lon=new_drone_data.pilot_lon,
                description=new_drone_data.description,
                time_str=new_drone_data.time
            )

    def remove_old_drones(self, max_age: float):
        """Removes drones/pilots that haven't been update in > max_age seconds."""
        now_ts = time.time()
        remove_list = []

        for drone_id in self.drones:
            iso_str = self.drone_dict[drone_id].time
            try:
                dt = datetime.datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
                last_seen_ts = dt.timestamp()
            except ValueError:
                # If 'time' is invalid, remove it to be safe
                logger.warning(f"Removing {drone_id}, invalid time field: {iso_str}")
                remove_list.append(drone_id)
                continue

            if (now_ts - last_seen_ts) > max_age:
                remove_list.append(drone_id)

        for drone_id in remove_list:
            logger.debug(f"Removing old drone: {drone_id}")
            if drone_id in self.drones:
                self.drones.remove(drone_id)
            if drone_id in self.drone_dict:
                del self.drone_dict[drone_id]
            
    def print_updates(self):
        """Returns what would be written to JSON file. Useful for debugging"""
        data_to_write = []
        for drone_id in self.drones:
            data_to_write.append(self.drone_dict[drone_id].to_dict())
        pretty = json.dumps(data_to_write, indent=4)
        return pretty
 
    def send_updates(self, file):
        """ Writes the current drone/pilot array to JSON file """
        data_to_write = []
        for drone_id in self.drones:
            data_to_write.append(self.drone_dict[drone_id].to_dict())
        try:
            JSONWriter(file, data_to_write)
        except Exception as e:
            logger.error(f"Error writing JSON: {e}")

def parse_esp32_dict(message: dict) -> dict:
    """ This function parses ESP32 formatted drone data (single dict) """
    drone_info = {}

    # Check for 'Basic ID'
    if 'Basic ID' in message:
        id_type = message['Basic ID'].get('id_type')
        if id_type == 'Serial Number (ANSI/CTA-2063-A)' and 'id' not in drone_info:
            drone_info['id'] = message['Basic ID'].get('id', 'unknown')
        elif id_type == 'CAA Assigned Registration ID' and 'id' not in drone_info:
            drone_info['id'] = message['Basic ID'].get('id', 'unknown')

    # custom 'drone_id' key
    if 'drone_id' in message and 'id' not in drone_info:
        drone_info['id'] = message['drone_id']

    # parse location data
    if 'latitude' in message:
        drone_info['lat'] = parse_float(str(message['latitude']))
    if 'longitude' in message:
        drone_info['lon'] = parse_float(str(message['longitude']))
    if 'altitude' in message:
        drone_info['alt'] = parse_float(str(message['altitude']))
    if 'speed' in message:
        drone_info['speed'] = parse_float(str(message['speed']))
    if 'vert_speed' in message:
        drone_info['vspeed'] = parse_float(str(message['vert_speed']))
    if 'height' in message:
        drone_info['height'] = parse_float(str(message['height']))

    # pilot lat/lon
    if 'pilot_lat' in message:
        drone_info['pilot_lat'] = parse_float(str(message['pilot_lat']))
    if 'pilot_lon' in message:
        drone_info['pilot_lon'] = parse_float(str(message['pilot_lon']))

    # top-level 'description'
    if 'description' in message:
        drone_info['description'] = message['description']
    else:
        drone_info['description'] = message.get('Self-ID Message', {}).get('text', "")

    return drone_info

def parse_list_format(message_list: list) -> dict:
    """ This function parses bluetooth formatted drone data (array of dicts) """
    drone_info = {}
    for item in message_list:
        if not isinstance(item, dict):
            logger.error(f"Unexpected item in list: {item}")
            continue

        # Basic ID
        if 'Basic ID' in item:
            id_type = item['Basic ID'].get('id_type')
            if id_type == 'Serial Number (ANSI/CTA-2063-A)' and 'id' not in drone_info:
                drone_info['id'] = item['Basic ID'].get('id', 'unknown')
            elif id_type == 'CAA Assigned Registration ID' and 'id' not in drone_info:
                drone_info['id'] = item['Basic ID'].get('id', 'unknown')

        # Location/Vector
        if 'Location/Vector Message' in item:
            drone_info['lat'] = parse_float(item['Location/Vector Message'].get('latitude', "0.0"))
            drone_info['lon'] = parse_float(item['Location/Vector Message'].get('longitude', "0.0"))
            drone_info['speed'] = parse_float(item['Location/Vector Message'].get('speed', "0.0"))
            drone_info['vspeed'] = parse_float(item['Location/Vector Message'].get('vert_speed', "0.0"))
            drone_info['alt'] = parse_float(item['Location/Vector Message'].get('geodetic_altitude', "0.0"))
            drone_info['height'] = parse_float(item['Location/Vector Message'].get('height_agl', "0.0"))

        # Self-ID
        if 'Self-ID Message' in item:
            drone_info['description'] = item['Self-ID Message'].get('text', "")

        # System
        if 'System Message' in item:
            sysm = item['System Message']
            drone_info['pilot_lat'] = parse_float(item['System Message'].get('latitude', "0.0"))
            drone_info['pilot_lon'] = parse_float(item['System Message'].get('longitude', "0.0"))

    return drone_info

def zmq_to_json(zmqsetting, file, max_age: float, max_drones: int = 30):
    """ This function processes ZMQ data, and writes it to the JSON file """
    context = zmq.Context()
    zmq_socket = context.socket(zmq.SUB)
    zmq_socket.connect(f"tcp://{zmqsetting}")
    zmq_socket.setsockopt_string(zmq.SUBSCRIBE, "")

    drone_manager = DroneManager(max_drones=max_drones)
    
    def signal_handler(sig, frame):
        logger.info("Interrupted by user. Shutting down.")
        zmq_socket.close()
        context.term()
        logger.info("Cleaned up ZMQ resources")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    while True:
        try:
            message = zmq_socket.recv_json()
        except Exception as e:
            logger.error(f"Error receiving JSON from ZME: {e}")
            continue

        # Decide which parser to use - can add wifi type here later
        try:
            if isinstance(message, list):
                drone_info = parse_list_format(message)
            elif isinstance(message, dict):
                drone_info = parse_esp32_dict(message)
            else:
                logger.error("Unknown ZMQ payload type - not list(bluetooth) or dict(esp32). Skipping.")
                continue

        except Exception as e:
            logger.error(f"Error parsing incoming messages: {e}")
            continue

        if 'id' in drone_info:
            # Always add a 'time' field in ISO8601 for tar1090 ingestion
            drone_iso_time = iso_timestamp_now()

            # If we have an ID, prefix with 'drone-' if needed
            if not drone_info['id'].startswith('drone-'):
                drone_info['id'] = f"drone-{drone_info['id']}"
            
            # Grab the main drone coords
            main_lat = drone_info.get('lat', 0.0)
            main_lon = drone_info.get('lon', 0.0)

            # Grab the pilot coords
            pilot_lat = drone_info.get('pilot_lat', 0.0)
            pilot_lon = drone_info.get('pilot_lon', 0.0)

            # If main drone lat/lon is invalid, skip adding the drone
            if not is_valid_latlon(main_lat, main_lon):
                logger.warning(f"Skipping drone {drone_info['id']} - invalid lat/lon: ({main_lat}, {main_lon})")
                pilot_id = drone_info['id'].replace("drone-", "pilot-")
                if pilot_id in drone_manager.drone_dict:
                    logger.debug(f"Removing stale pilot entry for invalid drone: {pilot_id}")
                    if pilot_id in drone_manager.drones:
                        drone_manager.drones.remove(pilot_id)
                    del drone_manager.drone_dict[pilot_id]
                continue

            # 1) Create or update the main Drone object
            main_drone = Drone(
                id=drone_info['id'],
                lat=main_lat,
                lon=main_lon,
                speed=drone_info.get('speed', 0.0),
                vspeed=drone_info.get('vspeed', 0.0),
                alt=drone_info.get('alt', 0.0),
                height=drone_info.get('height', 0.0),
                pilot_lat=pilot_lat,
                pilot_lon=pilot_lon,
                description=drone_info.get('description', ""),
                time_str=drone_iso_time
            )
            drone_manager.update_or_add_drone(main_drone.id, main_drone)

            # 2) If pilot lat/long is valid, create second "pilot" object
            if is_valid_latlon(pilot_lat, pilot_lon):
                pilot_id = main_drone.id.replace("drone-", "pilot-")
                pilot_drone = Drone(
                    id=pilot_id,
                    lat=pilot_lat,
                    lon=pilot_lon,
                    speed=0.0,
                    vspeed=0.0,
                    alt=0.0,
                    height=0.0,
                    pilot_lat=0.0,
                    pilot_lon=0.0,
                    description=main_drone.description,
                    time=drone_iso_time
                )
                drone_manager.update_or_add_drone(pilot_id, pilot_drone)

            else:
                # if pilot lat/lon is invalid or zero, remove leftover pilot
                pilot_id = main_drone.id.replace("drone-", "pilot-")
                if pilot_id in drone_manager.drone_dict:
                    logger.debug(f"Removing stale pilot entry {pilot_id} (invalid or no pilot coords)")
                    if pilot_id in drone_manager.drones:
                        drone_manager.drones.remove(pilot_id)
                    del drone_manager.drone_dict[pilot_id]

        else:
            logger.warning("No 'id' found in message. Skipping...")

        # After updating, write JSON
        drone_manager.send_updates(file)

        # Remove any drones that haven't been updated for >10s
        drone_manager.remove_old_drones(max_age)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZMQ to JSON for tar1090, handling standard & ESP32 formats.")
    parser.add_argument("--zmqsetting", default="127.0.0.1:4224", help="Define ZMQ server to connect to (default=127.0.0.1:4224)")
    parser.add_argument("--json-file", default="/run/readsb/drone.json", help="JSON file to write parsed data to. (default=/run/readsb/drone.json)")
    parser.add_argument("--max-age", default=10, help="Number of seconds before drone is old and removing from JSON file (default=10)", type=float) # not yet added
    parser.add_argument("--max-drones", default=30, help="Number of drones to filter for. (default=30)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    logging.info("Starting ZMQ to json with log level: %s","DEBUG" if args.verbose else "INFO")

    zmq_to_json(args.zmqsetting, args.json_file, args.max_age)