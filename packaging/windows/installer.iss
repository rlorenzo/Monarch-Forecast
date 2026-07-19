; Inno Setup script for the Monarch Forecast Windows installer.
;
; Builds a per-user Setup.exe (no admin/UAC) from the `flet build windows`
; output folder. Invoked from .github/workflows/build.yml as:
;
;   ISCC.exe /DMyAppVersion=<x.y.z> /DSourceDir=<path\to\build\windows> /O<outdir> installer.iss
;
; The installer is NOT code-signed, so Windows SmartScreen still shows an
; "unknown publisher" prompt until a signing cert is added — that's a signing
; concern, independent of packaging (see README).

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\build\windows"
#endif

#define MyAppName "Monarch Forecast"
#define MyAppExeName "Monarch Forecast.exe"
#define MyAppPublisher "Rex Lorenzo"
#define MyAppURL "https://github.com/rlorenzo/Monarch-Forecast"

[Setup]
; Stable AppId — keep this constant across releases so upgrades/uninstall work.
AppId={{F79355FE-6D62-4542-83AA-D62FB73E43A4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
; Per-user install → no admin prompt, no UAC.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputBaseFilename=monarch-forecast-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; Recurse the whole flet build output into the install dir.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
