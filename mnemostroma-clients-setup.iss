; =============================================================================
; mnemostroma-clients-setup.iss — Inno Setup script for Mnemostroma Clients
; (System Tray + Browser Extension)
;
; Installs cleanly to user space without requiring Administrator privileges:
;   - Tray executable -> C:\Users\<Name>\.mnemostroma\tray\mnemostroma-tray.exe
;   - Extension folder -> C:\Users\<Name>\.mnemostroma\extension\
;
; Requires: Inno Setup 6.3+ (https://jrsoftware.org/isinfo.php)
; Build on Windows VM:
;   iscc mnemostroma-clients-setup.iss
; =============================================================================

#define AppName      "Mnemostroma Clients"
#define AppVersion   "2.3.2"
#define AppPublisher "GG-QandV"
#define AppURL       "https://github.com/GG-QandV/mnemostroma"
#define TrayExeName  "mnemostroma-tray.exe"

[Setup]
; --- Identity -----------------------------------------------------------------
AppId={{C7B2F8E1-2D4C-4B6A-91FA-2D5E6F8A9B1C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases

; --- Installation paths -------------------------------------------------------
; Installs directly into user's home folder .mnemostroma
DefaultDirName={%USERPROFILE}\.mnemostroma
DisableDirPage=yes
DisableProgramGroupPage=yes

; --- Output -------------------------------------------------------------------
OutputDir=installer
OutputBaseFilename=mnemostroma-clients-setup
SetupIconFile=

; --- Privileges ---------------------------------------------------------------
; NO ADMIN PRIVILEGES REQUIRED. Installs seamlessly inside userprofile.
PrivilegesRequired=lowest

; --- UI -----------------------------------------------------------------------
WizardStyle=modern
WizardResizable=no
DisableWelcomePage=no
LicenseFile=
InfoBeforeFile=

; --- Compression --------------------------------------------------------------
Compression=lzma2/ultra64
SolidCompression=no

; --- Misc ---------------------------------------------------------------------
UninstallDisplayIcon={app}\tray\{#TrayExeName}
UninstallDisplayName={#AppName} {#AppVersion}
ChangesEnvironment=no
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no
MinVersion=10.0.10240

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
russian.WelcomeLabel1=Установка Mnemostroma Clients
russian.WelcomeLabel2=Этот мастер установит клиентские приложения Mnemostroma (системный трей и расширение браузера) в вашу домашнюю папку.%n%nПрава администратора не требуются.%n%nНажмите «Далее», чтобы продолжить.
russian.FinishedHeadingLabel=Установка завершена
russian.FinishedLabel=Системный трей и расширение браузера успешно установлены!%n%nПапка расширения: {app}\extension%nПапка системного трея: {app}\tray%n%nДля завершения настройки расширения в браузере (Chrome, Edge, Brave, Opera):%n1. Откройте страницу chrome://extensions/%n2. Включите «Режим разработчика» (вверху справа).%n3. Нажмите «Загрузить распакованное расширение» (вверху слева).%n4. Выберите папку: {app}\extension

english.WelcomeLabel1=Welcome to {#AppName} Setup
english.WelcomeLabel2=This will install Mnemostroma client components (system tray and browser extension) into your home folder.%n%nNo administrator privileges are required.%n%nClick Next to continue.
english.FinishedHeadingLabel=Setup Complete
english.FinishedLabel={#AppName} has been successfully installed!%n%nExtension Folder: {app}\extension%nTray Folder: {app}\tray%n%nTo finish browser extension setup (Chrome, Edge, Brave, Opera):%n1. Open chrome://extensions/ in your browser.%n2. Enable "Developer Mode" (top right toggle).%n3. Click "Load unpacked" (top left button).%n4. Select the folder: {app}\extension

[Files]
; --- System Tray ---
Source: "dist\{#TrayExeName}"; DestDir: "{app}\tray"; Flags: ignoreversion

; --- Browser Extension (entire directory structure) ---
Source: "src\extension\*"; DestDir: "{app}\extension"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "node_modules\*"

[Dirs]
; Ensure directories are created
Name: "{app}\tray"
Name: "{app}\extension"

[Registry]
; --- Autostart System Tray on Windows User Login ---
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "MnemostromaTray"; \
  ValueData: """{app}\tray\{#TrayExeName}"""; Flags: uninsdeletevalue

[Run]
; --- Launch System Tray immediately after setup completes ---
Filename: "{app}\tray\{#TrayExeName}"; \
  Description: "{cm:LaunchProgram,Mnemostroma Tray}"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Terminate tray before uninstalling
Filename: "taskkill.exe"; Parameters: "/F /IM {#TrayExeName}"; Flags: runhidden waituntilterminated

[UninstallDelete]
; Clean up installed folders
Type: filesandordirs; Name: "{app}\tray"
Type: filesandordirs; Name: "{app}\extension"
