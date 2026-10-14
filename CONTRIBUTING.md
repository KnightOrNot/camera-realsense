# 开发与修改指南

[项目首页](README.md) · [模块架构](docs/index.md) · [CLI](docs/reference/cli.md) · [配置](docs/reference/config.md)

## 开发环境与入口

```bash
uv sync
uv run camera-realsense --help
uv run pyright
uv run python -m unittest discover -s tests -v
```

命令入口由 `pyproject.toml` 的 `[project.scripts]` 注册为 `camera_realsense.cli:main`。
普通 Python 源码或 TOML 修改在下次执行时读取；修改依赖、入口或构建配置后运行 uv sync。
不要手动改 `.venv/bin/camera-realsense` 或 uv.lock 的依赖内容。
更新依赖使用 uv 的解析/同步命令，并检查锁文件变化。

代码位于 src/camera_realsense，tests 是离线测试；scripts 中其他独立程序不在主 CLI 调用链内。
Python 配置对象共享 models，参数注册放 arguments，默认值和结构校验放 configuration，
实验流程放 experiments。不要把新功能重新集中到 __init__.py 或 argparse 回调中。

## 修改现有默认参数

现在默认值的唯一数值来源是 config/default.toml，无需改 Python 的数字常量。

1. 找到对应公共分组或 commands 表，按 [配置参考](docs/reference/config.md) 修改字段。
2. 查看命令级同名字段和本次 CLI 参数是否覆盖公共值。
3. 运行对应命令的 --help，检查默认值确实更新。
4. 用支持的相机 profile 做短测；稳定性验证再延长到 30 秒。
5. 同步配置/CLI 文档中“仓库默认值”的表格，并记录变更。

例如要改变全局视频默认 FPS，编辑 video.fps；只改变 depth，编辑 commands.depth.fps。
改变全局 width/height 不会覆盖已有命令表中的尺寸。
无论 TOML 设成什么，单次 `--fps 15` 都应覆盖它，`--no-preview` 应覆盖 preview=true。

不打开相机也能检查有效配置：

```bash
uv run python -c "from camera_realsense.cli import build_parser; p=build_parser(); a=p.parse_args(['depth']); print(a.width, a.height, a.fps, a.preview)"
uv run python -c "from camera_realsense import ExperimentConfig; print(ExperimentConfig.from_defaults('depth'))"
```

自定义配置必须是完整文件。开发测试应复制 TOML 到临时目录或使用测试中的临时文件，
避免为一项测试把仓库默认值永久改成特定相机的 profile。

## 修改参数定义或验证

每个参数有独立 add_*_argument() 函数。args 类型校验负责显式 CLI 输入；
configuration.convert_default() 负责 TOML 的严格类型和范围校验。
两处都要同步，否则可能出现 CLI 拒绝、配置接受的不同规则。

布尔参数采用 argparse.BooleanOptionalAction，支持 --preview / --no-preview 等成对形式。
不要用 `explicit_value or config_value` 合并：它会错误覆盖 false、0 和清空路径。
本项目给 argparse 注入配置默认值，再让显式参数正常覆盖，保留这些值的含义。

配置 schema 位于 configuration.GROUP_FIELDS 和 COMMAND_FIELDS。
公共分组字段必须齐全；命令级字段必须适用于该命令。
新的数值默认值写入 TOML，参数注册函数只定义名称、类型、choices 和帮助文字。

## 新增一个参数

按从功能到入口的顺序实现，再将它注册到需要的命令：

1. 在功能模块写独立函数或扩展已有算法函数，明确输入、单位和返回结果。
2. 在 models 的对应配置类型添加字段。
3. 在 configuration 添加合法字段、类型/范围转换；按需调整命令字段集合。
4. 在 default.toml 的公共分组或对应命令表添加实际默认值。
5. 在 arguments 添加独立注册函数，无数值 default。
6. 在 cli.add_video_arguments()/add_capture_arguments()/build_parser() 接入合适命令。
7. 检查 ExperimentConfig.from_values() 是否能把新字段传入配置。它按 fields() 自动收集三组配置字段；ExperimentConfig 自身新增字段需要显式接入。
8. 在 experiments 将配置值传给功能函数，不让算法读取 Namespace。
9. 写验证覆盖规则与关键行为的测试，更新 CLI、配置和变更文档。

例如，未来新增仅供点云使用的 voxel-size 时，注册函数可以写成：

```python
import argparse

from camera_realsense.arguments import nonnegative_float


def add_voxel_size_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--voxel-size", type=nonnegative_float,
                        help="点云降采样体素边长（米）；0 表示关闭")
```

