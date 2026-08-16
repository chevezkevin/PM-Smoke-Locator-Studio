from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


APP_TITLE = "PM Smoke Locator Studio"
APP_VERSION = "0.1.8"


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
TOOLS = BUNDLE / "work" / "tools"
DEFAULT_ICON = BUNDLE / "SmokeLocatorStudio" / "assets" / "mod_icon.jpg"
CONVERTER_PIX = TOOLS / "converter_pix" / "converter_pix.exe"
CONVERSION_TOOLS_ZIP = TOOLS / "conversion_tools_2_21.zip"
EXTRACTOR = TOOLS / "sk_extractor_gh" / "extractor.exe"
SCS_EXTRACTOR = TOOLS / "scs_extractor_1_55" / "scs_extractor.exe"
ATS_MOD_DIR = Path.home() / "Documents" / "American Truck Simulator" / "mod"
DEFAULT_SMOKE_MOD = ATS_MOD_DIR / "PM_389_Smoke_All_Trucks_ATS_1.60.zip"
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


@dataclass(frozen=True)
class ExhaustModel:
    model_no_ext: str
    source_def: Path
    variant: str
    look: str


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


def patch_pim_with_smoke(pim_path: Path, skip_part_names: set[str] | None = None) -> tuple[int, int, int, list[str]]:
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

    def locators_from_pieces(pieces: list[int]) -> list[tuple[float, float, float]]:
        piece_positions: list[tuple[float, float, float]] = []
        for piece in pieces:
            piece_positions.extend(smoke_positions(piece_vertices.get(piece, [])))
        if len(piece_positions) > 1:
            return merge_close_positions(piece_positions)

        vertices: list[tuple[float, float, float]] = []
        for piece in pieces:
            vertices.extend(piece_vertices.get(piece, []))
        return smoke_positions(vertices)

    def patch_part(match: re.Match[str]) -> str:
        nonlocal next_locator, added
        block = match.group(0)
        name_match = re.search(r'Name:\s*"([^"]+)"', block)
        part_name = name_match.group(1) if name_match else ""
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
            positions = locators_from_pieces(pieces)
            for position in positions:
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
                            "     Rotation: ( &248d3132  &00000000  &3f800000  &00000000 )",
                            "     Scale: ( &3f800000  &3f800000  &3f800000 )",
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
    model_re = re.compile(r'exterior_model:\s*"([^"]+\.pmd)"', re.I)
    variant_re = re.compile(r"\bvariant:\s*([^\s]+)", re.I)
    look_re = re.compile(r"\blook:\s*([^\s]+)", re.I)
    found: dict[str, ExhaustModel] = {}

    truck_def = extracted / "def" / "vehicle" / "truck"
    if not truck_def.exists():
        return []

    for sii in truck_def.rglob("*.sii"):
        text = sii.read_text(encoding="utf-8", errors="ignore")
        for model in model_re.findall(text):
            if Path(model).stem.lower() == "empty":
                continue
            if score_exhaust_candidate(sii, truck_def, text, model) < 7:
                continue
            model_no_ext = model[:-4]
            pmd = extracted / model.lstrip("/").replace("/", os.sep)
            pmg = pmd.with_suffix(".pmg")
            if not pmd.exists() or not pmg.exists():
                continue
            variant = (variant_re.search(text).group(1) if variant_re.search(text) else "default")
            look = (look_re.search(text).group(1) if look_re.search(text) else "default")
            found.setdefault(model_no_ext, ExhaustModel(model_no_ext, sii, variant, look))

    return [found[key] for key in sorted(found)]


def write_manifest(stage: Path, display_name: str, description: str) -> None:
    write_mod_icon(stage)
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


def write_mod_icon(stage: Path) -> None:
    icon = stage / "mod_icon.jpg"
    if icon.exists():
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


