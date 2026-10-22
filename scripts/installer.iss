; -*- coding: utf-8 -*-
; PhoneDesktop - Inno Setup 安装包脚本
; 用法（需先跑 scripts\build_portable.ps1 -OutName PhoneDesktop_v10）：
;   "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" scripts\installer.iss
;
; 产物：dist\PhoneDesktop_v10_Setup.exe
; 特性：默认安装到 %LOCALAPPDATA%\Programs（免管理员权限）、
;       开始菜单 + 桌面快捷方式、可选开机自启、卸载时清理用户数据（可选）。

#define MyAppName "PhoneDesktop"
#define MyAppNameEn "PhoneDesktop"
#define MyAppVersion "4.0.0"
#define MyAppPublisher "随便玩玩ay"
#define MyAppExe "PhoneDesktop.exe"

; 打包目录名 / 产物名参数化：运行中的旧实例会锁住 dist\<BuildDir>，
; 换名重打时用 ISCC /DBuildDir=xxx /DOutBase=xxx 覆盖即可，不必改脚本。
#ifndef BuildDir
  #define BuildDir "PhoneDesktop_v10"
#endif
#ifndef OutBase
  #define OutBase "PhoneDesktop_v10_Setup"
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
; onedir 产物整体拷贝，保留子目录结构（与 build_portable.ps1 -OutName PhoneDesktop_v10 对应）
Source: "..\dist\{#BuildDir}\PhoneDesktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; v10 D1 改名（反馈 4）：AppId 不变（仍是同一个产品，覆盖升级走同一条记录），
; 但安装目录名换了。旧目录只放程序文件（用户数据在 %APPDATA%），整目录清掉。
Type: filesandordirs; Name: "{autopf}\DesktopOrganizerDemo"

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
; 卸载时清理用户数据（%APPDATA%\PhoneDesktop：布局与设置）。
; 改名前的旧目录也一起清（老用户升级后旧目录已被 v10 一次性迁移删掉，
; 这里兜住"从没跑过新版就卸载"的情况）。
Type: filesandordirs; Name: "{userappdata}\{#MyAppNameEn}"
Type: filesandordirs; Name: "{userappdata}\DesktopOrganizerDemo"

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
    Result := '检测到 PhoneDesktop 可能正在运行，建议先退出再安装。';
  // v10 A2（反馈 3）：勾选「清除旧版本个人数据」时，装前删掉旧数据目录，
  // 让新版以默认设置启动（否则旧 state.json 的 dev_mode=True 会被继承）。
  if WizardIsTaskSelected('cleardata') then
  begin
    // 新旧两个目录都要清：只清新目录时，新版启动会从旧目录"迁移"回旧数据，
    // 用户勾了清除却还是旧配置（改名后的真实坑）。
    DataDir := ExpandConstant('{userappdata}\{#MyAppNameEn}');
    if DirExists(DataDir) then
      DelTree(DataDir, True, True, True);
    DataDir := ExpandConstant('{userappdata}\DesktopOrganizerDemo');
    if DirExists(DataDir) then
      DelTree(DataDir, True, True, True);
  end;
end;
