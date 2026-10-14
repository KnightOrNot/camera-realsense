# RealSense D455F：USB 2.0 功能实验

使用 `pyrealsense2`，不需要编译 librealsense。命令入口是
`src/camera_realsense/cli.py` 中的 `main()`，由 `pyproject.toml` 注册为 `camera-realsense`。
`__init__.py` 只导出公共配置和结果类型，导入包不会启动相机。

## 1. 准备环境

```bash
cd /home/knight/projects/camera-realsense
uv sync
uv run camera-realsense --help
```

所有实验都使用 `uv run camera-realsense <子命令>`。只执行 `uv run` 不会启动程序；
只执行 `uv run camera-realsense` 会提示选择子命令。

Python 依赖：`pyrealsense2`、`numpy`、`pillow`，已写入 `pyproject.toml`。
无窗口采集不需要 OpenCV 或 Tk。`--preview` 使用系统的 Tk 和桌面环境，
Ubuntu 缺少 Tk 时可安装 `sudo apt install python3-tk`；自建 Python 还需确认其自身可导入 `tkinter`。

### Linux 设备权限

USB/IMU 出现 `Permission denied` 时安装官方 udev 规则：

```bash
curl -fL https://raw.githubusercontent.com/realsenseai/librealsense/master/config/99-realsense-libusb.rules \
  -o /tmp/99-realsense-libusb.rules
sudo install -m 644 /tmp/99-realsense-libusb.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

然后拔下并重新插入相机。正常实验无需使用 `sudo uv run`。
一次只运行一个采集命令；先关闭其他预览、相机服务和客户端。

## 2. 项目结构与扩展方式

原来集中在 `__init__.py` 的功能按职责拆分如下。现有 13 个子命令、参数、
USB 2.0 默认模式和输出格式保持兼容。

```text
camera-realsense/
├── pyproject.toml                 # 依赖、命令入口、类型检查配置
├── README.md
├── config/
│   └── default.toml               # 预留，目前不自动读取
├── src/camera_realsense/
│   ├── __init__.py                # 公共配置和结果类型的导出
│   ├── cli.py                     # 命令行解析、参数校验、命令分发
│   ├── models.py                  # 配置对象、采集统计、处理结果
│   ├── device.py                  # 设备枚举、标定、传感器选项
│   ├── capture.py                 # 流配置、pipeline 生命周期、采集轮询
│   ├── processing.py              # 测距、伪彩、对齐、点云、快照准备
│   ├── storage.py                 # PNG / NPY / JSON / CSV / PLY 写入
│   ├── preview.py                 # 可选的 Tk 图像窗口
│   ├── diagnostics.py             # 帧率评估、PASS / FAIL、控制台报告
│   └── experiments.py             # 组合上述模块，执行视频与 IMU 实验
├── tests/                        # 离线数据完整性及异常路径测试
├── typings/                      # pyrealsense2 的本地类型声明
└── scripts/
    └── generate_realsense_stubs.py
```

| 模块 | 主要接口 | 后续扩展位置 |
| --- | --- | --- |
| `cli.py` | `build_parser()`、`to_experiment_config()`、`main()` | 新命令、命令行参数与校验 |
| `models.py` | `CaptureConfig`、`VideoConfig`、`OutputConfig`、`ExperimentConfig`、`CaptureStats` | 新配置字段、共享结果类型 |
| `device.py` | `select_device()`、`show_info()`、`read_calibration()`、`camera_options()`、`set_option()` | 多设备选择、更多相机设置 |
| `capture.py` | `configure_video()`、`configure_imu()`、`pipeline_session()`、`collect()` | 新输入流、采集策略；统一释放相机 |
| `processing.py` | `measure_depth()`、`depth_image()`、`align_to_color()`、`cloud_arrays()`、`prepare_snapshot()` | 深度滤波、图像算法、点云处理 |
| `storage.py` | `save_images()`、`csv_output()`、`write_json()`、`write_ply()`、`prepare_recording()` | 新文件格式和目录规则 |
| `preview.py` | `Preview` | 新的显示方式和窗口交互 |
| `diagnostics.py` | `slow_streams()`、`summarize_video()`、`summarize_imu()`、`result_code()` | 新质量指标和结果判定规则 |
| `experiments.py` | `run_video()`、`run_imu()` | 组合采集、处理和输出的新业务流程 |

调用流程：`cli → experiments → device / capture / processing / storage / preview / diagnostics`。
配置和结果通过 `models` 中的对象传递，只有 `cli.py` 使用 `argparse.Namespace`。
`collect()` 负责轮询、每路超时和统计，通过回调交给实验层处理帧；
`pipeline_session()` 在正常结束、处理报错或中断时释放已经启动的相机。

`processing.prepare_snapshot()` 将 SDK 帧复制成图像数组与元数据，
`storage.save_images()` 接收这些结果并落盘，不负责访问相机。
原始流录像需要 SDK 在起流前启用，因而由 `capture.enable_recording()` 执行；
`storage.prepare_recording()` 只负责检查扩展名和创建目录。

### 在 Python 中复用

从项目环境运行下面的代码，可跳过命令行解析直接执行深度实验：

```python
from pathlib import Path