def build_smoke_patch(
    mod_path: Path,
    output_dir: Path,
    mode: str = "patch",
    install: bool = False,
    smoke_mod: Path = DEFAULT_SMOKE_MOD,
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

    log("Agregando locators smoke_new...")
    for pim in pim_files:
        pit = pim.with_suffix(".pit")
        skip_parts = common_visible_parts_from_pit(pit) if pit.exists() else set()
        added, removed, total, pim_warnings = patch_pim_with_smoke(pim, skip_parts)
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
    return BuildResult(output_zip, report, len(models), locator_count, removed_smoke, warnings)


class StudioApp:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.root = tk.Tk()
        self.root.title(f"{APP_TITLE} {APP_VERSION}")
        self.root.geometry("980x700")
        self.root.minsize(860, 620)

        self.mod_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(ATS_MOD_DIR))
        self.smoke_mod = tk.StringVar(value=str(DEFAULT_SMOKE_MOD))
        self.mode = tk.StringVar(value="patch")
        self.install = tk.BooleanVar(value=True)

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
        style.configure("TButton", font=("Segoe UI Semibold", 10), padding=(12, 8))
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 11), padding=(14, 10))
        style.configure("TRadiobutton", background="#171d23", foreground="#edf2f7")
        style.configure("TCheckbutton", background="#171d23", foreground="#edf2f7")

    def _build(self) -> None:
        tk = self.tk
        ttk = self.ttk
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=f"{APP_TITLE} {APP_VERSION}", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Selecciona un mod de camion, analiza sus escapes y crea el humo con smoke_new.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 14))

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

        modes = ttk.Frame(panel, style="Panel.TFrame")
        modes.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 4))
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
        ttk.Button(actions, text="Crear humo", style="Accent.TButton", command=self._build_patch).pack(side="left", padx=10)
        ttk.Button(actions, text="Limpiar log", command=self._clear_log).pack(side="right")

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

    def _choose_mod(self) -> None:
        path = self.filedialog.askopenfilename(
            title="Seleccionar mod de camion",
            filetypes=[("Mods ATS", "*.scs *.zip"), ("Todos", "*.*")],
            initialdir=str(ATS_MOD_DIR if ATS_MOD_DIR.exists() else Path.home()),
        )
        if path:
            self.mod_path.set(path)

    def _choose_output(self) -> None:
        path = self.filedialog.askdirectory(title="Seleccionar carpeta de salida", initialdir=self.output_dir.get())
        if path:
            self.output_dir.set(path)

    def _choose_smoke_mod(self) -> None:
        path = self.filedialog.askopenfilename(
            title="Seleccionar PM Smoke principal",
            filetypes=[("Zip/SCS", "*.zip *.scs"), ("Todos", "*.*")],
            initialdir=str(ATS_MOD_DIR if ATS_MOD_DIR.exists() else Path.home()),
        )
        if path:
            self.smoke_mod.set(path)

    def _run_worker(self, target: Callable[[], None]) -> None:
        if self.worker and self.worker.is_alive():
            self.messagebox.showwarning(APP_TITLE, "Ya hay un trabajo corriendo.")
            return
        self.progress.start(10)
        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def _validate_mod(self) -> Path | None:
        mod = Path(self.mod_path.get().strip('" '))
        if not mod.exists():
            self.messagebox.showerror(APP_TITLE, "Selecciona un mod valido.")
            return None
        return mod

    def _analyze(self) -> None:
        mod = self._validate_mod()
        if not mod:
            return

        def work() -> None:
            try:
                analyze_mod(mod, self._thread_log)
                self.queue.put(("done", "Analisis terminado."))
            except Exception as exc:
                self.queue.put(("error", str(exc)))

        self._run_worker(work)

    def _build_patch(self) -> None:
        mod = self._validate_mod()
        if not mod:
            return
        output = Path(self.output_dir.get().strip('" '))
        smoke = Path(self.smoke_mod.get().strip('" '))

        def work() -> None:
            try:
                result = build_smoke_patch(
                    mod_path=mod,
                    output_dir=output,
                    mode=self.mode.get(),
                    install=self.install.get(),
                    smoke_mod=smoke,
                    log=self._thread_log,
                )
                self.queue.put(("done", f"Creado: {result.output_zip}"))
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

    def _pump_queue(self) -> None:
        try:
            while True:
                kind, message = self.queue.get_nowait()
                if kind == "log":
                    self._log(message)
                elif kind == "done":
                    self.progress.stop()
                    self._log(message)
                    self.messagebox.showinfo(APP_TITLE, message)
                elif kind == "error":
                    self.progress.stop()
                    self._log("ERROR: " + message)
                    self.messagebox.showerror(APP_TITLE, message)
        except queue.Empty:
            pass
        self.root.after(100, self._pump_queue)

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--cli", action="store_true", help="Run without GUI")
    parser.add_argument("--analyze", action="store_true", help="Analyze only")
    parser.add_argument("--mod", type=Path, help="Truck mod .scs/.zip")
    parser.add_argument("--output", type=Path, default=ATS_MOD_DIR, help="Output folder")
    parser.add_argument("--mode", choices=["patch", "standalone", "integrate"], default="patch")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--smoke-mod", type=Path, default=DEFAULT_SMOKE_MOD)
    args = parser.parse_args()

    if args.cli:
        if not args.mod:
            parser.error("--mod is required with --cli")
        if args.analyze:
            analyze_mod(args.mod)
        else:
            build_smoke_patch(args.mod, args.output, args.mode, args.install, args.smoke_mod)
        return 0

    app = StudioApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


