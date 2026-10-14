# 配置文件、默认值与覆盖规则

[文档首页](../index.md) · [CLI](cli.md) · [开发指南](../../CONTRIBUTING.md)

## 生效规则

所有 CLI 参数的默认值集中在 [config/default.toml](../../config/default.toml)。
数值不再分别硬编码在 argparse、CLI 转换函数或配置 dataclass 中。
每次启动会重新读取文件，优先级为：

1. 显式命令行参数。
2. `[commands.<命令名>]` 中针对该参数的值。
3. `[common]`、`[capture]`、`[video]`、`[output]`、`[imu]` 公共分组中的值。

每个字段独立覆盖；显式 `--fps 30` 不会清除配置中的 `color_fps=15`，
需要 `--color-fps 0` 才重新跟随主流。配置不支持环境变量插值或自动加载 `.env`。

默认文件路径按 `configuration.py` 的源码位置定位，不依赖当前工作目录。
自定义文件可在子命令前或后指定；相对配置路径按工作目录解析：

```bash
cp config/default.toml /tmp/realsense-test.toml
uv run camera-realsense --config /tmp/realsense-test.toml depth --help
uv run camera-realsense depth --config /tmp/realsense-test.toml --fps 30
```

`--config` 选择整份配置，不把它与默认文件叠加。
所有公共分组及字段必须保留；命令覆盖值可以按需要增删。
info 的 profiles、options 的 sensor、set-option 的 sensor/option/value/restore_after
没有对应公共字段，必须保留在各自的命令表中。
未知分组、未知字段、命令不支持的字段、错误类型和非法范围都会在访问相机前报错。
即使 CLI 覆盖了一个错误字段，也应先修正配置：整份文件会先校验。

## 全部公共默认字段

键名使用下划线；命令行使用连字符，例如 `timeout_ms` 对应 `--timeout-ms`。
TOML 必须用原生数值/布尔类型，不能写 `fps="30"` 或 `preview="true"`。

| 分组 | 字段 | 仓库值 | 说明 |
| --- | --- | --- | --- |
| common | serial | `""` | 不指定序列号，自动选择唯一相机 |
| capture | duration | `0` | 非负有限秒数；0 表示不限时 |
| capture | timeout_ms | `5000` | 每路无新帧阈值，正整数毫秒 |
| capture | max_timeouts | `2` | 连续超时次数上限，正整数 |
| capture | frames | `0` | 非负完整新帧组目标；0 只按时长；IMU 不使用 |
| capture | warmup_frames | `0` | 非负预热组数；IMU 不使用 |
| capture | min_fps_ratio | `0.5` | 按时长结束时最低平均帧率比例，范围 0–1 |
| video | width | `640` | 主流宽度，正整数 |
| video | height | `480` | 主流高度，正整数 |
| video | fps | `30` | 目标视频 FPS，正整数 |
| video | color_width | `0` | 0 跟随 width，否则正整数 |
| video | color_height | `0` | 0 跟随 height，否则正整数 |
| video | color_fps | `0` | 0 跟随 fps，否则正整数 |
| video | pixel | `[]` | 中心像素；也可 `[X, Y]` 两个非负整数 |
| video | max_depth | `3.0` | 伪彩/点云距离上限，有限且 >0，单位米 |
| video | stream | `"depth"` | snapshot/record 的输入；depth/color/infrared/rgbd |
| video | colored | `false` | pointcloud 是否同时打开 RGB 并映射颜色 |
| output | preview | `false` | 八个视频命令是否显示输入图像 |
| output | output | `""` | info/calibration 的 JSON、IMU 的 CSV、点云 PLY、录像 db3 路径 |
| output | output_dir | `""` | 视频第一组图像和统计的目录 |
| imu | accel_fps | `200` | 加速度计请求 Hz，正整数 |
| imu | gyro_fps | `200` | 陀螺仪请求 Hz，正整数 |

只应用命令支持的字段。例如 video.width 不影响 IMU，output.preview 不让 info 打开窗口。
output.output 按命令有不同语义，通常建议把实际文件路径写在命令表里，避免共用同一路径。

## 命令级默认值

| 命令表 | 仓库覆盖字段 | 最终视频模式或说明 |
| --- | --- | --- |
| commands.info | profiles=false | 不展开完整 profile 列表 |
| commands.calibration | width=640、height=480 | FPS 继承 video.fps |
| commands.options | sensor="depth" | 查询深度设置 |
| commands.set-option | sensor="depth"、restore_after=5、option=""、value="" | option/value 未设置，需要 CLI 输入 |
| commands.depth | width=480、height=270 | FPS 继承 video.fps |
| commands.color | width=424、height=240 | FPS 继承 video.fps |
| commands.infrared | width=480、height=270 | FPS 继承 video.fps |
| commands.rgbd | 空表 | 继承公共默认值 |
| commands.align | 空表 | 继承公共默认值 |
| commands.imu | 空表 | 继承公共控制及 IMU 默认值 |
| commands.snapshot | 空表 | 继承公共默认值，默认 depth |
| commands.pointcloud | 空表 | 继承公共默认值，默认灰色点云 |
| commands.record | 空表 | 继承公共默认值，默认 depth |

命令表只能放该命令支持的参数，完整范围见 [CLI](cli.md)。
`commands.set-option.value` 为有限数值，空字符串是未设置标记；restore_after 是非负有限秒数。
`commands.options.sensor` 和 `commands.set-option.sensor` 为 depth/color/motion。

