# CLI 命令与参数参考

[文档首页](../index.md) · [配置与默认值](config.md) · [排障](errors.md) · [开发指南](../../CONTRIBUTING.md)

## 调用规则

```bash
uv run camera-realsense --help
uv run camera-realsense depth --help
uv run camera-realsense --config config/default.toml depth --fps 30 --preview
```

语法是 `camera-realsense [--config PATH] <子命令> [参数]`。
`--config` 也可放在子命令后；配置文件与显式参数的优先级见 [配置参考](config.md)。
下面列出的数值是仓库当前 `config/default.toml` 的值；修改配置后，以对应命令的
`--help` 中显示的有效默认值为准。修改默认值无需改参数注册函数。

## 全部命令

| 命令 | 输入或作用 | 仓库默认值 |
| --- | --- | --- |
| `info` | 设备、USB、传感器与可用模式 | 不起流，默认不展开所有模式 |
| `calibration` | 读取已有内参、外参和深度单位 | 640×480 @30 的模式 |
| `options` | 列出传感器选项 | depth 传感器 |
| `set-option` | 修改并读回一个选项 | 5 秒后恢复；option/value 未设 |
| `depth` | 深度图和像素测距 | 480×270 @30 |
| `color` | RGB 彩色图 | 424×240 @30 |
| `infrared` | 左红外灰度图 | 480×270 @30，index 1 |
| `rgbd` | 深度和彩色双流 | 两路 640×480 @30 |
| `align` | 将深度对齐到彩色视角 | 两路 640×480 @30 |
| `imu` | 加速度计与陀螺仪 | 两路 200 Hz，保存 CSV |
| `snapshot` | 保存一组完整图像 | depth，640×480 @30 |
| `pointcloud` | 导出第一个非空点云 | depth，640×480 @30，灰色 PLY |
| `record` | SDK 原始流录像 | depth，640×480 @30，`.db3` |

只有下表明确列出的参数适用于对应命令。没有 `rgb` 子命令；彩色命令是 `color`，
状态行将其显示为 `mode=rgb`。没有回放子命令，也没有从 CLI 同时录制 IMU 的参数。

## 参数适用范围

- 所有命令：`-h` / `--help`、`--config`、`--serial`。
- 四个非采集命令：参数在各自命令段中完整列出。
- 八个视频命令 `depth/color/infrared/rgbd/align/snapshot/pointcloud/record`：支持下面“视频通用参数”的全部项。
- `imu`：支持采集控制参数中的 `--duration`、`--timeout-ms`、`--max-timeouts`、`--min-fps-ratio`，以及自己的采样率和输出参数。

### 所有命令共用的参数

| 参数 | 仓库默认值 | 说明 |
| --- | --- | --- |
| `-h` / `--help` | 不触发 | 查看该层帮助并退出，不访问相机 |
| `--config PATH` | 项目 `config/default.toml` | 完整 TOML 文件；路径按当前工作目录解析 |
| `--serial SERIAL` | `""`，自动选择 | 多台相机时指定序列号；显式 `--serial ""` 可清除配置中的序列号 |

### 视频通用参数

| 参数 | 仓库默认值 | 取值和行为 |
| --- | --- | --- |
| `--width W` | 见命令总览 | 正整数；主流宽度 |
| `--height H` | 见命令总览 | 正整数；主流高度 |
| `--fps FPS` | `30` | 正整数；请求的主流帧率，不是固定软件上限 |
| `--color-width W` | `0`，跟随 width | 非负整数；0 清除彩色宽度覆盖 |
| `--color-height H` | `0`，跟随 height | 非负整数；0 清除彩色高度覆盖 |
| `--color-fps FPS` | `0`，跟随 fps | 非负整数；0 清除彩色帧率覆盖 |
| `--duration SECONDS` | `15` | 非负有限数；0 表示不限时；正数为起流完成后的最长秒数，不包含 SDK 初始化 |
| `--frames N` | `0` | 非负整数；完整新帧组目标；0 只按时长，先达到目标或时长即结束 |
| `--warmup-frames N` | `0` | 非负整数；收到 N 组完整帧后再保存、对齐、生成点云和预览 |
| `--timeout-ms MS` | `5000` | 正整数；每路连续无新帧多久算一次超时 |
| `--max-timeouts N` | `2` | 正整数；任一路连续超时 N 次后提前停止 |
| `--min-fps-ratio RATIO` | `0.5` | 0–1 的有限数；按时长结束时平均 FPS/请求 FPS 的最低比例；0 关闭此项判定 |
| `--pixel X Y` | `[]`，中心像素 | 两个非负整数；有深度流时必须位于输入深度图内 |
| `--max-depth METERS` | `3` | 大于 0 的有限数；深度伪彩上限和点云截断距离，不改变相机硬件量程 |
| `--preview` / `--no-preview` | `false` | 创建或关闭图像窗口；显式关闭可覆盖 TOML 的 true |
| `--output-dir PATH` | `""`，不指定 | 保存第一组可处理图像、元数据和统计；`snapshot` 未指定时生成时间戳目录 |

