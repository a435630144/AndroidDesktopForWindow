; 简体中文消息覆盖层（v13a：全路径补齐，消灭中英混搭）
;
; **这不是一份完整的语言翻译**：Inno Setup 官方语言包里没有简体中文，
; 而本项目"零外部依赖 + 离线可构建"，所以走官方支持的
; 「MessagesFile 用逗号串多个文件、后者覆盖前者」机制——
;   chinesesimplified: compiler:Default.isl,languages\ChineseSimplified.isl
; 英文语言仍只用 Default.isl，两种语言各自独立。
;
; v13a：收录范围从「实际会走到的页面」扩到**安装/卸载全路径**（含错误框、
; 文件占用、共享文件、回滚状态条）。此前只盖住主流程，冷门框一弹就是英文，
; 用户看到的是「中文向导 + 英文报错」的混搭。未收录的只剩多磁盘/网络下载
; 这类本安装包用不到的分支。
;
; 约定：`[name]` / `[name/ver]` / `%1` / `%n` 这类占位符一个字符都不能动；
;       `&` 是助记符，字面量 `&` 写 `&&`。

[LangOptions]
; v12c：自动选语言的匹配依据。MessagesFile 叠加时本段会覆盖 Default.isl
; 的 LanguageID=$0409——没有它，Inno 永远匹配不到简体中文（会按列表第一项
; 兜底），`LanguageDetectionMethod=uilanguage` 形同虚设。
; $0804 = 简体中文(中国)，主语言 $04 与应用侧 i18n.system_language() 同口径。
LanguageName=简体中文
LanguageID=$0804
LanguageCodePage=936

[Messages]
; ---- 窗口标题 / 通用对话框 ----
SetupAppTitle=安装程序
SetupWindowTitle=安装 %1
UninstallAppTitle=卸载
UninstallAppFullTitle=卸载 %1
InformationTitle=提示
ConfirmTitle=确认
ErrorTitle=错误
LastErrorMessage=%1%n%2 (错误码 %3)
SetupLdrStartupMessage=这将安装 %1。是否继续？
HelpTextNote=（无帮助）
SetupFileMissing=安装目录中缺少文件 %1。请重新获取安装包再试。
SetupFileCorrupt=安装文件已损坏。请重新获取安装包再试。
SetupFileCorruptOrWrongVer=安装文件已损坏，或与本安装程序版本不匹配。请重新获取安装包再试。
InvalidParameter=命令行参数无效：%1
SetupAlreadyRunning=安装程序已在运行。
WindowsVersionNotSupported=本程序不支持当前运行的 Windows 版本。
WindowsServicePackRequired=本程序需要 %1 或更高版本。
NotOnThisPlatform=本程序不能在 %1 上运行。
OnlyOnThisPlatform=本程序只能在 %1 上运行。
OnlyOnTheseArchitectures=本程序只能安装在下列架构的 Windows 上：%1
WinVersionTooLowError=本程序需要 %1 或更高版本。
WinVersionTooHighError=本程序不能安装在 %1 或更高版本上。
AdminPrivilegesRequired=安装本程序需要管理员权限。
PowerUserPrivilegesRequired=安装本程序需要管理员或 Power Users 组权限。
SetupAppRunningError=安装程序检测到 %1 正在运行。%n%n请先关闭它的所有实例，然后点“确定”继续，或点“取消”退出。
UninstallAppRunningError=卸载程序检测到 %1 正在运行。%n%n请先关闭它的所有实例，然后点“确定”继续，或点“取消”退出。
PrivilegesRequiredOverrideTitle=选择安装模式
PrivilegesRequiredOverrideInstruction=请选择安装模式：
PrivilegesRequiredOverrideText1=%1 可以按下列任一方式安装：
PrivilegesRequiredOverrideText2=为所有用户安装（需要管理员权限）；或仅为当前用户安装。
PrivilegesRequiredOverrideAllUsers=为所有用户安装(&A)
PrivilegesRequiredOverrideAllUsersRecommended=为所有用户安装（推荐）(&A)
PrivilegesRequiredOverrideCurrentUser=仅为当前用户安装(&U)
PrivilegesRequiredOverrideCurrentUserRecommended=仅为当前用户安装（推荐）(&U)
ErrorCreatingDir=安装程序无法创建目录“%1”。
ErrorTooManyFilesInDir=无法向目录“%1”写入文件，因为其中文件太多。
ExitSetupTitle=退出安装
ExitSetupMessage=安装尚未完成。现在退出将不会安装本程序。%n%n你可以稍后重新运行安装程序完成安装。%n%n要退出安装吗？
AboutSetupMenuItem=关于安装程序(&A)...
AboutSetupTitle=关于安装程序
AboutSetupMessage=%1 版本 %2%n%3%n%n%1 主页：%n%4
AboutSetupNote=翻译：本地化贡献者%n%n注意：本翻译仅供个人非商业用途免费使用。
TranslatorNote=简体中文由本项目自维护覆盖层提供。

