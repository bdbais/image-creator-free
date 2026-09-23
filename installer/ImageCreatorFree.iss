; Installer di Image Creator Free (Inno Setup 6).
; Compilato da build.ps1 con  /DAppVersion=x.y.z

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define AppName "Image Creator Free"
#define AppExe "ImageCreatorFree.exe"
#define AppUrl "https://imagecreator.bais.info"

[Setup]
AppId={{B7A4E9D2-5C31-4F8A-9E27-1D3C6A8F2B40}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=bais.info
AppPublisherURL={#AppUrl}
AppSupportURL=https://github.com/bdbais/image-creator-free/issues
AppUpdatesURL=https://github.com/bdbais/image-creator-free/releases
DefaultDirName={autopf}\Image Creator Free
DefaultGroupName=Image Creator Free
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=Output
OutputBaseFilename=ImageCreatorFree-Setup
SetupIconFile=..\assets\ImageCreatorFree.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "italiano"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\ImageCreatorFree.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\ImageCreatorFree.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\ImageCreatorFree.pyw"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\src\imagecreator\*"; DestDir: "{app}\app\src\imagecreator"; Flags: ignoreversion recursesubdirs; Excludes: "__pycache__"
Source: "..\worker\qwen_worker.py"; DestDir: "{app}\app\worker"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; I collegamenti puntano al lanciatore: la finestra deve girare con il Python
; dell'ambiente di calcolo, non dentro l'eseguibile.
Name: "{group}\{#AppName}"; Filename: "{app}\ImageCreatorFree.cmd"; IconFilename: "{app}\{#AppExe}"; Flags: runminimized
Name: "{group}\Sito del progetto"; Filename: "{#AppUrl}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ImageCreatorFree.cmd"; IconFilename: "{app}\{#AppExe}"; Flags: runminimized; Tasks: desktopicon

[Run]
Filename: "{app}\ImageCreatorFree.cmd"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runminimized shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}\worker"
Type: filesandordirs; Name: "{app}\app"

[Messages]
italiano.WelcomeLabel2=Verra' installato {#AppName} sul tuo computer.%n%nAl primo avvio il programma scarica l'ambiente di calcolo (circa 3 GB) e, alla prima generazione, il modello Qwen-Image-2.1 (circa 33 GB). Servono quindi circa 40 GB liberi e una connessione veloce.
