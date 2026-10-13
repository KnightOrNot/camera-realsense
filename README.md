Linux 设备权限问题：SDK 无法写入相机的陀螺仪（IMU）节点。pyrealsense2 可以直接使用，但 Linux 下还需要安装官方的 udev 权限规则。官方规则
执行以下命令即可，无需编译 SDK：
```bash
curl -fL https://raw.githubusercontent.com/realsenseai/librealsense/master/config/99-realsense-libusb.rules \
  -o /tmp/99-realsense-libusb.rules
```
```bash
sudo install -m 644 /tmp/99-realsense-libusb.rules /etc/udev/rules.d/
```
```bash
sudo udevadm control --reload-rules
```
然后拔下相机，再重新插上，运行：
```bash
uv run camera-realsense
```