from camera_realsense import CaptureConfig, ExperimentConfig, OutputConfig, VideoConfig
from camera_realsense.experiments import run_video

config = ExperimentConfig(
    command="depth",
    capture=CaptureConfig(duration=30),
    video=VideoConfig(width=480, height=270, fps=5),
    output=OutputConfig(output_dir=Path("captures/python_depth")),
)
exit_code = run_video(config)
```

配置对象使用不可变 dataclass。`run_video()` 和 `run_imu()` 返回与命令行一致的状态码；
设备或参数异常会向调用方抛出，由调用方处理，命令行入口则负责打印错误并转换为退出码。
`VideoConfig` 自身默认 640×480 @5 FPS；命令行针对深度、彩色和红外设置的不同默认值
在 `cli.py` 中转换，因此通过 Python 调用时应显式选择所需分辨率。
`device.show_info()` 和 `device.read_calibration()` 返回字典，可供其他功能复用。

新增算法通常只需放入 `processing.py` 并由 `experiments.py` 调用；新增独立功能时，
再在 `cli.py` 注册子命令。`config/default.toml` 当前只是预留文件，修改它不会改变运行参数。

## 3. 命令总览

| 功能 | 子命令 | 默认模式 / 输出 |
| --- | --- | --- |
| 设备信息、USB 类型和可用流 | `info` | 不起流；`--profiles` 列出所有模式 |
| 读取内参、外参、深度单位 | `calibration` | 640×480 @5 FPS 的标定，不重新标定相机 |
| 查询曝光、增益、投射器等选项 | `options` | 默认查询深度传感器 |
| 修改一个相机选项 | `set-option` | 默认 5 秒后恢复原值 |
| 深度图、像素测距 | `depth` | 480×270 @5 FPS |
| 彩色 RGB 图 | `color` | 424×240 @5 FPS |
| 左侧红外灰度图 | `infrared` | 480×270 @5 FPS，Y8，stream index 1 |
| 彩色＋深度双流 | `rgbd` | 两路均为 640×480 @5 FPS |
| 将深度对齐到彩色图 | `align` | 两路均为 640×480 @5 FPS |
| 陀螺仪和加速度计 | `imu` | 两路均为 200 Hz；保存 CSV |
| 保存一组图像 | `snapshot` | 默认深度 640×480 @5 FPS；保存后结束 |
| 生成并导出点云 | `pointcloud` | 默认纯深度 640×480 @5 FPS；导出成功后结束 |
| 录制原始相机数据 | `record` | 默认深度 640×480 @5 FPS；保存 `.db3` |

`snapshot`、`record` 可用 `--stream depth|color|infrared|rgbd` 选择输入。
`pointcloud --colored` 开启深度＋彩色，生成真实彩色点云。

## 4. 建议实验顺序

先枚举设备，再分别验证深度、彩色、红外和 IMU；单流稳定后再测试双流、对齐及点云。
所有示例都可以独立复制执行。测试稳定性时建议采集 30 秒，保留 `--frames 0` 的默认值。

### 设备信息与可用参数

```bash
uv run camera-realsense info
uv run camera-realsense info --profiles --output captures/profiles.json
```

查看 `usb_type_descriptor`：`2.1` 表示当前是 USB 2.0 速率连接，`3.x` 表示 USB 3.x。
`info --profiles` 是当前设备、固件和连接实际提供的模式列表；选择模式时以它为准。
程序会先检查请求的单流模式是否存在；单路支持某参数，不保证多路组合也能正常运行。

多台相机时，在子命令后指定序列号，例如：

```bash
uv run camera-realsense info --serial 341522300932
```

### 深度与测距

```bash
uv run camera-realsense depth --duration 30
uv run camera-realsense depth --preview --duration 30
uv run camera-realsense depth --pixel 240 135 --duration 30 --output-dir captures/depth
```

输出像素距离（米）和整幅深度图的有效像素比例。默认测距位置是图像中心。
`0` 是无有效深度，不表示物体距离为零。中心像素无效不代表整幅深度图都无效。
将目标放在相机有效测距范围内、具有纹理和正常光照的位置再实验。

USB 2.0 的较高分辨率、低帧率例子：

```bash
uv run camera-realsense depth --width 1280 --height 720 --fps 5 --duration 30
```

其他官方支持的单深度流模式包括 640×480 @5/15/30 FPS、480×270 @5/15/30/60 FPS。
这些是规格支持的参数，不是本机稳定性测试结论。

### 彩色图

```bash
uv run camera-realsense color --duration 30
uv run camera-realsense color --preview --duration 30 --output-dir captures/color
uv run camera-realsense color --width 640 --height 480 --fps 5 --duration 30
```

程序请求 `rgb8`；SDK 完成相机原生格式到 RGB 的转换。保存的 `color.png` 是 RGB 图片。

### 左侧红外图

```bash
uv run camera-realsense infrared --duration 30
uv run camera-realsense infrared --preview --duration 30 --output-dir captures/infrared
```

保存的 `infrared.png` 是 8 位灰度图。这些命令只启用左侧红外流；
USB 2.0 下不将左右红外同时输出作为本工具的普通采集模式。

### 彩色＋深度双流

```bash
uv run camera-realsense rgbd --duration 30
uv run camera-realsense rgbd --preview --duration 30 --output-dir captures/rgbd
```

默认两路都是 640×480 @5 FPS。两路可以分别指定参数，例如降低彩色分辨率以排查带宽：

```bash
uv run camera-realsense rgbd --width 480 --height 270 --fps 5 \
  --color-width 424 --color-height 240 --color-fps 5 --duration 30
