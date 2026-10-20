[Setup]
AppId={{4A7B104D-C3CC-4F31-B4D5-F78284CCCE7A}
AppName=Posture Detector
AppVersion=1.1
AppPublisher=L & M
DefaultDirName={autopf}\PostureDetector
DefaultGroupName=Posture Detector
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=PostureDetector-Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayIcon={app}\Posture_Detection.exe
; SetupIconFile=app.ico

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "startup"; Description: "Start Posture Detector when Windows starts"; Flags: unchecked

[Files]
Source: "dist\Posture_Detection\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Posture Detector"; Filename: "{app}\Posture_Detection.exe"
Name: "{autodesktop}\Posture Detector"; Filename: "{app}\Posture_Detection.exe"; Tasks: desktopicon
Name: "{userstartup}\Posture Detector"; Filename: "{app}\Posture_Detection.exe"; Tasks: startup

[Run]
Filename: "{app}\Posture_Detection.exe"; Description: "Launch Posture Detector"; Flags: nowait postinstall skipifsilent

[Code]
// The app has no normal window, so Windows can't ask it to close politely.
// This ends any running copy before installing, updating or uninstalling,
// so files aren't locked and the camera is released.
procedure StopApp();
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/f /im Posture_Detection.exe', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
end;

function InitializeSetup(): Boolean;
begin
  StopApp();
  Result := True;
end;

function InitializeUninstall(): Boolean;
begin
  StopApp();
  Result := True;
end;