; La versión se puede pasar desde la línea de comandos con /DMyAppVersion=x.y.z
; (lo hace el workflow de GitHub Actions a partir del tag). Si no se define,
; se usa este valor por defecto para los builds locales.
#ifndef MyAppVersion
  #define MyAppVersion "3.8.2"
#endif

[Setup]
AppName=Moodle Desktop
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\MoodleDesktop
DefaultGroupName=Moodle Desktop
OutputBaseFilename=MoodleDesktop_Installer
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Crear un icono en el escritorio"; GroupDescription: "Iconos adicionales:"

[Files]
Source: "dist\MoodleDesktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Moodle Desktop"; Filename: "{app}\MoodleDesktop.exe"
Name: "{commondesktop}\Moodle Desktop"; Filename: "{app}\MoodleDesktop.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MoodleDesktop.exe"; Description: "Ejecutar Moodle Desktop"; Flags: nowait postinstall skipifsilent
