; 简体中文消息覆盖层（v10 D2，反馈 5）
;
; **这不是一份完整的语言翻译**：Inno Setup 官方语言包里没有简体中文，
; 而本项目"零外部依赖 + 离线可构建"，所以走官方支持的
; 「MessagesFile 用逗号串多个文件、后者覆盖前者」机制——
;   chinesesimplified: compiler:Default.isl,languages\ChineseSimplified.isl
; 英文语言仍只用 Default.isl，两种语言各自独立。
;
; 收录范围：本安装包**实际会走到**的页面与按钮（无许可协议页、免管理员、
; modern 向导）。未收录的冷门消息（网络下载、多磁盘、命令行错误等）
; 在中文界面下会显示英文原文——不做"半吊子翻译"，需要时再补。
;
; 约定：`[name]` / `[name/ver]` / `%1` 这类占位符一个字符都不能动。

[Messages]
SetupAppTitle=安装程序
SetupWindowTitle=安装 %1
UninstallAppTitle=卸载
UninstallAppFullTitle=卸载 %1
SelectLanguageTitle=选择安装语言
SelectLanguageLabel=请选择安装过程中使用的语言。
SetupLdrStartupMessage=这将安装 %1。是否继续？
WelcomeLabel1=欢迎使用 [name] 安装向导
WelcomeLabel2=这将在你的电脑上安装 [name/ver]。%n%n建议在继续之前关闭其它正在运行的程序。
WizardSelectDir=选择安装位置
SelectDirDesc=[name] 应该安装到哪个文件夹？
SelectDirLabel3=安装程序将把 [name] 安装到下面的文件夹。
SelectDirBrowseLabel=继续请点“下一步”；要换一个文件夹请点“浏览”。
WizardSelectProgramGroup=选择开始菜单文件夹
SelectStartMenuFolderDesc=安装程序应该在哪里创建程序快捷方式？
SelectStartMenuFolderLabel3=安装程序将在下面的开始菜单文件夹里创建程序快捷方式。
SelectStartMenuFolderBrowseLabel=继续请点“下一步”；要换一个文件夹请点“浏览”。
SelectTasksDesc=需要执行哪些附加任务？
SelectTasksLabel2=选择安装 [name] 时要一并完成的附加任务，然后点“下一步”。
ExtractingLabel=正在解压文件...
WizardSelectTasks=选择附加任务
WizardReady=准备安装
DiskSpaceMBLabel=需要至少 [mb] MB 可用磁盘空间。
DiskSpaceGBLabel=需要至少 [gb] GB 可用磁盘空间。
DiskSpaceWarningTitle=磁盘空间不足
DiskSpaceWarning=安装至少需要 %1 KB 可用空间，但所选磁盘只剩 %2 KB。%n%n仍要继续吗？
ReadyMemoUserInfo=用户信息：
ReadyMemoDir=安装位置：
ReadyMemoType=安装类型：
ReadyMemoComponents=已选组件：
ReadyMemoGroup=开始菜单文件夹：
ReadyMemoTasks=附加任务：
ReadyLabel1=安装程序已准备好，将在你的电脑上安装 [name]。
ReadyLabel2a=点“安装”开始；想再检查一遍设置，点“上一步”。
ReadyLabel2b=点“安装”开始安装。
WizardPreparing=正在准备安装
PreparingDesc=安装程序正在准备安装 [name]。
WizardInstalling=正在安装
InstallingLabel=正在安装 [name]，请稍候。
FinishedHeadingLabel=[name] 安装完成
FinishedLabelNoIcons=[name] 已安装到你的电脑上。
FinishedLabel=[name] 已安装到你的电脑上，可以从开始菜单或桌面快捷方式启动。
ClickNext=点“下一步”继续，或点“取消”退出安装。
ClickInstall=点“安装”开始安装，或点“取消”退出安装。
WizardSelectLanguage=选择安装语言
ClickFinish=点“完成”退出安装程序。
ButtonBack=< 上一步(&B)
ButtonNext=下一步(&N) >
ButtonInstall=安装(&I)
ButtonOK=确定
ButtonCancel=取消
ButtonYes=是(&Y)
ButtonNo=否(&N)
ButtonFinish=完成(&F)
ButtonBrowse=浏览(&B)...
ButtonWizardBrowse=浏览(&R)...
ButtonNewFolder=新建文件夹(&M)
StatusExtractFiles=正在解压文件...
ExitSetupTitle=退出安装
ExitSetupMessage=安装尚未完成。现在退出将不会安装本程序。%n%n你可以稍后重新运行安装程序完成安装。%n%n要退出安装吗？
ConfirmUninstall=确定要完全卸载 %1 及其所有组件吗？
UninstalledAll=%1 已从你的电脑上卸载。
UninstalledMost=%1 卸载完成。%n%n部分元素无法删除，可以手动清理。
