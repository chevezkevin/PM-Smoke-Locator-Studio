from __future__ import annotations

import argparse
import json
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


APP_TITLE = "PM Smoke Locator Studio"
APP_VERSION = "0.3.16"
GITHUB_REPO = "chevezkevin/PM-Smoke-Locator-Studio"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundled_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return app_root()


ROOT = app_root()
BUNDLE = bundled_root()
WORK = (Path.home() / "Documents" / "PM Smoke Locator Studio" / "work") if getattr(sys, "frozen", False) else ROOT / "work"
UPDATES = (Path.home() / "Documents" / "PM Smoke Locator Studio" / "updates") if getattr(sys, "frozen", False) else ROOT / "outputs" / "updates"
BLENDER_EXPORTS = Path.home() / "Documents" / "PM Smoke Locator Studio" / "blender"
TOOLS = BUNDLE / "work" / "tools"
DEFAULT_ICON = BUNDLE / "SmokeLocatorStudio" / "assets" / "mod_icon.jpg"
MOD_ICON_SIZE = (276, 162)
CONVERTER_PIX = TOOLS / "converter_pix" / "converter_pix.exe"
CONVERSION_TOOLS_ZIP = TOOLS / "conversion_tools_2_21.zip"
EXTRACTOR = TOOLS / "sk_extractor_gh" / "extractor.exe"
SCS_EXTRACTOR = TOOLS / "scs_extractor_1_55" / "scs_extractor.exe"
ATS_MOD_DIR = Path.home() / "Documents" / "American Truck Simulator" / "mod"
ETS2_MOD_DIR = Path.home() / "Documents" / "Euro Truck Simulator 2" / "mod"
DEFAULT_SMOKE_FILE = "PM_389_Smoke_All_Trucks_ATS_1.60.zip"
DEFAULT_SMOKE_MOD = ATS_MOD_DIR / DEFAULT_SMOKE_FILE
GAME_MOD_DIRS = {
    "ats": ATS_MOD_DIR,
    "ets2": ETS2_MOD_DIR,
}
EXHAUST_ACCESSORY_DIRS = {
    "exhaust",
    "cab_exhaust",
    "exh",
    "exhrear",
    "exhaust_rear",
    "rear_exhaust",
    "stacks",
}
EXHAUST_HINTS = {
    "exhaust",
    "exh",
    "stack",
    "stacks",
    "pipe",
    "pipes",
    "muffler",
    "smoke",
    "escape",
    "escapes",
    "chimney",
}
MODEL_EXCLUDE_HINTS = {
    "/empty/",
    "/interior/",
    "/bumper/",
    "/beacon/",
    "/headlight/",
    "/mirror/",
    "/horn/",
    "/wheel/",
    "/fender/",
    "/mudflap/",
    "/paintjob/",
    "/license",
}


LogFn = Callable[[str], None]
LocatorOffset = tuple[float, float, float]
SMOKE_PROFILE_SCALES = {
    "Actual": 1.0,
    "Suave": 0.75,
    "Fuerte": 1.25,
    "Pesado": 1.5,
}
SMOKE_DIRECTION_ROTATIONS = {
    "Original PM": (6.123234262925839e-17, 0.0, 1.0, 0.0),
    "Arriba": (0.70710677, -0.70710677, 0.0, 0.0),
    "Abajo": (0.70710677, 0.70710677, 0.0, 0.0),
    "Adelante": (1.0, 0.0, 0.0, 0.0),
    "Atras": (0.0, 0.0, 1.0, 0.0),
    "Izquierda": (0.70710677, 0.0, -0.70710677, 0.0),
    "Derecha": (0.70710677, 0.0, 0.70710677, 0.0),
}
SMOKE_DIRECTION_CHOICES = list(SMOKE_DIRECTION_ROTATIONS) + ["Automatico"]
CLEANUP_MODES = {
    "Al terminar bien": "success",
    "Siempre": "always",
    "Nunca": "never",
}


@dataclass(frozen=True)
class ExhaustModel:
    model_no_ext: str
    source_def: Path
    variant: str
    look: str


@dataclass(frozen=True)
class LocatorCandidate:
    key: str
    model_no_ext: str
    pim_rel: str
    part_name: str
    ordinal: int
    position: tuple[float, float, float]
    bounds: tuple[float, float, float, float, float, float]
    outlet_position: tuple[float, float, float]
    suggested_direction: str
    outlet_kind: str
    preview_vertices: tuple[tuple[float, float, float], ...]


@dataclass(frozen=True)
class LocatorEdit:
    enabled: bool
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float] | None = None


@dataclass
class BuildResult:
    output_zip: Path
    report_path: Path
    model_count: int
    locator_count: int
    removed_smoke_locators: int
    warnings: list[str]


class ToolError(RuntimeError):
    pass


def parse_version(value: str) -> tuple[int, ...]:
    clean = value.strip().lower().lstrip("v")
    parts = []
    for part in clean.split("."):
        number = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(number or "0"))
    return tuple(parts or [0])


