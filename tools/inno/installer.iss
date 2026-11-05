; 降妖伏魔 安装包脚本(Inno Setup 6)
; 打包 dist/降妖伏魔 里的绿色版(只取 exe + _internal,不带本机运行数据),
; 产物: dist/降妖伏魔安装包.exe —— 对方双击装完即可用,无需管理员权限。
;
; 编译: ISCC tools/inno/installer.iss   (需先跑 package.py 生成绿色版)

[Setup]
AppId={{8F5E6C2A-9B1D-4E7A-9C3F-2A7D51B0E4D8}
AppName=降妖伏魔
AppVersion=1.0.0
AppVerName=降妖伏魔 1.0.0
; 每用户安装:不弹 UAC,装在 %LocalAppData%\降妖伏魔(程序要往自己目录写
; config/data,Program Files 会没权限)
PrivilegesRequired=lowest
DefaultDirName={localappdata}\降妖伏魔
DisableProgramGroupPage=yes
; 卸载时把整个安装目录删干净(底图/标定重装时会自动重新生成)
UninstallFilesDir={app}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\..\dist
OutputBaseFilename=mhxy_bell
SetupIconFile=..\..\data\bell.ico
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chs"; MessagesFile: "ChineseSimplified.isl"

[Files]
Source: "..\..\dist\降妖伏魔\降妖伏魔.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\降妖伏魔\_internal\*"; DestDir: "{app}\_internal"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userdesktop}\降妖伏魔"; Filename: "{app}\降妖伏魔.exe"
Name: "{autoprograms}\降妖伏魔"; Filename: "{app}\降妖伏魔.exe"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Run]
Filename: "{app}\降妖伏魔.exe"; Description: "立即运行 降妖伏魔"; \
    Flags: nowait postinstall skipifsilent
