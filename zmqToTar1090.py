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
import threading
import re
import socket

# Configure logging
logger = logging.getLogger(__name__)

# Setup global running variable
running = True

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
            logger.debug(f"Wrote new data to JSON file: '{file}'")
    except FileNotFoundError:
        with open(file, 'w', encoding='utf-8') as json_file:
            json.dump(data, json_file, indent=4)
            logger.debug(f"Created new JSON file: '{file}'")
    except (IOError, TypeError) as e:
        print(f"An error occurred while writing to the file: {e}")

def is_valid_latlon(lat: float, lon: float) -> bool:
    """Check if lat/lon is valid."""
    if (lat < -90.0 or lat > 90.0) or (lat == 0.0):
        return False
    if (lon < -180.0 or lon > 180.0) or (lon == 0.0):
        return False
    return True

def is_valid_mac(mac: str) -> bool:
    """Validate MAC address format."""
    if not mac:
        return False
    mac_regex = re.compile(r'^([0-9A-Fa-f]{2}:){5}([0-9A-Fa-f]{2})$')
    return bool(mac_regex.match(mac))

def signal_handler(signum, frame):
    global running
    logger.info("Received signal. Shutting down...")
    running = False

def zmq_feeder(zmqsetting: str, pub_port: int):
    logger.debug(f"Started ZMQ Feeder thread")
    zmq_context = zmq.Context()

    # SUB to ZMQ Decoder
    zmq_socket = zmq_context.socket(zmq.SUB)
    zmq_socket.connect(f"tcp://{zmqsetting}")
    zmq_socket.setsockopt_string(zmq.SUBSCRIBE, "")

    # New PUB socket to broadcast same messages to internal function listeners
    zmq_pub_socket = zmq_context.socket(zmq.PUB)
    zmq_pub_socket.bind(f"tcp://127.0.0.1:{pub_port}")
    logger.debug(f"Connected to ZMQ on {zmqsetting} - forwarding to tcp://127.0.0.1:{pub_port}")
    
    while running:
        try:
            zmq_msg = zmq_socket.recv_json()
            logger.debug(f"Received ZMQ message: {zmq_msg}")
            zmq_pub_socket.send_json(zmq_msg)
        except zmq.ZMQError as e:
            logger.error(f"Error receiving ZMQ message: {e}")
            continue

class Drone:
    """Represents a drone and its telemetry data."""
    def __init__(self, id: str, mac: str = ""):
        self.id = id # Serial Number or FAA ID
        self.mac = mac.lower() if mac else ""
        self.lat = 0.0
        self.lon = 0.0
        self.speed = 0.0
        self.vspeed = 0.0
        self.alt = 0.0
        self.height = 0.0
        self.pilot_lat = 0.0
        self.pilot_lon = 0.0
        self.description_parts = set() # Use set() to store unique description parts
        self.time = iso_timestamp_now()

    def update(self, data: dict):
        """Updates the drone's telemetry data and last seen time"""
        # Update telemetry if present
        self.lat = data.get('lat', self.lat)
        self.lon = data.get('lon', self.lon)
        self.speed = data.get('speed', self.speed)
        self.vspeed = data.get('vspeed', self.vspeed)
        self.alt = data.get('alt', self.alt)
        self.height = data.get('height', self.height)
        self.pilot_lat = data.get('pilot_lat', self.pilot_lat)
        self.pilot_lon = data.get('pilot_lon', self.pilot_lon)
        
        # Update description
        new_description = data.get('description', "")
        if new_description:
            parts = [part.strip() for part in new_description.split(';') if part.strip()]
            self.description_parts.update(parts)
            logger.debug(f"Updated description parts for drone '{self.id}': {self.description_parts}")

        # Update timestamp
        self.time = data.get('time', iso_timestamp_now())

    def to_dict(self) -> dict:
        """Convert the Drone instance to a dictionary."""
        drone_dict = {
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
            "description": "; ".join(sorted(self.description_parts))
        }

        pilot_lat = self.pilot_lat
        pilot_lon = self.pilot_lon
        if is_valid_latlon(pilot_lat, pilot_lon):
            drone_dict["pilot_lat"] = self.pilot_lat
            drone_dict["pilot_lon"] = self.pilot_lon

        return drone_dict