单彩色模式的“主流”是 color：最终彩色参数取 `color_*` 覆盖值或主流值。
深度和彩色双流时主流是 depth。无彩色流时 `color_*` 不起作用；无深度流时 `pixel` 不使用。
`max_depth` 只影响深度显示和点云处理，不修改保存的原始深度。

预热帧仍计入帧数、平均帧率和超时；`--frames` 目标也包含预热帧。
例如 `--warmup-frames 5 --frames 5` 会在能保存之前结束，截图/点云可能判为 FAIL。
预览窗口本身在起流后创建，预热完成后才显示图像。

`--duration 0` 仅关闭时长上限，适用于全部视频命令和 IMU。
Ctrl+C、关窗、帧数目标和每路停帧超时仍可结束采集；未加 preview 的截图/点云仍在保存后结束。
负值、inf 和 NaN 继续被拒绝。

```bash
uv run camera-realsense rgbd --duration 0 --preview
uv run camera-realsense imu --duration 0 --output captures/imu.csv
```

显式 `--output-dir ""` 清除配置中的目录。对 `snapshot` 来说，清除后仍使用自动目录，
因为保存截图是该命令的功能。`--output` 同理：清除指定路径后，IMU/点云/录像仍自动生成输出路径。

## info

参数：共用参数，另有 `--profiles` / `--no-profiles`（默认 false）、`--output PATH`（默认不保存）。

```bash
uv run camera-realsense info
uv run camera-realsense info --profiles --output captures/profiles.json
uv run camera-realsense info --serial 341522300932
```

返回设备名称、序列号、固件、USB 描述和传感器。`--profiles` 展开当前连接提供的模式，
包括 stream、index、format、FPS，以及视频宽高。该列表不能证明某个多流组合一定可起流。
`--output` 将最终信息字典保存为 JSON；输出路径相对于当前工作目录。

## calibration

参数：共用参数，加 `--width`、`--height`、`--fps`、`--output`；前三项默认 640、480、30。

```bash
uv run camera-realsense calibration --output captures/calibration.json
uv run camera-realsense calibration --width 640 --height 480 --fps 30
```

读取所选模式已有的 depth/color 内参（fx/fy/ppx/ppy、畸变模型和系数）、
深度单位和 depth→color 旋转/位移。位移为米，深度数值单位在 `depth_units_m` 中。
只读取标定，不运行 self-calibration 或 tare，也不采集图像或显示预览。
指定模式必须同时有对应深度和彩色 profile。

## options

参数：共用参数，加 `--sensor depth|color|motion`，默认 depth。

```bash
uv run camera-realsense options --sensor depth
uv run camera-realsense options --sensor color
uv run camera-realsense options --sensor motion
```

列出选项名、当前值、范围、步长、默认值和只读状态。
某些声明支持的遥测选项只在起流时可读，命令会逐项报告读取失败并继续枚举。
没有文件输出参数，也没有图像预览参数。

## set-option

参数：共用参数，加 `--sensor`（默认 depth）、`--option NAME`、`--value NUMBER`、
`--restore-after SECONDS`（默认 5，非负有限数）。

```bash
uv run camera-realsense set-option --option emitter_enabled --value 0
uv run camera-realsense set-option --sensor depth --option enable_auto_exposure --value 0 --restore-after 0
uv run camera-realsense set-option --sensor depth --option enable_auto_exposure --value 1 --restore-after 0
```

仓库配置没有实际 option/value，必须提供这两个参数；若在 `[commands.set-option]`
设置了它们，则允许省略，并由显式参数覆盖。写入前检查支持、只读和范围，写后读回确认。
正数 restore_after 表示等待后恢复原值，Ctrl+C 也走恢复逻辑；0 表示保留新值。
保留值会影响后续实验，恢复时使用此前记录的原值。曝光单位应结合对应传感器选项说明，
不要假设深度和彩色曝光取值单位完全相同。没有图像预览参数。

## depth

支持全部视频通用参数。默认 480×270 @30，格式 z16。

```bash
uv run camera-realsense depth --duration 30
uv run camera-realsense depth --fps 30 --preview --duration 30
uv run camera-realsense depth --pixel 240 135 --output-dir captures/depth --duration 30
```

测距值为米，默认使用输入图中心。`invalid` / 距离 0 代表无有效深度；中心像素无效不代表
整幅图无效。图像全为 0 会判 FAIL。最后一次测距和有效比例在 `summary.json` 的
`depth_measurement` 中；没有指定目录时只显示状态，不保存统计。

## color