```

这是诊断组合，实际能否起流以 SDK 解析和采集结果为准。进行对齐/彩色点云实验时，
优先用两路均为 640×480 @5 FPS 的组合。需要 RGB 与深度硬件同步时，两路使用相同帧率。

### 读取标定参数

```bash
uv run camera-realsense calibration --output captures/calibration.json
```

输出深度和彩色的内参、畸变参数、depth→color 的旋转和位移，以及深度数值单位。
位移单位为米；该命令读取已有标定，不执行 self-calibration 或 tare。

可用 `--width`、`--height`、`--fps` 指定需要读取标定的模式，默认 640×480 @5 FPS。

### 深度对齐到彩色

```bash
uv run camera-realsense align --duration 30 --output-dir captures/aligned
uv run camera-realsense align --preview --duration 30
```

使用 SDK `rs.align(rs.stream.color)`，输出深度图的像素坐标对应彩色相机视角。
`captures/aligned/depth.png` 和 `depth.npy` 是对齐后的深度数据。
对齐需要两路帧和有效标定；对齐后可能出现没有有效深度的区域。

### IMU：加速度计＋陀螺仪

```bash
uv run camera-realsense imu --duration 15 --output captures/imu.csv
uv run camera-realsense imu --accel-fps 100 --gyro-fps 200 --duration 15
```

该命令只打开运动流，独立于视频实验。CSV 包含 stream、帧号、时间戳、时间戳域、x/y/z 和单位。
加速度单位 `m/s^2`，包含重力；角速度单位 `rad/s`，不是角度或姿态。
程序按每路帧号去重，并分别检测 accel 和 gyro 是否停止更新。
支持的采样率以 `info --profiles` 为准；有权限错误时按第 1 节安装规则并重新插拔。

### 保存图片和原始深度

```bash
uv run camera-realsense snapshot --stream depth --output-dir captures/snapshot_depth
uv run camera-realsense snapshot --stream color --width 424 --height 240 \
  --fps 5 --output-dir captures/snapshot_color