class DroneManager:
    """Manages a collection of drones and handles their updates."""    
    def __init__(self, max_drones=30):
        self.drones = deque(maxlen=max_drones)
        self.mac_to_drone_id = {}
        self.drone_dict = {}

    def update_or_add_main_drone(self, drone_info: dict) -> str:
        """Updates an existing drone or adds a new one to the collection."""
        mac = drone_info.get('mac')
        serial_number = drone_info.get('id', None)
        description = drone_info.get('description')

        if not mac:
            logger.debug(f"Drone with ID '{serial_number}' has no MAC address. Skipping...")
            return None

        if serial_number:
            drone_id_full = f"drone-{serial_number}"
        else:
            drone_id_full = "drone-unknown"
        
        if mac in self.mac_to_drone_id:
            existing_id = self.mac_to_drone_id[mac]
            existing_drone = self.drone_dict[existing_id]

            # Update 'id' if a serial number is provided and it's different
            if serial_number and existing_drone.id != drone_id_full:
                existing_drone.id = drone_id_full
                self.drone_dict[drone_id_full] = existing_drone
                del self.drone_dict[existing_id]
                self.mac_to_drone_id[mac] = drone_id_full
                logger.debug(f"Updated drone ID from '{existing_id}' to '{drone_id_full}' based on serial number.")

            # Append CAA assigned registration ID to description if present
            if description:
                existing_drone.update({'description': description})
                logger.debug(f"Appended description to drone '{existing_drone.id}': {description}")

            # Update telemtry
            existing_drone.update(drone_info)
            logger.debug(f"Updated drone '{existing_drone.id}' with MAC '{mac}'.")

            return self.mac_to_drone_id[mac]

        else:
            # New drone, add to manager
            if len(self.drones) >= self.drones.maxlen:
                oldest_mac, oldest_id = self.drones_popleft()
                del self.mac_to_drone_id[oldest_mac]
                del self.drone_dict[oldest_id]
                logger.debug(f"Removed oldest drone '{oldest_id}' with MAC '{oldest_mac}'.")

            new_drone = Drone(id=drone_id_full, mac=mac)
            new_drone.update(drone_info)
            self.drones.append((mac, drone_id_full))
            self.drone_dict[drone_id_full] = new_drone
            self.mac_to_drone_id[mac] = drone_id_full
            logger.debug(f"Added new drone '{drone_id_full}' with MAC '{mac}'.")

            return drone_id_full

    def update_or_add_pilot_drone(self, main_drone_id: str, drone_info: dict):
        """
        Creates or updates a pilot drone associated with the main drone.
        Pilot drone ID is 'pilot-' + main drone ID.
        Pilot drones do not have MAC addresses.
        """
        pilot_id = f"pilot-{main_drone_id}"
        pilot_lat = drone_info.get('pilot_lat', 0.0)
        pilot_lon = drone_info.get('pilot_lon', 0.0)

        if is_valid_latlon(pilot_lat, pilot_lon):
            if pilot_id not in self.drone_dict:
                # Add new pilot drone
                new_pilot = Drone(id=pilot_id)
                new_pilot.lat = pilot_lat
                new_pilot.lon = pilot_lon
                new_pilot.speed = 0.0
                new_pilot.vspeed = 0.0
                new_pilot.alt = 0.0
                new_pilot.height = 0.0
                new_pilot.pilot_lat = 0.0
                new_pilot.pilot_lon = 0.0
                # Inherit descriptions from main drone
                if main_drone_id in self.drone_dict:
                    main_drone = self.drone_dict[main_drone_id]
                    new_pilot.description_parts = set(main_drone.description_parts)
                new_pilot.time = drone_info.get('time', iso_timestamp_now())
                self.drones.append((None, pilot_id))  # Pilots don't have a MAC
                self.drone_dict[pilot_id] = new_pilot
                logger.debug(f"Added new pilot drone '{pilot_id}'.")
            else:
                # Update existing pilot drone
                pilot_drone = self.drone_dict[pilot_id]
                pilot_drone.lat = pilot_lat
                pilot_drone.lon = pilot_lon
                pilot_drone.update(drone_info)
                logger.debug(f"Updated pilot drone '{pilot_id}'.")
        else:
            # Pilot coordinates are invalid; remove pilot drone if exists
            if pilot_id in self.drone_dict:
                logger.debug(f"Removing stale pilot drone '{pilot_id}' due to invalid or zero coordinates.")
                self.drones = deque([(m, d) for (m, d) in self.drones if d != pilot_id], maxlen=self.drones.maxlen)
                del self.drone_dict[pilot_id]

    def remove_old_drones(self, max_age: float):
        """Removes drones/pilots that haven't been update in > max_age seconds."""
        now_ts = time.time()
        remove_list = []

        for drone_id, drone in list(self.drone_dict.items()):
            if drone.id.startswith("pilot-"):
                # Pilot drones are handled with their main drones
                continue
            iso_str = drone.time
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
            drone = self.drone_dict[drone_id]
            mac = None
            # Find the MAC associated with this drone
            for m, d_id in self.mac_to_drone_id.items():
                if d_id == drone_id:
                    mac = m
                    break

            if mac:
                self.drones = deque([(m, d) for (m, d) in self.drones if m != mac], maxlen=self.drones.maxlen)
                del self.mac_to_drone_id[mac]
            del self.drone_dict[drone_id]
            logger.debug(f"Removed stale drone: {drone_id} with MAC '{mac}'.")

            # Also remove associated pilot drone if exists
            pilot_id = f"pilot-{drone_id}"
            if pilot_id in self.drone_dict:
                self.drones = deque([(m, d) for (m, d) in self.drones if d != pilot_id], maxlen=self.drones.maxlen)
                del self.drone_dict[pilot_id]
                logger.debug(f"Removed stale pilot drone {pilot_id} associated with {drone_id}.")
            
    def print_updates(self):
        """Returns what would be written to JSON file. Useful for debugging"""
        data_to_write = []
        for mac, drone_id in self.drones:
            data_to_write.append(self.drone_dict[drone_id].to_dict())
        pretty = json.dumps(data_to_write, indent=4)
        return pretty

    def to_json_list(self) -> list:
        """Converts all drones to a list of dictionaries for JSON serialization."""
        return [drone.to_dict() for drone in self.drone_dict.values()]
 
    def send_updates(self, file):
        """ Writes the current drone/pilot array to JSON file """
        data_to_write = self.to_json_list()
        try:
            JSONWriter(file, data_to_write)
            logger.debug(f"Updated JSON file '{file}' with {len(data_to_write)} drones.")
        except Exception as e:
            logger.error(f"Error writing JSON: {e}")

