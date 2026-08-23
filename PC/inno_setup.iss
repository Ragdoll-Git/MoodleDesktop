; La versión se puede pasar desde la línea de comandos con /DMyAppVersion=x.y.z
; (lo hace el workflow de GitHub Actions a partir del tag). Si no se define,
; se usa este valor por defecto para los builds locales.
#ifndef MyAppVersion
  #define MyAppVersion "3.8.2"
#endif

[Setup]
AppName=FMoodle
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\FMoodle
DefaultGroupName=FMoodle
OutputBaseFilename=FMoodle_Installer
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Crear un icono en el escritorio"; GroupDescription: "Iconos adicionales:"

[Files]
Source: "dist\FMoodle\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FMoodle"; Filename: "{app}\FMoodle.exe"
Name: "{commondesktop}\FMoodle"; Filename: "{app}\FMoodle.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FMoodle.exe"; Description: "Ejecutar FMoodle"; Flags: nowait postinstall skipifsilent
