# PM Smoke Locator Studio

Herramienta visual para crear locators `model.particle.smoke_new` en modelos de escape de camiones ATS.

## Que hace

- Lee un mod `.scs` o `.zip`.
- Busca definiciones de escapes en `def/vehicle/truck/.../accessory/exhaust`.
- Convierte modelos `.pmd/.pmg` a `.pim`.
- Quita locators viejos de humo como `smokeken`.
- Agrega locators nuevos `model.particle.smoke_new`.
- Crea un parche seguro o integra el resultado dentro del mod principal `PM_389_Smoke_All_Trucks_ATS_1.60.zip`.
- Genera un reporte con modelos encontrados, locators agregados y avisos.
- Permite escoger modo `ATS` o `ETS2` para usar la carpeta correcta de mods.
- Incluye ajustes manuales `X/Y/Z` para mover los locators si un escape queda alto, bajo o corrido.
- Usa un detector ampliado para encontrar escapes con nombres o carpetas menos comunes.

## Uso normal

1. Ejecuta `Abrir_PM_Smoke_Locator_Studio.bat`.
2. Selecciona el mod del camion.
3. Escoge `ATS` o `ETS2`.
4. Presiona `Analizar`.
5. Si el humo necesita ajuste, cambia `X/Y/Z`.
6. Presiona `Crear humo`.
7. En el Mod Manager, pon el parche arriba del mod del camion.

## Crear EXE

Ejecuta en PowerShell:

```powershell
.\SmokeLocatorStudio\build_exe.ps1
```

El ejecutable queda en:

```text
dist\PMSmokeLocatorStudio.exe
```

Tambien se crea una copia versionada:

```text
dist\PMSmokeLocatorStudio_v0.2.0.exe
```

## Crear Setup

El instalador se crea con Inno Setup usando:

```text
SmokeLocatorStudio\installer.iss
```

Cuando GitHub Actions corre desde un tag `v...`, compila:

- `PMSmokeLocatorStudio.exe`
- `PMSmokeLocatorStudio_vX.X.X.exe`
- `PMSmokeLocatorStudio_Setup_vX.X.X.exe`

## GitHub y actualizaciones

Este proyecto esta listo para subirse a GitHub y publicar instaladores.

Ruta recomendada:

```text
PM-Smoke-Locator-Studio
```

Para publicar actualizaciones:

1. Sube el proyecto a GitHub.
2. Cambia `APP_VERSION` y `installer.iss` a la nueva version.
3. Crea un tag, por ejemplo `v0.2.0`.
4. Sube el tag a GitHub.
5. GitHub Actions compila el `.exe` y el `Setup`.
6. La app instalada puede usar el boton `Actualizar` para abrir la descarga del ultimo Release.

Ejemplo:

```powershell
git tag v0.2.0
git push origin v0.2.0
```

## Seguridad

La herramienta no cambia motores, sonidos, fisica ni definiciones originales del camion. El modo mas seguro es `Crear parche seguro aparte`.
