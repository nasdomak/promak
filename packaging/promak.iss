; Inno Setup recipe: turns dist\Promak into PromakSetup-<version>.exe
;     iscc /DAppVersion=0.4.0 packaging\promak.iss
; Built by .github/workflows/release.yml on every version tag.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3C8E2A-5B4D-4C1E-9A7F-2D8B1E0C4A55}
AppName=Promak
AppVersion={#AppVersion}
AppPublisher=Promak contributors
AppPublisherURL=https://github.com/nasdomak/promak
DefaultDirName={autopf}\Promak
DefaultGroupName=Promak
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=PromakSetup-{#AppVersion}
SetupIconFile=..\assets\promak.ico
UninstallDisplayIcon={app}\Promak.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Promak\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Promak"; Filename: "{app}\Promak.exe"; AppUserModelID: "Promak.Promak.App"
Name: "{autodesktop}\Promak"; Filename: "{app}\Promak.exe"; AppUserModelID: "Promak.Promak.App"; Tasks: desktopicon

[Run]
Filename: "{app}\Promak.exe"; Description: "{cm:LaunchProgram,Promak}"; Flags: nowait postinstall skipifsilent