; ---- 按钮 ----
ButtonBack=< 上一步(&B)
ButtonNext=下一步(&N) >
ButtonInstall=安装(&I)
ButtonOK=确定
ButtonCancel=取消
ButtonYes=是(&Y)
ButtonYesToAll=全是(&A)
ButtonNo=否(&N)
ButtonNoToAll=全否(&O)
ButtonFinish=完成(&F)
ButtonBrowse=浏览(&B)...
ButtonWizardBrowse=浏览(&R)...
ButtonNewFolder=新建文件夹(&M)
ButtonStopDownload=停止下载(&S)
ButtonStopExtraction=停止解压(&S)

; ---- 欢迎 / 许可 / 用户信息（本包未启用许可页，保留翻译防将来开启）----
SelectLanguageTitle=选择安装语言
SelectLanguageLabel=请选择安装过程中使用的语言。
ClickNext=点“下一步”继续，或点“取消”退出安装。
BeveledLabel=安装向导
BrowseDialogTitle=浏览文件夹
BrowseDialogLabel=请在下面的树状列表中选择一个文件夹，然后点“确定”。
NewFolderName=新建文件夹
WelcomeLabel1=欢迎使用 [name] 安装向导
WelcomeLabel2=这将在你的电脑上安装 [name/ver]。%n%n建议在继续之前关闭其它正在运行的程序。
WizardPassword=安装验证
PasswordLabel1=本安装包受密码保护。
PasswordLabel3=请输入密码，然后点“下一步”继续。
PasswordEditLabel=密码(&P)：
IncorrectPassword=输入的密码不正确。请重试。
WizardLicense=许可协议
LicenseLabel=继续安装前请阅读下列重要信息。
LicenseLabel3=请阅读下列许可协议。建议在继续安装之前读完协议全文。
LicenseAccepted=我接受协议(&A)
LicenseNotAccepted=我不接受协议(&N)
WizardInfoBefore=安装说明
InfoBeforeLabel=继续安装前请阅读下列重要信息。
InfoBeforeClickLabel=准备好后点“下一步”继续安装。
WizardInfoAfter=自述文件
InfoAfterLabel=安装即将完成，请阅读下列重要信息。
InfoAfterClickLabel=准备好后点“完成”退出安装向导。
WizardUserInfo=用户信息
UserInfoDesc=请输入下列信息，然后点“下一步”继续。
UserInfoName=用户名(&U)：
UserInfoOrg=组织(&O)：
UserInfoSerial=序列号(&S)：
UserInfoNameRequired=必须输入用户名。

