# Music 工作台 v0.2

整合 AMDL 下载、fre:ac 转码以及自动匹配标签、封面和歌词的 Windows x64 桌面工具，采用 Apple Music 风格的中文界面。

## 下载 v0.2.0 预览版

- [便携版 ZIP，约 245 MB（推荐）](https://github.com/DSHwithdsh/music-workbench-portable/releases/download/v0.2.0/MusicWorkbench-0.2.0-Portable-Windows-x64.zip)：完整解压到可写目录，双击 `MusicWorkbench.exe`。
- [安装版 EXE，约 203 MB](https://github.com/DSHwithdsh/music-workbench-portable/releases/download/v0.2.0/MusicWorkbench-0.2.0-Setup-x64.exe)：标准安装的开始菜单和卸载注册表登记尚未完成验收。
- [v0.2.0 发布说明、SHA256 和验收报告](https://github.com/DSHwithdsh/music-workbench-portable/releases/tag/v0.2.0)

已内置 Python、AMDL 下载引擎、fre:ac、FFmpeg、MP4Box 和 Mutagen，无需自行安装 Python。请保留包内全部子目录，不要在 ZIP 内直接运行。支持 Windows 10/11 的 Intel/AMD 64 位电脑；Windows on ARM 未验收。此构建未配置代码签名证书。

## v0.2 新增

- “标签与歌词”页面：批量自动匹配、候选预览和手动确认，可选择匹配后自动补全。
- 支持 M4A（ALAC/AAC）、FLAC、MP3 的标签、封面和歌词读写。
- 默认补全缺失项；同步歌词内嵌并导出 LRC，纯文本歌词导出 TXT。
- 写入前备份，完整解码校验 PCM 不变，失败时回滚，并维护转码校验记录。
- 下载任务完成后可将本次成品交给标签匹配流程。
- 可指定外部 `MusicTag.exe` 并打开文件夹；外部 MusicTag 程序未随包分发。内置自动匹配不依赖它。

在线标签来自 Apple 公开目录，歌词来自 LRCLIB；仅提交检索文字，不上传音频。候选可能缺失或不准确，请确认低置信度结果。

## 下载与转码

支持搜索、Apple Music 链接解析、整张专辑或所选曲目下载为 ALAC，并生成 FLAC 等级6、AAC-LC 256 kbps 立体声副本。原文件保留，已有成品仅在记录及完整性一致时跳过。

本地转码可直接使用。AMDL 下载仍需要本机 WSL1 解密服务、自己的有效 Apple Music 订阅及本机登录。包内提供干净的 Ubuntu Base 22.04.5 与 wrapper；首次运行“一键准备解密服务.cmd”创建独立的 `MusicWorkbench-Portable-*` 发行版，不覆盖已有环境。系统组件可能需要用户启用及手动重启。已注册 WSL 服务后，其安装目录不可直接移动。

详见[使用说明](使用说明.md)。发行文件不含个人账号、令牌、登录缓存、音乐或操作日志。配置、音乐、标签备份和服务状态保存在本机；卸载安装版会保留这些生成的数据，也不会自动注销独立 WSL 环境。

## 验收与限制

实际冻结 EXE 已通过 18 项事务与转码测试、FLAC/AAC 编码、GUI 初始化、中文及空格路径、无外部 Python/工具 PATH、在线标签及同步歌词匹配。实际安装器 `/PORTABLE=1` 模式的安装、重复安装及卸载保留个人数据验证通过。

当前测试环境拒绝写入开始菜单与 HKCU 卸载登记，标准安装测试已回滚，这两个系统登记环节尚未验收。首次启用 WSL1 和全新电脑上的服务导入尚未实测。建议优先使用便携 ZIP。公开验收结果见 [validation/v0.2.0.json](validation/v0.2.0.json)。

## 源码与历史版本

`src` 保存与发行包对应的工作台源码。第三方许可见 [THIRD-PARTY.md](THIRD-PARTY.md) 及包内 `licenses`。`packaging/v0.2-local` 保存此次本机构建配方，其依赖的原工作区布局见该目录说明；不是可在任意空目录直接执行的独立构建系统。

[v0.1.0 发布记录与原便携包](https://github.com/DSHwithdsh/music-workbench-portable/releases/tag/v0.1.0) 继续保留。
