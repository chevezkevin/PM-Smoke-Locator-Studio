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
- Incluye perfiles de nivel de humo: `Actual`, `Suave`, `Fuerte` y `Pesado`; `Actual` es el predeterminado.
- Incluye ajustes manuales `X/Y/Z` para mover los locators si un escape queda alto, bajo o corrido.
- Usa un detector ampliado para encontrar escapes con nombres o carpetas menos comunes.
- Descarga e inicia el `Setup` automaticamente desde GitHub Releases al usar `Actualizar`.
- Limpia temporales de trabajo para evitar llenar el disco.
- Muestra vista previa antes de crear, barra de espacio libre y permite importar varios mods a la vez.
- Guarda diagnosticos cuando un mod falla.
- Coloca `Actualizar` en la cabecera para separarlo de las acciones de crear humo.
- Agrega una referencia visual para los ejes X/Y/Z del ajuste manual.
- Abre el instalador de actualizacion desde un lanzador temporal para evitar errores de validacion.
- Incluye editor visual de locators con tabla, vista X/Z, activacion y ajuste X/Y/Z por punto.
- Corrige el bloqueo del editor visual al abrir locators detectados.
- Limpia el ambiente de PyInstaller al actualizar y deja sin marcar abrir la app al terminar el setup.
- Permite filtrar el editor visual por cada modelo de escape para ver sus puntos separados.
- Dibuja una referencia gris del cuerpo del escape y agrega botones X/Y/Z para mover puntos con paso fino.
- El editor visual muestra por defecto solo el locator seleccionado, con opcion para ver todos los puntos.
- Marca en verde una salida sugerida del escape y permite mover el locator directamente a esa posicion.
- La salida sugerida ahora usa la altura superior del escape y puede aplicarse a todos los locators visibles.
- Mantiene la direccion/rotacion original de PM como predeterminada y conserva las mejoras de posicion/altura.
- Permite direccion de humo opcional por escape y ajuste por locator desde el editor visual.

## Uso normal

1. Ejecuta `Abrir_PM_Smoke_Locator_Studio.bat`.
2. Selecciona el mod del camion.
3. Escoge `ATS` o `ETS2`.
4. Presiona `Analizar`.
5. Deja el nivel en `Actual` o escoge otro perfil.
6. Si el humo necesita ajuste, cambia `X/Y/Z`.
7. Revisa `Vista previa`.
8. Presiona `Crear humo`.
9. En el Mod Manager, pon el parche arriba del mod del camion.

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
dist\PMSmokeLocatorStudio_v0.3.10.exe
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
3. Crea un tag, por ejemplo `v0.3.10`.
4. Sube el tag a GitHub.
5. GitHub Actions compila el `.exe` y el `Setup`.
6. La app instalada puede usar el boton `Actualizar` para descargar y abrir el Setup del ultimo Release.

Ejemplo:

```powershell
git tag v0.3.10
git push origin v0.3.10
```

## Seguridad

La herramienta no cambia motores, sonidos, fisica ni definiciones originales del camion. El modo mas seguro es `Crear parche seguro aparte`.
