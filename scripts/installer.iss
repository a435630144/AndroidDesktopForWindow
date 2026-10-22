; -*- coding: utf-8 -*-
; 桌面美化整理软件 Demo - Inno Setup 安装包脚本
; 用法（需先跑 scripts\build_portable.ps1 -OutName DesktopOrganizerDemo_v6g）：
;   "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" scripts\installer.iss
;
; 产物：dist\DesktopOrganizerDemo_v6g_Setup.exe
; 特性：默认安装到 %LOCALAPPDATA%\Programs（免管理员权限）、
;       开始菜单 + 桌面快捷方式、可选开机自启、卸载时清理用户数据（可选）。

#define MyAppName "桌面整理Demo"
#define MyAppNameEn "DesktopOrganizerDemo"
#define MyAppVersion "4.0.0"
#define MyAppPublisher "DesktopOrganizerDemo"
#define MyAppExe "DesktopOrganizerDemo.exe"

; 打包目录名 / 产物名参数化：运行中的旧实例会锁住 dist\<BuildDir>，
; 换名重打时用 ISCC /DBuildDir=xxx /DOutBase=xxx 覆盖即可，不必改脚本。
#ifndef BuildDir
  #define BuildDir "DesktopOrganizerDemo_v9a"
#endif
#ifndef OutBase
  #define OutBase "DesktopOrganizerDemo_v9a_Setup"
#endif

[Setup]
; 免管理员安装：装到当前用户目录
PrivilegesRequired=lowest
AppId={{8A3F2C41-7D5E-4B9A-9E6F-DesktopOrganizer01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppNameEn}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\dist
OutputBaseFilename={#OutBase}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExe}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"
Name: "autostart"; Description: "开机自动启动"; GroupDescription: "附加任务:"; Flags: unchecked
; v10 A2（反馈 3）：安装器只在卸载时清 %APPDATA%，覆盖安装会继承旧 state.json
; —— 用户在旧版里开过「开发者调试网格」，新版就带着满屏网格启动。
; 给一个装前清除的选项（默认不勾，避免误删用户布局）。
Name: "cleardata"; Description: "清除旧版本的个人数据（布局与设置）"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
; onedir 产物整体拷贝，保留子目录结构（与 build_portable.ps1 -OutName DesktopOrganizerDemo_v6g 对应）
Source: "..\dist\{#BuildDir}\DesktopOrganizerDemo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; 开机自启任务：写 HKCU Run（与软件内设置保持一致，命令为安装后的实际路径）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#MyAppNameEn}"; \
    ValueData: """{app}\{#MyAppExe}"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "立即运行 {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清理用户数据（%APPDATA%\DesktopOrganizerDemo：布局与设置）
Type: filesandordirs; Name: "{userappdata}\{#MyAppNameEn}"

[Code]
// 安装前如发现旧版便携包解压目录正在运行，提示关闭
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Wnd: HWND;
  DataDir: String;
begin
  Result := '';
  Wnd := FindWindowByClassName('Qt6103QWindowIcon');
  // 类名随 Qt 版本变化，仅作提示用途：找不到也不拦截
  if Wnd <> 0 then
    Result := '检测到桌面整理Demo可能正在运行，建议先退出再安装。';
  // v10 A2（反馈 3）：勾选「清除旧版本个人数据」时，装前删掉旧数据目录，
  // 让新版以默认设置启动（否则旧 state.json 的 dev_mode=True 会被继承）。
  if WizardIsTaskSelected('cleardata') then
  begin
    DataDir := ExpandConstant('{userappdata}\{#MyAppNameEn}');
    if DirExists(DataDir) then
      DelTree(DataDir, True, True, True);
  end;
end;