def parse_list_format(message_list: list) -> dict:
    """ This function parses bluetooth formatted drone data (array of dicts) """
    drone_info = {}
    drone_info['mac'] = None
    serial_number = None
    caa_id = None
    descriptions = set()

    for item in message_list:
        if not isinstance(item, dict):
            logger.error(f"Unexpected item in list: {item}")
            continue

        # Basic ID
        if 'Basic ID' in item:
            id_type = item['Basic ID'].get('id_type', '').strip().lower()
            current_id = item['Basic ID'].get('id', 'unknown').strip()

            if id_type == 'serial number (ansi/cta-2063-a)':
                serial_number = current_id
                logger.debug(f"Parsed Serial Number: {current_id}")
            elif id_type == 'caa assigned registration id':
                caa_id = current_id
                descriptions.add(caa_id)
                logger.debug(f"Parsed CAA Assigned Registration ID: {caa_id}")

            # Extract MAC address
            mac = item['Basic ID'].get('MAC', '').strip()
            if mac and is_valid_mac(mac):
                drone_info['mac'] = mac.lower()
                logger.debug(f"Parsed MAC address: {mac.lower()}")
            else:
                logger.debug(f"Invalid or missing MAC address is BT message: '{mac}'.")

        # Location/Vector
        if 'Location/Vector Message' in item:
            drone_info['lat'] = parse_float(item['Location/Vector Message'].get('latitude', "0.0"))
            drone_info['lon'] = parse_float(item['Location/Vector Message'].get('longitude', "0.0"))
            drone_info['speed'] = parse_float(item['Location/Vector Message'].get('speed', "0.0"))
            drone_info['vspeed'] = parse_float(item['Location/Vector Message'].get('vert_speed', "0.0"))
            drone_info['alt'] = parse_float(item['Location/Vector Message'].get('geodetic_altitude', "0.0"))
            drone_info['height'] = parse_float(item['Location/Vector Message'].get('height_agl', "0.0"))

        # System
        if 'System Message' in item:
            drone_info['pilot_lat'] = parse_float(item['System Message'].get('latitude', "0.0"))
            drone_info['pilot_lon'] = parse_float(item['System Message'].get('longitude', "0.0"))
            logger.debug(f"Parsed System Message: pilot_lat={drone_info['pilot_lat']}, pilot_lon={drone_info['pilot_lon']}")

    # Combine all descriptions into a single string
    if descriptions:
        drone_info['description'] = "; ".join(sorted(descriptions))
        logger.debug(f"Combined descriptions: {drone_info['description']}")
    else:
        drone_info['description'] = ""

    # Now, set 'id' as 'serial_number' if exists
    if serial_number:
        drone_info['id'] = serial_number
        drone_info['id_type'] = 'Serial Number'

    return drone_info

