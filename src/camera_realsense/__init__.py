import pyrealsense2 as rs

def main() -> None:
    print("Hello from camera-realsense!")

    pipeline = rs.pipeline() # Create a pipeline
    # Request only depth; the default configuration may also open the IMU.
    config = rs.config()
    config.enable_stream(rs.stream.depth, 480, 270, rs.format.z16, 5)
    pipeline.start(config)

    try:
        while True:
            frames = pipeline.wait_for_frames()
            depth_frame = frames.get_depth_frame()
            if not depth_frame:
                continue

            width, height = depth_frame.get_width(), depth_frame.get_height()
            dist = depth_frame.get_distance(width // 2, height // 2)
            print(f"The camera is facing an object {dist:.3f} meters away", end="\r")

    finally:
        pipeline.stop() # Stop streaming
