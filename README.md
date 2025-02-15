# zmqToTar1090

zmqToTar1090 proxies traffic from a Sniffle receiver (https://github.com/alphafox02/Sniffle) to JSON data formatted for ingestion into tar1090. A lot of this project was borrowed from alphafox (cemaexecutor).

## Features

## Requirements
- Sniffle compatible dongle
- tar1090 with local mountpoint to /run/readsb
- python3
- pyzmq

## Setup and Usage

### docker-tarDRONE

I have built a docker compose file at https://github.com/l0g-lab/docker-tarDRONE to automate all of this. You can modify a single environment file and it will take care of the rest. 

If you want to run set it up manually, see below.

### Setup tar1090 for drone ingestion

#### docker-tar1090

You can use the dockerized tar1090 available at https://github.com/sdr-enthusiasts/docker-tar1090 . You'll need to add a line to the config for it to read the drone.json file:

##### Dockerfile

- Append `TAR1090_CONFIGJS_APPEND='droneJson="./data/drone.json"'` to the ENV section of the docker-tar1090 Dockerfile
- Create local mountpoint from docker container to /run/readsb

##### Docker Compose

- Append `TAR1090_CONFIGJS_APPEND='droneJson="./data/drone.json"'` to the "environment" section of the docker-compose-tar1090.yml file
- Create local mountpoint from docker container to /run/readsb

### Clone Sniffle from alphafox02 repo (this it the one I used, you can likely use the one he forked from bkerler)

```sh
git clone https://github.com/alphafox02/Sniffle
```

### Run sniffle providing ZMQ output
```sh
python3 Sniffle/python_cli/sniff_receiver.py -s <SNIFFLE_DONGLE_INTERFACE> -l -e -z --zmqsetting 127.0.0.1:4222
```

This command configures the Sniffle dongle to look for Bluetooth 5 long range extended packets and forwards them via ZeroMQ (ZMQ).

### Clone DroneID repo from bkerler for the zmqdecoder script

```sh
git clone https://github.com/bkerler/DroneID
```

### Run the ZMQ decoder script
```sh
python3 DroneID/zmq_decoder.py -z --zmqsetting 127.0.0.1:4224 --zmqclients 127.0.0.1:4222
```

This command will setup the ZMQ decoder to ingest the BLE packets and decode the Drone RemoteID data.

### Start the zmqToTar1090 proxy with the expected ZMQ server/port information.

The following command specifies the ZMQ host and ZMQ port that are default

```sh
python3 zmqToTar1090.py --zmqsetting 127.0.0.1:4224 --zmqjson
```

This will create a `drone.json` file in the /run/readsb directory by default. The output location for this file is configurable. 

Please see ```python3 zmqToTar10909.py --help``` for more runtime options such as forwarding to SBS (coming soon)

## Testing

I created a separate script you can run if you don't yet have a Sniffle compatible dongle.

For more information on this, see the README in that folder

## How It Works

## Troubleshooting

## License

```
MIT License

© 2024 l0g

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```