def fetch_latest_release() -> dict:
    request = urllib.request.Request(
        GITHUB_LATEST_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"{APP_TITLE}/{APP_VERSION}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ToolError("Todavia no hay Releases publicados en GitHub.") from exc
        raise ToolError(f"No pude revisar GitHub: HTTP {exc.code}") from exc
    except Exception as exc:
        raise ToolError(f"No pude revisar actualizaciones: {exc}") from exc


def setup_asset_url(data: dict) -> str | None:
    for asset in data.get("assets", []):
        name = str(asset.get("name") or "")
        if name.lower().startswith("pmsmokelocatorstudio_setup_") and name.lower().endswith(".exe"):
            return str(asset.get("browser_download_url") or "")
    return None


def latest_release() -> tuple[str, str, str | None]:
    data = fetch_latest_release()
    tag = str(data.get("tag_name") or "").strip()
    url = str(data.get("html_url") or GITHUB_RELEASES_URL)
    if not tag:
        raise ToolError("GitHub no devolvio una version valida.")
    return tag, url, setup_asset_url(data)


def manual_text() -> str:
    return f"""PM Smoke Locator Studio - Manual de uso
Version: {APP_VERSION}

1. Para que sirve
Esta app agrega humo smoke_new a escapes de camiones ATS y ETS2. Puede crear un parche aparte, crear un mod completo nuevo o integrar el resultado dentro del PM Smoke principal.

2. Orden recomendado
1. Escoge el juego: ATS o ETS2.
2. En Mod del camion, selecciona el .scs o .zip del camion.
3. En Salida, deja la carpeta mod del juego o escoge otra carpeta.
4. En PM Smoke principal, selecciona tu PM_389_Smoke_All_Trucks_ATS_1.60.zip cuando vas a integrar.
5. Presiona Analizar para ver si encontro escapes.
6. Presiona Vista previa para revisar cuantos locators va a crear.
7. Si hace falta, abre Editor locators y ajusta los puntos.
8. Presiona Crear humo.
9. En el Mod Manager, pon el parche arriba del mod del camion.

3. Juego ATS / ETS2
ATS usa la carpeta Documents/American Truck Simulator/mod.
ETS2 usa la carpeta Documents/Euro Truck Simulator 2/mod.
La logica del humo sirve para ambos juegos, pero cada juego usa su propia carpeta de mods.

4. Mod del camion
Aqui va el camion que quieres adaptar. Puede ser .scs o .zip. La app extrae el mod, busca modelos de escape y les agrega locators de humo.

5. Salida
Aqui se guarda el parche o mod creado. Si activas Copiar a carpeta de salida, la app copia el resultado ahi.

6. PM Smoke principal
Usalo cuando eliges Integrar dentro del PM Smoke principal. La app mete el camion nuevo dentro de ese mod de humo sin tocar motores ni fisicas del camion.

7. Foto del mod
Puedes escoger una imagen propia. La app la convierte al formato que ATS/ETS2 usa para el icono del mod.

8. Nivel
Actual: humo normal recomendado.
Suave: menos humo.
Fuerte: mas humo.
Pesado: humo mas denso.

9. Ajuste manual locators X/Y/Z
X - mueve a la izquierda.
X + mueve a la derecha.
Y - baja el humo.
Y + sube el humo.
Z - mueve hacia atras.
Z + mueve hacia adelante.
Usa cambios pequenos como 0.02 o 0.05 para afinar.

10. Auto-limpieza
Al terminar bien: borra temporales solo si todo sale bien.
Siempre: borra temporales aunque falle.
Nunca: deja temporales para revisar errores.

11. Modo diagnostico
Si un mod falla, guarda un reporte con detalles para revisar que paso.

12. Direccion humo
Original PM: recomendado. Usa la direccion original del PM Smoke, que normalmente se ve mejor en el juego.
Automatico: intenta calcular direccion segun la pieza del escape.
Arriba, Abajo, Adelante, Atras, Izquierda, Derecha: ajustes manuales especiales si un mod lo necesita.

13. Modos de creacion
Crear parche seguro aparte: recomendado. Crea un parche separado para poner arriba del camion.
Crear mod completo nuevo: crea un mod nuevo con el humo incluido.
Integrar dentro del PM Smoke principal: agrega el camion al mod PM Smoke principal.

14. Botones principales
Analizar: busca los escapes y muestra cuantos encontro.
Vista previa: muestra lo que va a crear antes de modificar.
Editor locators: permite mover cada punto de humo.
Crear humo: crea el parche/mod final.
Limpiar temporales: libera espacio borrando carpetas de trabajo.
Limpiar log: limpia la pantalla de mensajes.
Actualizar: descarga el setup nuevo desde GitHub Releases.
Manual: guarda este manual en tu PC.

15. Editor visual de locators
Amarillo: punto de humo seleccionado.
Verde: salida sugerida del escape.
Gris: silueta del modelo real del escape.
Rectangulo: limite de la pieza del escape.
Solo seleccionado: muestra solo el punto actual para verlo claro.
Modelo de escape: filtra los puntos por escape.
Vista 3D libre: visor simple tipo Blender. Arrastra con el mouse para girar el escape completo y usa la rueda para acercar o alejar.
Vista X/Z: ve el escape desde arriba.
Vista X/Y: ve el escape de lado para revisar altura y curva.
Vista Z/Y: ve el escape de frente/atras para revisar salida hacia adelante o atras.
Reset 3D: vuelve la camara del visor 3D a la posicion inicial.
Abrir Blender: exporta el escape seleccionado a OBJ y abre Blender real si esta instalado. El OBJ incluye el escape, PM_humo_actual y PM_boca_detectada para revisar mejor la posicion.
Zoom boca: acerca la vista a la punta del escape cuando necesitas detalle. Desmarcalo si quieres ver el escape completo.
Usar este locator: activa o desactiva ese punto.
X/Y/Z: mueve el punto exacto.
Paso: cantidad que mueve cada boton.
Mover a salida sugerida: lleva el punto amarillo a la salida verde.
Mover visibles a salida alta: mueve todos los puntos visibles a la salida alta sugerida.
Aplicar punto: guarda el cambio del punto actual.
Guardar y cerrar: guarda todos los cambios del editor.

16. Si el humo queda bajo
Abre Editor locators, selecciona el modelo de escape, marca Solo seleccionado, usa Y + para subir o Mover a salida sugerida. Luego guarda y vuelve a crear humo.

17. Si el humo sale en direccion rara
Deja Direccion humo en Original PM. Esa es la direccion base recomendada. Solo cambia a Automatico o direcciones manuales si estas probando un mod especial.

18. Boca inteligente
La app usa vertices reales del escape para colocar el humo en la boca mas probable. Esto ayuda con escapes rectos, curvos, cortados a 45 grados y salidas laterales. Si no queda perfecto, usa el editor visual y mueve el punto amarillo encima de la boca verde.

18.1 Blender real
El boton Abrir Blender crea un archivo OBJ en Documents/PM Smoke Locator Studio/blender y lo abre en Blender si lo encuentra.
Ese visor es para revisar el modelo con mas detalle. La app todavia no importa cambios desde Blender; despues de mirar el escape, vuelve al editor de locators y ajusta X/Y/Z en la app.

19. Si no encuentra escapes
Activa Modo diagnostico y presiona Analizar otra vez. Algunos mods usan carpetas o nombres raros. Revisa el reporte creado en Documents/PM Smoke Locator Studio/work.

20. Si sale No space left on device
Presiona Limpiar temporales. Tambien puedes cambiar Auto-limpieza a Siempre si estas probando muchos mods grandes.

21. Recomendacion final
Para trabajar seguro usa:
Juego correcto, Nivel Actual, Direccion humo Original PM, Crear parche seguro aparte y Copiar a carpeta de salida.
"""


def default_manual_path() -> Path:
    return Path.home() / "Documents" / "PM Smoke Locator Studio" / f"PM_Smoke_Locator_Studio_Manual_v{APP_VERSION}.txt"


def download_update_setup(tag: str, setup_url: str, log: LogFn = print) -> Path:
    if not setup_url:
        raise ToolError("El Release nuevo no tiene un Setup .exe adjunto.")

    UPDATES.mkdir(parents=True, exist_ok=True)
    dest = UPDATES / f"PMSmokeLocatorStudio_Setup_{tag.lstrip('v')}.exe"
    part = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(setup_url, headers={"User-Agent": f"{APP_TITLE}/{APP_VERSION}"})
    log(f"Descargando actualizacion {tag}...")
    with urllib.request.urlopen(request, timeout=30) as response, part.open("wb") as fh:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        next_report = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                percent = int(done * 100 / total)
                if percent >= next_report:
                    log(f"  descarga {percent}%")
                    next_report += 10
    if dest.exists():
        dest.unlink()
    part.replace(dest)
    log(f"Setup descargado: {dest}")
    return dest


def launch_update_setup(setup_path: Path) -> Path:
    UPDATES.mkdir(parents=True, exist_ok=True)
    launcher = UPDATES / "run_pm_smoke_update.cmd"
    setup_log = UPDATES / f"{setup_path.stem}.log"
    launcher.write_text(
        "\n".join(
            [
                "@echo off",
                "timeout /t 2 /nobreak >nul",
                "set PYINSTALLER_RESET_ENVIRONMENT=1",
                "set _PYI_ARCHIVE_FILE=",
                "set _PYI_PARENT_PROCESS_LEVEL=",
                "set _PYI_APPLICATION_HOME_DIR=",
                "set _PYI_SPLASH_IPC=",
                f'start /wait "" "{setup_path}" /CURRENTUSER /CLOSEAPPLICATIONS /NORESTART /LOG="{setup_log}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    creationflags = 0
    for name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NO_WINDOW"):
        creationflags |= getattr(subprocess, name, 0)
    subprocess.Popen(
        ["cmd.exe", "/d", "/c", str(launcher)],
        cwd=str(UPDATES),
        close_fds=True,
        creationflags=creationflags,
    )
    return setup_log


def game_mod_dir(game: str) -> Path:
    return GAME_MOD_DIRS.get(game.lower(), ATS_MOD_DIR)


def default_smoke_mod(game: str) -> Path:
    return game_mod_dir(game) / DEFAULT_SMOKE_FILE


def run_command(args: list[str | Path], cwd: Path | None = None, log: LogFn | None = None) -> str:
    if log:
        log("> " + " ".join(str(a) for a in args))
    proc = subprocess.run(
        [str(a) for a in args],
        cwd=cwd,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if log and output.strip():
        for line in output.splitlines():
            log(line)
    if proc.returncode:
        raise ToolError(f"Command failed ({proc.returncode}): {' '.join(str(a) for a in args)}\n{output}")
    return output


def read_float_token(token: str) -> float:
    if token.startswith("&"):
        return struct.unpack(">f", bytes.fromhex(token[1:]))[0]
    return float(token)


def write_float_token(value: float) -> str:
    return "&" + struct.pack(">f", float(value)).hex()


def average(points: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    return tuple(sum(point[i] for point in points) / len(points) for i in range(3))  # type: ignore[return-value]


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    idx = min(len(values) - 1, max(0, int(len(values) * q)))
    return sorted(values)[idx]


def smoke_positions(vertices: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    if not vertices:
        return []

    y_cut = quantile([v[1] for v in vertices], 0.985)
    top = [v for v in vertices if v[1] >= y_cut] or vertices
    by_x = sorted(top, key=lambda point: point[0])

    if len(by_x) >= 2:
        gaps = [(by_x[i + 1][0] - by_x[i][0], i) for i in range(len(by_x) - 1)]
        largest_gap, split_at = max(gaps, key=lambda item: item[0])
        x_span = by_x[-1][0] - by_x[0][0]

        # Split only when the model is wide enough and has a clear gap between
        # two outlets. Some exhaust caps expose very few top vertices per side.
        if x_span > 1.0 and largest_gap > max(0.45, x_span * 0.25):
            left = by_x[: split_at + 1]
            right = by_x[split_at + 1 :]
            if left and right:
                return [average(left), average(right)]

    return [average(top)]


def horizontal_distance(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return ((left[0] - right[0]) ** 2 + (left[2] - right[2]) ** 2) ** 0.5


def merge_close_positions(
    positions: list[tuple[float, float, float]], min_distance: float = 0.28
) -> list[tuple[float, float, float]]:
    clusters: list[list[tuple[float, float, float]]] = []
    for position in sorted(positions, key=lambda point: (point[0], point[2], point[1])):
        for cluster in clusters:
            if horizontal_distance(position, average(cluster)) < min_distance:
                cluster.append(position)
                break
        else:
            clusters.append([position])
    return [average(cluster) for cluster in clusters]


def parse_piece_vertices(pim_path: Path) -> dict[int, list[tuple[float, float, float]]]:
    piece_vertices: dict[int, list[tuple[float, float, float]]] = {}
    vertex_re = re.compile(
        r"\s+\d+\s+\(\s+([&0-9a-fA-F.\-]+)\s+([&0-9a-fA-F.\-]+)\s+([&0-9a-fA-F.\-]+)\s+\)"
    )

    current_index: int | None = None
    current_vertices: list[tuple[float, float, float]] = []
    in_piece = False
    in_position_stream = False
    depth = 0

    with pim_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped == "Piece {":
                in_piece = True
                current_index = None
                current_vertices = []
                depth = 1
                continue

            if not in_piece:
                continue

            depth += line.count("{") - line.count("}")

            if current_index is None:
                match_index = re.match(r"\s*Index:\s+(\d+)", line)
                if match_index:
                    current_index = int(match_index.group(1))

            if 'Tag: "_POSITION"' in line:
                in_position_stream = True
                continue

            if in_position_stream:
                if stripped == "}":
                    in_position_stream = False
                    continue
                match_vertex = vertex_re.match(line)
                if match_vertex:
                    current_vertices.append(tuple(read_float_token(part) for part in match_vertex.groups()))

            if depth == 0:
                if current_index is not None:
                    piece_vertices[current_index] = current_vertices
                in_piece = False

    return piece_vertices


def parse_part_pieces(text: str) -> dict[str, list[int]]:
    part_counts: dict[str, int] = {}
    parts: dict[str, list[int]] = {}
    for part_match in re.finditer(r"Part \{\n.*?\n\}", text, flags=re.S):
        block = part_match.group(0)
        name_match = re.search(r'Name:\s*"([^"]+)"', block)
        part_name = name_match.group(1) if name_match else "part"
        part_counts[part_name] = part_counts.get(part_name, 0) + 1
        part_identity = f"{part_name}#{part_counts[part_name]}"
        pieces_match = re.search(r"Pieces:\s*([0-9 ]*)", block)
        parts[part_identity] = [int(value) for value in pieces_match.group(1).split()] if pieces_match else []
    return parts


def parse_piece_meshes(
    pim_path: Path, target_pieces: set[int]
) -> dict[int, tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]]:
    meshes: dict[int, tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]] = {}
    vertex_re = re.compile(
        r"\s+\d+\s+\(\s+([&0-9a-fA-F.\-]+)\s+([&0-9a-fA-F.\-]+)\s+([&0-9a-fA-F.\-]+)\s+\)"
    )
    triangle_re = re.compile(r"\s+\d+\s+\(\s+(\d+)\s+(\d+)\s+(\d+)\s+\)")
    current_index: int | None = None
    current_vertices: list[tuple[float, float, float]] = []
    current_triangles: list[tuple[int, int, int]] = []
    in_piece = False
    in_position_stream = False
    in_triangles = False
    depth = 0

    with pim_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped == "Piece {":
                in_piece = True
                current_index = None
                current_vertices = []
                current_triangles = []
                in_position_stream = False
                in_triangles = False
                depth = 1
                continue

            if not in_piece:
                continue

            depth += line.count("{") - line.count("}")

            if current_index is None:
                match_index = re.match(r"\s*Index:\s+(\d+)", line)
                if match_index:
                    current_index = int(match_index.group(1))

            wanted = current_index in target_pieces if current_index is not None else False
            if 'Tag: "_POSITION"' in line and wanted:
                in_position_stream = True
                continue
            if stripped == "Triangles {" and wanted:
                in_triangles = True
                continue

            if in_position_stream:
                if stripped == "}":
                    in_position_stream = False
                    continue
                match_vertex = vertex_re.match(line)
                if match_vertex:
                    current_vertices.append(tuple(read_float_token(part) for part in match_vertex.groups()))

            if in_triangles:
                if stripped == "}":
                    in_triangles = False
                    continue
                match_triangle = triangle_re.match(line)
                if match_triangle:
                    current_triangles.append(tuple(int(value) for value in match_triangle.groups()))

            if depth == 0:
                if current_index in target_pieces:
                    meshes[current_index] = (current_vertices, current_triangles)
                in_piece = False

    return meshes


def blender_executable() -> Path | None:
    found = shutil.which("blender")
    if found:
        return Path(found)
    roots = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        str(Path.home() / "AppData" / "Local" / "Programs"),
    ]
    candidates: list[Path] = []
    for root_text in roots:
        if not root_text:
            continue
        root = Path(root_text)
        candidates.extend(root.glob("Blender Foundation/Blender*/blender.exe"))
        candidates.extend(root.glob("Blender*/blender.exe"))
    return sorted(candidates, reverse=True)[0] if candidates else None


def write_blender_materials(mtl_path: Path) -> None:
    mtl_path.write_text(
        "\n".join(
            [
                "newmtl escape_gray",
                "Kd 0.70 0.76 0.84",
                "Ks 0.25 0.25 0.25",
                "",
                "newmtl smoke_yellow",
                "Kd 1.00 0.82 0.08",
                "",
                "newmtl outlet_green",
                "Kd 0.13 0.77 0.37",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def ats_to_blender(point: tuple[float, float, float]) -> tuple[float, float, float]:
    return (point[0], point[2], point[1])


def write_obj_marker(
    fh,
    name: str,
    point: tuple[float, float, float],
    size: float,
    material: str,
    next_index: int,
) -> int:
    x_value, y_value, z_value = ats_to_blender(point)
    corners = [
        (x_value - size, y_value - size, z_value - size),
        (x_value + size, y_value - size, z_value - size),
        (x_value + size, y_value + size, z_value - size),
        (x_value - size, y_value + size, z_value - size),
        (x_value - size, y_value - size, z_value + size),
        (x_value + size, y_value - size, z_value + size),
        (x_value + size, y_value + size, z_value + size),
        (x_value - size, y_value + size, z_value + size),
    ]
    fh.write(f"\no {name}\nusemtl {material}\n")
    for corner in corners:
        fh.write(f"v {corner[0]:.6f} {corner[1]:.6f} {corner[2]:.6f}\n")
    faces = [(1, 2, 3, 4), (5, 8, 7, 6), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 8, 4), (4, 8, 5, 1)]
    for face in faces:
        fh.write("f " + " ".join(str(next_index + index - 1) for index in face) + "\n")
    return next_index + len(corners)


def export_pim_part_to_obj(
    pim_path: Path,
    part_identity: str,
    obj_path: Path,
    smoke_position: tuple[float, float, float],
    outlet_position: tuple[float, float, float],
    max_triangles: int = 140000,
) -> tuple[int, int]:
    text = pim_path.read_text(encoding="utf-8", errors="ignore")
    part_pieces = parse_part_pieces(text)
    pieces = part_pieces.get(part_identity)
    if not pieces:
        raise ToolError(f"No encontre la pieza {part_identity} dentro del modelo convertido.")
    meshes = parse_piece_meshes(pim_path, set(pieces))
    if not meshes:
        raise ToolError("No pude leer la malla del escape para Blender.")

    total_triangles = sum(len(triangles) for _vertices, triangles in meshes.values())
    triangle_step = max(1, total_triangles // max_triangles) if total_triangles > max_triangles else 1
    obj_path.parent.mkdir(parents=True, exist_ok=True)
    write_blender_materials(obj_path.with_suffix(".mtl"))

    exported_vertices = 0
    exported_faces = 0
    next_index = 1
    with obj_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"mtllib {obj_path.with_suffix('.mtl').name}\n")
        fh.write("# Exportado por PM Smoke Locator Studio\n")
        fh.write("# En Blender: X queda igual, Z es adelante/atras, altura ATS Y se muestra como Z vertical.\n")
        fh.write(f"o {safe_name(part_identity)}\nusemtl escape_gray\n")
        for piece, (vertices, triangles) in meshes.items():
            selected_triangles = triangles[::triangle_step] if triangles else []
            used_indices = sorted({index for triangle in selected_triangles for index in triangle})
            if not used_indices:
                used_indices = list(range(0, len(vertices), max(1, len(vertices) // 2500)))
            index_map: dict[int, int] = {}
            fh.write(f"g piece_{piece}\n")
            for local_index in used_indices:
                if local_index >= len(vertices):
                    continue
                index_map[local_index] = next_index
                x_value, y_value, z_value = ats_to_blender(vertices[local_index])
                fh.write(f"v {x_value:.6f} {y_value:.6f} {z_value:.6f}\n")
                next_index += 1
                exported_vertices += 1
            for triangle in selected_triangles:
                if all(index in index_map for index in triangle):
                    fh.write(f"f {index_map[triangle[0]]} {index_map[triangle[1]]} {index_map[triangle[2]]}\n")
                    exported_faces += 1
            if not selected_triangles and index_map:
                fh.write("p " + " ".join(str(value) for value in index_map.values()) + "\n")
        next_index = write_obj_marker(fh, "PM_humo_actual", smoke_position, 0.045, "smoke_yellow", next_index)
        write_obj_marker(fh, "PM_boca_detectada", outlet_position, 0.035, "outlet_green", next_index)
    return exported_vertices, exported_faces


def export_candidate_to_blender_obj(
    mod_path: Path,
    candidate: LocatorCandidate,
    smoke_position: tuple[float, float, float],
    outlet_position: tuple[float, float, float],
    log: LogFn = print,
) -> Path:
    if not CONVERTER_PIX.exists():
        raise ToolError(f"Missing converter: {CONVERTER_PIX}")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    extract_dir = WORK / f"blender_extract_{safe_name(mod_path.stem)}_{stamp}"
    mid_dir = WORK / f"blender_mid_{safe_name(mod_path.stem)}_{stamp}"
    try:
        extract_mod(mod_path, extract_dir, log)
        log(f"Convirtiendo para Blender: {candidate.model_no_ext}")
        run_command([CONVERTER_PIX, "-b", extract_dir, "-e", mid_dir, "-m", candidate.model_no_ext], log=log)
        pim_path = mid_dir / Path(candidate.pim_rel)
        if not pim_path.exists():
            fallback = list(mid_dir.rglob(Path(candidate.pim_rel).name))
            if fallback:
                pim_path = fallback[0]
        if not pim_path.exists():
            raise ToolError("No encontre el .pim convertido para exportar a Blender.")
        part_identity = candidate.key.split("|")[1] if "|" in candidate.key else f"{candidate.part_name}#1"
        obj_name = f"{safe_name(mod_path.stem)}_{safe_name(candidate.part_name)}_{candidate.ordinal}_{stamp}.obj"
        obj_path = BLENDER_EXPORTS / obj_name
        vertices, faces = export_pim_part_to_obj(pim_path, part_identity, obj_path, smoke_position, outlet_position)
        log(f"OBJ Blender creado: {obj_path}")
        log(f"  Vertices: {vertices} | Caras: {faces}")
        return obj_path
    finally:
        cleanup_paths([extract_dir, mid_dir], "always", True, log)


def open_obj_in_blender(obj_path: Path) -> bool:
    blender = blender_executable()
    if blender:
        subprocess.Popen([str(blender), str(obj_path)], close_fds=True)
        return True
    if os.name == "nt":
        os.startfile(str(obj_path.parent))  # type: ignore[attr-defined]
    return False


def parse_locator_blocks(text: str) -> tuple[list[tuple[int, int, str]], dict[int, str]]:
    blocks: list[tuple[int, int, str]] = []
    by_index: dict[int, str] = {}
    for match in re.finditer(r"\nLocator \{\n.*?\n\}", text, flags=re.S):
        block = match.group(0).strip()
        index_match = re.search(r"\bIndex:\s+(\d+)", block)
        if not index_match:
            continue
        index = int(index_match.group(1))
        blocks.append((match.start(), match.end(), block))
        by_index[index] = block
    return blocks, by_index


def is_smoke_locator(block: str) -> bool:
    lowered = block.lower()
    return "smoke" in lowered or "smokeken" in lowered


def rewrite_locator_index(block: str, new_index: int) -> str:
    return re.sub(r"\bIndex:\s+\d+", f"Index: {new_index}", block, count=1)


def iter_named_blocks(text: str, name: str) -> list[str]:
    blocks: list[str] = []
    pattern = re.compile(rf"\b{re.escape(name)}\s*\{{")
    for match in pattern.finditer(text):
        depth = 0
        end = None
        for index in range(match.start(), len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is not None:
            blocks.append(text[match.start() : end])
    return blocks


def common_visible_parts_from_pit(pit_path: Path) -> set[str]:
    text = pit_path.read_text(encoding="utf-8", errors="ignore")
    variant_sets: list[set[str]] = []
    all_parts: set[str] = set()

    for variant_block in iter_named_blocks(text, "Variant"):
        visible_parts: set[str] = set()
        for part_block in iter_named_blocks(variant_block, "Part"):
            name_match = re.search(r'Name:\s*"([^"]+)"', part_block)
            visible_match = re.search(
                r'Tag:\s*"visible".*?Value:\s*\(\s*([01])\s*\)',
                part_block,
                flags=re.S,
            )
            if not name_match:
                continue
            part_name = name_match.group(1)
            all_parts.add(part_name)
            if visible_match and visible_match.group(1) == "1":
                visible_parts.add(part_name)
        if visible_parts:
            variant_sets.append(visible_parts)

    if len(variant_sets) < 2:
        return set()

    common = set.intersection(*variant_sets)
    if not common or len(all_parts - common) == 0:
        return set()
    return common


def apply_offset(position: tuple[float, float, float], offset: LocatorOffset) -> tuple[float, float, float]:
    return tuple(position[i] + offset[i] for i in range(3))  # type: ignore[return-value]


def locator_key(pim_rel: str, part_name: str, ordinal: int) -> str:
    return f"{pim_rel}|{part_name}|{ordinal}"


def locator_positions_from_pieces(
    piece_vertices: dict[int, list[tuple[float, float, float]]], pieces: list[int]
) -> list[tuple[float, float, float]]:
    piece_positions: list[tuple[float, float, float]] = []
    for piece in pieces:
        piece_positions.extend(smoke_positions(piece_vertices.get(piece, [])))
    if len(piece_positions) > 1:
        return merge_close_positions(piece_positions)

    vertices: list[tuple[float, float, float]] = []
    for piece in pieces:
        vertices.extend(piece_vertices.get(piece, []))
    return smoke_positions(vertices)


def vertices_from_pieces(
    piece_vertices: dict[int, list[tuple[float, float, float]]],
    pieces: list[int],
    locator_offset: LocatorOffset = (0.0, 0.0, 0.0),
) -> list[tuple[float, float, float]]:
    vertices: list[tuple[float, float, float]] = []
    for piece in pieces:
        for vertex in piece_vertices.get(piece, []):
            vertices.append(apply_offset(vertex, locator_offset))
    return vertices


def sampled_vertices(
    vertices: list[tuple[float, float, float]], limit: int = 4200
) -> tuple[tuple[float, float, float], ...]:
    if len(vertices) <= limit:
        return tuple(vertices)
    step = max(1, len(vertices) // limit)
    return tuple(vertices[::step][:limit])


def locator_bounds_from_pieces(
    piece_vertices: dict[int, list[tuple[float, float, float]]], pieces: list[int], locator_offset: LocatorOffset
) -> tuple[float, float, float, float, float, float] | None:
    vertices = vertices_from_pieces(piece_vertices, pieces, locator_offset)
    if not vertices:
        return None
    xs = [vertex[0] for vertex in vertices]
    ys = [vertex[1] for vertex in vertices]
    zs = [vertex[2] for vertex in vertices]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def outlet_from_position_and_bounds(
    position: tuple[float, float, float], bounds: tuple[float, float, float, float, float, float]
) -> tuple[float, float, float]:
    min_x, _min_y, min_z, max_x, max_y, max_z = bounds
    x_value, y_value, z_value = position
    y_outlet = max(y_value, max_y) + 0.06
    distances = {
        "x_min": abs(x_value - min_x),
        "x_max": abs(max_x - x_value),
        "z_min": abs(z_value - min_z),
        "z_max": abs(max_z - z_value),
    }
    nearest = min(distances, key=distances.get)
    if nearest == "x_min":
        return (min_x, y_outlet, z_value)
    if nearest == "x_max":
        return (max_x, y_outlet, z_value)
    if nearest == "z_min":
        return (x_value, y_outlet, min_z)
    return (x_value, y_outlet, max_z)


def smart_outlet_from_vertices(
    position: tuple[float, float, float],
    bounds: tuple[float, float, float, float, float, float],
    vertices: list[tuple[float, float, float]],
) -> tuple[float, float, float]:
    if not vertices:
        return outlet_from_position_and_bounds(position, bounds)

    min_x, min_y, min_z, max_x, max_y, max_z = bounds
    x_span = max(max_x - min_x, 0.01)
    y_span = max(max_y - min_y, 0.01)
    z_span = max(max_z - min_z, 0.01)

    top_cut = max(quantile([vertex[1] for vertex in vertices], 0.965), max_y - max(0.16, y_span * 0.12))
    top_vertices = [vertex for vertex in vertices if vertex[1] >= top_cut] or vertices
    horizontal_span = max(x_span, z_span)
    radius = max(0.18, horizontal_span * 0.16)
    local = [
        vertex
        for vertex in top_vertices
        if horizontal_distance((vertex[0], 0.0, vertex[2]), (position[0], 0.0, position[2])) <= radius
    ]
    if len(local) < 8:
        closest = sorted(
            top_vertices,
            key=lambda vertex: horizontal_distance((vertex[0], 0.0, vertex[2]), (position[0], 0.0, position[2])),
        )
        local = closest[: min(max(12, len(closest) // 12), 90)] or closest

    mouth = average(local)
    return (mouth[0], max(mouth[1], max_y) + 0.06, mouth[2])


def outlet_kind_from_vertices(
    position: tuple[float, float, float],
    outlet: tuple[float, float, float],
    bounds: tuple[float, float, float, float, float, float],
) -> str:
    min_x, min_y, min_z, max_x, max_y, max_z = bounds
    x_span = max_x - min_x
    y_span = max_y - min_y
    z_span = max_z - min_z
    horizontal_span = max(x_span, z_span, 0.01)
    shift = horizontal_distance((position[0], 0.0, position[2]), (outlet[0], 0.0, outlet[2]))
    if y_span < horizontal_span * 0.9:
        return "lateral/bajo"
    if shift > max(0.18, horizontal_span * 0.12):
        return "curva/45"
    return "recto"


def suggested_direction_from_bounds(
    position: tuple[float, float, float], bounds: tuple[float, float, float, float, float, float]
) -> str:
    min_x, min_y, min_z, max_x, max_y, max_z = bounds
    x_span = max_x - min_x
    y_span = max_y - min_y
    z_span = max_z - min_z
    if y_span >= max(x_span, z_span, 0.1) * 1.15:
        return "Arriba"

    x_value, _y_value, z_value = position
    distances = {
        "Izquierda": abs(x_value - min_x),
        "Derecha": abs(max_x - x_value),
        "Atras": abs(z_value - min_z),
        "Adelante": abs(max_z - z_value),
    }
    return min(distances, key=distances.get)


def smoke_rotation_for_direction(
    direction: str, position: tuple[float, float, float], bounds: tuple[float, float, float, float, float, float]
) -> tuple[float, float, float, float]:
    selected = suggested_direction_from_bounds(position, bounds) if direction == "Automatico" else direction
    return SMOKE_DIRECTION_ROTATIONS.get(selected, SMOKE_DIRECTION_ROTATIONS["Original PM"])


def direction_for_rotation(rotation: tuple[float, float, float, float] | None, fallback: str) -> str:
    if rotation is None:
        return fallback
    for name, candidate in SMOKE_DIRECTION_ROTATIONS.items():
        if all(abs(rotation[index] - candidate[index]) < 0.0001 for index in range(4)):
            return name
    return fallback


def inspect_pim_locator_candidates(
    pim_path: Path,
    pim_rel: str,
    model_no_ext: str,
    skip_part_names: set[str] | None = None,
    locator_offset: LocatorOffset = (0.0, 0.0, 0.0),
) -> list[LocatorCandidate]:
    text = pim_path.read_text(encoding="utf-8", errors="ignore")
    piece_vertices = parse_piece_vertices(pim_path)
    skip_part_names = skip_part_names or set()
    candidates: list[LocatorCandidate] = []
    part_counts: dict[str, int] = {}

    for part_match in re.finditer(r"Part \{\n.*?\n\}", text, flags=re.S):
        block = part_match.group(0)
        name_match = re.search(r'Name:\s*"([^"]+)"', block)
        part_name = name_match.group(1) if name_match else "part"
        part_counts[part_name] = part_counts.get(part_name, 0) + 1
        part_identity = f"{part_name}#{part_counts[part_name]}"
        if part_name in skip_part_names:
            continue
        pieces_match = re.search(r"Pieces:\s*([0-9 ]*)", block)
        pieces = [int(value) for value in pieces_match.group(1).split()] if pieces_match else []
        if not pieces:
            continue
        part_bounds = locator_bounds_from_pieces(piece_vertices, pieces, locator_offset)
        part_vertices = vertices_from_pieces(piece_vertices, pieces, locator_offset)
        preview_vertices = sampled_vertices(part_vertices)
        positions = locator_positions_from_pieces(piece_vertices, pieces)
        for ordinal, position in enumerate(positions, 1):
            detected_position = apply_offset(position, locator_offset)
            candidate_bounds = part_bounds or (
                detected_position[0],
                detected_position[1],
                detected_position[2],
                detected_position[0],
                detected_position[1],
                detected_position[2],
            )
            final_position = smart_outlet_from_vertices(detected_position, candidate_bounds, part_vertices)
            candidates.append(
                LocatorCandidate(
                    key=locator_key(pim_rel, part_identity, ordinal),
                    model_no_ext=model_no_ext,
                    pim_rel=pim_rel,
                    part_name=part_name,
                    ordinal=ordinal,
                    position=final_position,
                    bounds=candidate_bounds,
                    outlet_position=final_position,
                    suggested_direction=suggested_direction_from_bounds(final_position, candidate_bounds),
                    outlet_kind=outlet_kind_from_vertices(detected_position, final_position, candidate_bounds),
                    preview_vertices=preview_vertices,
                )
            )
    return candidates


def patch_pim_with_smoke(
    pim_path: Path,
    pim_rel: str = "",
    skip_part_names: set[str] | None = None,
    locator_offset: LocatorOffset = (0.0, 0.0, 0.0),
    smoke_scale: float = 1.0,
    smoke_direction: str = "Original PM",
    locator_edits: dict[str, LocatorEdit] | None = None,
) -> tuple[int, int, int, list[str]]:
    text = pim_path.read_text(encoding="utf-8", errors="ignore")
    piece_vertices = parse_piece_vertices(pim_path)
    locator_blocks, locators_by_index = parse_locator_blocks(text)
    warnings: list[str] = []
    skip_part_names = skip_part_names or set()
    skipped_parts: set[str] = set()

    old_to_new: dict[int, int] = {}
    preserved_blocks: list[str] = []
    removed_smoke = 0
    for old_index in sorted(locators_by_index):
        block = locators_by_index[old_index]
        if is_smoke_locator(block):
            removed_smoke += 1
            continue
        new_index = len(preserved_blocks)
        old_to_new[old_index] = new_index
        preserved_blocks.append(rewrite_locator_index(block, new_index))

    text = re.sub(r"\nLocator \{\n.*?\n\}", "", text, flags=re.S)
    next_locator = len(preserved_blocks)
    new_blocks = preserved_blocks[:]
    added = 0
    part_counts: dict[str, int] = {}

    def patch_part(match: re.Match[str]) -> str:
        nonlocal next_locator, added
        block = match.group(0)
        name_match = re.search(r'Name:\s*"([^"]+)"', block)
        part_name = name_match.group(1) if name_match else ""
        part_counts[part_name] = part_counts.get(part_name, 0) + 1
        part_identity = f"{part_name}#{part_counts[part_name]}"
        pieces_match = re.search(r"Pieces:\s*([0-9 ]*)", block)
        locators_match = re.search(r"Locators:\s*([0-9 ]*)", block)

        kept_locator_indices: list[int] = []
        if locators_match:
            old_values = [int(value) for value in locators_match.group(1).split()]
            kept_locator_indices = [old_to_new[value] for value in old_values if value in old_to_new]

        pieces = [int(value) for value in pieces_match.group(1).split()] if pieces_match else []
        if pieces and part_name in skip_part_names:
            skipped_parts.add(part_name)
        elif pieces:
            part_bounds = locator_bounds_from_pieces(piece_vertices, pieces, locator_offset)
            part_vertices = vertices_from_pieces(piece_vertices, pieces, locator_offset)
            positions = locator_positions_from_pieces(piece_vertices, pieces)
            for ordinal, position in enumerate(positions, 1):
                edit = (locator_edits or {}).get(locator_key(pim_rel, part_identity, ordinal))
                if edit and not edit.enabled:
                    continue
                detected_position = apply_offset(position, locator_offset)
                candidate_bounds = part_bounds or (
                    detected_position[0],
                    detected_position[1],
                    detected_position[2],
                    detected_position[0],
                    detected_position[1],
                    detected_position[2],
                )
                position = edit.position if edit else smart_outlet_from_vertices(
                    detected_position, candidate_bounds, part_vertices
                )
                rotation = edit.rotation if edit and edit.rotation else smoke_rotation_for_direction(
                    smoke_direction, position, candidate_bounds
                )
                index = next_locator
                next_locator += 1
                added += 1
                kept_locator_indices.append(index)
                new_blocks.append(
                    "\n".join(
                        [
                            "Locator {",
                            f'     Name: "smoke_{index + 1:03d}"',
                            '     Hookup: "model.particle.smoke_new"',
                            f"     Index: {index}",
                            "     Position: ( " + "  ".join(write_float_token(value) for value in position) + " )",
                            "     Rotation: ( " + "  ".join(write_float_token(value) for value in rotation) + " )",
                            "     Scale: ( " + "  ".join(write_float_token(smoke_scale) for _ in range(3)) + " )",
                            "}",
                        ]
                    )
                )

        if not pieces and removed_smoke:
            if name_match and kept_locator_indices:
                warnings.append(f"Part {name_match.group(1)} kept only non-smoke locators")

        block = re.sub(r"LocatorCount:\s+\d+", f"LocatorCount: {len(kept_locator_indices)}", block, count=1)
        block = re.sub(
            r"Locators:\s*[0-9 ]*",
            "Locators: " + " ".join(str(i) for i in kept_locator_indices) + (" " if kept_locator_indices else ""),
            block,
            count=1,
        )
        return block

    text = re.sub(r"Part \{\n.*?\n\}", patch_part, text, flags=re.S)
    text = re.sub(r"LocatorCount:\s+\d+", f"LocatorCount: {next_locator}", text, count=1)
    pim_path.write_text(text.rstrip() + "\n" + "\n".join(new_blocks) + "\n", encoding="utf-8")
    if skipped_parts:
        warnings.append("Partes base omitidas por PIT: " + ", ".join(sorted(skipped_parts)))
    return added, removed_smoke, next_locator, warnings


def zip_dir(src: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(p for p in src.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(src).as_posix())


def same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve().samefile(right.resolve())
    except FileNotFoundError:
        return left.resolve() == right.resolve()


def copy_with_retries(src: Path, dest: Path, log: LogFn, attempts: int = 5) -> None:
    if same_path(src, dest):
        log(f"Ya esta instalado: {dest}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error: OSError | None = None
    for attempt in range(1, attempts + 1):
        try:
            shutil.copy2(src, dest)
            return
        except OSError as exc:
            last_error = exc
            if getattr(exc, "winerror", None) != 32 or attempt == attempts:
                break
            log(f"Archivo ocupado, reintentando copia ({attempt}/{attempts})...")
            time.sleep(1.0)
    raise ToolError(
        "Windows tiene bloqueado el archivo de salida. "
        "Cierra ATS, Mod Downloader, Explorer preview o cualquier programa que lo este usando y prueba de nuevo."
    ) from last_error


def remove_tree_safe(path: Path, root: Path) -> int:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    if path_resolved == root_resolved or root_resolved not in path_resolved.parents:
        raise ToolError(f"Ruta temporal insegura: {path_resolved}")

    size = sum(file.stat().st_size for file in path_resolved.rglob("*") if file.is_file())
    shutil.rmtree(path_resolved, ignore_errors=True)
    return size


def cleanup_studio_work(log: LogFn = print) -> tuple[int, int]:
    WORK.mkdir(parents=True, exist_ok=True)
    prefixes = ("studio_extract_", "studio_mid_", "studio_convert_", "studio_stage_")
    removed = 0
    freed = 0
    for path in sorted(WORK.iterdir()):
        if not path.is_dir() or not path.name.startswith(prefixes):
            continue
        try:
            freed += remove_tree_safe(path, WORK)
            removed += 1
        except Exception as exc:
            log(f"No pude borrar {path.name}: {exc}")
    log(f"Temporales borrados: {removed} carpeta(s), {freed / 1024 / 1024 / 1024:.2f} GB liberados")
    return removed, freed


def cleanup_paths(paths: list[Path], mode: str, success: bool, log: LogFn = print) -> None:
    if mode == "never" or (mode == "success" and not success):
        return
    freed = 0
    for path in paths:
        if path.exists():
            try:
                freed += remove_tree_safe(path, WORK)
            except Exception as exc:
                log(f"No pude borrar temporal {path.name}: {exc}")
    if freed:
        log(f"Temporales del trabajo liberados: {freed / 1024 / 1024 / 1024:.2f} GB")


def disk_usage_for(path: Path) -> tuple[int, int, int]:
    probe = path if path.exists() else Path.home()
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return usage.total, usage.used, usage.free


def format_gb(value: int) -> str:
    return f"{value / 1024 / 1024 / 1024:.1f} GB"


def write_diagnostic_report(
    report_path: Path,
    mod_path: Path,
    error: Exception,
    models: list[ExhaustModel],
    temp_dirs: list[Path],
) -> Path:
    lines = [
        "PM Smoke Locator Studio - Diagnostico",
        f"Fecha: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Version: {APP_VERSION}",
        f"Mod origen: {mod_path}",
        f"Error: {error}",
        f"Modelos detectados antes del error: {len(models)}",
        "",
        "Temporales:",
    ]
    lines.extend(f"- {path}" for path in temp_dirs)
    if models:
        lines.append("")
        lines.append("Modelos:")
        lines.extend(f"- {model.model_no_ext} | variant={model.variant} | def={model.source_def}" for model in models)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return cleaned or "truck_mod"


def score_exhaust_candidate(sii: Path, truck_def: Path, text: str, model: str) -> int:
    model_lower = model.replace("\\", "/").lower()
    rel_parts = [part.lower() for part in sii.relative_to(truck_def).parts]
    rel_text = "/".join(rel_parts)
    text_lower = text.lower()
    model_stem = Path(model_lower).stem
    score = 0

    if any(hint in model_lower for hint in MODEL_EXCLUDE_HINTS):
        score -= 10
    if Path(model_lower).stem == "empty":
        score -= 100

    if "accessory" in rel_parts:
        score += 1
    if any(part in EXHAUST_ACCESSORY_DIRS for part in rel_parts):
        score += 8
    if "/upgrade/exhaust/" in model_lower or "/accessory/exhaust/" in model_lower:
        score += 12
    if "/exhaust/" in model_lower:
        score += 8

    if any(hint in model_stem for hint in EXHAUST_HINTS):
        score += 6
    if any(hint in rel_text for hint in EXHAUST_HINTS):
        score += 5

    unit_match = re.search(r"accessory_addon_data\s*:\s*([^\s{]+)", text_lower)
    if unit_match and any(f".{hint}" in unit_match.group(1) for hint in EXHAUST_HINTS):
        score += 5

    name_match = re.search(r'name:\s*"([^"]+)"', text_lower)
    if name_match and any(hint in name_match.group(1) for hint in EXHAUST_HINTS):
        score += 4

    icon_match = re.search(r'icon:\s*"([^"]+)"', text_lower)
    if icon_match and any(hint in icon_match.group(1) for hint in EXHAUST_HINTS):
        score += 3

    if re.search(r"overrides\[\]:\s*\"[^\"]*/accessory/(exh|exhrear|exhaust|cab_exhaust)/", text_lower):
        score += 4

    return score


def model_path_score(path_text: str) -> int:
    model_lower = path_text.replace("\\", "/").lower()
    model_stem = Path(model_lower).stem
    score = 0

    if any(hint in model_lower for hint in MODEL_EXCLUDE_HINTS):
        score -= 10
    if model_stem == "empty":
        score -= 100

    if "/upgrade/exhaust/" in model_lower or "/accessory/exhaust/" in model_lower:
        score += 12
    if "/exhaust/" in model_lower:
        score += 8
    if any(hint in model_stem for hint in EXHAUST_HINTS):
        score += 6
    if any(f"/{hint}" in model_lower or f"_{hint}" in model_lower for hint in EXHAUST_HINTS):
        score += 4
    return score


def iter_model_refs(text: str) -> list[str]:
    refs: list[str] = []
    patterns = [
        r'\b(?:exterior_model|model|model_path|model_desc):\s*"([^"]+\.pmd)"',
        r'"([^"]+\.pmd)"',
    ]
    for pattern in patterns:
        for model in re.findall(pattern, text, flags=re.I):
            normalized = model.replace("\\", "/")
            if normalized not in refs:
                refs.append(normalized)
    return refs


def extract_mod(mod_path: Path, dest: Path, log: LogFn) -> None:
    log(f"Extrayendo mod: {mod_path}")
    dest.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(mod_path):
        with zipfile.ZipFile(mod_path) as zf:
            zf.extractall(dest)
        return

    if EXTRACTOR.exists():
        run_command([EXTRACTOR, mod_path, "--dest", dest, "--quiet"], log=log)
        return

    if SCS_EXTRACTOR.exists():
        run_command([SCS_EXTRACTOR, mod_path, dest], log=log)
        return

    raise ToolError("No extractor was found for non-zip SCS files.")


def find_exhaust_models(extracted: Path) -> list[ExhaustModel]:
    variant_re = re.compile(r"\bvariant:\s*([^\s]+)", re.I)
    look_re = re.compile(r"\blook:\s*([^\s]+)", re.I)
    found: dict[str, ExhaustModel] = {}

    truck_def = extracted / "def" / "vehicle" / "truck"
    scan_root = truck_def if truck_def.exists() else extracted / "def"
    if not scan_root.exists():
        scan_root = extracted

    for sii in scan_root.rglob("*.sii"):
        text = sii.read_text(encoding="utf-8", errors="ignore")
        for model in iter_model_refs(text):
            if Path(model).stem.lower() == "empty":
                continue
            candidate_score = score_exhaust_candidate(sii, scan_root, text, model) + model_path_score(model)
            if candidate_score < 7:
                continue
            model_no_ext = model[:-4]
            pmd = extracted / model.lstrip("/").replace("/", os.sep)
            pmg = pmd.with_suffix(".pmg")
            if not pmd.exists() or not pmg.exists():
                continue
            variant = (variant_re.search(text).group(1) if variant_re.search(text) else "default")
            look = (look_re.search(text).group(1) if look_re.search(text) else "default")
            found.setdefault(model_no_ext, ExhaustModel(model_no_ext, sii, variant, look))

    if not found:
        for pmd in extracted.rglob("*.pmd"):
            rel = "/" + pmd.relative_to(extracted).as_posix()
            if model_path_score(rel) < 8:
                continue
            pmg = pmd.with_suffix(".pmg")
            if not pmg.exists():
                continue
            found.setdefault(rel[:-4], ExhaustModel(rel[:-4], pmd, "auto", "auto"))

    return [found[key] for key in sorted(found)]


def write_manifest(stage: Path, display_name: str, description: str, icon_source: Path | None = None) -> None:
    write_mod_icon(stage, icon_source)
    (stage / "manifest.sii").write_text(
        "\n".join(
            [
                "SiiNunit",
                "{",
                "mod_package : .package_name {",
                f'    display_name: "{display_name}"',
                '    author: "Chevez / PM Smoke Locator Studio"',
                '    category[]: "truck"',
                '    icon: "mod_icon.jpg"',
                "}",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (stage / "mod_description.txt").write_text(description.rstrip() + "\n", encoding="utf-8")


def convert_mod_icon(source: Path, dest: Path) -> None:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise ToolError("Falta Pillow para convertir fotos. Ejecuta: python -m pip install pillow") from exc

    if not source.exists():
        raise ToolError(f"No existe la foto del mod: {source}")

    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image = ImageOps.fit(image, MOD_ICON_SIZE, method=resample, centering=(0.5, 0.5))
        image.save(dest, "JPEG", quality=92, optimize=True)


def write_mod_icon(stage: Path, icon_source: Path | None = None) -> None:
    icon = stage / "mod_icon.jpg"
    if icon.exists():
        return
    if icon_source:
        convert_mod_icon(icon_source, icon)
        return
    if not DEFAULT_ICON.exists():
        raise ToolError(f"No encontre el icono por defecto: {DEFAULT_ICON}")
    shutil.copy2(DEFAULT_ICON, icon)


def make_report(
    report_path: Path,
    mod_path: Path,
    models: list[ExhaustModel],
    locator_count: int,
    removed_smoke_locators: int,
    warnings: list[str],
    output_zip: Path | None = None,
) -> None:
    lines = [
        "PM Smoke Locator Studio - Reporte",
        f"Fecha: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Mod origen: {mod_path}",
        f"Modelos de escape encontrados: {len(models)}",
        f"Locators smoke_new agregados: {locator_count}",
        f"Locators viejos de humo removidos: {removed_smoke_locators}",
    ]
    if output_zip:
        lines.append(f"Salida: {output_zip}")
    lines.append("")
    lines.append("Modelos:")
    for model in models:
        lines.append(f"- {model.model_no_ext} | variant={model.variant} | def={model.source_def}")
    if warnings:
        lines.append("")
        lines.append("Avisos:")
        for warning in warnings:
            lines.append(f"- {warning}")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze_mod(mod_path: Path, log: LogFn = print) -> tuple[Path, list[ExhaustModel], Path]:
    if not mod_path.exists():
        raise ToolError(f"No existe el mod: {mod_path}")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    extract_dir = WORK / f"studio_extract_{safe_name(mod_path.stem)}_{stamp}"
    extract_mod(mod_path, extract_dir, log)
    models = find_exhaust_models(extract_dir)
    report = WORK / f"studio_report_{safe_name(mod_path.stem)}_{stamp}.txt"
    make_report(report, mod_path, models, 0, 0, [], None)
    log(f"Modelos de escape encontrados: {len(models)}")
    for model in models:
        log(f"  {model.model_no_ext} ({model.variant})")
    log(f"Reporte: {report}")
    return extract_dir, models, report


def preview_mod(mod_path: Path, cleanup_mode: str, log: LogFn = print) -> tuple[int, Path]:
    if not mod_path.exists():
        raise ToolError(f"No existe el mod: {mod_path}")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    extract_dir = WORK / f"studio_extract_{safe_name(mod_path.stem)}_{stamp}"
    try:
        extract_mod(mod_path, extract_dir, log)
        models = find_exhaust_models(extract_dir)
        report = WORK / f"studio_preview_{safe_name(mod_path.stem)}_{stamp}.txt"
        make_report(report, mod_path, models, 0, 0, [], None)
        return len(models), report
    finally:
        cleanup_paths([extract_dir], cleanup_mode, True, log)


def inspect_mod_locator_candidates(
    mod_path: Path,
    cleanup_mode: str,
    locator_offset: LocatorOffset = (0.0, 0.0, 0.0),
    log: LogFn = print,
) -> list[LocatorCandidate]:
    if not CONVERTER_PIX.exists():
        raise ToolError(f"Missing converter: {CONVERTER_PIX}")
    if not mod_path.exists():
        raise ToolError(f"No existe el mod: {mod_path}")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    extract_dir = WORK / f"studio_extract_{safe_name(mod_path.stem)}_{stamp}"
    mid_dir = WORK / f"studio_mid_{safe_name(mod_path.stem)}_{stamp}"
    temp_dirs = [extract_dir, mid_dir]

    try:
        extract_mod(mod_path, extract_dir, log)
        models = find_exhaust_models(extract_dir)
        if not models:
            raise ToolError("No encontre modelos de escape en ese mod.")

        log(f"Preparando editor visual con {len(models)} modelo(s)...")
        for index, model in enumerate(models, 1):
            log(f"[{index}/{len(models)}] {model.model_no_ext}")
            run_command([CONVERTER_PIX, "-b", extract_dir, "-e", mid_dir, "-m", model.model_no_ext], log=log)

        candidates: list[LocatorCandidate] = []
        for pim in sorted(mid_dir.rglob("*.pim")):
            pit = pim.with_suffix(".pit")
            skip_parts = common_visible_parts_from_pit(pit) if pit.exists() else set()
            pim_rel = pim.relative_to(mid_dir).as_posix()
            model_no_ext = "/" + Path(pim_rel).with_suffix("").as_posix()
            candidates.extend(
                inspect_pim_locator_candidates(pim, pim_rel, model_no_ext, skip_parts, locator_offset)
            )
        log(f"Locators detectados para editar: {len(candidates)}")
        return candidates
    finally:
        cleanup_paths(temp_dirs, cleanup_mode, True, log)


def build_smoke_patch(
    mod_path: Path,
    output_dir: Path,
    mode: str = "patch",
    install: bool = False,
    smoke_mod: Path = DEFAULT_SMOKE_MOD,
    icon_path: Path | None = None,
    locator_offset: LocatorOffset = (0.0, 0.0, 0.0),
    smoke_scale: float = 1.0,
    smoke_direction: str = "Original PM",
    locator_edits: dict[str, LocatorEdit] | None = None,
    cleanup_mode: str = "success",
    diagnostic: bool = False,
    log: LogFn = print,
) -> BuildResult:
    if not CONVERTER_PIX.exists():
        raise ToolError(f"Missing converter: {CONVERTER_PIX}")
    if not CONVERSION_TOOLS_ZIP.exists():
        raise ToolError(f"Missing conversion tools: {CONVERSION_TOOLS_ZIP}")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    extract_dir = WORK / f"studio_extract_{safe_name(mod_path.stem)}_{stamp}"
    mid_dir = WORK / f"studio_mid_{safe_name(mod_path.stem)}_{stamp}"
    convert_run = WORK / f"studio_convert_{safe_name(mod_path.stem)}_{stamp}"
    stage_dir = WORK / f"studio_stage_{safe_name(mod_path.stem)}_{stamp}"
    temp_dirs = [extract_dir, mid_dir, convert_run, stage_dir]
    models: list[ExhaustModel] = []
    success = False

    try:
        extract_mod(mod_path, extract_dir, log)
        models = find_exhaust_models(extract_dir)
        if not models:
            raise ToolError("No encontre modelos de escape en ese mod.")

        log(f"Convirtiendo {len(models)} modelo(s) de escape...")
        for index, model in enumerate(models, 1):
            log(f"[{index}/{len(models)}] {model.model_no_ext}")
            run_command([CONVERTER_PIX, "-b", extract_dir, "-e", mid_dir, "-m", model.model_no_ext], log=log)

        locator_count = 0
        removed_smoke = 0
        warnings: list[str] = []
        pim_files = list(mid_dir.rglob("*.pim"))
        if not pim_files:
            raise ToolError("La conversion no produjo archivos PIM.")

        if locator_offset != (0.0, 0.0, 0.0):
            log(f"Ajuste manual locators: X={locator_offset[0]} Y={locator_offset[1]} Z={locator_offset[2]}")
        if smoke_scale != 1.0:
            log(f"Nivel de humo aplicado: escala {smoke_scale}")

        log("Agregando locators smoke_new...")
        for pim in pim_files:
            pit = pim.with_suffix(".pit")
            skip_parts = common_visible_parts_from_pit(pit) if pit.exists() else set()
            pim_rel = pim.relative_to(mid_dir).as_posix()
            added, removed, total, pim_warnings = patch_pim_with_smoke(
                pim,
                pim_rel=pim_rel,
                skip_part_names=skip_parts,
                locator_offset=locator_offset,
                smoke_scale=smoke_scale,
                smoke_direction=smoke_direction,
                locator_edits=locator_edits,
            )
            locator_count += added
            removed_smoke += removed
            warnings.extend(f"{pim.name}: {warning}" for warning in pim_warnings)
            skip_note = f", base omitidas {len(skip_parts)}" if skip_parts else ""
            log(f"  {pim.relative_to(mid_dir)}: +{added}, removidos {removed}, total {total}{skip_note}")

        shutil.unpack_archive(str(CONVERSION_TOOLS_ZIP), str(convert_run), "zip")
        shutil.copytree(mid_dir, convert_run / "base", dirs_exist_ok=True)
        log("Reconstruyendo PMD/PMG...")
        run_command([convert_run / "convert.cmd"], cwd=convert_run, log=log)

        cache = convert_run / "rsrc" / "base" / "@cache"
        if not cache.exists():
            raise ToolError("La conversion final no creo cache.")

        if mode == "integrate":
            if not smoke_mod.exists():
                raise ToolError(f"No encontre el mod PM Smoke principal: {smoke_mod}")
            log(f"Integrando dentro de: {smoke_mod}")
            with zipfile.ZipFile(smoke_mod) as zf:
                zf.extractall(stage_dir)
            backup = smoke_mod.with_suffix(smoke_mod.suffix + f".bak_{stamp}")
            shutil.copy2(smoke_mod, backup)
            shutil.copytree(cache, stage_dir, dirs_exist_ok=True)
            output_zip = output_dir / smoke_mod.name
            zip_dir(stage_dir, output_zip)
            if install:
                copy_with_retries(output_zip, smoke_mod, log)
                log(f"Backup creado: {backup}")
        elif mode == "standalone":
            if not smoke_mod.exists():
                raise ToolError(f"No encontre el mod PM Smoke principal: {smoke_mod}")
            log(f"Creando mod completo nuevo desde: {smoke_mod}")
            with zipfile.ZipFile(smoke_mod) as zf:
                zf.extractall(stage_dir)
            shutil.copytree(cache, stage_dir, dirs_exist_ok=True)
            display = f"PM Smoke Complete - {safe_name(mod_path.stem)}"
            write_manifest(
                stage_dir,
                display,
                "Standalone smoke mod generated by PM Smoke Locator Studio.\n"
                "Includes PM Smoke base files and generated truck smoke locators.",
                icon_source=icon_path,
            )
            output_zip = output_dir / f"PM_Smoke_{safe_name(mod_path.stem)}_Complete_{stamp}.zip"
            zip_dir(stage_dir, output_zip)
            if install:
                copy_with_retries(output_zip, output_dir / output_zip.name, log)
                log(f"Listo en carpeta de salida: {output_dir / output_zip.name}")
        else:
            shutil.copytree(cache, stage_dir, dirs_exist_ok=True)
            display = f"PM Smoke Patch - {safe_name(mod_path.stem)}"
            write_manifest(
                stage_dir,
                display,
                "Smoke locator patch generated by PM Smoke Locator Studio.\n"
                "Load above the truck mod and above PM Smoke base files.",
                icon_source=icon_path,
            )
            output_zip = output_dir / f"PM_Smoke_{safe_name(mod_path.stem)}_Patch_{stamp}.zip"
            zip_dir(stage_dir, output_zip)
            if install:
                copy_with_retries(output_zip, output_dir / output_zip.name, log)
                log(f"Listo en carpeta de salida: {output_dir / output_zip.name}")

        report = output_dir / f"{output_zip.stem}_REPORT.txt"
        make_report(report, mod_path, models, locator_count, removed_smoke, warnings, output_zip)
        log(f"Salida: {output_zip}")
        log(f"Reporte: {report}")
        success = True
        return BuildResult(output_zip, report, len(models), locator_count, removed_smoke, warnings)
    except Exception as exc:
        if diagnostic:
            diag = WORK / f"diagnostic_{safe_name(mod_path.stem)}_{stamp}.txt"
            write_diagnostic_report(diag, mod_path, exc, models, temp_dirs)
            log(f"Diagnostico guardado: {diag}")
        raise
    finally:
        cleanup_paths(temp_dirs, cleanup_mode, success, log)


class StudioApp:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.locator_edits: dict[str, LocatorEdit] = {}
        self.locator_editor_source = ""

        self.root = tk.Tk()
        self.root.title(f"{APP_TITLE} {APP_VERSION}")
        self.root.geometry("1080x760")
        self.root.minsize(940, 680)

        self.game = tk.StringVar(value="ats")
        self.mod_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(game_mod_dir("ats")))
        self.smoke_mod = tk.StringVar(value=str(DEFAULT_SMOKE_MOD))
        self.icon_path = tk.StringVar()
        self.smoke_profile = tk.StringVar(value="Actual")
        self.smoke_direction = tk.StringVar(value="Original PM")
        self.offset_x = tk.StringVar(value="0.00")
        self.offset_y = tk.StringVar(value="0.00")
        self.offset_z = tk.StringVar(value="0.00")
        self.mode = tk.StringVar(value="patch")
        self.install = tk.BooleanVar(value=True)
        self.diagnostic = tk.BooleanVar(value=True)
        self.cleanup_label = tk.StringVar(value="Al terminar bien")
        self.disk_text = tk.StringVar(value="Espacio libre: calculando...")

        self._style()
        self._build()
        self.root.after(100, self._pump_queue)

    def _style(self) -> None:
        style = self.ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background="#101418")
        style.configure("Panel.TFrame", background="#171d23")
        style.configure("TLabel", background="#101418", foreground="#edf2f7", font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background="#101418", foreground="#93a4b5", font=("Segoe UI", 9))
        style.configure("Title.TLabel", background="#101418", foreground="#ffffff", font=("Segoe UI Semibold", 20))
        style.configure("Card.TLabel", background="#171d23", foreground="#edf2f7")
        style.configure("Hint.TLabel", background="#171d23", foreground="#93a4b5", font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI Semibold", 10), padding=(12, 8))
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 11), padding=(14, 10))
        style.configure("TRadiobutton", background="#171d23", foreground="#edf2f7")
        style.configure("TCheckbutton", background="#171d23", foreground="#edf2f7")

    def _build(self) -> None:
        tk = self.tk
        ttk = self.ttk
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text=f"{APP_TITLE} {APP_VERSION}", style="Title.TLabel").pack(side="left", anchor="w")
        ttk.Button(header, text="Actualizar", command=self._check_updates).pack(side="right")
        ttk.Button(header, text="Manual", command=self._save_manual).pack(side="right", padx=(0, 10))
        ttk.Label(
            outer,
            text="Selecciona un mod de camion, analiza sus escapes y crea el humo con smoke_new.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 14))

        gamebar = ttk.Frame(outer, style="Panel.TFrame", padding=(16, 10))
        gamebar.pack(fill="x", pady=(0, 10))
        ttk.Label(gamebar, text="Juego", style="Card.TLabel").pack(side="left")
        ttk.Radiobutton(gamebar, text="ATS", value="ats", variable=self.game, command=self._game_changed).pack(
            side="left", padx=(16, 0)
        )
        ttk.Radiobutton(gamebar, text="ETS2", value="ets2", variable=self.game, command=self._game_changed).pack(
            side="left", padx=(16, 0)
        )

        panel = ttk.Frame(outer, style="Panel.TFrame", padding=16)
        panel.pack(fill="x")
        panel.columnconfigure(1, weight=1)

        ttk.Label(panel, text="Mod del camion", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(panel, textvariable=self.mod_path).grid(row=0, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(panel, text="Buscar", command=self._choose_mod).grid(row=0, column=2, pady=5)

        ttk.Label(panel, text="Salida", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(panel, textvariable=self.output_dir).grid(row=1, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(panel, text="Carpeta", command=self._choose_output).grid(row=1, column=2, pady=5)

        ttk.Label(panel, text="PM Smoke principal", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(panel, textvariable=self.smoke_mod).grid(row=2, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(panel, text="Buscar", command=self._choose_smoke_mod).grid(row=2, column=2, pady=5)

        ttk.Label(panel, text="Foto del mod", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(panel, textvariable=self.icon_path).grid(row=3, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(panel, text="Buscar", command=self._choose_icon).grid(row=3, column=2, pady=5)

        offset_panel = ttk.Frame(panel, style="Panel.TFrame")
        offset_panel.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        offset_controls = ttk.Frame(offset_panel, style="Panel.TFrame")
        offset_controls.pack(fill="x")
        ttk.Label(offset_controls, text="Nivel", style="Card.TLabel").pack(side="left")
        ttk.Combobox(
            offset_controls,
            textvariable=self.smoke_profile,
            values=list(SMOKE_PROFILE_SCALES),
            width=10,
            state="readonly",
        ).pack(side="left", padx=(8, 18))
        ttk.Label(offset_controls, text="Ajuste manual locators", style="Card.TLabel").pack(side="left")
        ttk.Label(offset_controls, text="X", style="Card.TLabel").pack(side="left", padx=(18, 4))
        ttk.Entry(offset_controls, textvariable=self.offset_x, width=8).pack(side="left")
        ttk.Label(offset_controls, text="Y", style="Card.TLabel").pack(side="left", padx=(12, 4))
        ttk.Entry(offset_controls, textvariable=self.offset_y, width=8).pack(side="left")
        ttk.Label(offset_controls, text="Z", style="Card.TLabel").pack(side="left", padx=(12, 4))
        ttk.Entry(offset_controls, textvariable=self.offset_z, width=8).pack(side="left")
        ttk.Label(
            offset_panel,
            text="Referencia: X - izquierda / X + derecha    Y - abajo / Y + arriba    Z - atras / Z + adelante",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(5, 0))

        options_panel = ttk.Frame(panel, style="Panel.TFrame")
        options_panel.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        ttk.Label(options_panel, text="Auto-limpieza", style="Card.TLabel").pack(side="left")
        ttk.Combobox(
            options_panel,
            textvariable=self.cleanup_label,
            values=list(CLEANUP_MODES),
            width=16,
            state="readonly",
        ).pack(side="left", padx=(8, 18))
        ttk.Checkbutton(options_panel, text="Modo diagnostico", variable=self.diagnostic).pack(side="left")
        ttk.Label(options_panel, text="Direccion humo", style="Card.TLabel").pack(side="left", padx=(18, 0))
        ttk.Combobox(
            options_panel,
            textvariable=self.smoke_direction,
            values=SMOKE_DIRECTION_CHOICES,
            width=14,
            state="readonly",
        ).pack(side="left", padx=(8, 0))

        modes = ttk.Frame(panel, style="Panel.TFrame")
        modes.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(12, 4))
        ttk.Radiobutton(modes, text="Crear parche seguro aparte", value="patch", variable=self.mode).pack(side="left")
        ttk.Radiobutton(modes, text="Crear mod completo nuevo", value="standalone", variable=self.mode).pack(
            side="left", padx=(18, 0)
        )
        ttk.Radiobutton(modes, text="Integrar dentro del PM Smoke principal", value="integrate", variable=self.mode).pack(
            side="left", padx=18
        )
        ttk.Checkbutton(modes, text="Copiar a carpeta de salida", variable=self.install).pack(side="left")

        actions = ttk.Frame(outer, padding=(0, 14, 0, 10))
        actions.pack(fill="x")
        ttk.Button(actions, text="Analizar", command=self._analyze).pack(side="left")
        ttk.Button(actions, text="Vista previa", command=self._preview).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Editor locators", command=self._open_locator_editor).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Crear humo", style="Accent.TButton", command=self._build_patch).pack(side="left", padx=10)
        ttk.Button(actions, text="Limpiar temporales", command=self._cleanup_work).pack(side="left", padx=10)
        ttk.Button(actions, text="Limpiar log", command=self._clear_log).pack(side="right")

        disk_panel = ttk.Frame(outer)
        disk_panel.pack(fill="x", pady=(0, 10))
        ttk.Label(disk_panel, textvariable=self.disk_text, style="Muted.TLabel").pack(side="left")
        self.disk_progress = ttk.Progressbar(disk_panel, mode="determinate", maximum=100)
        self.disk_progress.pack(side="left", fill="x", expand=True, padx=(12, 0))

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 10))

        self.log_text = tk.Text(
            outer,
            height=22,
            bg="#0b0f13",
            fg="#dbe7f3",
            insertbackground="#ffffff",
            relief="flat",
            font=("Consolas", 10),
            wrap="word",
        )
        self.log_text.pack(fill="both", expand=True)
        self._log("Listo. Escoge un mod .scs o .zip para empezar.")
        self._refresh_disk()

    def _selected_mod_dir(self) -> Path:
        return game_mod_dir(self.game.get())

    def _cleanup_mode(self) -> str:
        return CLEANUP_MODES.get(self.cleanup_label.get(), "success")

    def _selected_mods(self) -> list[Path] | None:
        raw = self.mod_path.get().strip()
        if not raw:
            self.messagebox.showerror(APP_TITLE, "Selecciona uno o varios mods validos.")
            return None
        mods = [Path(part.strip().strip('"')) for part in raw.split(";") if part.strip()]
        missing = [str(path) for path in mods if not path.exists()]
        if missing:
            self.messagebox.showerror(APP_TITLE, "No existe este mod:\n" + "\n".join(missing[:5]))
            return None
        return mods

    def _refresh_disk(self) -> None:
        try:
            total, used, free = disk_usage_for(Path(self.output_dir.get().strip('" ') or Path.home()))
            used_percent = int(used * 100 / total) if total else 0
            self.disk_text.set(f"Espacio libre: {format_gb(free)} | usado {used_percent}%")
            self.disk_progress["value"] = used_percent
        except Exception as exc:
            self.disk_text.set(f"Espacio libre: no disponible ({exc})")

    def _game_changed(self) -> None:
        selected_dir = self._selected_mod_dir()
        old_defaults = {game_mod_dir("ats"), game_mod_dir("ets2")}
        output_text = self.output_dir.get().strip('" ')
        current_output = Path(output_text) if output_text else None
        if current_output is None or current_output in old_defaults:
            self.output_dir.set(str(selected_dir))

        smoke_text = self.smoke_mod.get().strip('" ')
        current_smoke = Path(smoke_text) if smoke_text else None
        if current_smoke is None or current_smoke in {default_smoke_mod("ats"), default_smoke_mod("ets2")}:
            self.smoke_mod.set(str(default_smoke_mod(self.game.get())))
        self._log(f"Juego seleccionado: {self.game.get().upper()} | carpeta mod: {selected_dir}")
        self._refresh_disk()

    def _locator_offset(self) -> LocatorOffset | None:
        try:
            return (float(self.offset_x.get() or 0), float(self.offset_y.get() or 0), float(self.offset_z.get() or 0))
        except ValueError:
            self.messagebox.showerror(APP_TITLE, "Los ajustes X/Y/Z deben ser numeros. Ejemplo: 0.10 o -0.05")
            return None

    def _smoke_scale(self) -> float:
        return SMOKE_PROFILE_SCALES.get(self.smoke_profile.get(), 1.0)

    def _smoke_direction(self) -> str:
        return self.smoke_direction.get() if self.smoke_direction.get() in SMOKE_DIRECTION_CHOICES else "Original PM"

    def _choose_mod(self) -> None:
        paths = self.filedialog.askopenfilenames(
            title="Seleccionar mod(s) de camion",
            filetypes=[("Mods ATS/ETS2", "*.scs *.zip"), ("Todos", "*.*")],
            initialdir=str(self._selected_mod_dir() if self._selected_mod_dir().exists() else Path.home()),
        )
        if paths:
            self.mod_path.set(";".join(paths))

    def _choose_output(self) -> None:
        path = self.filedialog.askdirectory(title="Seleccionar carpeta de salida", initialdir=self.output_dir.get())
        if path:
            self.output_dir.set(path)
            self._refresh_disk()

    def _choose_smoke_mod(self) -> None:
        path = self.filedialog.askopenfilename(
            title="Seleccionar PM Smoke principal",
            filetypes=[("Zip/SCS", "*.zip *.scs"), ("Todos", "*.*")],
            initialdir=str(self._selected_mod_dir() if self._selected_mod_dir().exists() else Path.home()),
        )
        if path:
            self.smoke_mod.set(path)

    def _choose_icon(self) -> None:
        path = self.filedialog.askopenfilename(
            title="Seleccionar foto del mod",
            filetypes=[("Imagenes", "*.jpg *.jpeg *.png *.bmp *.webp"), ("Todos", "*.*")],
            initialdir=str(Path.home() / "Pictures"),
        )
        if path:
            self.icon_path.set(path)

    def _run_worker(self, target: Callable[[], None]) -> None:
        if self.worker and self.worker.is_alive():
            self.messagebox.showwarning(APP_TITLE, "Ya hay un trabajo corriendo.")
            return
        self.progress.start(10)
        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def _validate_mod(self) -> Path | None:
        mods = self._selected_mods()
        if not mods:
            return None
        mod = mods[0]
        if not mod.exists():
            self.messagebox.showerror(APP_TITLE, "Selecciona un mod valido.")
            return None
        return mod

    def _analyze(self) -> None:
        mods = self._selected_mods()
        if not mods:
            return

        def work() -> None:
            try:
                for index, mod in enumerate(mods, 1):
                    self._thread_log(f"Analisis [{index}/{len(mods)}]: {mod.name}")
                    extract_dir, _models, _report = analyze_mod(mod, self._thread_log)
                    if self._cleanup_mode() != "never":
                        cleanup_paths([extract_dir], self._cleanup_mode(), True, self._thread_log)
                self.queue.put(("done", f"Analisis terminado: {len(mods)} mod(s)."))
            except Exception as exc:
                self.queue.put(("error", str(exc)))

        self._run_worker(work)

    def _preview(self) -> None:
        mods = self._selected_mods()
        if not mods:
            return
        locator_offset = self._locator_offset()
        if locator_offset is None:
            return
        output = Path(self.output_dir.get().strip('" ') or self._selected_mod_dir())
        smoke = Path(self.smoke_mod.get().strip('" '))
        mode_label = self.mode.get()
        install_label = "si" if self.install.get() else "no"
        profile = self.smoke_profile.get()
        smoke_scale = self._smoke_scale()
        smoke_direction = self._smoke_direction()
        cleanup = self.cleanup_label.get()

        def work() -> None:
            try:
                total, used, free = disk_usage_for(output)
                self._thread_log("Vista previa")
                self._thread_log(f"  Juego: {self.game.get().upper()}")
                self._thread_log(f"  Mods seleccionados: {len(mods)}")
                self._thread_log(f"  Salida: {output}")
                self._thread_log(f"  PM Smoke principal: {smoke}")
                self._thread_log(f"  Modo: {mode_label} | Copiar: {install_label}")
                self._thread_log(f"  Nivel: {profile} | escala {smoke_scale}")
                self._thread_log(f"  Direccion humo: {smoke_direction}")
                self._thread_log(f"  Offset X/Y/Z: {locator_offset[0]} / {locator_offset[1]} / {locator_offset[2]}")
                self._thread_log(f"  Auto-limpieza: {cleanup}")
                self._thread_log(f"  Espacio libre: {format_gb(free)} de {format_gb(total)}")
                for index, mod in enumerate(mods, 1):
                    self._thread_log(f"Previsualizando [{index}/{len(mods)}]: {mod.name}")
                    count, report = preview_mod(mod, self._cleanup_mode(), self._thread_log)
                    self._thread_log(f"  Escapes detectados: {count}")
                    self._thread_log(f"  Reporte preview: {report}")
                self.queue.put(("done", "Vista previa terminada."))
            except Exception as exc:
                self.queue.put(("error", str(exc)))

        self._run_worker(work)

    def _open_locator_editor(self) -> None:
        mods = self._selected_mods()
        if not mods:
            return
        mod = mods[0]
        if len(mods) > 1:
            self.messagebox.showinfo(APP_TITLE, "El editor visual abre el primer mod seleccionado.")
        locator_offset = self._locator_offset()
        if locator_offset is None:
            return

        def work() -> None:
            try:
                candidates = inspect_mod_locator_candidates(
                    mod,
                    self._cleanup_mode(),
                    locator_offset,
                    self._thread_log,
                )
                self.queue.put(("locator_editor_ready", (str(mod.resolve()), candidates)))
            except Exception as exc:
                self.queue.put(("error", str(exc)))

        self._run_worker(work)

    def _show_locator_editor(self, mod_source: str, candidates: list[LocatorCandidate]) -> None:
        if not candidates:
            self.messagebox.showwarning(APP_TITLE, "No encontre locators para editar en ese mod.")
            return

        tk = self.tk
        ttk = self.ttk
        win = tk.Toplevel(self.root)
        win.title("Editor visual de locators")
        win.geometry("1220x760")
        win.minsize(1040, 660)
        win.configure(bg="#101418")

        state: dict[str, dict[str, object]] = {}
        for candidate in candidates:
            edit = self.locator_edits.get(candidate.key) if self.locator_editor_source == mod_source else None
            default_direction = candidate.suggested_direction if self._smoke_direction() == "Automatico" else self._smoke_direction()
            selected_direction = direction_for_rotation(edit.rotation if edit else None, default_direction)
            state[candidate.key] = {
                "candidate": candidate,
                "enabled": edit.enabled if edit else True,
                "position": list(edit.position if edit else candidate.position),
                "direction": selected_direction,
                "rotation": SMOKE_DIRECTION_ROTATIONS[selected_direction],
            }

        selected_key = tk.StringVar(value=candidates[0].key)
        model_options = ["Todos"] + sorted({candidate.model_no_ext for candidate in candidates})
        model_var = tk.StringVar(value="Todos")
        model_summary = tk.StringVar()
        enabled_var = tk.BooleanVar(value=True)
        x_var = tk.StringVar()
        y_var = tk.StringVar()
        z_var = tk.StringVar()
        step_var = tk.StringVar(value="0.02")
        direction_var = tk.StringVar()
        isolate_var = tk.BooleanVar(value=True)
        view_var = tk.StringVar(value="3D libre")
        zoom_var = tk.BooleanVar(value=False)

        outer = ttk.Frame(win, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Editor visual de locators", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Selecciona un punto, ajusta X/Y/Z o desactivalo. Estos cambios se usaran al crear humo para este mod.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 10))

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        table_frame = ttk.Frame(body)
        table_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        table_frame.rowconfigure(1, weight=1)
        table_frame.columnconfigure(0, weight=1)

        model_bar = ttk.Frame(table_frame)
        model_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        model_bar.columnconfigure(1, weight=1)
        ttk.Label(model_bar, text="Modelo de escape", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        model_combo = ttk.Combobox(model_bar, textvariable=model_var, values=model_options, state="readonly")
        model_combo.grid(row=0, column=1, sticky="ew", padx=(10, 10))
        ttk.Label(model_bar, textvariable=model_summary, style="Hint.TLabel").grid(row=0, column=2, sticky="e")

        columns = ("enabled", "locator", "x", "y", "z", "kind", "part", "model")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "enabled": "Usar",
            "locator": "#",
            "x": "X",
            "y": "Y",
            "z": "Z",
            "kind": "Tipo",
            "part": "Parte",
            "model": "Modelo",
        }
        widths = {"enabled": 58, "locator": 48, "x": 76, "y": 76, "z": 76, "kind": 92, "part": 140, "model": 230}
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="w", stretch=column in {"part", "model"})
        tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)

        right = ttk.Frame(body, style="Panel.TFrame", padding=12)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        canvas = tk.Canvas(right, height=380, bg="#0b0f13", highlightthickness=0)
        canvas.grid(row=0, column=0, columnspan=4, sticky="ew")
        view_controls = ttk.Frame(right, style="Panel.TFrame")
        view_controls.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 16))
        ttk.Label(
            view_controls,
            text="Gris = modelo real, amarillo = humo, verde = boca detectada",
            style="Hint.TLabel",
        ).pack(side="left")
        view_combo = ttk.Combobox(
            view_controls,
            textvariable=view_var,
            values=["3D libre", "X/Z arriba", "X/Y lado", "Z/Y frente"],
            width=12,
            state="readonly",
        )
        view_combo.pack(side="left", padx=(10, 0))
        ttk.Button(view_controls, text="Reset 3D", command=lambda: reset_3d()).pack(side="left", padx=(8, 0))
        ttk.Button(view_controls, text="Abrir Blender", command=lambda: open_selected_in_blender()).pack(
            side="left", padx=(8, 0)
        )
        ttk.Checkbutton(view_controls, text="Zoom boca", variable=zoom_var, command=lambda: draw()).pack(
            side="left", padx=(10, 0)
        )
        ttk.Checkbutton(view_controls, text="Solo seleccionado", variable=isolate_var, command=lambda: draw()).pack(
            side="right"
        )

        ttk.Checkbutton(right, text="Usar este locator", variable=enabled_var).grid(row=2, column=0, columnspan=4, sticky="w")
        ttk.Label(right, text="X", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=(12, 4))
        ttk.Entry(right, textvariable=x_var, width=10).grid(row=3, column=1, sticky="w", pady=(12, 4))
        ttk.Label(right, text="Y", style="Card.TLabel").grid(row=3, column=2, sticky="w", pady=(12, 4), padx=(12, 0))
        ttk.Entry(right, textvariable=y_var, width=10).grid(row=3, column=3, sticky="w", pady=(12, 4))
        ttk.Label(right, text="Z", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(right, textvariable=z_var, width=10).grid(row=4, column=1, sticky="w", pady=4)
        ttk.Label(right, text="Paso", style="Card.TLabel").grid(row=4, column=2, sticky="w", pady=4, padx=(12, 0))
        ttk.Entry(right, textvariable=step_var, width=10).grid(row=4, column=3, sticky="w", pady=4)
        ttk.Label(right, text="Direccion", style="Card.TLabel").grid(row=5, column=0, sticky="w", pady=4)
        direction_combo = ttk.Combobox(
            right,
            textvariable=direction_var,
            values=list(SMOKE_DIRECTION_ROTATIONS),
            width=12,
            state="readonly",
        )
        direction_combo.grid(row=5, column=1, columnspan=3, sticky="w", pady=4)

        def fmt(value: float) -> str:
            return f"{value:.3f}"

        def row_values(key: str) -> tuple[str, str, str, str, str, str, str, str]:
            item = state[key]
            candidate = item["candidate"]
            position = item["position"]
            assert isinstance(candidate, LocatorCandidate)
            assert isinstance(position, list)
            return (
                "si" if item["enabled"] else "no",
                str(candidate.ordinal),
                fmt(float(position[0])),
                fmt(float(position[1])),
                fmt(float(position[2])),
                candidate.outlet_kind,
                candidate.part_name,
                candidate.model_no_ext,
            )

        def visible_keys() -> list[str]:
            selected_model = model_var.get()
            keys: list[str] = []
            for candidate in candidates:
                if selected_model == "Todos" or candidate.model_no_ext == selected_model:
                    keys.append(candidate.key)
            return keys

        def refill_tree() -> None:
            current = selected_key.get()
            tree.delete(*tree.get_children())
            keys = visible_keys()
            for key in keys:
                tree.insert("", "end", iid=key, values=row_values(key))
            model_summary.set(f"{len(keys)} de {len(candidates)} locators")
            if current in keys:
                load_selected(current)
            elif keys:
                load_selected(keys[0])
            else:
                selected_key.set("")
                draw()

        camera = {
            "yaw": math.radians(-18.0),
            "pitch": math.radians(10.0),
            "scale": 1.08,
            "drag": None,
        }

        def reset_3d() -> None:
            camera["yaw"] = math.radians(-18.0)
            camera["pitch"] = math.radians(10.0)
            camera["scale"] = 1.08
            view_var.set("3D libre")
            draw()

        def rotate_3d(
            point: tuple[float, float, float], center: tuple[float, float, float]
        ) -> tuple[float, float, float]:
            x_value = point[0] - center[0]
            y_value = point[1] - center[1]
            z_value = point[2] - center[2]
            yaw = float(camera["yaw"])
            pitch = float(camera["pitch"])
            cos_yaw = math.cos(yaw)
            sin_yaw = math.sin(yaw)
            x_rot = x_value * cos_yaw + z_value * sin_yaw
            z_rot = -x_value * sin_yaw + z_value * cos_yaw
            cos_pitch = math.cos(pitch)
            sin_pitch = math.sin(pitch)
            y_rot = y_value * cos_pitch - z_rot * sin_pitch
            depth = y_value * sin_pitch + z_rot * cos_pitch
            return x_rot, y_rot, depth

        def draw_3d(width: int, height: int, keys_to_draw: list[str]) -> None:
            vertices: list[tuple[str, tuple[float, float, float]]] = []
            smoke_points: list[tuple[str, tuple[float, float, float], bool]] = []
            outlet_points: list[tuple[str, tuple[float, float, float]]] = []
            for key in keys_to_draw:
                item = state[key]
                candidate = item["candidate"]
                position = item["position"]
                assert isinstance(candidate, LocatorCandidate)
                assert isinstance(position, list)
                vertices.extend((key, vertex) for vertex in candidate.preview_vertices)
                smoke_points.append(
                    (
                        key,
                        (float(position[0]), float(position[1]), float(position[2])),
                        bool(item["enabled"]),
                    )
                )
                outlet_points.append((key, candidate.outlet_position))
            if not smoke_points:
                canvas.create_text(width / 2, height / 2, fill="#93a4b5", text="No hay locators en este modelo")
                return
            selected = selected_key.get()
            if zoom_var.get() and isolate_var.get() and selected in state:
                selected_item = state[selected]
                selected_candidate = selected_item["candidate"]
                selected_position = selected_item["position"]
                assert isinstance(selected_candidate, LocatorCandidate)
                assert isinstance(selected_position, list)
                center_point = (
                    (float(selected_position[0]) + selected_candidate.outlet_position[0]) / 2,
                    (float(selected_position[1]) + selected_candidate.outlet_position[1]) / 2,
                    (float(selected_position[2]) + selected_candidate.outlet_position[2]) / 2,
                )
                selected_vertices = [vertex for key, vertex in vertices if key == selected]
                if selected_vertices:
                    radius = 0.8
                    close_vertices = [
                        (key, vertex)
                        for key, vertex in vertices
                        if key == selected
                        and (
                            (vertex[0] - center_point[0]) ** 2
                            + (vertex[1] - center_point[1]) ** 2
                            + (vertex[2] - center_point[2]) ** 2
                        )
                        ** 0.5
                        <= radius
                    ]
                    if len(close_vertices) < 120:
                        close_vertices = [
                            (selected, vertex)
                            for vertex in sorted(
                                selected_vertices,
                                key=lambda vertex: (
                                    (vertex[0] - center_point[0]) ** 2
                                    + (vertex[1] - center_point[1]) ** 2
                                    + (vertex[2] - center_point[2]) ** 2
                                )
                                ** 0.5,
                            )[: min(900, len(selected_vertices))]
                        ]
                    vertices = close_vertices
            coords = [point for _key, point in vertices]
            coords.extend(point for _key, point, _enabled in smoke_points)
            coords.extend(point for _key, point in outlet_points)
            if not coords:
                canvas.create_text(width / 2, height / 2, fill="#93a4b5", text="No hay geometria para mostrar")
                return
            center = (
                sum(point[0] for point in coords) / len(coords),
                sum(point[1] for point in coords) / len(coords),
                sum(point[2] for point in coords) / len(coords),
            )
            span = max(
                max(point[0] for point in coords) - min(point[0] for point in coords),
                max(point[1] for point in coords) - min(point[1] for point in coords),
                max(point[2] for point in coords) - min(point[2] for point in coords),
                0.2,
            )
            render_width = max(width - 34, 280)
            render_height = max(height - 34, 220)
            scale = min(render_width, render_height) * 0.84 / span * float(camera["scale"])

            def project_3d(point: tuple[float, float, float]) -> tuple[float, float, float]:
                x_rot, y_rot, depth = rotate_3d(point, center)
                return width / 2 + x_rot * scale, height / 2 - y_rot * scale, depth

            def convex_hull(points_2d: list[tuple[float, float]]) -> list[tuple[float, float]]:
                unique = sorted(set((round(x_value, 1), round(y_value, 1)) for x_value, y_value in points_2d))
                if len(unique) <= 2:
                    return unique

                def cross(
                    origin: tuple[float, float], point_a: tuple[float, float], point_b: tuple[float, float]
                ) -> float:
                    return (point_a[0] - origin[0]) * (point_b[1] - origin[1]) - (
                        point_a[1] - origin[1]
                    ) * (point_b[0] - origin[0])

                lower: list[tuple[float, float]] = []
                for point in unique:
                    while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
                        lower.pop()
                    lower.append(point)
                upper: list[tuple[float, float]] = []
                for point in reversed(unique):
                    while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
                        upper.pop()
                    upper.append(point)
                return lower[:-1] + upper[:-1]

            def centerline(vertex_group: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
                if len(vertex_group) < 4:
                    return vertex_group
                spans = [
                    max(vertex[index] for vertex in vertex_group) - min(vertex[index] for vertex in vertex_group)
                    for index in range(3)
                ]
                axis = max(range(3), key=lambda index: spans[index])
                min_axis = min(vertex[axis] for vertex in vertex_group)
                max_axis = max(vertex[axis] for vertex in vertex_group)
                axis_span = max(max_axis - min_axis, 0.01)
                bucket_count = min(34, max(8, len(vertex_group) // 70))
                buckets: list[list[tuple[float, float, float]]] = [[] for _ in range(bucket_count)]
                for vertex in vertex_group:
                    bucket = int((vertex[axis] - min_axis) / axis_span * (bucket_count - 1))
                    buckets[max(0, min(bucket_count - 1, bucket))].append(vertex)
                centers: list[tuple[float, float, float]] = []
                for bucket in buckets:
                    if not bucket:
                        continue
                    centers.append(
                        (
                            sum(vertex[0] for vertex in bucket) / len(bucket),
                            sum(vertex[1] for vertex in bucket) / len(bucket),
                            sum(vertex[2] for vertex in bucket) / len(bucket),
                        )
                    )
                return centers

            canvas.create_text(
                12,
                12,
                anchor="nw",
                fill="#93a4b5",
                text="Vista 3D libre: arrastra para girar, rueda = zoom",
            )
            canvas.create_text(
                12,
                32,
                anchor="nw",
                fill="#93a4b5",
                text="Amarillo = humo, verde = boca, gris = escape real",
            )
            if isolate_var.get():
                note = "Zoom boca activo" if zoom_var.get() else "Viendo solo seleccionado"
                canvas.create_text(width - 12, 12, anchor="ne", fill="#93a4b5", text=note)

            model_draw = vertices
            if len(model_draw) > 12000:
                step = max(1, len(model_draw) // 12000)
                model_draw = model_draw[::step]
            projected_by_key: dict[str, list[tuple[float, float, float]]] = {}
            vertices_by_key: dict[str, list[tuple[float, float, float]]] = {}
            for key, vertex in model_draw:
                px, py, depth = project_3d(vertex)
                if px < -30 or py < -30 or px > width + 30 or py > height + 30:
                    continue
                projected_by_key.setdefault(key, []).append((px, py, depth))
                vertices_by_key.setdefault(key, []).append(vertex)
            for key, projected in sorted(
                projected_by_key.items(),
                key=lambda item: sum(point[2] for point in item[1]) / max(len(item[1]), 1),
            ):
                selected_model = key == selected
                hull = convex_hull([(px, py) for px, py, _depth in projected])
                if len(hull) >= 3:
                    polygon = [coord for point in hull for coord in point]
                    canvas.create_polygon(
                        polygon,
                        fill="#18212b" if selected_model else "#101820",
                        outline="#cbd5e1" if selected_model else "#475569",
                        width=2 if selected_model else 1,
                        smooth=True,
                    )
                draw_points = projected[:: max(1, len(projected) // 1800)]
                for px, py, _depth in draw_points:
                    color = "#d7dee8" if selected_model else "#64748b"
                    canvas.create_line(px, py, px + 1, py, fill=color)
                centers = centerline(vertices_by_key.get(key, []))
                if len(centers) >= 2:
                    line_points: list[float] = []
                    for center_vertex in centers:
                        px, py, _depth = project_3d(center_vertex)
                        line_points.extend([px, py])
                    canvas.create_line(line_points, fill="#334155", width=8, smooth=True)
                    canvas.create_line(line_points, fill="#e2e8f0" if selected_model else "#64748b", width=3, smooth=True)

            for key, point in outlet_points:
                px, py, _depth = project_3d(point)
                color = "#22c55e" if key == selected else "#166534"
                canvas.create_line(px - 11, py, px + 11, py, fill=color, width=2)
                canvas.create_line(px, py - 11, px, py + 11, fill=color, width=2)
                canvas.create_oval(px - 6, py - 6, px + 6, py + 6, outline=color, width=2)
                if key == selected:
                    canvas.create_text(px + 12, py - 12, anchor="sw", fill=color, text="boca")
            for key, point, enabled in smoke_points:
                px, py, _depth = project_3d(point)
                color = "#facc15" if key == selected else ("#38bdf8" if enabled else "#64748b")
                radius = 8 if key == selected else 5
                canvas.create_oval(px - radius, py - radius, px + radius, py + radius, fill=color, outline="")

            axis_origin = (44, height - 42)
            axis_length = 34
            axes = [
                ("X", (1.0, 0.0, 0.0), "#38bdf8"),
                ("Y", (0.0, 1.0, 0.0), "#22c55e"),
                ("Z", (0.0, 0.0, 1.0), "#f97316"),
            ]
            for label, vector, color in axes:
                x_rot, y_rot, _depth = rotate_3d(vector, (0.0, 0.0, 0.0))
                end_x = axis_origin[0] + x_rot * axis_length
                end_y = axis_origin[1] - y_rot * axis_length
                canvas.create_line(axis_origin[0], axis_origin[1], end_x, end_y, fill=color, width=2)
                canvas.create_text(end_x + 4, end_y, anchor="w", fill=color, text=label)

        def draw() -> None:
            canvas.delete("all")
            width = max(canvas.winfo_width(), 320)
            height = max(canvas.winfo_height(), 260)
            view = view_var.get()
            keys_to_draw = [selected_key.get()] if isolate_var.get() and selected_key.get() in state else visible_keys()
            if view == "3D libre":
                draw_3d(width, height, keys_to_draw)
                return
            if view == "X/Y lado":
                axis_text = ("X - izquierda   X + derecha", "Y - abajo       Y + arriba")
                project_index = (0, 1)
            elif view == "Z/Y frente":
                axis_text = ("Z - atras       Z + adelante", "Y - abajo       Y + arriba")
                project_index = (2, 1)
            else:
                axis_text = ("X - izquierda   X + derecha", "Z - atras       Z + adelante")
                project_index = (0, 2)
            canvas.create_text(12, 12, anchor="nw", fill="#93a4b5", text=axis_text[0])
            canvas.create_text(12, 32, anchor="nw", fill="#93a4b5", text=axis_text[1])
            points: list[tuple[str, float, float, bool]] = []
            outlets: list[tuple[str, float, float]] = []
            bounds_items: list[tuple[str, tuple[float, float, float, float, float, float]]] = []
            model_points: list[tuple[str, float, float]] = []

            def project_tuple(point: tuple[float, float, float]) -> tuple[float, float]:
                return point[project_index[0]], point[project_index[1]]

            def bounds_projection(
                bounds: tuple[float, float, float, float, float, float]
            ) -> tuple[float, float, float, float]:
                min_x, min_y, min_z, max_x, max_y, max_z = bounds
                corners = [
                    (min_x, min_y, min_z),
                    (min_x, min_y, max_z),
                    (min_x, max_y, min_z),
                    (min_x, max_y, max_z),
                    (max_x, min_y, min_z),
                    (max_x, min_y, max_z),
                    (max_x, max_y, min_z),
                    (max_x, max_y, max_z),
                ]
                projected = [project_tuple(corner) for corner in corners]
                values_a = [point[0] for point in projected]
                values_b = [point[1] for point in projected]
                return (min(values_a), min(values_b), max(values_a), max(values_b))

            for key in keys_to_draw:
                item = state[key]
                candidate = item["candidate"]
                position = item["position"]
                assert isinstance(candidate, LocatorCandidate)
                assert isinstance(position, list)
                point_a, point_b = project_tuple((float(position[0]), float(position[1]), float(position[2])))
                outlet_a, outlet_b = project_tuple(candidate.outlet_position)
                points.append((key, point_a, point_b, bool(item["enabled"])))
                outlets.append((key, outlet_a, outlet_b))
                bounds_items.append((key, candidate.bounds))
                for vertex in candidate.preview_vertices:
                    vertex_a, vertex_b = project_tuple(vertex)
                    model_points.append((key, vertex_a, vertex_b))
            if not points:
                canvas.create_text(width / 2, height / 2, fill="#93a4b5", text="No hay locators en este modelo")
                return
            zoom_mode = bool(zoom_var.get() and isolate_var.get() and selected_key.get() in state)
            if zoom_mode:
                selected = selected_key.get()
                selected_points = [point for point in points if point[0] == selected]
                selected_outlets = [outlet for outlet in outlets if outlet[0] == selected]
                selected_model_points = [point for point in model_points if point[0] == selected]
                if selected_model_points and selected_points and selected_outlets:
                    center_a = (selected_points[0][1] + selected_outlets[0][1]) / 2
                    center_b = (selected_points[0][2] + selected_outlets[0][2]) / 2
                    all_a = [point[1] for point in selected_model_points]
                    all_b = [point[2] for point in selected_model_points]
                    full_span = max(max(all_a) - min(all_a), max(all_b) - min(all_b), 0.1)
                    radius = max(0.22, min(full_span * 0.22, 0.75))
                    close_points = [
                        point
                        for point in selected_model_points
                        if ((point[1] - center_a) ** 2 + (point[2] - center_b) ** 2) ** 0.5 <= radius
                    ]
                    if len(close_points) < 80:
                        close_points = sorted(
                            selected_model_points,
                            key=lambda point: ((point[1] - center_a) ** 2 + (point[2] - center_b) ** 2) ** 0.5,
                        )[: min(520, len(selected_model_points))]
                    model_points = close_points
                    bounds_items = []
            xs = [point[1] for point in points]
            zs = [point[2] for point in points]
            xs.extend(outlet[1] for outlet in outlets)
            zs.extend(outlet[2] for outlet in outlets)
            xs.extend(point[1] for point in model_points)
            zs.extend(point[2] for point in model_points)
            for _key, bounds in bounds_items:
                bounds_a_min, bounds_b_min, bounds_a_max, bounds_b_max = bounds_projection(bounds)
                xs.extend([bounds_a_min, bounds_a_max])
                zs.extend([bounds_b_min, bounds_b_max])
            min_x, max_x = min(xs), max(xs)
            min_z, max_z = min(zs), max(zs)
            pad = 58
            x_span = max(max_x - min_x, 0.1)
            z_span = max(max_z - min_z, 0.1)

            def project(x_value: float, z_value: float) -> tuple[float, float]:
                px = pad + (x_value - min_x) / x_span * (width - pad * 2)
                py = height - pad - (z_value - min_z) / z_span * (height - pad * 2)
                return px, py

            canvas.create_line(pad, height - pad, width - pad, height - pad, fill="#334155")
            canvas.create_line(pad, height - pad, pad, pad, fill="#334155")
            if isolate_var.get():
                note = "Zoom boca activo" if zoom_mode else "Viendo solo seleccionado"
                canvas.create_text(width - 12, 12, anchor="ne", fill="#93a4b5", text=note)
            model_draw = model_points
            if len(model_draw) > 2600:
                step = max(1, len(model_draw) // 2600)
                model_draw = model_draw[::step]
            cells: dict[tuple[int, int, bool], int] = {}
            cell_size = 5 if zoom_mode else 4
            for key, x_value, z_value in model_draw:
                px, py = project(x_value, z_value)
                cell_x = int(px // cell_size)
                cell_y = int(py // cell_size)
                selected_cell = key == selected_key.get()
                cells[(cell_x, cell_y, selected_cell)] = cells.get((cell_x, cell_y, selected_cell), 0) + 1
            for (cell_x, cell_y, selected_cell), count in cells.items():
                x0 = cell_x * cell_size
                y0 = cell_y * cell_size
                fill = "#64748b" if selected_cell else "#334155"
                if count > 5:
                    fill = "#94a3b8" if selected_cell else "#475569"
                canvas.create_rectangle(x0, y0, x0 + cell_size + 1, y0 + cell_size + 1, fill=fill, outline="")
            for key, bounds in bounds_items:
                bounds_a_min, bounds_b_min, bounds_a_max, bounds_b_max = bounds_projection(bounds)
                left, top = project(bounds_a_min, bounds_b_max)
                right_px, bottom = project(bounds_a_max, bounds_b_min)
                outline = "#facc15" if key == selected_key.get() else "#475569"
                canvas.create_rectangle(left, top, right_px, bottom, outline=outline, width=2 if key == selected_key.get() else 1)
            for key, x_value, z_value in outlets:
                px, py = project(x_value, z_value)
                color = "#22c55e" if key == selected_key.get() else "#166534"
                canvas.create_line(px - 9, py, px + 9, py, fill=color, width=2)
                canvas.create_line(px, py - 9, px, py + 9, fill=color, width=2)
                canvas.create_oval(px - 5, py - 5, px + 5, py + 5, outline=color, width=2)
                if key == selected_key.get():
                    canvas.create_text(px + 12, py - 12, anchor="sw", fill=color, text="salida")
            for key, x_value, z_value, enabled in points:
                px, py = project(x_value, z_value)
                color = "#facc15" if key == selected_key.get() else ("#38bdf8" if enabled else "#64748b")
                radius = 7 if key == selected_key.get() else 5
                canvas.create_oval(px - radius, py - radius, px + radius, py + radius, fill=color, outline="")

        def load_selected(key: str) -> None:
            selected_key.set(key)
            item = state[key]
            position = item["position"]
            assert isinstance(position, list)
            enabled_var.set(bool(item["enabled"]))
            x_var.set(fmt(float(position[0])))
            y_var.set(fmt(float(position[1])))
            z_var.set(fmt(float(position[2])))
            direction_var.set(str(item.get("direction") or "Original PM"))
            if tree.selection() != (key,):
                tree.selection_set(key)
            tree.see(key)
            draw()

        def apply_selected() -> bool:
            key = selected_key.get()
            if key not in state:
                return False
            try:
                position = [float(x_var.get()), float(y_var.get()), float(z_var.get())]
            except ValueError:
                self.messagebox.showerror(APP_TITLE, "X/Y/Z deben ser numeros. Ejemplo: 0.10 o -0.05")
                return False
            state[key]["enabled"] = bool(enabled_var.get())
            state[key]["position"] = position
            selected_direction = direction_var.get() if direction_var.get() in SMOKE_DIRECTION_ROTATIONS else "Original PM"
            state[key]["direction"] = selected_direction
            state[key]["rotation"] = SMOKE_DIRECTION_ROTATIONS[selected_direction]
            tree.item(key, values=row_values(key))
            draw()
            return True

        def step_size() -> float | None:
            try:
                value = abs(float(step_var.get() or 0.02))
            except ValueError:
                self.messagebox.showerror(APP_TITLE, "El paso debe ser numero. Ejemplo: 0.02 o 0.05")
                return None
            return value or 0.02

        def nudge(axis: int, direction: int) -> None:
            step = step_size()
            if step is None:
                return
            try:
                values = [float(x_var.get()), float(y_var.get()), float(z_var.get())]
            except ValueError:
                self.messagebox.showerror(APP_TITLE, "X/Y/Z deben ser numeros. Ejemplo: 0.10 o -0.05")
                return
            values[axis] += step * direction
            x_var.set(fmt(values[0]))
            y_var.set(fmt(values[1]))
            z_var.set(fmt(values[2]))
            apply_selected()

        def move_to_outlet() -> None:
            key = selected_key.get()
            if key not in state:
                return
            candidate = state[key]["candidate"]
            assert isinstance(candidate, LocatorCandidate)
            x_var.set(fmt(candidate.outlet_position[0]))
            y_var.set(fmt(candidate.outlet_position[1]))
            z_var.set(fmt(candidate.outlet_position[2]))
            apply_selected()

        def move_visible_to_outlets() -> None:
            keys = visible_keys()
            for key in keys:
                item = state[key]
                candidate = item["candidate"]
                assert isinstance(candidate, LocatorCandidate)
                item["position"] = list(candidate.outlet_position)
                tree.item(key, values=row_values(key))
            if selected_key.get() in state:
                load_selected(selected_key.get())
            draw()

        def apply_direction_to_visible() -> None:
            selected_direction = direction_var.get() if direction_var.get() in SMOKE_DIRECTION_ROTATIONS else "Original PM"
            for key in visible_keys():
                state[key]["direction"] = selected_direction
                state[key]["rotation"] = SMOKE_DIRECTION_ROTATIONS[selected_direction]
            if selected_key.get() in state:
                load_selected(selected_key.get())
            draw()

        def model_changed(_event: object | None = None) -> None:
            if selected_key.get() and selected_key.get() in state:
                apply_selected()
            refill_tree()

        def reset_selected() -> None:
            key = selected_key.get()
            if key not in state:
                return
            candidate = state[key]["candidate"]
            assert isinstance(candidate, LocatorCandidate)
            state[key]["enabled"] = True
            state[key]["position"] = list(candidate.position)
            default_direction = candidate.suggested_direction if self._smoke_direction() == "Automatico" else self._smoke_direction()
            state[key]["direction"] = default_direction
            state[key]["rotation"] = SMOKE_DIRECTION_ROTATIONS[default_direction]
            load_selected(key)
            tree.item(key, values=row_values(key))

        def save_and_close() -> None:
            if not apply_selected():
                return
            self.locator_editor_source = mod_source
            self.locator_edits = {}
            for key, item in state.items():
                position = item["position"]
                assert isinstance(position, list)
                rotation = item["rotation"]
                assert isinstance(rotation, tuple)
                self.locator_edits[key] = LocatorEdit(
                    enabled=bool(item["enabled"]),
                    position=(float(position[0]), float(position[1]), float(position[2])),
                    rotation=rotation,
                )
            active = sum(1 for item in state.values() if item["enabled"])
            self._log(f"Editor locators guardado: {active}/{len(state)} activos para {Path(mod_source).name}")
            win.destroy()

        def open_selected_in_blender() -> None:
            if not apply_selected():
                return
            key = selected_key.get()
            if key not in state:
                return
            item = state[key]
            candidate = item["candidate"]
            position = item["position"]
            assert isinstance(candidate, LocatorCandidate)
            assert isinstance(position, list)
            smoke_position = (float(position[0]), float(position[1]), float(position[2]))

            def work() -> None:
                try:
                    obj_path = export_candidate_to_blender_obj(
                        Path(mod_source),
                        candidate,
                        smoke_position,
                        candidate.outlet_position,
                        self._thread_log,
                    )
                    opened = open_obj_in_blender(obj_path)
                    if opened:
                        self.queue.put(("done", f"Modelo abierto en Blender:\n{obj_path}"))
                    else:
                        self.queue.put(
                            (
                                "done",
                                "No encontre Blender instalado o en PATH.\n"
                                f"Deje el OBJ listo aqui:\n{obj_path}",
                            )
                        )
                except Exception as exc:
                    self.queue.put(("error", str(exc)))

            self._run_worker(work)

        def on_select(_event: object) -> None:
            selection = tree.selection()
            if selection and selection[0] != selected_key.get():
                load_selected(selection[0])

        def on_canvas_press(event: object) -> None:
            if view_var.get() != "3D libre":
                return
            camera["drag"] = (event.x, event.y)

        def on_canvas_drag(event: object) -> None:
            if view_var.get() != "3D libre":
                return
            drag = camera.get("drag")
            if not isinstance(drag, tuple):
                return
            last_x, last_y = drag
            dx = event.x - last_x
            dy = event.y - last_y
            camera["yaw"] = float(camera["yaw"]) + dx * 0.010
            camera["pitch"] = max(-1.35, min(1.35, float(camera["pitch"]) + dy * 0.010))
            camera["drag"] = (event.x, event.y)
            draw()

        def on_canvas_wheel(event: object) -> None:
            if view_var.get() != "3D libre":
                return
            delta = getattr(event, "delta", 0)
            factor = 1.12 if delta > 0 else 1 / 1.12
            camera["scale"] = max(0.25, min(5.0, float(camera["scale"]) * factor))
            draw()

        tree.bind("<<TreeviewSelect>>", on_select)
        canvas.bind("<Configure>", lambda _event: draw())
        canvas.bind("<ButtonPress-1>", on_canvas_press)
        canvas.bind("<B1-Motion>", on_canvas_drag)
        canvas.bind("<MouseWheel>", on_canvas_wheel)
        model_combo.bind("<<ComboboxSelected>>", model_changed)
        view_combo.bind("<<ComboboxSelected>>", lambda _event: draw())
        direction_combo.bind("<<ComboboxSelected>>", lambda _event: apply_selected())

        direction_buttons = ttk.Frame(right, style="Panel.TFrame")
        direction_buttons.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Button(direction_buttons, text="Aplicar direccion a visibles", command=apply_direction_to_visible).pack(
            side="left"
        )

        nudge_buttons = ttk.Frame(right, style="Panel.TFrame")
        nudge_buttons.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        ttk.Button(nudge_buttons, text="X -", command=lambda: nudge(0, -1)).pack(side="left")
        ttk.Button(nudge_buttons, text="X +", command=lambda: nudge(0, 1)).pack(side="left", padx=(6, 0))
        ttk.Button(nudge_buttons, text="Y -", command=lambda: nudge(1, -1)).pack(side="left", padx=(14, 0))
        ttk.Button(nudge_buttons, text="Y +", command=lambda: nudge(1, 1)).pack(side="left", padx=(6, 0))
        ttk.Button(nudge_buttons, text="Z -", command=lambda: nudge(2, -1)).pack(side="left", padx=(14, 0))
        ttk.Button(nudge_buttons, text="Z +", command=lambda: nudge(2, 1)).pack(side="left", padx=(6, 0))

        outlet_buttons = ttk.Frame(right, style="Panel.TFrame")
        outlet_buttons.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Button(outlet_buttons, text="Mover a salida sugerida", command=move_to_outlet).pack(side="left")
        ttk.Button(outlet_buttons, text="Mover visibles a salida alta", command=move_visible_to_outlets).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(
            outlet_buttons,
            text="Verde = boca estimada con Y alto",
            style="Hint.TLabel",
        ).pack(side="left", padx=(12, 0))

        ttk.Label(
            right,
            text="Tip: usa 0.02 para detalle fino o 0.10 para mover mas rapido.",
            style="Hint.TLabel",
        ).grid(row=9, column=0, columnspan=4, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(right, style="Panel.TFrame")
        buttons.grid(row=10, column=0, columnspan=4, sticky="ew", pady=(18, 0))
        ttk.Button(buttons, text="Aplicar punto", command=apply_selected).pack(side="left")
        ttk.Button(buttons, text="Restablecer punto", command=reset_selected).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Guardar y cerrar", style="Accent.TButton", command=save_and_close).pack(side="right")

        refill_tree()

    def _check_updates(self) -> None:
        def work() -> None:
            try:
                tag, _url, setup_url = latest_release()
                latest = parse_version(tag)
                current = parse_version(APP_VERSION)
                if latest > current:
                    setup_path = download_update_setup(tag, setup_url or "", self._thread_log)
                    self.queue.put(("update_ready", f"{tag}|{setup_path}"))
                else:
                    self.queue.put(("done", f"Ya tienes la ultima version: {APP_VERSION}"))
            except Exception as exc:
                self.queue.put(("error", str(exc)))

        self._run_worker(work)

    def _cleanup_work(self) -> None:
        def work() -> None:
            try:
                removed, freed = cleanup_studio_work(self._thread_log)
                self.queue.put(("done", f"Temporales borrados: {removed} carpeta(s), {freed / 1024 / 1024 / 1024:.2f} GB liberados"))
            except Exception as exc:
                self.queue.put(("error", str(exc)))

        self._run_worker(work)

    def _build_patch(self) -> None:
        mods = self._selected_mods()
        if not mods:
            return
        output = Path(self.output_dir.get().strip('" '))
        try:
            _total, _used, free = disk_usage_for(output)
            self._refresh_disk()
            if free < 10 * 1024 * 1024 * 1024:
                if not self.messagebox.askyesno(
                    APP_TITLE,
                    f"Queda poco espacio libre ({format_gb(free)}). El proceso puede fallar.\n\nQuieres continuar?",
                ):
                    return
        except Exception:
            pass
        smoke = Path(self.smoke_mod.get().strip('" '))
        icon_text = self.icon_path.get().strip('" ')
        icon = Path(icon_text) if icon_text else None
        locator_offset = self._locator_offset()
        if locator_offset is None:
            return
        smoke_scale = self._smoke_scale()
        smoke_direction = self._smoke_direction()

        def work() -> None:
            try:
                outputs: list[Path] = []
                for index, mod in enumerate(mods, 1):
                    self._thread_log(f"Creando humo [{index}/{len(mods)}]: {mod.name}")
                    result = build_smoke_patch(
                        mod_path=mod,
                        output_dir=output,
                        mode=self.mode.get(),
                        install=self.install.get(),
                        smoke_mod=smoke,
                        icon_path=icon,
                        locator_offset=locator_offset,
                        smoke_scale=smoke_scale,
                        smoke_direction=smoke_direction,
                        locator_edits=self.locator_edits if str(mod.resolve()) == self.locator_editor_source else None,
                        cleanup_mode=self._cleanup_mode(),
                        diagnostic=self.diagnostic.get(),
                        log=self._thread_log,
                    )
                    outputs.append(result.output_zip)
                self.queue.put(("done", f"Creado(s): {len(outputs)} mod(s). Ultima salida: {outputs[-1]}"))
            except Exception as exc:
                self.queue.put(("error", str(exc)))

        self._run_worker(work)

    def _thread_log(self, message: str) -> None:
        self.queue.put(("log", message))

    def _log(self, message: str) -> None:
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")

    def _clear_log(self) -> None:
        self.log_text.delete("1.0", "end")

    def _save_manual(self) -> None:
        default_path = default_manual_path()
        default_path.parent.mkdir(parents=True, exist_ok=True)
        target = self.filedialog.asksaveasfilename(
            title="Guardar manual",
            initialdir=str(default_path.parent),
            initialfile=default_path.name,
            defaultextension=".txt",
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")],
        )
        if not target:
            return
        path = Path(target)
        try:
            path.write_text(manual_text(), encoding="utf-8")
        except Exception as exc:
            self.messagebox.showerror(APP_TITLE, f"No pude guardar el manual:\n{exc}")
            return
        self._log(f"Manual guardado: {path}")
        if self.messagebox.askyesno(APP_TITLE, "Manual guardado. Quieres abrirlo ahora?"):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception as exc:
                self.messagebox.showwarning(APP_TITLE, f"Manual guardado, pero no pude abrirlo:\n{exc}")

    def _pump_queue(self) -> None:
        try:
            while True:
                kind, message = self.queue.get_nowait()
                if kind == "log":
                    self._log(str(message))
                elif kind == "done":
                    self.progress.stop()
                    self._log(str(message))
                    self._refresh_disk()
                    self.messagebox.showinfo(APP_TITLE, str(message))
                elif kind == "update_ready":
                    self.progress.stop()
                    tag, setup = str(message).split("|", 1)
                    setup_log = launch_update_setup(Path(setup))
                    text = (
                        f"Actualizacion {tag} descargada. La app se cerrara y abrira el instalador limpio.\n"
                        f"Log del instalador: {setup_log}"
                    )
                    self._log(text)
                    self.messagebox.showinfo(APP_TITLE, text)
                    self.root.after(100, self.root.destroy)
                elif kind == "locator_editor_ready":
                    self.progress.stop()
                    try:
                        mod_source, candidates = message
                        self._show_locator_editor(str(mod_source), candidates)
                    except Exception as exc:
                        self._log("ERROR: " + str(exc))
                        self.messagebox.showerror(APP_TITLE, str(exc))
                elif kind == "error":
                    self.progress.stop()
                    self._log("ERROR: " + str(message))
                    self._refresh_disk()
                    self.messagebox.showerror(APP_TITLE, str(message))
        except queue.Empty:
            pass
        self.root.after(100, self._pump_queue)

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--cli", action="store_true", help="Run without GUI")
    parser.add_argument("--analyze", action="store_true", help="Analyze only")
    parser.add_argument("--mod", type=Path, nargs="+", help="Truck mod .scs/.zip")
    parser.add_argument("--game", choices=["ats", "ets2"], default="ats", help="Game mod folder preset")
    parser.add_argument("--output", type=Path, help="Output folder")
    parser.add_argument("--mode", choices=["patch", "standalone", "integrate"], default="patch")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--smoke-mod", type=Path)
    parser.add_argument("--icon", type=Path, help="Foto para convertir a mod_icon.jpg")
    parser.add_argument("--offset-x", type=float, default=0.0, help="Manual X offset for generated locators")
    parser.add_argument("--offset-y", type=float, default=0.0, help="Manual Y offset for generated locators")
    parser.add_argument("--offset-z", type=float, default=0.0, help="Manual Z offset for generated locators")
    parser.add_argument("--smoke-profile", choices=list(SMOKE_PROFILE_SCALES), default="Actual")
    parser.add_argument("--smoke-scale", type=float, help="Manual smoke locator scale; overrides --smoke-profile")
    parser.add_argument("--smoke-direction", choices=SMOKE_DIRECTION_CHOICES, default="Original PM")
    parser.add_argument("--cleanup-mode", choices=["success", "always", "never"], default="success")
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    output_dir = args.output or game_mod_dir(args.game)
    smoke_mod = args.smoke_mod or default_smoke_mod(args.game)
    locator_offset = (args.offset_x, args.offset_y, args.offset_z)
    smoke_scale = args.smoke_scale if args.smoke_scale is not None else SMOKE_PROFILE_SCALES[args.smoke_profile]

    if args.cli:
        if not args.mod:
            parser.error("--mod is required with --cli")
        for mod in args.mod:
            if args.analyze:
                analyze_mod(mod)
            else:
                build_smoke_patch(
                    mod_path=mod,
                    output_dir=output_dir,
                    mode=args.mode,
                    install=args.install,
                    smoke_mod=smoke_mod,
                    icon_path=args.icon,
                    locator_offset=locator_offset,
                    smoke_scale=smoke_scale,
                    smoke_direction=args.smoke_direction,
                    cleanup_mode=args.cleanup_mode,
                    diagnostic=args.diagnostic,
                )
        return 0

    app = StudioApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