; ---- 安装位置 ----
WizardSelectDir=选择安装位置
SelectDirDesc=[name] 应该安装到哪个文件夹？%n%n安装程序将在下面的文件夹中安装 [name]。要使用不同的文件夹，请点“浏览”。
SelectDirLabel3=安装程序将把 [name] 安装到下面的文件夹。%n%n要使用不同的文件夹，请点“浏览”。继续请点“下一步”。
SelectDirBrowseLabel=继续请点“下一步”；要换一个文件夹请点“浏览”。
DiskSpaceMBLabel=需要至少 [mb] MB 可用磁盘空间。
DiskSpaceGBLabel=需要至少 [gb] GB 可用磁盘空间。
CannotInstallToNetworkDrive=安装程序不能安装到网络驱动器。
CannotInstallToUNCPath=安装程序不能安装到 UNC 路径。如果要安装到网络共享，请先把它映射为网络驱动器。
InvalidPath=请输入完整的驱动器路径或 UNC 路径。%n%n例如：C:\APP 或 \\服务器\共享名
InvalidDrive=所选的驱动器或 UNC 共享不存在。请重新选择。
DiskSpaceWarningTitle=磁盘空间不足
DiskSpaceWarning=安装至少需要 %1 KB 可用空间，但所选磁盘只剩 %2 KB。%n%n仍要继续吗？
DirNameTooLong=目录名或路径过长。
InvalidDirName=目录名无效。
BadDirName32=目录名不能包含下列字符：%n%n%1
DirExistsTitle=目录已存在
DirExists=目录：%n%n%1%n%n已经存在。仍要安装到这个目录吗？
DirDoesntExistTitle=目录不存在
DirDoesntExist=目录：%n%n%1%n%n不存在。要创建这个目录吗？

; ---- 组件（本包无组件页，保留翻译）----
WizardSelectComponents=选择组件
SelectComponentsDesc=请选择要安装的组件。
SelectComponentsLabel2=请选择要安装的组件，取消不希望安装的组件。点“下一步”继续。
FullInstallation=完整安装
CompactInstallation=紧凑安装
CustomInstallation=自定义安装
NoUninstallWarningTitle=存在组件
NoUninstallWarning=下列组件已经在本机上安装：%n%n%1%n%n卸载这些组件后再继续吗？%n%n如果保留，仍可继续安装。
ComponentSize1=占用：%1 KB
ComponentSize2=占用：%1 MB
ComponentsDiskSpaceGBLabel=当前选择至少需要 [gb] GB 磁盘空间。
ComponentsDiskSpaceMBLabel=当前选择至少需要 [mb] MB 磁盘空间。

; ---- 附加任务 ----
WizardSelectTasks=选择附加任务
SelectTasksDesc=需要执行哪些附加任务？
SelectTasksLabel2=选择安装 [name] 时要一并完成的附加任务，然后点“下一步”。
ExtractingLabel=正在解压文件...

; ---- 开始菜单 ----
WizardSelectProgramGroup=选择开始菜单文件夹
SelectStartMenuFolderDesc=安装程序应该在哪里创建程序快捷方式？%n%n安装程序将在下面的开始菜单文件夹中创建快捷方式。要使用不同的文件夹，请输入名称或点“浏览”。
SelectStartMenuFolderLabel3=安装程序将在下面的开始菜单文件夹里创建程序快捷方式。继续请点“下一步”；要换一个文件夹请点“浏览”。
SelectStartMenuFolderBrowseLabel=继续请点“下一步”；要换一个文件夹请点“浏览”。
MustEnterGroupName=请输入文件夹名。
GroupNameTooLong=文件夹名或路径过长。
InvalidGroupName=文件夹名无效。
BadGroupName=文件夹名不能包含下列字符：%n%n%1
NoProgramGroupCheck2=不要创建开始菜单文件夹(&D)

; ---- 准备安装 ----
WizardReady=准备安装
ReadyLabel1=安装程序已准备好，在你的电脑上安装 [name]。
ReadyLabel2a=点“安装”开始；想再检查一遍设置，点“上一步”。
ReadyLabel2b=点“安装”开始安装。
ReadyMemoUserInfo=用户信息：
ReadyMemoDir=安装位置：
ReadyMemoType=安装类型：
ReadyMemoComponents=已选组件：
ReadyMemoGroup=开始菜单文件夹：
ReadyMemoTasks=附加任务：