uv run camera-realsense snapshot --stream infrared --width 480 --height 270 \
  --fps 5 --output-dir captures/snapshot_ir
uv run camera-realsense snapshot --stream rgbd --warmup-frames 5 --output-dir captures/snapshot_rgbd
```

默认等待第一组完整图像，保存后结束，最长等待 `--duration` 秒。
即使深度全为 0，也保存原始图用于诊断，但结果会标记为 `FAIL`。
相机刚起流时自动曝光可能尚未收敛。可加 `--warmup-frames 5`，接收到 5 组完整帧后再保存；
预热帧仍计入帧数、帧率和超时统计。如果还指定 `--frames`，该目标也包含预热帧。

输出文件按启用的流决定：

| 文件 | 内容 |
| --- | --- |
| `color.png` | RGB 图片 |
| `infrared.png` | 8 位红外灰度图片 |
| `depth.png` | 16 位原始深度图片，不是 8 位显示图 |
| `depth.npy` | 同一幅原始深度 NumPy 数组，保留原数值 |
| `depth_preview.png` | 深度伪彩图；无效像素为黑色 |
| `frames.json` | 图片对应的模式、帧号、时间戳；深度还包含 `units_m` |
| `summary.json` | 本次采集统计及 PASS / FAIL |

距离换算：`深度数组[y, x] × frames.json 中 depth.units_m`，得到米。
不要把原始值直接假定为毫米，也不要用 `depth_preview.png` 做测距。
显式指定相同的输出目录会覆盖同名文件；不指定时使用时间戳目录。

### 点云与 PLY 导出

只需要深度流的几何点云：

```bash
uv run camera-realsense pointcloud --output captures/depth_cloud.ply
```

需要深度和彩色两路的真实彩色点云：

```bash
uv run camera-realsense pointcloud --colored --warmup-frames 5 --output captures/rgb_cloud.ply
```

默认丢弃深度为 0、非有限数值和超过 3 米的点，可用 `--max-depth` 修改截断距离：

```bash
uv run camera-realsense pointcloud --max-depth 6 --duration 30 \
  --output captures/cloud_6m.ply
