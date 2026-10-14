# 错误与排障参考

[文档首页](../index.md) · [安装](../installation.md) · [CLI](cli.md) · [配置](config.md)

## 先保留证据

```bash
uv run camera-realsense info --profiles --output captures/profiles.json
uv run camera-realsense depth --duration 30 --output-dir captures/diagnostic_depth
lsusb -t
```

保留完整命令、使用的 TOML、设备信息、统计 JSON 和终端错误。
记录是否加 preview、分辨率、输入流和相机连接路径，比较时使用同一组参数。
程序不会自动刷固件、复位设备、修改 USB 电源管理或反复重启采集。

## 配置文件错误

| 现象 | 检查 |
| --- | --- |
| 找不到配置文件 | 确认文件存在；用 --config 指定完整文件；默认文件不随 cwd 改变 |
| 缺少分组或默认字段 | 自定义文件应复制完整 default.toml，而非只有一个 fps 覆盖 |
| 未知分组/未知参数 | TOML 键使用下划线，命令名与实际子命令相同；检查拼写 |
| 命令不支持参数 | 如 commands.info 不能配置 fps；按 CLI 支持范围选择命令表 |
| 类型错误 | fps=30、preview=true，不要用字符串 "30" 或 "true" |
| 数值范围错误 | 负帧数、零超时、NaN/inf、min_fps_ratio 超过 0–1 都会拒绝 |
| 想把默认预览关闭却仍打开 | 显式传 --no-preview；只省略 --preview 会继续使用 TOML 的 true |
| 改了公共宽高却没变化 | 对应 commands 表可能还有 width/height 覆盖，或 CLI 显式传了值 |

配置错误在打开相机前发生，退出码为 2；修配置即可，不需要反复插拔相机。

## 未找到相机或多台相机

“未找到相机”可能是设备未接入、序列号筛选不匹配或权限不足。
检查 `lsusb -t` 和 info；配置了 serial 时可用 `--serial ""` 临时自动选择。
多台相机必须显式指定 `--serial`，否则程序拒绝猜测。
设备忙或已被其他程序占用时，先关闭其他 Viewer、脚本或服务；不要并行启动多个采集实验。

## Permission denied / scan_elements

该错误表示访问 USB、HID 或 IMU 的权限不足，并不表示图像目标太远。
按 [安装指南](../installation.md) 安装官方 udev 规则并重新插拔。
如果只修改了用户组，需要重新登录使组生效。不要长期依赖 sudo 启动整个 uv 环境。

“could not initialize udev monitor”也可能来自容器或执行沙箱对系统枚举服务的限制。
即使是 SDK 软件设备离线测试也会初始化它；在允许该服务的环境再测试，
不要把这种环境限制直接归为相机损坏。

## 未支持的模式 / 无法起流

程序在起流前检查每路请求是否出现在设备 profile 中，不会自动换分辨率或降 FPS。
当前 USB 连接、固件和相机决定可用列表。先看 info --profiles，再尝试单流。
若单流都支持却双流失败，检查多流组合、传输带宽、其他占用程序和设备状态。
calibration 还要求同一宽高/FPS 存在 depth 和 color 的标定 profile。

## Frame didn't arrive within 5000 / 超时

旧 SDK 样例常见 `wait_for_frames()` 超时。当前主程序采用轮询和每路超时，
状态显示超时提示后，根据 max_timeouts 或 duration 停止并释放 pipeline。
duration=0 只取消时长上限，不关闭停帧超时检测；不限时模式仍可能因停帧提前结束。

超时表示没有收到新帧，与“收到了深度帧但像素是 0”不同。
物体过远通常体现为无效深度，不能直接解释视频传输完全停帧。
逐项排查单流/双流差别、设备占用、USB 路径、线缆和供电；降低参数只是诊断方法，
不能把任何超时都直接归为 USB 2.0 带宽不足。

## USB 2.0、换口和 30 FPS

USB 描述 2.1 和系统 480M 表示当前 USB 2.0 速率连接。
部分 RealSense 模式能够在 USB 2.0 下工作；30 FPS 本身不能证明已经切换到 USB 3.x。
链路速率也不等于有效图像吞吐量。换口改善可能涉及连接路径、接触、供电或重插后的设备状态，
需要同线、同参数重复对比才能缩小原因，不能仅据“换口好了”确定接触不良。

```bash
journalctl -k -b --no-pager | rg -i 'usb|uvcvideo|xhci'
```

观察反复 reset、非人为 disconnect 和协议错误；人为拔插记录本身不证明端口坏了。
Linux 对 USB 传输错误的区分也有限，参见[内核错误码说明](https://www.kernel.org/doc/html/latest/driver-api/usb/error-codes.html)。

## 帧率不足或 IMU 明显低于请求值

不指定 fps 时，使用 TOML 的值，当前配置请求 30 FPS；修改 TOML 或显式 --fps 可改变请求。
状态行是最近约一秒的频率，average_fps 是全程均值，包含首帧等待，两者可能不同。
按时长测试的默认阈值是请求值的 50%；低于它即 FAIL。

在同一组参数下比较加预览与不加预览，可以区分绘制/处理开销对采集的影响。
双流要分别看各路 counts；IMU 要看 CSV 中 accel/gyro 的独立帧号和时间戳。
调整 min_fps_ratio 或延长 timeout 只改变判定规则，不会修复停帧或提高实际采样率。
设置为 0 可临时关闭平均频率判定，但不能据此证明硬件达到目标频率。
历史短测记录见 [CHANGELOG](../../CHANGELOG.md)，不能作为当前连接的稳定性保证。

## 深度全零、彩色全黑、点云为空

- 深度全零：帧已到达但无有效测距；检查场景、距离、镜头和采集状态。截图仍保存全零原始图便于诊断。
- 中心像素为 0：不代表整幅图无效，检查有效比例或改 pixel。
- 彩色全黑：检查光照、遮挡和曝光；试 warmup-frames 等待收敛。全黑提示不单独判传输失败。
- 点云为空：检查有效深度、max_depth 截断和 RGB 映射；程序不写空 PLY。
- 对齐结果无有效深度：检查两路帧与标定；状态中的测距来自对齐前输入图，可能与保存的对齐图不同。

## 预览窗口和终端显示

无法创建 Tk 窗口时检查实际 uv Python 的 tkinter 和桌面访问；无桌面可 --no-preview。
窗口等待预热结束后才更新图像。Q / Esc / 关窗会结束测试，Ctrl+C 的退出码则为 130。
截图/点云开启 preview 后不会保存完立即退出，而会继续到时长、帧数或关窗。

状态后部被截断通常是终端宽度不足；增大窗口或看 summary.json。
终端重定向后只有一条最终状态是预期行为，过程刷新不是日志文件。

## 文件输出与录像扩展名

record 当前要求 .db3，不能传旧样例的 .bag 或 .mp4。
输出父目录会自动创建，但权限、目标是目录或文件系统空间问题仍会失败。
固定路径重复运行会覆盖同名 PNG/NPY/JSON/CSV/PLY。
如果只有 db3 而没有有效帧数或 summary FAIL，不能据文件存在认定录像成功。
SDK 起流前报错时可能没有最终统计文件。

## 何时修改代码

如果配置和硬件 profile 都正确，仍出现稳定可复现的数据计数、窗口清理或输出格式问题，
先按 [开发指南](../../CONTRIBUTING.md) 增加针对问题的回归测试，再修改对应模块。
设备传输状态异常和 Python 算法错误应结合各自证据处理，避免只扩大超时来隐藏问题。
