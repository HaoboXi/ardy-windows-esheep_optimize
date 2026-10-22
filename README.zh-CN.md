# ARDY Windows / NF4 后端 v0.6.0

这是 ARDY Motion Bridge 的 Windows 部署后端，面向 Blender PMX/MMD。
它是社区 Windows/NF4 优化版本，**不是 NVIDIA 官方维护发行版**。
真实 ARDY/Core27 源码、NF4/offload 适配、原生 MotionCorrection、HTTP/Worker
和中文离线 CPU 翻译均包含在源码中，未用空 README 替代运行模块。

## 普通用户

安装 Blender 插件 ZIP → N 面板 ARDY → **Step 1 – AI Environment Setup** →
选择安装目录 → **Install AI Environment**。不需要手动执行 Conda、pip、Git 或 CMake。

安装器检测可复用的 Conda 程序；没有时安装固定版本、校验 SHA256 的用户级
Miniforge，不修改系统 PATH 或默认 Python。运行环境始终是独立 prefix，
不改其他 Conda 环境，不在 Blender 内装 PyTorch/量化/CUDA 包。

实际下载超过 5 GB，以面板和 `config/deployment_descriptor.json` 为准，另有
Conda 包及元数据开销。下载大小不等于解压后占用，建议预留至少 24 GiB。
下载逐文件校验并保留可续传缓存；Conda/pip 无可靠字节进度时只显示步骤和日志。
必须通过真实 CPU 翻译和 NF4/Core27 推理才标记 READY。

生成流程保持为：中文/英文输入 → 必要时 CPU 翻译 → NF4/Core 生成 → 原有
PMX 重定向与头脚修正 → 独立 Action。没有修改模型算法、量化精度、Foot IK
或序列拼接。已有 Action 可脱离 AI 环境离线播放。

## 已有部署

Advanced Installation Settings → Detect Existing → Import Existing。
也可显式选择原后端目录与 Conda Python。安装器复制精简运行源码到新安装目录，
读取并校验已有权重，引用已有环境与翻译资源；不重新下载几 GB 模型，
不改原目录、不升级借用环境、不移动用户资产。

新安装模型默认目录：

```
<INSTALL_ROOT>/models/Esheep-ardy-llm2vec_NF4/
<INSTALL_ROOT>/checkpoints/ARDY-Core-RP-20FPS-Horizon40/
```

旧的有效模型文件夹仍可通过生成的 `runtime_config.json` 引用，不要求为了
更换仓库名复制或重下载权重。ModelPathResolver 依次使用运行配置、显式目录、
安装默认目录。推理时离线，不回退到任意变化的远程 `main` 或个人主目录覆盖。

## 检测与恢复

主要验证目标为 RTX 5070 Ti Laptop 12GB。安装前检查 Windows x64、AVX、NVIDIA
驱动、CUDA 驱动能力、总/可用显存及磁盘。8 GiB 总显存、5.75 GiB 空闲是预检
阈值，不代表所有显卡兼容；实际推理是最终验证。CUDA wheel 自带运行库，
普通用户无需安装完整 CUDA Toolkit 或 Visual Studio Build Tools。

Miniforge 首次引导要求 ASCII 路径，不支持时会明确提示换目录或复用现有 Conda。
其他空格/中文路径是否通过见真实测试报告，不能以模拟测试代替实际验证。

- Verify：重新验证文件、依赖、DLL、CPU 翻译与实际动作推理。
- Repair：修复安装器自有环境，保留并复用有效模型；不修改借用的旧环境。
- Reinstall Backend：重装已校验源码，不清空用户模型或历史动作。
- 修改 Installation Directory：在新位置安装，原位置保留。
- Uninstall：明确确认后只删除拥有的文件/环境；默认保留模型、下载缓存、NPZ。
  外部借用路径和 BLEND 工程始终不删除。

状态文件、日志、模型、环境、session/token 和输出均在安装目录或用户本地
AppData 中，不属于可提交源码。错误日志保留，失败/取消不会提前显示 READY。

## 命令行与发布

独立入口为 `installer/install_backend.ps1` / `install_backend.py`，可使用 Blender
内置 Python 作为引导，不依赖已有 ARDY 环境。依赖清单区分 Conda Python、CUDA
PyTorch wheel、正式运行锁定包和仅发布构建机需要的构建依赖，未启用原项目 `[all]`。

请阅读 [PUBLISHING.md](PUBLISHING.md)。本次交付由维护者手动提交代码、创建 Tag
并上传 Release 文件；尚未上传时，面向新用户的 GitHub 下载入口会明确失败，
不能据此宣称公开网络安装已完成。

原 ARDY Apache-2.0 与第三方版权完整保留。权重许可不等同于源码许可；Core
采用 NVIDIA Open Model License。NF4 仓库模型卡/许可证补充按维护者要求暂缓，
在发布清单标注待补充，本源码不分发模型权重。见 [ATTRIBUTIONS.md](ATTRIBUTIONS.md)。