## 如何修改默认值

以下片段用于编辑已有表，不是完整文件；不要向同一文件重复追加同名表。

### 所有视频默认请求 30 FPS

```toml
[video]
fps = 30
```

保留该表其他字段。所有没有单独 FPS 覆盖的命令会使用 30，包括 calibration 选择的标定模式；
IMU 仍使用 imu 分组的采样率。如果标定想保持 5，可在 commands.calibration 单独写 fps=5。

```bash
uv run camera-realsense depth --help
uv run camera-realsense depth --fps 15 --duration 10
```

第二条命令只在本次使用 15 FPS，不改写 TOML，也不修改设备固件。

### 只修改一个命令

```toml
[commands.depth]
width = 640
height = 480
fps = 30
preview = true
```

其他命令不受这个表影响。关闭本次预览：

```bash
uv run camera-realsense depth --no-preview
```

修改 video.width/height 不会覆盖已有的 depth/color/infrared/calibration 命令级值。
要让某命令继承公共尺寸，删除它对应的 width/height 覆盖；要固定它，直接修改命令表。

### 不限制采集时长

在已有 capture 表中设置 `duration = 0`，所有未被命令表或 CLI 覆盖的采集命令就不限时。
也可只在 `commands.rgbd` 等命令表设置 duration=0，或本次传 `--duration 0`。

```toml
[capture]
duration = 0
```

默认文件仍保留 15 秒。不限时只关闭时间上限，Ctrl+C、关窗、帧数目标、
截图/点云完成保存以及停帧超时仍能退出。负数、inf 和 NaN 不合法。

### 双流分别设置

```toml
[commands.rgbd]
width = 640
height = 480
fps = 30
color_width = 640
color_height = 480
color_fps = 15
```

单次让彩色也跟随 30：

```bash
uv run camera-realsense rgbd --color-fps 0 --duration 30
```

支持的组合仍要通过 `info --profiles` 和实测确认。

### 默认保存目录与关闭布尔项

```toml
[commands.depth]
width = 480
height = 270
output_dir = "captures/default_depth"
preview = true
```

```bash
uv run camera-realsense depth --no-preview --output-dir ""
```

路径按运行时工作目录解析，不按 TOML 所在目录解析。
同一固定路径的文件会被覆盖；需要保留多次实验时，使用不同目录。
`--no-colored`、`--no-profiles` 同样可覆盖 true；`--frames 0` 和 `--min-fps-ratio 0`
不会被“非零默认值”重新覆盖。

### TOML 的空值表示

TOML 没有 null，本项目使用明确的标记：

| 文件值 | 转换后的含义 | CLI 对应操作 |
| --- | --- | --- |
| serial="" | 自动选择 | `--serial ""` |
| output/output_dir="" | 未指定路径 | `--output ""` / `--output-dir ""` |
| color_width/height/fps=0 | 跟随主流 | 对应参数传 0 |
| pixel=[] | 测距中心 | 省略 pixel 使用配置；CLI 指定 X Y 可覆盖 |
| option/value="" | 必需值未设置 | set-option 需提供缺失的参数 |

未指定路径不一定等于不保存：snapshot、IMU、pointcloud、record 仍生成自动时间戳输出。
帮助页的 `None` 表示上述空值已经转换，而不是遗漏默认设置。

## 在 Python 中复用相同默认值

推荐通过命令级工厂创建配置，读取公共分组和该命令的覆盖：

```python
from dataclasses import replace
from pathlib import Path

from camera_realsense import ExperimentConfig
from camera_realsense.experiments import run_video

config = ExperimentConfig.from_defaults("depth")
config = replace(
    config,
    video=replace(config.video, fps=30),
    output=replace(config.output, preview=True, output_dir=Path("captures/python_depth")),
)
exit_code = run_video(config)
```

需要自定义文件时用 `ExperimentConfig.from_defaults("depth", config_path=Path("/tmp/realsense-test.toml"))`。
直接构造 `VideoConfig()` 或 `CaptureConfig()` 会从默认文件的公共分组取值，
不会自动选择 commands.depth；其 width 默认为公共 640，而工厂创建深度配置的 width 为 480。
显式 dataclass 字段覆盖各自默认值；直接 Python 构造参数由调用方保证有效，
不经过 argparse 类型校验。`run_video()` / `run_imu()` 返回状态码，设备或参数异常仍向调用方抛出。

## 新字段或新配置行为应该改哪里

| 需求 | 修改位置 |
| --- | --- |
| 修改现有参数默认值 | 只改 default.toml；检查命令级覆盖及帮助页 |
| 修改取值范围或解析方式 | arguments.py 的校验函数，configuration.py 的 convert_default() |
| 新增参数 | 参数注册函数、CLI 组合、configuration 分组/命令字段集合、TOML、配置模型、功能函数 |
| 新增命令级覆盖 | 在已有命令表写该命令支持的字段；不需要新增 Python 数值默认 |
| 修改默认文件路径 | configuration.DEFAULT_CONFIG_PATH；部署时也可直接用 --config |
| 修改单行刷新频率或预览画布尺寸 | diagnostics.CaptureStatus.refresh()/preview.Preview.show()；当前是内部显示常量，不是 CLI 参数 |

本次参数默认值已集中到 TOML，显示刷新 0.25 秒、FPS 统计窗口约 1 秒、预览画布上限 1280×720
仍是实现内部常量。扩展为配置字段的方法见 [开发指南](../../CONTRIBUTING.md)。