def parse_esp32_dict(message: dict) -> dict:
    """ Parses ESP32 formatted drone data (single dict) """
    drone_info = {}
    descriptions = set()

        # Check for 'Basic ID'
    if 'Basic ID' in message:
        id_type = message['Basic ID'].get('id_type', '').strip().lower()
        if id_type == 'serial number (ansi/cta-2063-a)':
            drone_info['id'] = message['Basic ID'].get('id', 'unknown').strip()
            drone_info['id_type'] = 'Serial Number'
            logger.debug(f"Parsed Serial Number: {drone_info['id']}")
        elif id_type == 'caa assigned registration id':
            caa_assigned_number = message['Basic ID'].get('id', 'unknown').strip()
            descriptions.add(caa_assigned_number)  # Add only the CAA number
            drone_info['id_type'] = 'CAA Assigned'
            # Do not set 'id' for CAA Assigned ID
            logger.debug(f"Parsed CAA Assigned Registration ID: {caa_assigned_number}")

        # Extract MAC address
        mac = message['Basic ID'].get('MAC', '').strip()
        if mac and is_valid_mac(mac):
            drone_info['mac'] = mac.lower()  # Standardize to lowercase
            logger.debug(f"Parsed MAC address: {mac.lower()}")
        else:
            logger.debug(f"Invalid or missing MAC address in ESP32 message: '{mac}'.")

    # Parse location data
    if 'latitude' in message:
        drone_info['lat'] = parse_float(str(message['latitude']))
        logger.debug(f"Parsed latitude: {drone_info['lat']}")
    if 'longitude' in message:
        drone_info['lon'] = parse_float(str(message['longitude']))
        logger.debug(f"Parsed longitude: {drone_info['lon']}")
    if 'altitude' in message:
        drone_info['alt'] = parse_float(str(message['altitude']))
        logger.debug(f"Parsed altitude: {drone_info['alt']}")
    if 'speed' in message:
        drone_info['speed'] = parse_float(str(message['speed']))
        logger.debug(f"Parsed speed: {drone_info['speed']}")
    if 'vert_speed' in message:
        drone_info['vspeed'] = parse_float(str(message['vert_speed']))
        logger.debug(f"Parsed vertical speed: {drone_info['vspeed']}")
    if 'height' in message:
        drone_info['height'] = parse_float(str(message['height']))
        logger.debug(f"Parsed height: {drone_info['height']}")

    # Pilot lat/lon
    if 'pilot_lat' in message:
        drone_info['pilot_lat'] = parse_float(str(message['pilot_lat']))
        logger.debug(f"Parsed pilot_lat: {drone_info['pilot_lat']}")
    if 'pilot_lon' in message:
        drone_info['pilot_lon'] = parse_float(str(message['pilot_lon']))
        logger.debug(f"Parsed pilot_lon: {drone_info['pilot_lon']}")

    # Combine all descriptions into a single string
    if descriptions:
        drone_info['description'] = "; ".join(sorted(descriptions))
        logger.debug(f"Combined descriptions: {drone_info['description']}")
    else:
        drone_info['description'] = ""

    # Now, set 'id' as 'serial_number' if exists
    if 'id' in drone_info and drone_info['id']:
        drone_info['id_type'] = 'Serial Number'

    return drone_info

