[Setup]
AppId={{D37D0851-A3D2-4E90-B8B7-3D32F46A19AC}
AppName=SNMP Visual Manager
AppVersion=1.0.0
AppPublisher=Bhagyaraj Bheesetty
AppComments=Net-SNMP 5.9.5.2 GUI Management Tool
AppContact=net-snmp-coders@lists.sourceforge.net
AppSupportURL=http://www.net-snmp.org/
AppUpdatesURL=https://github.com/Bhagyarajbheesetty/net-snmp-visual-manager
LicenseFile=LICENSE
DefaultDirName={autopf}\NetSNMPManager
DefaultGroupName=SNMP Visual Manager
AllowNoIcons=yes
OutputDir=dist_installer
OutputBaseFilename=NetSNMPManager_Setup_v1.0
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayName=SNMP Visual Manager
UninstallDisplayIcon={app}\NetSNMPManager.exe
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\NetSNMPManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "share\snmp\mibs\*"; DestDir: "{app}\mibs"; Flags: ignoreversion recursesubdirs; Excludes: "*PROXIM*,*PXM*"
Source: "bin\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "CREDITS.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SNMP Visual Manager"; Filename: "{app}\NetSNMPManager.exe"
Name: "{group}\{cm:UninstallProgram,SNMP Visual Manager}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SNMP Visual Manager"; Filename: "{app}\NetSNMPManager.exe"; Tasks: desktopicon
Name: "{app}\Uninstall"; Filename: "{uninstallexe}"

[UninstallDelete]
Type: filesandordirs; Name: "{%USERPROFILE}\.snmp-manager"
Type: filesandordirs; Name: "{app}\mibs"
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\*.log"
Type: files; Name: "{app}\*.txt"
Type: dirifempty; Name: "{app}"

[Run]
Filename: "{app}\NetSNMPManager.exe"; Description: "{cm:LaunchProgram,SNMP Visual Manager}"; Flags: nowait postinstall skipifsilent

[Code]
// Complete uninstall cleanup: Stop running processes and remove application runtime data directory
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    // Terminate any running application or background helper process to release file locks
    Exec('taskkill.exe', '/F /IM NetSNMPManager.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill.exe', '/F /IM snmpwalk.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill.exe', '/F /IM snmpbulkwalk.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill.exe', '/F /IM snmpget.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(500);
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    // Ensure all application-owned persistent files in %USERPROFILE%\.snmp-manager are completely removed:
    // - register.json (and temp files)
    // - snmp_manager.db (and WAL / SHM / journal files)
    // - managed MIB copies and staging folders
    // - query exports and desktop_app.log
    DataDir := ExpandConstant('{%USERPROFILE}\.snmp-manager');
    if (DataDir <> '') and DirExists(DataDir) then
    begin
      DelTree(DataDir, True, True, True);
    end;
  end;
end;
