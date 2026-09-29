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
;
; Run over an installed copy, setup is an update: it skips the tasks page
; (the previous choices stand), says which version it replaces, and leaves
; the start-at-sign-in value to the app, which owns that switch.

#ifndef AppVersion
  #error Pass the version: iscc /DAppVersion=X.Y.Z packaging/installer.iss
#endif

#define AppName "Previously On"
#define AppExe "PreviouslyOn.exe"
#define RunKey "Software\Microsoft\Windows\CurrentVersion\Run"
; autostart.VALUE_NAME: the app reads and rewrites the same value.
#define RunValue "PreviouslyOn"
; Inno Setup's uninstall entry for the AppId below (non-admin: under HKCU).
#define UninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\{6B0E5C1A-4F3D-4C7E-9A61-2F5D8E3B7C49}_is1"

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
; Shown only for an update (ShouldSkipPage): a fresh install goes from the
; tasks page straight to installing.
DisableReadyPage=no
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
var
  { The installed copy's version, empty on a fresh install. }
  PreviousVersion: String;

function InitializeSetup(): Boolean;
begin
  if not RegQueryStringValue(HKCU, '{#UninstallKey}', 'DisplayVersion', PreviousVersion) then
    PreviousVersion := '';
  Result := True;
end;

function IsUpdate(): Boolean;
begin
  Result := PreviousVersion <> '';
end;

function UpdateVerb(): String;
begin
  if PreviousVersion = '{#AppVersion}' then
    Result := 'reinstall'
  else
    Result := 'update';
end;

procedure InitializeWizard();
begin
  if IsUpdate() then
    WizardForm.Caption := '{#AppName} ' + '{#AppVersion}' + ' ' + UpdateVerb();
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ((PageID = wpSelectTasks) and IsUpdate()) or
            ((PageID = wpReady) and not IsUpdate());
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpSelectTasks) and not IsUpdate() then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall);
  if (CurPageID = wpReady) and IsUpdate() then
  begin
    WizardForm.PageNameLabel.Caption := 'Ready to ' + UpdateVerb();
    WizardForm.PageDescriptionLabel.Caption := '{#AppName} ' + PreviousVersion + ' is installed.';
    if UpdateVerb() = 'update' then
      WizardForm.ReadyLabel.Caption := 'Setup will update it to version {#AppVersion}.'
    else
      WizardForm.ReadyLabel.Caption := 'Setup will reinstall the same version.';
    WizardForm.ReadyLabel.Caption := WizardForm.ReadyLabel.Caption + #13#10#13#10 +
      'Your sessions, recaps and settings are kept. If {#AppName} is running, it is closed first and its session saved.';
    WizardForm.ReadyMemo.Visible := False;
    if UpdateVerb() = 'update' then
      WizardForm.NextButton.Caption := '&Update';
  end;
  if (CurPageID = wpFinished) and IsUpdate() then
  begin
    WizardForm.FinishedHeadingLabel.Caption := '{#AppName} is up to date';
    WizardForm.FinishedLabel.Caption := 'Version {#AppVersion} is installed.';
  end;
end;

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
    app since the last install, and the app owns that switch. An update never
    touches it: the player may have turned it off since. }
  if (CurStep = ssPostInstall) and not IsUpdate() and WizardIsTaskSelected('startup') then
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