这是扩展示例，当前程序没有 --voxel-size。还必须完成模型、命令 schema、TOML 默认值和
点云算法接入；单独注册参数不会实现降采样。命令专属字段不要误加到所有视频命令的支持范围。
若把刷新间隔、FPS 窗口或预览尺寸扩展为配置，也按同样步骤处理它们的校验和传递。

## 新增命令

先决定是视频实验、运动实验，还是不采集的设备操作。

- 与现有视频命令同一模式：在 build_parser 注册说明，复用参数函数；更新 video_mode 和配置 COMMAND_FIELDS。
- 新视频模式：同时扩展 capture.configure_video 的请求流、profile 检查和实验回调。
- 新独立流程：在 experiments 定义入口函数并在 execute_command 分发，不仅添加命令名称。
- 非采集命令：按需返回结构化数据，由 CLI 负责输出和退出码；不用强行创建预览窗口。

为新命令建立 TOML 表或声明公共继承，更新 CLI 的支持范围和安装后的帮助页。
当前 run_video/run_imu 返回状态码；直接 Python 调用仍可能抛异常，CLI 把已处理的异常转为退出码。

## 修改图像处理、预览和输出

| 修改目标 | 具体位置和注意点 |
| --- | --- |
| 新增深度滤波 | processing 定义处理函数，experiments 选择使用输入帧还是处理帧；明确保存数据的含义 |
| 改测距像素/单位 | measure_depth；不能把深度 raw 值直接当毫米；使用 SDK units |
| 改点云过滤或颜色 | cloud_arrays / export_pointcloud；保持米制坐标和 RGB 通道，处理非有限与无效 UV |
| 改原始图保存 | prepare_snapshot / save_images；保持 16 位 depth.png 和 depth.npy 一致 |
| 改预览布局 | show_preview / Preview.show；不在未启用 preview 时创建 Tk |
| 改单行文字或频率 | format_capture_status / CaptureStatus.refresh；滚动 FPS 不能用请求值替代 |
| 改结果判定 | summarize_video / summarize_imu / slow_streams；人工中断 reason 和退出码分别处理 |
| 改输出目录规则 | storage.output_path 和实验层的路径选择；注意相对 cwd、覆盖与时间戳 |
| 改录像格式 | prepare_recording / enable_recording；必须核对实际 SDK 版本，不能只改后缀 |

preview_session 和 pipeline_session 必须覆盖异常/中断路径。新增日志通过 diagnostics.log，
使采集中消息进入单行状态；直接 print 会重新造成刷屏。大体量统计写 JSON，而不是逐帧输出。

## 测试范围

| 测试文件 | 保护的行为 |
| --- | --- |
| tests/test_configuration.py | 公共/命令/显式优先级、false/0/空路径、配置校验、文件路径、帮助页、Python 默认值 |
| tests/test_display.py | 双流独立 FPS、停帧回落、单行刷新、重定向、预览开关与清理、参数非法输入 |
| tests/test_experiments.py | 每路超时、低 FPS、设置恢复、pipeline 清理、16 位深度、米制/RGB 点云、截图预览去重 |

离线测试通过 SDK 软件设备构造帧，验证数据和失败路径；它不能代替实体 USB 传输或测距精度实验。
配置优先级测试使用 tests/fixtures/default.toml 的固定数据，不受运行默认值修改影响。
修改纯文档时检查链接、示例命令和默认值表即可，不需要每次重新跑实体相机。
新功能或行为变更应加有意义的回归测试，不只检查“调用了新函数”。

```bash
uv run pyright
uv run python -m unittest discover -s tests -v
uv run camera-realsense info --profiles
uv run camera-realsense depth --duration 5 --output-dir captures/dev_check
```

若涉及预览，再做一次带 preview 的短测，确认关窗释放相机；若涉及录像，检查有效帧和文件完整性。
实机测试一次只运行一个命令，保存实际 profile、counts、average_fps 和停止原因。

## 文档与变更记录

README 保留快速入口；docs/index 维护结构；installation 维护环境；cli 维护完整命令和参数；
config 维护字段和优先级；errors 维护错误解释。新增或删除参数应同时更新 CLI/config 文档。
当前没有自动生成文档的构建器，Markdown 可直接在编辑器或 GitHub 阅读。

CHANGELOG 描述最终行为和验证证据，不将历史短测写成设备长期稳定性保证。
只在实际版本发布时新增发布条目并同步 pyproject 版本，当前 0.1.0 是开发状态。
LICENSE 当前只记录未选定许可证，不是 MIT 或 Apache 许可声明。
