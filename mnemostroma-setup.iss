; =============================================================================
; mnemostroma-setup.iss — Inno Setup script for Mnemostroma Windows Installer
;
; Produces: mnemostroma-setup.exe (~215 MB, self-contained)
; Requires: Inno Setup 6.3+ (https://jrsoftware.org/isinfo.php)
;
; Build on Windows VM:
;   iscc mnemostroma-setup.iss
;
; Output: installer\mnemostroma-setup.exe
; =============================================================================

#define AppName      "Mnemostroma"
#define AppVersion   "2.3.2"
#define AppPublisher "GG-QandV"
#define AppURL       "https://github.com/GG-QandV/mnemostroma"
#define AppExeName   "mnemostroma-service.exe"
#define ServiceName  "mnemostroma-service"
#define ServiceDisp  "Mnemostroma Service"
#define DataDir      "{localappdata}\Mnemostroma"

[Setup]
; --- Identity -----------------------------------------------------------------
AppId={{A3F2C1D7-8B4E-4F6A-9C2D-1E5B7F3A8C0D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases

; --- Installation paths -------------------------------------------------------
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; --- Output -------------------------------------------------------------------
OutputDir=installer
OutputBaseFilename=mnemostroma-setup
SetupIconFile=

; --- Privileges ---------------------------------------------------------------
; RequireAdministrativePrivileges so Windows shows proper UAC prompt.
; User just clicks "Yes" — no manual "Run as Administrator" needed.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=

; --- UI -----------------------------------------------------------------------
WizardStyle=modern
WizardResizable=no
DisableWelcomePage=no
LicenseFile=
InfoBeforeFile=

; --- Compression --------------------------------------------------------------
; LZMA2 solid — best ratio for the ONNX payload.
; The exe itself is already UPX-compressed by PyInstaller; skip double-compress.
Compression=lzma2/ultra64
SolidCompression=no

; --- Misc ---------------------------------------------------------------------
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
ChangesEnvironment=no
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no
MinVersion=10.0.10240

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
; Override key messages so they are clear for non-technical users
WelcomeLabel1=Welcome to {#AppName} Setup
WelcomeLabel2=This will install {#AppName} {#AppVersion} as a background Windows service that automatically captures your AI session memory.%n%nNo Python or Git installation required.%n%nClick Next to continue.
FinishedHeadingLabel=Setup Complete
FinishedLabel={#AppName} has been installed and the background service has started.%n%nIt will now run automatically every time you log in. No further action is needed.%n%nTo verify the service is running, check the system tray or open Services (services.msc).

[Tasks]
; No optional tasks — keep it simple for non-technical users

[Files]
; --- Main executable (self-contained: Python + ONNX models bundled inside) ---
Source: "dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
; Create data directory for user — memory DB, logs, config
Name: "{#DataDir}"; Flags: uninsneveruninstall

[Icons]
; No Start Menu shortcuts — this is a background service, not a GUI app

[Run]
; STEP 1: Stop existing service if upgrading over old installation
Filename: "sc.exe"; Parameters: "stop {#ServiceName}"; \
  Flags: runhidden waituntilterminated; StatusMsg: "Stopping existing service..."; \
  Check: IsServiceInstalled

; Brief pause for SCM to fully stop the service before re-registering
Filename: "{sys}\timeout.exe"; Parameters: "/t 3 /nobreak"; \
  Flags: runhidden waituntilterminated; Check: IsServiceInstalled

; STEP 2: Remove old SCM registration if upgrading
Filename: "{app}\{#AppExeName}"; Parameters: "remove"; \
  Flags: runhidden waituntilterminated; StatusMsg: "Removing old service registration..."; \
  Check: IsServiceInstalled

; Brief pause for SCM to process the delete before re-registering  
Filename: "{sys}\timeout.exe"; Parameters: "/t 3 /nobreak"; \
  Flags: runhidden waituntilterminated; Check: IsServiceInstalled

; STEP 3: Install/re-register service in SCM
Filename: "{app}\{#AppExeName}"; Parameters: "install"; \
  Flags: runhidden waituntilterminated; StatusMsg: "Registering Mnemostroma service..."

; STEP 4: Configure service recovery — auto-restart on crash
; sc.exe failure: reset=86400 (1 day), actions= restart/5000ms x3 then noop
Filename: "sc.exe"; \
  Parameters: "failure {#ServiceName} reset= 86400 actions= restart/5000/restart/5000/restart/5000"; \
  Flags: runhidden waituntilterminated; StatusMsg: "Configuring service recovery..."

; STEP 5: Start the service
Filename: "sc.exe"; Parameters: "start {#ServiceName}"; \
  Flags: runhidden waituntilterminated; StatusMsg: "Starting Mnemostroma service..."

[UninstallRun]
; STEP 1: Stop service
Filename: "sc.exe"; Parameters: "stop {#ServiceName}"; \
  Flags: runhidden waituntilterminated

; Brief pause
Filename: "{sys}\timeout.exe"; Parameters: "/t 5 /nobreak"; \
  Flags: runhidden waituntilterminated

; STEP 2: Unregister from SCM
Filename: "{app}\{#AppExeName}"; Parameters: "remove"; \
  Flags: runhidden waituntilterminated

[UninstallDelete]
; Remove the entire install directory (exe + temp files)
Type: filesandordirs; Name: "{app}"

[Code]
// ---------------------------------------------------------------------------
// Helper: check if mnemostroma-service is already registered in SCM.
// Used to skip stop/remove steps on fresh installs.
// ---------------------------------------------------------------------------
function IsServiceInstalled: Boolean;
var
  Res: DWORD;
begin
  // A quick sc.exe query returns 0 if service exists, non-zero otherwise.
  Result := (RegQueryDWordValue(HKLM,
    'SYSTEM\CurrentControlSet\Services\{#ServiceName}',
    'Type', Res) = True);
end;

// ---------------------------------------------------------------------------
// OnUninstallNeedRestart: never force restart after uninstall
// ---------------------------------------------------------------------------
function InitializeUninstall: Boolean;
begin
  Result := True;
end;
