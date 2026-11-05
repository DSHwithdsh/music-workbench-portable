# Included third-party components

- fre:ac 1.1.7: original Windows x64 distribution from https://github.com/enzo1982/freac/releases/tag/v1.1.7 . License in `tools/freac/COPYING`; core source archive included here as `freac-1.1.7.tar.gz`, plus sources supplied in the original distribution. https://www.freac.org/
- AMDL engine: the same downloader binary used by the existing apmyx installation, copied read-only. apmyx upstream license is GPL-3.0, included as `apmyx-LICENSE.txt`; upstream source snapshot in `apmyx-source.zip`. Repository: https://github.com/rwnk-12/apmyx-gui . The copied engine has not been rebuilt from that snapshot.
- wrapper: fresh upstream `Wrapper.x86_64.latest.zip` from https://github.com/WorldObservationLog/wrapper/releases/tag/wrapper.x86_64.latest . Upstream wrapper license text in `wrapper-LICENSE.txt`; version is pinned by the archive SHA256 in `service/rootfs-manifest.json`.
- Ubuntu Base 22.04.5 amd64: https://cdimage.ubuntu.com/ubuntu-base/releases/22.04/release/ . The Ubuntu archive is verified against the publisher's SHA256SUMS. Package copyright and license information remain in `/usr/share/doc` inside the Linux filesystem. This is a new upstream base, not an export of the user's installed WSL.
- FFmpeg and GPAC/MP4Box: unmodified Windows binaries and their runtime DLLs copied read-only from the existing offline tools. FFmpeg version and license output are included in this directory. Upstream projects: https://ffmpeg.org/ and https://gpac.io/ . Source and licensing resources: https://ffmpeg.org/legal.html and https://github.com/gpac/gpac . These copied builds were not rebuilt for this bundle.
- CPython 3.14 runtime, Tcl/Tk runtime and PyInstaller bootloader are bundled to run the desktop application without a separate Python installation. Project licenses and attribution: https://docs.python.org/3/license.html , https://www.tcl-lang.org/software/tcltk/license.html , https://pyinstaller.org/en/stable/license.html .

The workstation's credentials, tokens, configuration backups, music files and account caches are not included. Runtime files and login caches created later on the recipient's machine are not part of this distribution.


## v0.2 标签组件
Mutagen 1.48.1，GPL-2.0-or-later；许可证及元数据见 mutagen-1.48.1.dist-info。https://github.com/quodlibet/mutagen