```

得到第一个非空点云后导出并结束。纯几何点云使用统一灰色；`--colored` 通过标定映射真实 RGB，
并剔除没有有效颜色映射的点。坐标单位为米，x 向右、y 向下、z 向前。
PLY 可用 MeshLab、CloudCompare 或 Open3D 打开。旁边的 `.json` 保存测试结果。
没有有效点时不会生成空 PLY；`--preview` 显示输入图像，不是交互式 3D 点云窗口。
点云也支持 `--warmup-frames 5`，用于等待曝光和深度收敛。

### 录制相机原始数据

```bash
uv run camera-realsense record --stream depth --duration 30 --output captures/depth.db3
uv run camera-realsense record --stream rgbd --duration 30 --output captures/rgbd.db3
```

当前使用的 SDK 2.59.1 原始流录像采用 ROS2 rosbag2 的 SQLite `.db3` 格式，
保留深度数值及流元数据；不是 MP4，也不是旧版 ROS1 `.bag`。
使用这项功能不需要安装 ROS2。可用支持该格式的 RealSense Viewer 或 SDK playback API 回放。
同名 `.json` 保存统计；即使存在 `.db3`，也要检查帧数、有效深度和超时结果。
`Ctrl+C` 会结束采集并停止 pipeline，使录制文件正常关闭。
这些录像命令不包含 IMU；运动数据单独用 `imu` 命令保存 CSV。

### 查询和修改相机选项

```bash
uv run camera-realsense options --sensor depth
uv run camera-realsense options --sensor color
uv run camera-realsense options --sensor motion
```

输出选项名、当前值、范围、步长、默认值和只读状态。实际可写性及范围以查询结果为准。

临时关闭深度红外投射器，5 秒后自动恢复原值：

```bash
uv run camera-realsense set-option --sensor depth --option emitter_enabled --value 0
```

修改后会立即读回确认；默认 `--restore-after 5`，Ctrl+C 也恢复。
`--restore-after 0` 表示保留新设置供下一条采集命令使用。例如手动曝光实验：

```bash
uv run camera-realsense set-option --sensor depth --option enable_auto_exposure --value 0 --restore-after 0
uv run camera-realsense set-option --sensor depth --option exposure --value 10000 --restore-after 0
uv run camera-realsense depth --duration 30
uv run camera-realsense set-option --sensor depth --option enable_auto_exposure --value 1 --restore-after 0
```

实验前记录原值，实验后恢复自己的设置。深度曝光单位通常为微秒；
彩色传感器的曝光取值单位可能不同，请结合 SDK 的选项说明。
程序校验支持情况、只读状态和范围，最终是否接受取值由 SDK 判断。

## 5. 通用采集参数

以下参数适用于 `depth`、`color`、`infrared`、`rgbd`、`align`、`snapshot`、`pointcloud`、`record`：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--serial SERIAL` | 自动选择唯一相机 | 多台相机时必填；所有子命令均支持 |
| `--width W --height H` | 见命令总览 | 主流分辨率；双流时主流是深度 |
| `--fps FPS` | `5` | 主流帧率；彩色未单独设置时也使用此值 |
| `--color-width W --color-height H` | 跟随主流 | 彩色图分辨率，可单独覆盖 |
| `--color-fps FPS` | 跟随 `--fps` | 彩色图帧率，可单独覆盖 |
| `--duration SECONDS` | `15` | 起流后的最长采集时间；不包含 SDK 初始化时间 |
| `--frames N` | `0` | 完整新帧组目标；0 表示按时长采集；先达到帧数或时长即结束 |
| `--warmup-frames N` | `0` | 接收 N 组完整帧后再保存、对齐、生成点云或预览；统计仍包含预热 |
| `--timeout-ms MS` | `5000` | 每一路连续没有新帧多久算超时 |
| `--max-timeouts N` | `2` | 同一路连续超时次数达到该值后提前结束 |
| `--min-fps-ratio RATIO` | `0.5` | 按时长测试时，平均帧率至少达到请求值的该比例；0 关闭帧率判定 |
| `--pixel X Y` | 深度图中心 | 测距位置，像素从 0 开始；无深度流时不使用 |
| `--max-depth METERS` | `3` | 伪彩图上限及点云过滤上限，不改变硬件测距范围 |
| `--preview` | 关闭 | 显示输入图像；Q / Esc / 关窗停止 |
| `--output-dir PATH` | 不保存图片 | 保存第一组完整图像及统计；snapshot 默认生成时间戳目录 |

`snapshot` 和 `pointcloud` 完成保存后会提前结束，即使还未达到 `--duration`。
IMU 支持 `--serial`、`--duration`、`--timeout-ms`、`--max-timeouts`、`--min-fps-ratio`，
并有独立的 `--accel-fps`、`--gyro-fps` 和 `--output`。

各命令还有自己的帮助页，例如：

```bash
uv run camera-realsense depth --help
uv run camera-realsense imu --help
uv run camera-realsense set-option --help
```

## 6. 如何判断实验结果

视频采集结果包含每路实际帧数、完整新帧组数、采集时间、平均帧率、最长无新帧间隔、
超时次数、有效深度帧数和停止原因。双流与 IMU 按每路帧号去重，重复的慢速帧不重复计数。

- `PASS`：本次请求收到所需各路数据、没有超过设定阈值的停帧；涉及深度时至少有一帧包含有效深度。按时长结束时，各路平均帧率还须达到请求值的 50%（可调整）。
- `FAIL`：没有所需数据、发生过超时、平均帧率过低、未达到显式帧数目标、深度始终全为 0，或没生成有效点云/对齐结果。
- `average_fps` 是整个采集区间的均值，包含首帧等待；短实验可能受首帧等待影响，稳定性测试建议 30 秒。`low_fps_streams` 指出帧率不足的流。短截图/单次点云和帧数目标提前结束时，不判定平均帧率，也不证明长时间稳定。
- 正常退出码为 `0`，测试失败/设备错误为 `2`，手动中断为 `130`。关窗会结束当前测试，并根据已收数据给出结果。
- `color_statistics` 给出最后一帧彩色图的像素范围、均值和标准差；接近全黑会额外提示，但黑暗场景本身不作为传输失败依据。

