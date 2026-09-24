; Inno Setup script for the Windows installer (M5 step 1).
;
;   uv run pyinstaller --noconfirm packaging/previously-on.spec
;   iscc /DAppVersion=0.1.0 packaging/installer.iss
;   -> dist/PreviouslyOn-0.1.0-windows-x64-setup.exe
;
; Per user, no administrator prompt: the app goes to
; %LOCALAPPDATA%\Programs\PreviouslyOn, which is also what lets a later
; setup.exe upgrade it in place without asking for elevation. Sessions and
; settings live elsewhere (%LOCALAPPDATA%\previously-on, platformdirs), so an
; upgrade never touches them and an uninstall keeps them unless asked.
;
; A running copy holds its DLLs open, so before replacing or removing files
; the installer asks it to quit (`PreviouslyOn.exe --quit`: the session log
; gets its end, a recap in flight its grace) and only then kills whatever is
; still running from the install folder.

#ifndef AppVersion
  #error Pass the version: iscc /DAppVersion=X.Y.Z packaging/installer.iss
#endif

#define AppName "Previously On"
#define AppExe "PreviouslyOn.exe"
#define RunKey "Software\Microsoft\Windows\CurrentVersion\Run"
; autostart.VALUE_NAME: the app reads and rewrites the same value.
#define RunValue "PreviouslyOn"

[Setup]
; Never change the AppId: it is how an upgrade finds the installed copy.
AppId={{6B0E5C1A-4F3D-4C7E-9A61-2F5D8E3B7C49}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=pedrocluis
AppPublisherURL=https://github.com/pedrocluis/previously-on
AppSupportURL=https://github.com/pedrocluis/previously-on/issues
PrivilegesRequired=lowest
DefaultDirName={autopf}\PreviouslyOn
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir=..\dist
OutputBaseFilename=PreviouslyOn-{#AppVersion}-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
; The running copy is closed by [Code] below, which lets it end its session;
; the Restart Manager would only offer to shut it down, or reopen it after.
CloseApplications=no
RestartApplications=no

[Tasks]
Name: startup; Description: "Start in the tray when I sign in to Windows (recommended: it only watches while a supported game runs)"
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[InstallDelete]
; Last version's runtime: stale modules must not outlive an upgrade.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\PreviouslyOn\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function AppExePath(): String;
begin
  Result := ExpandConstant('{app}\{#AppExe}');
end;

{ The line autostart.launcher() would write; the app rewrites it anyway if
  it differs (Autostart.refresh). }
function RunCommand(): String;
begin
  Result := '"' + AppExePath() + '" --background';
end;

{ Ask a running copy to quit, then kill any copy still running from the
  install folder (a version without --quit, or one that did not exit). }
procedure CloseRunningCopy();
var
  Code: Integer;
  Dir: String;
begin
  if FileExists(AppExePath()) then
    Exec(AppExePath(), '--quit', '', SW_HIDE, ewWaitUntilTerminated, Code);
  { A PowerShell single-quoted string: an apostrophe in the user name doubles. }
  Dir := ExpandConstant('{app}\');
  StringChangeEx(Dir, '''', '''''', True);
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "Get-Process -Name PreviouslyOn,previously-on-cli -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -and $_.Path.StartsWith(''' + Dir + ''', [StringComparison]::OrdinalIgnoreCase) } | ' +
    'Stop-Process -Force"',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CloseRunningCopy();
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { Unticked leaves the value alone: the player may have turned it on in the
    app since the last install, and the app owns that switch. }
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('startup') then
    RegWriteStringValue(HKCU, '{#RunKey}', '{#RunValue}', RunCommand());
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Value, DataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    CloseRunningCopy();
    { Only an entry that starts this copy: a development checkout's is not ours. }
    if RegQueryStringValue(HKCU, '{#RunKey}', '{#RunValue}', Value) and
       (Pos(Lowercase(ExpandConstant('{app}\')), Lowercase(Value)) > 0) then
      RegDeleteValue(HKCU, '{#RunKey}', '{#RunValue}');
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\previously-on');
    if DirExists(DataDir) and not UninstallSilent() and
       (MsgBox('Also delete your session logs, recaps and settings (including any API key)?' + #13#10#13#10 +
               'Keep them to pick up where you left off after reinstalling.' + #13#10 + DataDir,
               mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(DataDir, True, True, True);
  end;
end;