支持全部视频通用参数。默认 424×240 @30，请求 rgb8；状态模式为 rgb。

```bash
uv run camera-realsense color --duration 30
uv run camera-realsense color --width 640 --height 480 --fps 30 --preview --duration 30
uv run camera-realsense color --warmup-frames 5 --output-dir captures/color
```

SDK 转换为 RGB，保存的 `color.png` 也是 RGB。最后一帧 min/max/mean/std 在
`color_statistics` 中；接近全黑会提示，但黑暗场景本身不作为传输失败依据。

## infrared

支持全部视频通用参数。默认 480×270 @30，左红外 index 1，格式 y8。

```bash
uv run camera-realsense infrared --preview --duration 30 --output-dir captures/infrared
```

保存 `infrared.png` 为 8 位灰度。本命令只启用一路左红外，没有右红外或左右同时输出开关。

## rgbd

支持全部视频通用参数。默认两路 640×480 @30。

```bash
uv run camera-realsense rgbd --fps 30 --preview --duration 30
uv run camera-realsense rgbd --width 480 --height 270 --fps 5 \
  --color-width 424 --color-height 240 --color-fps 5 --duration 30
```

分别统计两路新帧。每路实际 profile 和 FPS 单独显示。
先验证单流，再测试不同分辨率或双流组合；组合是否支持以实际起流和统计结果为准。
计数的“完整帧组”不是严格硬件时间同步保证。

## align

支持全部视频通用参数。默认两路 640×480 @30，深度对齐到 color。

```bash
uv run camera-realsense align --preview --duration 30 --output-dir captures/aligned
```

保存的 depth.png/depth.npy 是对齐后深度，尺寸遵循彩色视角；状态行显示的是原始输入 profile。
状态行和 `depth_measurement` 的像素测距发生在对齐之前，仍使用原始深度坐标。
对齐会产生无有效深度区域；没有任何有效对齐帧会判 FAIL。

## imu

参数：共用参数，采集控制中的 duration/timeout-ms/max-timeouts/min-fps-ratio，
另有 `--accel-fps`（默认 200）、`--gyro-fps`（默认 200）、`--output PATH`。
两路频率参数必须是正整数，具体支持值见 `info --profiles`。

```bash
uv run camera-realsense imu --duration 15 --output captures/imu.csv
uv run camera-realsense imu --accel-fps 100 --gyro-fps 200 --duration 15
```

只打开运动流，单行显示两路实测 Hz。没有 width/height/fps/frames/warmup-frames/preview 参数。
默认路径为 `captures/imu_<时间戳>.csv`，同名 `.json` 保存统计。
CSV 列：stream、frame_number、timestamp_ms、timestamp_domain、x、y、z、unit。
加速度单位 m/s²，包含重力；角速度 rad/s，不是角度或姿态。

## snapshot

支持全部视频通用参数，加 `--stream depth|color|infrared|rgbd`，默认 depth。
默认分辨率始终来自 snapshot 配置（640×480），不会因 stream=color 自动切换到 color 命令的默认值。

```bash
uv run camera-realsense snapshot --stream depth --output-dir captures/snapshot_depth
uv run camera-realsense snapshot --stream color --width 424 --height 240 --output-dir captures/snapshot_color
uv run camera-realsense snapshot --stream rgbd --warmup-frames 5 --preview --output-dir captures/snapshot_rgbd
```

不加 preview 时，第一组可处理完整图像保存后退出；全零深度仍保存以供诊断，但判 FAIL。
加 preview 时保存一次后继续采集至时长/帧数目标或关窗。
未指定目录时为 `captures/snapshot_<时间戳>/`。没有独立 `--output` 文件路径参数。

## pointcloud

支持全部视频通用参数，加 `--colored` / `--no-colored`（默认 false）和 `--output PATH`。
纯几何点云只开深度；colored 开两路并映射真实 RGB，没有 `--stream` 参数。

```bash
uv run camera-realsense pointcloud --output captures/depth_cloud.ply
uv run camera-realsense pointcloud --colored --warmup-frames 5 --output captures/rgb_cloud.ply
uv run camera-realsense pointcloud --max-depth 6 --duration 30 --preview
```

过滤非有限点、z≤0、距离超过 max_depth 的点；彩色点云还剔除无有效颜色映射的点。
坐标单位米，x 向右、y 向下、z 向前；纯几何点使用统一灰色。
导出二进制 little-endian PLY，同名 JSON 保存统计。默认 `captures/cloud_<时间戳>.ply`。
无有效点时不生成空 PLY，并判 FAIL。preview 显示输入图像，当前不提供交互式 3D 点云窗口。
不加 preview 时首个非空点云导出后退出；加 preview 时导出一次后继续采集。

## record

支持全部视频通用参数，加 `--stream depth|color|infrared|rgbd`（默认 depth）、`--output PATH`。

