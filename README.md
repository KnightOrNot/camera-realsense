# camera-realsense

用 `pyrealsense2` 进行 RealSense 深度、RGB、红外、IMU、对齐、截图、点云和录像实验。
当前已在 D455F 上验证。直接安装 Python 包即可运行本项目，无需自行编译 librealsense。

采集时单行刷新输入模式、实际分辨率和实测 FPS；所有图像采集命令共用 `--preview`。
默认参数集中在 [config/default.toml](config/default.toml)：
**显式命令行参数 > 对应命令的配置 > 公共配置**。

## 快速开始

在项目根目录执行：

```bash
uv sync
uv run camera-realsense info --profiles
uv run camera-realsense depth --duration 30 --preview
```

当前配置的默认视频帧率为 30 FPS；实际默认值以 TOML 为准。显式指定帧率的实验：

```bash
uv run camera-realsense depth --fps 30 --duration 30 --preview
uv run camera-realsense rgbd --fps 30 --duration 30 --preview
```

持续采集到 Ctrl+C 或关窗时使用 `--duration 0`：

```bash
uv run camera-realsense rgbd --fps 30 --duration 0 --preview
```

0 仅取消时长上限，帧数目标、截图/点云保存完成和停帧超时仍可结束采集。

先根据 `info --profiles` 选择支持的分辨率和帧率；单流模式可用不保证双流组合稳定。
Linux 设备权限和 Tk 安装步骤见 [安装指南](docs/installation.md)。
`uv run` 本身不会启动程序，必须给出 `camera-realsense` 和子命令。

## 修改默认参数

要让所有未显式指定帧率的视频命令默认请求 30 FPS，修改 TOML：

```toml
[video]
fps = 30
```

只修改深度命令，在已有 `[commands.depth]` 表里加入：

```toml
[commands.depth]
width = 480
height = 270
fps = 30
```

以上是修改现有表的示例，不要在同一个文件中重复创建同名表。
下次运行会重新读取文件，不需要重新编译 SDK。
若配置打开了预览，单次命令仍可用 `--no-preview` 覆盖。
完整配置格式、优先级和 Python 调用方法见 [配置参考](docs/reference/config.md)。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [文档首页](docs/index.md) | 阅读路线、模块职责和数据流 |
| [安装指南](docs/installation.md) | uv 环境、Linux 权限、Tk、Pylance |
| [CLI 参考](docs/reference/cli.md) | 全部 13 个命令、全部参数、输出格式与退出码 |
| [配置参考](docs/reference/config.md) | TOML 所有字段、默认值、覆盖规则及修改实例 |
| [排障参考](docs/reference/errors.md) | 无设备、超时、低 FPS、权限、预览与配置错误 |
| [开发指南](CONTRIBUTING.md) | 如何改代码、新增参数/命令、测试和更新文档 |
| [变更记录](CHANGELOG.md) | 当前实现的变化和验证记录 |

## 开发检查

```bash
uv run pyright
uv run python -m unittest discover -s tests -v
```

离线测试不需要实体相机，但 SDK 软件设备仍需要系统允许初始化 udev monitor。
采集输出默认位于 `captures/`，已被 Git 忽略。相机一次只供一个程序采集。
项目尚未选定开源许可证，状态记录见 [LICENSE](LICENSE)。
