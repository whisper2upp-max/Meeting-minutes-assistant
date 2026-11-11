#ifndef AppVersion
  #define AppVersion "0.2.3"
#endif
[Setup]
AppId=com.meetingkit.app
AppName=会议纪要助手
AppVersion={#AppVersion}
AppPublisher=whisper2upp-max
DefaultDirName={localappdata}\Programs\MeetingMinutesAssistant
DefaultGroupName=会议纪要助手
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Meeting-Minutes-Assistant-v{#AppVersion}-Windows-x64-Setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\会议纪要助手.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
Source: "..\dist\会议纪要助手.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\会议纪要助手"; Filename: "{app}\会议纪要助手.exe"
Name: "{autodesktop}\会议纪要助手"; Filename: "{app}\会议纪要助手.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\会议纪要助手.exe"; Description: "启动会议纪要助手"; Flags: nowait postinstall skipifsilent
