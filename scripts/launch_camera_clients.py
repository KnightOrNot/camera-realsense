from dataclasses import dataclass
from typing import Tuple

import numpy as np
import tyro

from camera_realsense.camera_transport import ZMQClientCamera


@dataclass
class Args:
    ports: Tuple[int, ...] = (5000,)
    hostname: str = "127.0.0.1"
    # hostname: str = "128.32.175.167"


def main(args):
    cameras = []
    import cv2

    images_display_names = []
    for port in args.ports:
        cameras.append(ZMQClientCamera(port=port, host=args.hostname))
        images_display_names.append(f"image_{port}")
        cv2.namedWindow(images_display_names[-1], cv2.WINDOW_NORMAL)

    try:
        while True:
            for display_name, camera in zip(images_display_names, cameras):
                image, depth = camera.read()
                depth8 = cv2.convertScaleAbs(depth, alpha=0.03)
                stacked_depth = np.dstack([depth8, depth8, depth8])
                image_depth = cv2.hconcat([image[:, :, ::-1], stacked_depth])
                cv2.imshow(display_name, image_depth)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    return
    finally:
        for camera in cameras:
            camera.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main(tyro.cli(Args))