; ---- 安装进行中 ----
WizardPreparing=正在准备安装
PreparingDesc=安装程序正在准备安装 [name]。
PreviousInstallNotCompleted=上一次的安装/卸载操作尚未完成，需要重启电脑。%n%n建议重启后再运行本安装程序。%n%n现在仍要继续吗？
CannotContinue=安装程序无法继续。请点“取消”退出。
ApplicationsFound=下列程序正在使用需要更新的文件。建议让安装程序自动关闭这些程序。
ApplicationsFound2=下列程序正在使用需要更新的文件。建议让安装程序自动关闭这些程序。安装结束后会尝试重新启动这些程序。
CloseApplications=自动关闭这些程序(&A)
DontCloseApplications=不关闭这些程序(&D)
ErrorCloseApplications=安装程序无法自动关闭所有程序。建议在继续之前手动关闭所有使用待更新文件的程序。
PrepareToInstallNeedsRestart=安装程序需要重启电脑才能完成对 %1 的安装。%n%n重启后会自动继续安装。%n%n现在要立即重启吗？
WizardInstalling=正在安装
InstallingLabel=安装程序正在安装 [name]，请稍候。
FinishedHeadingLabel=[name] 安装完成
FinishedLabelNoIcons=[name] 已安装到你的电脑上。
FinishedLabel=[name] 已安装到你的电脑上，可以从开始菜单或桌面快捷方式启动。
ClickFinish=点“完成”退出安装程序。
FinishedRestartLabel=[name] 安装完成。安装程序需要重启电脑才能完成最后的安装。
FinishedRestartMessage=[name] 安装完成。安装程序需要重启电脑才能完成最后的安装。%n%n现在要立即重启吗？
ShowReadmeCheck=查看自述文件(&R)
YesRadio=是，立即重启电脑(&Y)
NoRadio=否，稍后自己重启(&N)
RunEntryExec=运行 %1
RunEntryShellExec=查看 %1

; ---- 状态条 ----
StatusClosingApplications=正在关闭程序...
StatusCreateDirs=正在创建目录...
StatusExtractFiles=正在解压文件...
StatusCreateIcons=正在创建快捷方式...
StatusCreateIniEntries=正在写入 INI 项...
StatusCreateRegistryEntries=正在写入注册表项...
StatusRegisterFiles=正在注册组件...
StatusSavingUninstall=正在保存卸载信息...
StatusRunProgram=正在完成安装...
StatusRestartingApplications=正在重新启动程序...
StatusRollback=正在撤销更改...