def zmq_to_json(file, max_age: float, max_drones: int, pub_port: int):
    """ This function processes ZMQ data, and writes it to the JSON file """
    # SUB to internal ZMQ
    zmq_context = zmq.Context()
    zmq_socket = zmq_context.socket(zmq.SUB)
    zmq_socket.connect(f"tcp://127.0.0.1:{pub_port}")
    zmq_socket.setsockopt_string(zmq.SUBSCRIBE, "")
    
    drone_manager = DroneManager(max_drones=max_drones)

    # Start internal ZMQ feed
    while running:
        message = zmq_socket.recv_json()
        logger.debug(f"Processing ZMQ message for JSON file")

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

        if 'mac' in drone_info and drone_info['mac'] and is_valid_latlon(drone_info['lat'], drone_info['lon']):
            # Always add a 'time' field in ISO8601 for tar1090 ingestion
            drone_info['time'] = iso_timestamp_now()

            main_drone_id = drone_manager.update_or_add_main_drone(drone_info)

            if main_drone_id:
                # Grab the main drone coords
                main_lat = drone_info.get('lat', 0.0)
                main_lon = drone_info.get('lon', 0.0)

                # Grab the pilot coords
                pilot_lat = drone_info.get('pilot_lat', 0.0)
                pilot_lon = drone_info.get('pilot_lon', 0.0)

                # If main drone lat/lon is invalid, skip adding the drone
                if not is_valid_latlon(main_lat, main_lon):
                    logger.info(f"Skipping drone {drone_info.get('id')} - invalid lat/lon: ({main_lat}, {main_lon})")
                    drone_manager.update_or_add_pilot_drone(main_drone_id, {'pilot_lat': 0.0, 'pilot_lon': 0.0, 'time': drone_info['time']})
                    continue

                drone_manager.update_or_add_pilot_drone(main_drone_id, drone_info)

        else:
            logger.warning("No 'id' or valid lat/lon found in message. Skipping...")

        # After updating, write JSON
        drone_manager.send_updates(file)

        # Remove any drones that haven't been updated for >10s
        drone_manager.remove_old_drones(max_age)

def zmq_to_sbs(max_age: float, max_drones: int, pub_port: int, sbs_setting: str):
    """
    This function takes in the ZMQ data and sends it to SBS (basestation)

    Format : MSG,3,1,1,icaoHex,1,messageDate,messageTime,currentDate,currentTime,callsign_8char,altitude_ft,groundspeed_kts,track,lat,lon,vert_rate_fpm,squawk,squawkChangeAlert,squawkEmergencyFlag,squawkIdentFlag,groundFlag_0airborne_-1ground
    Sample : MSG,3,1,1,4AC8B3,1,2019/12/10,19:10:46.320,2019/12/10,19:10:47.789,,36017,,,51.1001,10.1915,,,,,,
    """

    drone_iso_time = iso_timestamp_now()
    dt = datetime.datetime.fromisoformat(drone_iso_time.rstrip('Z'))
    date_str = dt.date().strftime('%Y/%m/%d')
    time_str = dt.time().strftime('%H:%M:%S.%f')[:-3]

    def generate_sbs_string(drone_info: dict) -> str:
        sbs_message = f"MSG,3,1,1," # MSG Type, TX Type, Session ID, Aircraft ID
        sbs_message += f"~{drone_info['id']}," # icaoHex (6 char upper case hex)
        sbs_message += "1," # Flight ID
        sbs_message += f"{date_str}," # YYYY/MM/DD -> Generation Date
        sbs_message += f"{time_str}," # HH:MM:SS.xxx -> Generation Time
        sbs_message += f"{date_str}," # YYYY/MM/DD -> Record Date
        sbs_message += f"{time_str}," # HH:MM:SS.xxx -> Record Time
        sbs_message += f"{drone_info['id']}," # Callsign (8 char)
        sbs_message += f"{drone_info['alt']:.0f}," # Altitude ft
        sbs_message += f"{drone_info['speed']:.0f}," # Ground speed
        sbs_message += f"," # Track
        sbs_message += f"{drone_info['lat']:.5f}," # Latitude {:.5f}
        sbs_message += f"{drone_info['lon']:.5f}," # Longitude {:.5f}
        sbs_message += f"{drone_info['vspeed']:.0f}," # Vertical Rate
        sbs_message += f",,,," # Squawk, Squawk Alert, Emergency, SPI, On Ground
        sbs_message += f"\r\n"
        return sbs_message

    # SUB to internal ZMQ
    zmq_context = zmq.Context()
    zmq_socket = zmq_context.socket(zmq.SUB)
    zmq_socket.connect(f"tcp://127.0.0.1:{pub_port}")
    zmq_socket.setsockopt_string(zmq.SUBSCRIBE, "")

    # Grab IP and Port for connection to SBS receiver
    sbs_host, sbs_port = sbs_setting.split(":")

    # Get drone data ready for processing
    drone_manager = DroneManager(max_drones  = max_drones)

    while running:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sbs_socket:
                sbs_socket.connect((sbs_host, int(sbs_port)))
                logger.info(f"Connection to SBS listener at {sbs_setting}")

                # Start internal ZMQ feed
                while True:
                    message = zmq_socket.recv_json()
                    logger.debug(f"Processing ZMQ message for SBS.")

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

                    ####### Adding in the code from zmq_to_json so we can make sure we are setting up drones correctly #######
                    if 'id' in drone_info:
                        # Always add a 'time' field in ISO8601 for tar1090 ingestion
                        #drone_iso_time = iso_timestamp_now()

                        # If we have a MAC, set last 6 characters to the icaoHex field
                        #mac = message[0]['Basic ID'].get('MAC').replace(":","")[-6:]
                        #print(f"MAC: {mac}")

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

                    for drone_id in drone_manager.drones:
                        drone_list = drone_manager.drone_dict[drone_id].to_dict()
                        drone_sbs_message = generate_sbs_string(drone_list)
                        sbs_socket.sendall(drone_sbs_message.encode())
                        logger.debug(f"Sent SBS message: {drone_sbs_message}")
                    ####### Adding in the code from zmq_to_json so we can make sure we are setting up drones correctly #######

        except (ConnectionRefusedError, socket.error) as e:
            logging.error(f"Connection error: {e}. Retrying in 5 seconds...")
            time.sleep(5)
            continue
        sbs_socket.close()
        logger.info("SBS Socket Closed")

