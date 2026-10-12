; Inno Setup script: builds gg-setup-windows-x64.exe (see .github/workflows/release.yml).
;   iscc /DAppVersion=0.3.3 /DGgExe=..\dist\gg.exe installer\greengold.iss
; Installs for the current user (no admin rights, so `gg update` can replace gg.exe) and adds the folder to PATH.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef GgExe
  #define GgExe "..\dist\gg.exe"
#endif

[Setup]
AppId={{6F0B8F5E-9C1A-4D0A-8B52-6D7A1E3B5C21}
AppName=Greengold
AppVersion={#AppVersion}
AppPublisher=Greengold
AppPublisherURL=https://greengoldlang.com
DefaultDirName={localappdata}\Greengold\bin
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=gg-setup-windows-x64
Compression=lzma2
SolidCompression=yes
ChangesEnvironment=yes
UninstallDisplayName=Greengold {#AppVersion}
LicenseFile=..\LICENSE

[Files]
Source: "{#GgExe}"; DestDir: "{app}"; DestName: "gg.exe"; Flags: ignoreversion

[Code]
const
  EnvKey = 'Environment';

function PathHas(const Dir: string): Boolean;
var
  Paths: string;
begin
  if not RegQueryStringValue(HKCU, EnvKey, 'Path', Paths) then
    Paths := '';
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') > 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Paths: string;
begin
  if (CurStep = ssPostInstall) and not PathHas(ExpandConstant('{app}')) then
  begin
    if not RegQueryStringValue(HKCU, EnvKey, 'Path', Paths) then
      Paths := '';
    if (Paths <> '') and (Paths[Length(Paths)] <> ';') then
      Paths := Paths + ';';
    RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Paths + ExpandConstant('{app}'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Paths, Dir: string;
  P: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Dir := ExpandConstant('{app}');
    if RegQueryStringValue(HKCU, EnvKey, 'Path', Paths) then
    begin
      Paths := ';' + Paths + ';';
      P := Pos(';' + Uppercase(Dir) + ';', Uppercase(Paths));
      if P > 0 then
      begin
        Delete(Paths, P, Length(Dir) + 1);
        Paths := Copy(Paths, 2, Length(Paths) - 2);
        RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Paths);
      end;
    end;
  end;
end;
