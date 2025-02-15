# zmqToTar1090

zmqToTar1090 proxies traffic from a Sniffle receiver (https://github.com/alphafox02/Sniffle) to JSON data formatted for ingestion into tar1090 for mapping. 

The ultimate goal is to get a site setup to use crowdsourcing for drones, like what's done with ADSB.

Thanks to the following peeps:

[CemaXecutor](https://github.com/alphafox02) -> Did a whole lot of troubleshooting and coding on the project. Checkout his project [DragonOS](https://cemaxecuter.com/)\
[W, the tar1090 guy](https://github.com/wiedehopf/) -> Helped with the specifics of tar1090 and readsb. Added changes just for drones.\
[Viper](https://github.com/bkerler) -> Don't know him, but he makes some great software that's used in this project\

## Requirements
- Sniffle compatible dongle - I use the SONOFF CC2652P. More information [here](https://github.com/bkerler/Sniffle/). Firmware found [here](https://github.com/nccgroup/Sniffle/releases)
- tar1090
- python3
- pyzmq module

## Setup and Usage

There are 2 ways to ingest drones into tar1090:
- drone.json (need to append a configuration line in the docker-compose for tar1090)
- SBS (BaseStation)

There are two sections below for each method.

*Note:* With the below `-v` argument, you can monitor the output of each script to make sure everything is working. If there are any RemoteID enabled drones in the area, you should see the packets being decoded. If you want less output, you can remove this flag.

See the `--help` argument for more information.

### docker-tarDRONE

I have built a docker compose file at https://github.com/l0g-lab/docker-tarDRONE to automate all of this. You can modify a single environment file and it will take care of the rest. 

If you want to run set the docker containers manually, see below.

## Setup for SBS Input

No modifications to the tar1090 project (docker or otherwise) are required to use SBS to send drones to Tar1090. You will only need to have the tar1090 instance available to the host you are running the zmqToTar1090 script from.

You'll need to open 3 terminal windows and follow these steps:
1. Clone sniffle from alphafox02 repo
```sh
git clone https://github.com/alphafox02/Sniffle
```
2. Run sniffle with: 
```sh
python3 Sniffle/python_cli/sniff_receiver.py -s <SNIFFLE_DONGLE_INTERFACE> -l -e -z --zmqsetting 127.0.0.1:4222 -v
```
3. Clone the DroneID repo from alphfox02 (this currently is the only one with support for MAC address decode):
```sh
git clone https://github.com/alphafox02/DroneID
```
4. Run zmq_decoder:
```sh
python3 DroneID/zmq_decoder.py -z --zmqsetting 127.0.0.1:4224 --zmqclients 127.0.0.1:4222 -v
```
5. Clone zmqToTar1090
```sh
git clone https://github.com/l0g-lab/zmqToTar1090
```
6. Run zmqToTar1090 with only SBS - if there is issues connecting to SBS, you will see a "Connection refused" error on your terminal.
```sh
python3 zmqToTar1090/zmqToTar1090.py --zmqsbs --zmqsetting 127.0.0.1:4224 --sbssetting <IP_ADDRESS_OF_TAR1090>:32006 -v
```

Open up your tar1090 instance on port 8078 and you should see the drones populating on the map

## Setup for JSON Input

You'll need to open 3 terminal windows and follow these steps:
1. Clone sniffle from alphafox02 repo
```sh
git clone https://github.com/alphafox02/Sniffle
```
2. Run sniffle with: 
```sh
python3 Sniffle/python_cli/sniff_receiver.py -s <SNIFFLE_DONGLE_INTERFACE> -l -e -z --zmqsetting 127.0.0.1:4222 -v
```
3. Clone the DroneID repo from alphfox02 (this currently is the only one with support for MAC address decode):
```sh
git clone https://github.com/alphafox02/DroneID
```
4. Run zmq_decoder:
```sh
python3 DroneID/zmq_decoder.py -z --zmqsetting 127.0.0.1:4224 --zmqclients 127.0.0.1:4222 -v
```
5. Clone zmqToTar1090
```sh
git clone https://github.com/l0g-lab/zmqToTar1090
```
6. Run zmqToTar1090 with only SBS - if there is issues connecting to SBS, you will see a "Connection refused" error on your terminal.
```sh
python3 zmqToTar1090/zmqToTar1090.py --zmqjson --zmqsetting 127.0.0.1:4224 -v
```

This will put the drone.json file into `/run/readsb/drone.json` for ingest into tar1090. Open up your tar1090 instance on port 8078 and you should see the drones populating on the map

## Dockerized

### docker-tar1090

The official docker-tar1090 project can be used - available at https://github.com/sdr-enthusiasts/docker-tar1090 

If you use the above and want to utilize SBS, the sections marked with (json method) can be ignored.

##### Dockerfile (json method)

- Append `TAR1090_CONFIGJS_APPEND='droneJson="./data/drone.json"'` to the ENV section of the docker-tar1090 Dockerfile
- Create a docker volume from docker container to /run/readsb

##### Docker Compose (json method)

- Append `TAR1090_CONFIGJS_APPEND='droneJson="./data/drone.json"'` to the "environment" section of the docker-compose-tar1090.yml file
- Create a docker volume from docker container to /run/readsb

## Testing

I created scripts you can use if you don't yet have a Sniffle compatible dongle. These are available in the `test/` directory of this project.

For more information, see the [README](https://github.com/l0g-lab/zmqToTar1090/blob/main/test/README.md)

## How It Works

The Sniffle and zmqDecoder do the heavy lifting, while zmqToTar1090 takes care of getting decoded drone RemoteID into a format acceptable for tar1090 mapping.

[Sniffle](https://github.com/bkerler/Sniffle) -> BT5 BLE LongRange Extended Adv Sniffer\
[zmqDecoder](https://github.com/bkerler/DroneID) -> Decodes the Sniffle packets and outputs them over ZMQ as JSON\
[zmqToTar1090](https://github.com/l0g-lab/zmqToTar1090) -> Receives the JSON data over ZMQ and generates either a JSON file or SBS (BaseStation) message for tar1090 to use\

Here is some ASCII art for a visual representation:
```
sniffle Drone RemoteID Decoder (ZMQ PUB)
              |                                   
             \|/  
zmq_decoder (ZMQ SUB / PUB)
              |                                          zmq_to_sbs() (ZMQ SUB)
             \|/                                        /
zmqToTar1090 (ZMQ SUB / PUB)  -> zmqToTar1090 (ZMQ PUB)
                                                        \
                                                         zmq_to_sbs() (ZMQ SUB)
```

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
