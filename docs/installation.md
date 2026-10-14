# 安装与环境准备

[文档首页](index.md) · [CLI 参考](reference/cli.md) · [排障](reference/errors.md)

## Python 和 uv

在项目根目录运行，系统应有 uv 和项目要求的 Python 3.11 或更高版本。
仓库 `.python-version` 当前选择 3.11；`uv.lock` 记录实际解析的依赖版本。

```bash
uv sync
uv run python --version
uv run camera-realsense --help
```

如果从别的目录启动，使用 `uv run --project /实际路径/camera-realsense camera-realsense info`。
默认配置路径按源码位置定位，工作目录改变不会切换默认配置文件；
输出的相对路径仍按运行时工作目录解析。

项目的主程序使用 `pyrealsense2`、NumPy 和 Pillow。`pyproject.toml` 还保留 OpenCV、
pyzmq、tyro 等依赖，安装时会一并同步；无窗口主程序不使用这些包的预览或网络功能。
开发依赖包含 Pyright 和 pybind11-stubgen，普通 `uv sync` 会安装当前配置中的 dev 组。

`pyrealsense2` 的二进制包已经提供 SDK 绑定。本项目无需先 clone 并编译 librealsense。
若某平台或 Python 版本没有适配的二进制包，需要单独处理 SDK 安装；
这与运行本项目的 uv 命令是两个步骤。

## Linux 设备权限

发现 USB、HID/IMU 或 `scan_elements` 的 `Permission denied` 时，安装
[SDK 官方 udev 规则](https://github.com/realsenseai/librealsense/blob/master/config/99-realsense-libusb.rules)：

```bash
curl -fL https://raw.githubusercontent.com/realsenseai/librealsense/master/config/99-realsense-libusb.rules \
  -o /tmp/99-realsense-libusb.rules
sudo install -m 644 /tmp/99-realsense-libusb.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

随后拔下并重新插入相机。正常采集使用自己的用户环境，无需 `sudo uv run`。
以上命令会修改系统 udev 规则，本项目本身不会自动执行它们。

## 可选图像预览

无窗口采集不需要 Tk 或桌面。使用 `--preview` 时要求当前 Python 可以导入 `tkinter`，
并且进程能访问图形桌面。

```bash
uv run python -c "import tkinter; print(tkinter.TkVersion)"
uv run camera-realsense depth --duration 5 --preview
```

Ubuntu 系统 Python 缺少 Tk 时可安装 `sudo apt install python3-tk`。
uv 下载或 pyenv 编译的 Python 不一定使用系统 Python 的模块，安装后仍需用上面的
`uv run python` 检查。远程无桌面环境可用 `--no-preview`，覆盖配置中的 `preview=true`。

## 初次连接检查

```bash
lsusb -t
uv run camera-realsense info --profiles --output captures/profiles.json
uv run camera-realsense depth --duration 10 --output-dir captures/first_depth
```

依次确认设备枚举、支持的模式和有效深度。随后再测试 RGB、红外、IMU、双流和点云。
相机一次只交给一个采集进程，先关闭其他 Viewer、预览或相机服务。

`usb_type_descriptor=2.1` 对应当前 USB 2.0 速率连接；系统 USB 树中的 `480M` 是链路速率，
不是实际图像有效吞吐量。USB 版本和 FPS 的关系见 [排障](reference/errors.md)。

## 编辑器与开发检查

VS Code 打开项目根目录，选择 `.venv/bin/python`；仓库 `.vscode/settings.json`
已设置默认解释器和 `typings/` 路径。

```bash
uv run pyright
uv run python -m unittest discover -s tests -v
```

`typings/` 为 SDK 原生扩展提供编辑器类型信息，运行程序不依赖它。
升级 SDK 后应核对声明与实际 API 是否一致，不能靠关闭所有类型诊断解决不匹配。
离线测试使用 SDK 软件设备，不需要实体相机；受限容器/沙箱仍可能禁止初始化 udev monitor，
遇到此情况应在允许访问系统设备枚举服务的环境运行测试。

## 配置文件的部署

默认读取项目的 `config/default.toml`。如使用不同配置：

```bash
cp config/default.toml /tmp/realsense-test.toml
uv run camera-realsense --config /tmp/realsense-test.toml depth --help
```

自定义文件必须包含完整公共分组，不能只提供部分覆盖。配置缺失或不合法会直接报错，
不会退回隐藏的数值默认值。仓库配置在包源码目录之外；单独安装构建出的包时，
应自行携带完整 TOML 文件并通过 `--config` 指定，不假定 wheel 自动附带仓库级配置。