; ---- 错误框 ----
ErrorInternal2=内部错误：%1
ErrorFunctionFailedNoCode=%1 失败
ErrorFunctionFailed=%1 失败，错误码 %2
ErrorFunctionFailedWithMessage=%1 失败，错误码：%n%2
ErrorExecutingProgram=无法执行文件：%n%1
ErrorRegOpenKey=打开注册表项时出错：%n%1\%2
ErrorRegCreateKey=创建注册表项时出错：%n%1\%2
ErrorRegWriteKey=写入注册表项时出错：%n%1\%2
ErrorIniEntry=向文件“%1”写入 INI 项时出错。
FileAbortRetryIgnoreSkipNotRecommended=跳过此文件（不推荐）(&S)
FileAbortRetryIgnoreIgnoreNotRecommended=忽略此错误并继续（不推荐）(&I)
SourceIsCorrupted=源文件已损坏。
SourceDoesntExist=源文件“%1”不存在。
SourceVerificationFailed=源文件“%1”校验失败。
VerificationSignatureDoesntExist=文件“%1”没有数字签名。
VerificationSignatureInvalid=文件“%1”的数字签名无效。
VerificationKeyNotFound=在“%1”中找不到证书颁发机构。
VerificationFileNameIncorrect=文件“%1”的证书中的文件名不正确。
VerificationFileTagIncorrect=文件“%1”的证书中的文件标签不正确。
VerificationFileSizeIncorrect=文件“%1”的证书中的文件大小不正确。
VerificationFileHashIncorrect=文件“%1”的证书中的文件哈希不正确。
ExistingFileReadOnly2=目标文件已存在且为只读：%n%n%1%n%n请去掉只读属性后重试。
ExistingFileReadOnlyRetry=重试(&R)
ExistingFileReadOnlyKeepExisting=保留现有文件(&K)
ErrorReadingExistingDest=读取目标文件时出错。
FileExistsSelectAction=请选择操作。
FileExists2=目标文件已存在：%n%n%1%n%n要怎样处理这个文件？
FileExistsOverwriteExisting=覆盖现有文件(&O)
FileExistsKeepExisting=保留现有文件(&K)
FileExistsOverwriteOrKeepAll=为后面所有冲突执行此操作(&A)
ExistingFileNewerSelectAction=请选择操作。
ExistingFileNewer2=目标文件已存在且比源文件更新：%n%n%1%n%n要怎样处理这个文件？
ExistingFileNewerOverwriteExisting=覆盖现有文件(&O)
ExistingFileNewerKeepExisting=保留现有文件(&K)
ExistingFileNewerOverwriteOrKeepAll=为后面所有冲突执行此操作(&A)
ErrorChangingAttr=修改下列文件属性时出错：%n%1
ErrorCreatingTemp=在目标目录中创建临时文件时出错。
ErrorReadingSource=读取源文件时出错：%n%1
ErrorCopying=复制文件时出错：%n%1%n%n到%n%n%2
ErrorDownloading=下载文件时出错：%n%1%n%n%2
ErrorExtracting=解压文件时出错：%n%n%1%n%n源文件可能已损坏。
ErrorReplacingExistingFile=替换现有文件时出错：%n%1
ErrorRestartReplace=重启后替换文件失败：%n%1
ErrorRenamingTemp=重命名目标目录中的临时文件时出错：%n%1
ErrorRegisterServer=无法注册 DLL/OCX：%n%1
ErrorRegSvr32Failed=RegSvr32 失败，退出码 %1
ErrorRegisterTypeLib=无法注册类型库：%n%1
ErrorOpeningReadme=无法打开自述文件。
ErrorRestartingComputer=安装程序无法重启电脑，请手动重启。

; ---- 卸载 ----
UninstallDisplayNameMark=%1 (%2)
UninstallDisplayNameMarks=%1 (%2, %3)
UninstallDisplayNameMark32Bit=32 位
UninstallDisplayNameMark64Bit=64 位
UninstallDisplayNameMarkAllUsers=所有用户
UninstallDisplayNameMarkCurrentUser=当前用户
UninstallNotFound=目录“%1”中找不到卸载信息。本程序可能未安装。
UninstallOpenError=无法打开文件“%1”。
UninstallUnsupportedVer=文件“%1”的卸载信息格式无法被本卸载程序识别。
UninstallUnknownEntry=在卸载信息“%1”中发现无法识别的项 (%2)。
ConfirmUninstall=确定要完全卸载 %1 及其所有组件吗？
UninstallOnlyOnWin64=本程序只能在 64 位 Windows 上卸载。
OnlyAdminCanUninstall=本程序只能由管理员权限的用户卸载。
UninstallStatusLabel=正在从你的电脑上卸载 %1，请稍候。
UninstalledAll=%1 已从你的电脑上卸载。
UninstalledMost=%1 卸载完成。%n%n部分元素无法删除，可以手动清理。
UninstalledAndNeedsRestart=要完成 %1 的卸载，必须重启电脑。%n%n现在要立即重启吗？
UninstallDataCorrupted=文件“%1”已损坏，无法卸载。
ConfirmDeleteSharedFileTitle=共享文件
ConfirmDeleteSharedFile2=系统显示下列共享文件已不再被其它程序使用。要卸载这些共享文件吗？%n%n如果仍有程序使用这些文件却被删除，这些程序可能无法正常运行。不确定请选“否”，把文件留在系统中不会造成损害。
SharedFileNameLabel=文件名：
SharedFileLocationLabel=位置：
WizardUninstalling=正在卸载
StatusUninstalling=正在卸载 %1...
ShutdownBlockReasonInstallingApp=正在安装 %1
ShutdownBlockReasonUninstallingApp=正在卸载 %1