程序使用轮询和每路超时检测，达到超时上限后停止并释放相机。
不会自动刷固件、硬件复位、修改 USB 电源管理或不断重启来掩盖采集中断。
起流成功后，`record` 和 `imu` 会输出各自的统计 JSON；视频可加 `--output-dir` 保留统计。

### 实机短测记录（2026-10-14）

设备为 D455F，序列号 `341522300932`，固件 `5.17.0.10`，SDK `2.59.1.11053`，USB `2.1`。
以下是模块拆分前若干独立短实验的记录，不是连续稳定性或测距精度保证。

| 功能 | 实测结果 |
| --- | --- |
| 信息、标定、选项 | 读取成功；临时投射器设置成功写入并恢复 |
| 深度 | 最新 6 秒收到 27 帧，约 4.50 FPS；此前轮次有停帧 |
| 彩色 | 最新 6 秒收到 25 帧，约 4.17 FPS；此前有零帧超时；预热后图像不再接近全黑 |
| 红外 | 收到灰度图片；一次 6 秒短测为 13 帧，约 2.17 FPS，低于请求值 |
| 对齐 | 最新 6 秒收到 25 帧深度、24 帧彩色，并得到有效对齐深度 |
| IMU | 两路均有数据；一次 3 秒短测约 12–13 Hz，明显低于请求的 200 Hz，因此判 FAIL |
| 截图 | 成功保存 16 位深度、RGB、元数据及统计；预热 5 帧后的 RGB-D 截图成功 |
| 点云 | 已实际导出几何和彩色 PLY；预热 5 帧的彩色实验导出 349 个有效点 |
| 录像 | 深度和 RGB-D 的 `.db3` 录制成功；SQLite 完整性检查通过，并确认包含图像消息 |
| 预览 | Tk 窗口成功创建并显示图像，限时结束后释放相机 |

模块拆分后再次检查：设备信息读取、深度截图、彩色点云、对齐和深度录像均成功；
4 秒对齐得到 15 组双流帧和有效对齐深度，4 秒录像得到 17 帧，SQLite 完整性检查通过。
IMU 在 3 秒内收到 accel 35 帧、gyro 36 帧，约 11.66 / 12.00 Hz，
低于请求的 200 Hz，仍按原有帧率规则判为 `FAIL`。本次拆分没有解决该采样率问题。
复核的输出和完整日志保存在 `/tmp/realsense-refactor/`，属于临时测试数据。

离线测试覆盖无帧退出、单路停帧、低帧率判定、设置恢复、原始深度精度、
点云米制坐标、RGB 映射，以及模块拆分后 pipeline 在报错和中断时的资源释放，共 10 项通过。
支持列表和单次 PASS 不等于所有功能在当前连接上始终稳定；建议按上述命令继续做 30 秒实验。

## 7. 开发检查

生成数据默认写入 `captures/`，已被 Git 忽略。类型检查和离线测试：

```bash
uv run pyright
uv run python -m unittest discover -s tests -v
```

离线测试通过 SDK 的软件设备构造帧，不需要连接实体相机。
类型检查范围为 `src/`、`tests/` 和类型声明生成脚本。
`typings/` 为 Pylance / Pyright 提供 SDK 类型信息，运行相机程序不依赖它。
升级 `pyrealsense2` 后如需重新生成类型声明：

```bash
uv run python scripts/generate_realsense_stubs.py
uv run pyright
```

## 8. 参考资料

- [D400 官方数据手册，USB 2.0 模式见第 84–85 页](https://realsenseai.com/wp-content/uploads/2024/10/Intel-RealSense-D400-Series-Datasheet-October-2024.pdf#page=84)
- [RealSense SDK Python 文档](https://realsenseai.github.io/librealsense/python_docs/)
- [Linux 权限规则](https://github.com/realsenseai/librealsense/blob/master/config/99-realsense-libusb.rules)
- [当前 SDK 的录制与回放格式](https://github.com/realsenseai/librealsense/blob/master/doc/record-and-playback.md)
