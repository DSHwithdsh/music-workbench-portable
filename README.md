# Music 工作台 Portable

整合 AMDL 下载和 fre:ac 转码的 Windows x64 便携桌面工具，采用 Apple Music 风格的中文界面。

## 下载

[下载 Windows 便携包（约 244 MB）](https://github.com/DSHwithdsh/music-workbench-portable/releases/download/v0.1.0/MusicWorkbench-Portable-Windows-x64.zip) · [SHA256 校验文件](https://github.com/DSHwithdsh/music-workbench-portable/releases/download/v0.1.0/MusicWorkbench-Portable-Windows-x64.zip.sha256)

也可进入 [Releases](https://github.com/DSHwithdsh/music-workbench-portable/releases) 查看全部版本。

完整解压后双击 `MusicWorkbench.exe`，无需安装 Python。不要只复制单个 EXE，也不要在 ZIP 内直接运行。

## 功能

- 搜索歌曲、艺人、专辑，解析 Apple Music 链接，显示封面和曲目列表。
- 整张专辑或选中曲目下载为 ALAC，并自动转为 FLAC、AAC-LC，或两者。
- 本地无损音频批量转码；保留原文件、目录结构及支持的标签和封面。
- FLAC 等级 6，检查与源音频的 PCM 一致性；AAC-LC 立体声 256 kbps，检查音频完整性。
- 校验后提交成品，已有文件验证后跳过；配置和音乐保存在便携目录。

## 首次下载

包内已提供 AMDL、fre:ac、FFmpeg、MP4Box，以及全新的离线解密环境文件。

AMDL 下载仍需要本机 WSL1 解密服务。新电脑请先运行 `一键准备解密服务.cmd`；如系统组件未启用，可能需要管理员权限及手动重启。服务使用独立的 `MusicWorkbench-Portable-*` 名称，不覆盖已有发行版。登录和验证码在用户本机完成，需要自己的有效 Apple Music 订阅。

本地转码可以直接使用。WSL 环境注册后，其安装目录不能直接移动；换电脑时请用原始 ZIP 重新准备服务并登录。

详见[使用说明](使用说明.md)。发行包不包含原电脑的账号、令牌、登录缓存或音乐。

## 验证范围

已验证独立 EXE 启动、包内 FLAC／AAC 编码与校验、中文和空格目录下运行，以及不依赖原电脑 Python／工具 PATH 的运行。首次系统组件启用及全新电脑上的 WSL 导入尚未实测。

本仓库的 `src` 保存工作台源码。第三方组件及许可说明见包内 `licenses` 和 [THIRD-PARTY.md](THIRD-PARTY.md)。