def main():
    parser = argparse.ArgumentParser(description="ZMQ to JSON for tar1090, handling standard & ESP32 formats.")
    parser.add_argument("--zmqsetting", default="127.0.0.1:4224", help="Define ZMQ server to connect to (default=127.0.0.1:4224)")
    parser.add_argument("--localport", default="5555", help="Local port to use for internal ZMQ. Choose unused port.")
    parser.add_argument("--zmqjson", help="Enable ZMQ to JSON", action="store_true")
    parser.add_argument("--json-file", default="/run/readsb/drone.json", help="JSON file to write parsed data to. (default=/run/readsb/drone.json)")
    parser.add_argument("--zmqsbs", help="Enable ZMQ to SBS", action="store_true")
    parser.add_argument("--sbssetting", default="127.0.0.1:30003", help="Define SBS server to connect to (default=127.0.0.1:30003)")
    parser.add_argument("--max-age", default=10, help="Number of seconds before drone is old and removing from JSON file (default=10)", type=float) # not yet added
    parser.add_argument("--max-drones", default=30, help="Number of drones to filter for. (default=30)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    logging.info("Starting zmqToTar1090 script with log level: %s","DEBUG" if args.verbose else "INFO")

    # Create a signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.zmqjson or args.zmqsbs:
        # Start feeder thread for ZMQ
        zmq_feeder_thread = threading.Thread(target=zmq_feeder, args=(args.zmqsetting,args.localport))
        zmq_feeder_thread.daemon = True
        zmq_feeder_thread.start()

        if args.zmqjson:
            zmq_json_thread = threading.Thread(target=zmq_to_json, args=(args.json_file, args.max_age, args.max_drones, args.localport))
            zmq_json_thread.daemon = True
            zmq_json_thread.start()
        if args.zmqsbs:
            zmq_sbs_thread = threading.Thread(target=zmq_to_sbs, args=(args.max_age, args.max_drones, args.localport, args.sbssetting))
            zmq_sbs_thread.daemon = True
            zmq_sbs_thread.start()
    else:
        parser.print_help()
        sys.exit(1)

    while running:
        time.sleep(0.1)

    logger.info("ZMQ Resources cleaned up. Program has exited cleanly.")

if __name__ == "__main__":
    main()