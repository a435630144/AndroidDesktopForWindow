; -*- coding: utf-8 -*-
; PhoneDesktop - Inno Setup 安装包脚本
; 用法（需先跑 scripts\build_portable.ps1 -OutName PhoneDesktop_v10b）：
;   "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" scripts\installer.iss
;
; 产物：dist\PhoneDesktop_v10b_Setup.exe
; 特性：默认安装到 %LOCALAPPDATA%\Programs（免管理员权限）、
;       开始菜单 + 桌面快捷方式、可选开机自启、卸载时清理用户数据（可选）。

#define MyAppName "PhoneDesktop"
#define MyAppNameEn "PhoneDesktop"
#define MyAppVersion "5.0.1"
#define MyAppPublisher "随便玩玩ay"
#define MyAppExe "PhoneDesktop.exe"

; 打包目录名 / 产物名参数化：运行中的旧实例会锁住 dist\<BuildDir>，
; 换名重打时用 ISCC /DBuildDir=xxx /DOutBase=xxx 覆盖即可，不必改脚本。
#ifndef BuildDir
  #define BuildDir "PhoneDesktop_v10b"
#endif
#ifndef OutBase
  #define OutBase "PhoneDesktop_v10b_Setup"
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
; v10 D2（反馈 5）：向导外观与语言选择。
; 图标与产品图都在编译期嵌进 Setup.exe，运行期不需要额外文件。
WizardSizePercent=120
; Inno 6 默认跳过欢迎页（DisableWelcomePage=auto）。产品图只挂在欢迎页/完成页上，
; 所以这里显式打开欢迎页，否则用户永远看不到它。
DisableWelcomePage=no
SetupIconFile=..\assets\app_icon.ico
WizardImageFile=..\assets\wizard.png
; Inno 6 里没有 DefaultLanguage / ShowLanguageDialog 指令：
; **多语言时安装包启动即弹语言选择**，[Languages] 第一项 = 默认语言（中文在前）。
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExe}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
; Inno 官方不提供简体中文语言包，这里用官方的"多文件覆盖"机制：
; 先读英文底 Default.isl，再用我们自己的覆盖层盖掉实际会走到的消息。
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl,languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
; v10 D2（反馈 5）：任务页/完成页的双语文案。{cm:Name} 按当前语言取。
chinesesimplified.TaskGroup=可选任务：
chinesesimplified.TaskDesktopIcon=创建桌面快捷方式
chinesesimplified.TaskAutostart=开机自动启动
chinesesimplified.TaskClearData=清除旧版本的个人数据（布局与设置）
chinesesimplified.RunApp=立即运行 PhoneDesktop
english.TaskGroup=Optional tasks:
english.TaskDesktopIcon=Create a desktop shortcut
english.TaskAutostart=Start with Windows
; 注意：Inno 的 & 是助记符，字面量 & 要写 &&，否则界面里出现下划线（
; 'layout _settings'）——英文截图目检发现的。
english.TaskClearData=Delete personal data from a previous version (layout && settings)
english.RunApp=Launch PhoneDesktop now

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktopIcon}"
Name: "autostart"; Description: "{cm:TaskAutostart}"; Flags: unchecked
; v10 A2（反馈 3）：安装器只在卸载时清 %APPDATA%，覆盖安装会继承旧 state.json
; —— 用户在旧版里开过「开发者调试网格」，新版就带着满屏网格启动。
; 给一个装前清除的选项（默认不勾，避免误删用户布局）。
Name: "cleardata"; Description: "{cm:TaskClearData}"; Flags: unchecked

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
Filename: "{app}\{#MyAppExe}"; Description: "{cm:RunApp}"; \
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
    if ActiveLanguage = 'english' then
      Result := 'PhoneDesktop appears to be running. Please close it, then continue.'
    else
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
