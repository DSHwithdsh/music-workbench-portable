# v0.2 macOS 移植记录

目标为用户指定的 Apple Silicon / macOS 27。分析与最初交叉编译宿主为 Windows；静态二进制证据不能证明 Mac 运行成功。

| 问题 | 观察与处理 | 证据或边界 |
|---|---|---|
| Windows 主程序是什么 | PE x86-64 外壳中为 PyInstaller 2.1 容器，Python 3.14，引用 python314.dll；容器成员完整性无矛盾 | REA `ev_92bd0774c77aee8c7d48f487415b7a2437b9f51d5e834164b1b888b8a575b640`；静态，不执行程序 |
| 原 AMDL 能否直接复用 | Windows amd64 Go1.26.4，CGO_ENABLED=1，vcs.modified=true；采用单独源码构建，不声称复原了所有本机修改 | REA `ev_13694401ca6c19ac1f0779f4a1e6bfd71c735fa814a862436510f320a95777bd` 及设置视图 `ev_ad212db6efa58dc85c71adddeb1c7444995c328f788b06b50d3a1d7d19c9aae6` |
| Windows fre:ac 能否直接复用 | freaccmd.exe 的 PE 导入表包含 KERNEL32.dll、smooth.dll、msvcrt.dll 和 libstdc++.dll | REA `ev_3e4afd5e209fa5ec3d651bf7e42b0c0f53757fc5eda43ad57b1790eb83270056`；4 个 DLL、76 个导入；不是运行时绑定证明 |
| 原生 ARM64 引擎 | 固定上游源码 5e17b686ca4a01b0c0397f28061788b7c36d07d5，保留其 legacy/go-mp4tag 本地依赖，Go1.27.3、CGO=0 交叉编译成功；产物为 Mach-O arm64 | REA `ev_92645d9788b8cd4652604e063ce94bbe8fae79e5651b9fae08ca6e3405771b18`；初始二进制 SHA256 `53cd31e0f5c66c2e827da15e5abdd30a77d0cb5fbe615288f7a325b099c3e9b1` |
| 应用写入位置 | 程序资源只读，配置和备份放用户 Library/Application Support；下载器及配置复制到用户数据目录，升级保留配置 | 源码适配及宿主事务测试；Mac 文件权限仍需 Mac 构建测试 |
| AAC 实现 | Mac fre:ac 采用 CoreAudio：`--encoder=coreaudio -- -f AAC -b 128`；继续检查 AAC-LC 与音频时长 | freac v1.1.7 src/startconsole.cpp 和 BoCA CoreAudio 源码；参数正确性测试不等于实际编码通过 |
| 解密服务 | 官方 ARM64 wrapper，独立 Docker 容器，两个端口只绑定127.0.0.1；交互登录不把账号密码写到 Docker Env/Cmd 或启动脚本 | 计划、目录及容器所有权约束有宿主测试；Docker Desktop、MFA、完整下载仍待真实 Mac 用户验收 |

完整初始 REA 记录保存在 `windows-v02-rea.json` 及后续合并证据文件；只分析此次指定产物，不读取原账号脚本或登录状态。

Mac 源码与冻结程序构建检查会另存 `build/reports`。GitHub macOS 26 或 macOS 15 ARM64 runner 的运行证据与用户 macOS 27 的最终验收应分别记录；没有实际运行证据的项保持未验证。

PyInstaller 官方说明其不是跨平台编译器，Mac Python/Tk 应用需要在 Mac 上构建：https://pyinstaller.org/en/stable/index.html 。
依赖依据：https://www.freac.org/downloads-mainmenu-33/362-freac-117 、https://github.com/enzo1982/freac/blob/v1.1.7/packaging/macosx/prepare.sh 、https://github.com/enzo1982/freac/blob/v1.1.7/src/startconsole.cpp 、https://github.com/WorldObservationLog/wrapper/tree/wrapper.arm64.latest 。
