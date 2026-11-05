# v0.2 Windows 发布构建

此目录独立于已部署本地版及 `portable-build` v0.1。不包含 GitHub 发布动作。

`release` 为最终安装 EXE、Portable ZIP、SHA256 与验收报告。个人设置、令牌、音乐和日志不进入发行文件。

## 构建

1. `C:\Python314\python.exe prepare.py`：从已验证本地 v0.2 快照源码；从干净 v0.1 发行目录复用固定工具和服务资产；记录旧文件哈希。
2. `C:\Python314\python.exe build.py`：使用已有 PyInstaller 及 Mutagen 构建自带 Python 的 EXE。构建依赖在上级 `_vendor` 与 `portable-build/builddeps`。
3. `tools\InnoSetup\ISCC.exe /Qp installer.iss`：编译安装器；需要可写临时目录，可把当前进程 TEMP/TMP 指向 `build/temp`。
4. `C:\Python314\python.exe validate.py install`：用实际安装器的 `/PORTABLE=1` 模式，安装到本目录 `build/便携安装验证 中文 path`；执行实际冻结程序的转码、18项事务／流水线测试、GUI初始化、联网匹配、服务计划与重复安装保留数据检查。目录已存在时须先审查，不会自动清空。
5. 检查实际窗口后，关闭测试程序，执行 `C:\Python314\python.exe validate.py finish`：卸载测试程序，验证保留用户数据，生成验收报告。
6. `C:\Python314\python.exe finalize.py`：打 ZIP 并核验每个 manifest 项和旧部署哈希。

官方 Inno Setup 7.1.1 下载签名已验证为 `Pyrsys B.V.`，原始下载 SHA256：`8a5a6711c3766a6e5fb74f280ba0e3551e719ce94538d901fdbd1f8f9920b3f0`。编译器仅以 `/PORTABLE=1` 解包到本目录，不安装到系统。

当前执行环境拒绝写入开始菜单及 HKCU 卸载登记，标准安装测试已回滚；这些登记步骤未验收。便携安装模式跳过这些步骤，仍测试相同文件解包、程序、升级与卸载逻辑。首次启用 WSL1／新建发行版未在已部署电脑上运行。详情见 `release/validation.json`。
