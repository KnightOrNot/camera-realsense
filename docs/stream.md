# 可复用 RGB-D 帧接口

`camera_realsense.stream` 供 controller 等应用组合，不负责机器人客户端、raw session、时间轴重采样或 LeRobot 转换。导入不打开相机；不用启动相机 CLI 子进程。

```python
from camera_realsense.stream import ColorStream

with ColorStream(depth_enabled=True) as camera:
    print(camera.metadata)
    while True:
        packet = camera.read(timeout_s=0.2)
        if packet is None:
            continue
        print(packet.stream, packet.timestamp_ns, packet.image.shape)
```

`ColorStream` 默认仅 RGB，`depth_enabled=True` 同时启用 Z16 深度，返回独立的 color/depth `VideoFrame` 包。同一消费者调用 read；不同流可能交错或有不同 FPS，不按帧号配对。每次返回复制后的 NumPy 数组，不持有 SDK 帧内存。

启动阶段必须等所有启用的流完成预热和时钟映射后才交付第一包。此前出现帧号回退、时间域切换或时钟映射失败，会清除两路候选帧、计数及映射并重新预热，日志保留原因。开始交付后，同类异常仍立即抛错，不自动恢复或掩盖录制中断。`startup_status` 提供阶段、预热计数和最近重启原因；应用应设置总启动超时（controller 使用 camera.startup_timeout_s），单次 read 的 timeout_s 只约束一次读取。

| 构造参数 | 默认值与含义 |
| --- | --- |
| serial | 空字符串，仅允许发现一台设备 |
| width / height / fps | RGB 640 / 480 / 30 |
| depth_enabled | false；应用显式启用 |
| depth_width / depth_height / depth_fps | 深度 640 / 480 / 30 |
| warmup_frames | 每路跳过 15 帧；非负整数 |

这些是 API 默认值；独立实验 CLI 的 TOML 配置保持原规则，应用可传入自己的配置。所有 profile 会经现有 configure_video 校验。start 后的 metadata 包含设备、RGB 内参和 profile；启用深度时附 depth 表（profile、depth_units_m、深度内参、到 RGB 外参）。深度为原生视角，未投影到 RGB。

`VideoFrame.image` 在 color 时是 uint8 H×W×3 RGB，在 depth 时是 uint16 H×W Z16。深度零表示无效，米制值为原数值乘 metadata.depth.depth_units_m。其他字段：

- timestamp_ns：映射到本机 time.monotonic_ns 的帧时间。
- received_time_ns：本机读到 SDK 帧并完成时钟采样时刻。
- sdk_timestamp_ms / sdk_timestamp_domain：原始 SDK 数值与域。
- frame_number：对应流的 SDK 帧号；相邻缺口不能伪装成连续采集。
- clock_offset_ns / clock_uncertainty_ns：墙钟到单调时钟的 epoch 偏移与采样跨度。
- stream：color 或 depth。

start 尝试为 RGB/深度传感器启用 global_time_enabled，close 恢复原选项，异常也释放已启动 pipeline。read 用 bounded poll，超时返回 None，由应用负责总启动/逐流停帧超时。

先预热并等待 global/system 域，hardware_clock 帧不会输出。SDK 主机相关毫秒加 epoch 偏移得到单调纳秒；检查时间倒退、帧计数重置、超过 5 ms 的主机采样跨度/offset 跳变，以及映射时间比接收时间晚超过 50 ms 或早超过 1 s，按上述启动/运行阶段规则处理。保留所有原时间用于审计；这些校验不能证明硬件曝光同步或测距精度。

离线测试覆盖 RGB/Z16 数值与内存所有权、逐流计数/预热、时钟映射及异常清理。持续 RGB-D 带宽、具体 profile 和 global time 行为仍需实体相机短测与长测验证。
