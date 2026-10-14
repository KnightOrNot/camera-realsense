"""Local RealSense and ZMQ adapters used by the two camera launcher scripts."""

from __future__ import annotations

from threading import Event

import numpy as np
import pyrealsense2 as rs
import zmq


def get_device_ids() -> list[str]:
    return [device.get_info(rs.camera_info.serial_number)
            for device in rs.context().query_devices()]


class RealSenseCamera:
    def __init__(self, device_id: str, width: int = 640, height: int = 480, fps: int = 5):
        self.device_id = device_id
        self.pipeline = rs.pipeline()
        config = rs.config()
        config.enable_device(device_id)
        config.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
        config.enable_stream(rs.stream.color, width, height, rs.format.rgb8, fps)
        self.pipeline.start(config)

    def read(self, img_size: tuple[int, int] | None = None) -> tuple[np.ndarray, np.ndarray]:
        frames = self.pipeline.wait_for_frames(5000)
        color, depth = frames.get_color_frame(), frames.get_depth_frame()
        if not color or not depth:
            raise RuntimeError("未收到完整的彩色和深度帧。")
        image = np.asanyarray(color.get_data()).copy()
        raw_depth = np.asanyarray(depth.get_data()).copy()
        if img_size is not None:
            import cv2
            image = cv2.resize(image, img_size)
            raw_depth = cv2.resize(raw_depth, img_size, interpolation=cv2.INTER_NEAREST)
        return image, raw_depth[:, :, None]

    def close(self) -> None:
        self.pipeline.stop()


class ZMQServerCamera:
    def __init__(self, camera: RealSenseCamera, port: int = 5000, host: str = "127.0.0.1"):
        self.camera = camera
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.RCVTIMEO, 1000)
        self.socket.bind(f"tcp://{host}:{port}")
        self.stopped = Event()

    def serve(self) -> None:
        try:
            while not self.stopped.is_set():
                try:
                    size = self.socket.recv_pyobj()
                except zmq.Again:
                    continue
                try:
                    reply = self.camera.read(size)
                except RuntimeError as exc:
                    self.socket.send_pyobj({"error": str(exc)})
                else:
                    self.socket.send_pyobj(reply)
        finally:
            self.socket.close()
            self.context.term()

    def stop(self) -> None:
        self.stopped.set()


class ZMQClientCamera:
    def __init__(self, port: int = 5000, host: str = "127.0.0.1"):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.RCVTIMEO, 7000)
        self.socket.setsockopt(zmq.SNDTIMEO, 7000)
        self.socket.connect(f"tcp://{host}:{port}")

    def read(self, img_size: tuple[int, int] | None = None) -> tuple[np.ndarray, np.ndarray]:
        try:
            self.socket.send_pyobj(img_size)
            reply = self.socket.recv_pyobj()
        except zmq.Again as exc:
            raise RuntimeError("相机服务端响应超时，请检查服务是否运行及端口是否一致。") from exc
        if isinstance(reply, dict):
            raise RuntimeError(f"相机采集失败：{reply.get('error', reply)}")
        return reply

    def close(self) -> None:
        self.socket.close()
        self.context.term()
