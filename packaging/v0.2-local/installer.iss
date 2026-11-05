#define AppVersion "0.2.0"
[Code]
function PortableMode: Boolean;
begin
  Result := ExpandConstant('{param:portable|0}') = '1';
end;

[Setup]
AppId={{536C28F7-AC48-4543-A0DE-918B0E87D7CB}
AppName=Music 工作台
AppVersion={#AppVersion}
AppPublisher=DSHwithdsh
DefaultDirName={localappdata}\Programs\MusicWorkbench
DefaultGroupName=Music 工作台
PrivilegesRequired=lowest
CreateUninstallRegKey=not PortableMode
UsePreviousAppDir=not PortableMode
AllowNoIcons=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
DisableReadyPage=yes
WizardStyle=modern
Compression=lzma2/normal
SolidCompression=yes
OutputDir=release
OutputBaseFilename=MusicWorkbench-{#AppVersion}-Setup-x64
SetupIconFile=payload\MusicWorkbench\app.ico
UninstallDisplayIcon={app}\MusicWorkbench.exe
CloseApplications=no
RestartApplications=no
UninstallDisplayName=Music 工作台 {#AppVersion}
VersionInfoVersion=0.2.0.0
VersionInfoDescription=Music 工作台安装程序
InfoBeforeFile=安装提示.txt

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "payload\MusicWorkbench\*"; DestDir: "{app}"; Excludes: "tools\amdl\GUI-downloader\_internal\src\core\config.yaml"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "payload\MusicWorkbench\tools\amdl\GUI-downloader\_internal\src\core\config.yaml"; DestDir: "{app}\tools\amdl\GUI-downloader\_internal\src\core"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\Music 工作台 v0.2"; Filename: "{app}\MusicWorkbench.exe"; WorkingDir: "{app}"; Check: not PortableMode
Name: "{group}\使用说明"; Filename: "{app}\使用说明.md"; Check: not PortableMode
Name: "{group}\卸载 Music 工作台"; Filename: "{uninstallexe}"; Check: not PortableMode
Name: "{autodesktop}\Music 工作台 v0.2"; Filename: "{app}\MusicWorkbench.exe"; WorkingDir: "{app}"; Tasks: desktopicon; Check: not PortableMode

[Run]
Filename: "{app}\MusicWorkbench.exe"; Description: "启动 Music 工作台 v0.2"; Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if (FileExists(ExpandConstant('{app}\apple_music_ui.py')) or
      FileExists(ExpandConstant('{app}\source\portable_entry.py'))) and
     not FileExists(ExpandConstant('{app}\.music-workbench-installer')) then
    Result := '此目录已有本地开发版或便携版。请选择一个新目录，以保留原部署。';
end;