```bash
uv run camera-realsense record --stream depth --duration 30 --output captures/depth.db3
uv run camera-realsense record --stream rgbd --duration 30 --preview --output captures/rgbd.db3
```

当前安装的 SDK 2.59.1 使用 `.db3`，程序要求该扩展名。
默认 `captures/record_<时间戳>.db3`，同名 JSON 保存统计。
记录原始流与元数据，保留原始深度；不是 MP4。使用这项功能不要求安装 ROS2。
Ctrl+C 停止 pipeline 并关闭录像；文件存在并不证明包含有效图像。
格式与回放能力应结合实际 SDK 版本及[官方录制文档](https://github.com/realsenseai/librealsense/blob/master/doc/record-and-playback.md)核对。
本命令没有 IMU 录像流；运动数据用 imu 输出 CSV。

## 图片和统计文件

指定 output-dir 后保存第一组处理图像；不会逐帧保存，也不会因为 record 而把该目录变为连续图片序列。
同名文件会被覆盖，自动时间戳路径相对于工作目录，时间取运行系统本地时间。

| 文件 | 内容 |
| --- | --- |
| `color.png` | RGB 图片（启用 color 时） |
| `infrared.png` | 8 位灰度（启用 infrared 时） |
| `depth.png` | 16 位原始深度（启用 depth 时） |
| `depth.npy` | 同一幅原始深度数组，保留数值 |
| `depth_preview.png` | 伪彩图，不能用来测距 |
| `frames.json` | 每幅图的 profile、帧号、毫秒时间戳；depth 另含 units_m |
| `summary.json` | 采集完成后的统计、质量和结果 |

像素距离 = `depth_array[y, x] × frames.json 中 depth.units_m`，单位米。
不要直接假定原始值是毫米。SDK 帧时间戳由设备及时间域定义，不一定是墙钟日期。
起流前发生错误时可能没有 summary；配置/权限错误应首先阅读终端错误。

### summary 的主要字段

| 字段 | 含义 |
| --- | --- |
| `result`、`reason` | PASS/FAIL 和停止原因；人工中断另由退出码表达 |
| `device`、`profiles` | 设备信息及实际视频 profile；IMU summary 不包含 profiles |
| `counts`、`complete_frames` | 去重后的各路新帧数和完整新帧组数 |
| `timeouts` | 发生超时检测的次数；多路同轮超时只累加一次 |
| `max_gap_s`、`elapsed_s` | 最长无新帧间隔和起流后统计时间 |
| `average_fps` | 各路整个采集区间的平均频率，包含首帧等待 |
| `low_fps_streams`、`min_fps_ratio` | 帧率不足的流和阈值 |
| `depth_units_m`、`valid_depth_frames` | 视频的深度单位和有效深度帧数 |
| `aligned_valid_frames` | 视频的有效对齐处理次数 |
| `depth_measurement` | 最后一次输入深度测距：pixel、distance_m、units_m、valid_ratio |
| `color_statistics` | 最后一次 RGB 像素范围、均值和标准差 |

### 单行状态、结束原因和退出码

```text
mode=rgbd | depth=640x480@29.8fps | rgb=640x480@29.9fps
```

这是格式示例。分辨率为实际输入模式；FPS 在最近约一秒内按新帧数计算，
每 0.25 秒左右刷新文字，与请求 FPS 或预览绘制次数不同。停止更新后 FPS 会回落到 0。
预览没有额外固定帧率上限，但绘制、处理和传输耗时可能降低实际采集速度。
终端过窄会截断后部提示；重定向时只输出一条最终状态，不保留过程刷新。

停止原因可能为 `duration`、`frame target`、`artifact saved`、`timeout limit`、`window closed`、`interrupted`。
超时按每路跟踪；达到任一路连续超时上限即停止。正数 duration 也能先于超时上限结束。
按时长结束时才做最低平均 FPS 判定；首个截图/点云或帧数目标结束不证明长期稳定。
duration=0 不会以 duration 原因结束，因此不触发该平均 FPS 判定；统计与超时检测仍保留。

视频 PASS 要求各路有数据、至少一个完整新帧组、无已记录超时，显式帧数目标满足，
涉及深度时有有效深度；截图、点云、对齐还各自要求相应有效结果。
IMU PASS 要求两路有数据、无已记录超时且通过适用的平均频率判定。
Ctrl+C 可显示 INTERRUPTED，而 JSON 的质量 result 仍按已收到的数据判定，应同时看 reason。
关窗不是 Ctrl+C，结果按已有数据判定。

| 退出码 | 含义 |
| --- | --- |
| `0` | 命令完成或采集判定 PASS |
| `2` | 参数/配置/设备错误，或采集 FAIL |
| `130` | Ctrl+C 人工中断 |
