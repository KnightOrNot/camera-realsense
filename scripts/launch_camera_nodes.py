from dataclasses import dataclass
from multiprocessing import Process

import tyro

from camera_realsense.camera_transport import RealSenseCamera, ZMQServerCamera, get_device_ids


@dataclass
class Args:
    hostname: str = "127.0.0.1"


def launch_server(port: int, camera_id: str, args: Args):
    camera = RealSenseCamera(camera_id)
    try:
        server = ZMQServerCamera(camera, port=port, host=args.hostname)
        print(f"Starting camera server on port {port}", flush=True)
        server.serve()
    finally:
        camera.close()


def main(args):
    ids = get_device_ids()
    camera_port = 5000
    camera_servers = []
    for camera_id in ids:
        # start a python process for each camera
        print(f"Launching camera {camera_id} on port {camera_port}")
        camera_servers.append(
            Process(target=launch_server, args=(camera_port, camera_id, args))
        )
        camera_port += 1

    for server in camera_servers:
        server.start()
    try:
        for server in camera_servers:
            server.join()
    except KeyboardInterrupt:
        pass
    finally:
        for server in camera_servers:
            if server.is_alive():
                server.terminate()
            server.join()


if __name__ == "__main__":
    main(tyro.cli(Args))
