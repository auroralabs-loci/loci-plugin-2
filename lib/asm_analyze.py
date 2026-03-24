#!/usr/bin/env python3
"""LOCI asm-analyze CLI — local ELF binary analysis tool.

Wraps the asm-analyze library to provide ELF binary analysis from the
command line. Intended to be called by Claude via Bash, replacing the
former MCP server interface.

Subcommands:
  slice-elf          — Full ELF analysis (asm, symbols, blocks, segments, callgraph, elfinfo)
  extract-assembly   — Per-function assembly in timing-backend-ready format
  extract-symbols    — Symbol map from an ELF
  diff-elfs          — Compare two ELF binaries
  blocks-to-timing   — Transform blocks CSV to timing-backend CSV format
  stack-depth        — Worst-case stack depth analysis via call-graph traversal
"""

# ---------------------------------------------------------------------------
# Venv auto-bootstrap: re-launch under the plugin's .venv Python if needed.
# This runs before any non-stdlib imports so it works with system Python.
# ---------------------------------------------------------------------------
import json
import os
import subprocess
import sys
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parent.parent
_VENV_DIR = _PLUGIN_DIR / ".venv"


def _file_key(f: Path) -> str:
    """Extract the logical key from a slicer output filename.

    The slicer may produce filenames like 'asm.csv' (simple) or
    'foo.o~bar.o.diff.csv' (compound). Path.stem only strips the last
    extension, giving 'foo.o~bar.o.diff' instead of 'diff'. This helper
    returns the last dot-segment of the stem so the key is always the
    logical output type (e.g. 'diff', 'asm', 'symmap').
    """
    stem = f.stem  # strips .csv
    last_dot = stem.rfind(".")
    if last_dot != -1:
        return stem[last_dot + 1:]
    return stem


def _find_venv_python():
    """Return the path to the venv Python, or None."""
    for p in [
        _VENV_DIR / "Scripts" / "python.exe",  # Windows
        _VENV_DIR / "bin" / "python3",          # Unix
        _VENV_DIR / "bin" / "python",           # Unix fallback
    ]:
        if p.is_file():
            return str(p)
    return None


def _in_venv():
    """Check whether we are already running inside the plugin's venv."""
    try:
        venv = str(_VENV_DIR.resolve())
        return str(Path(sys.prefix).resolve()).startswith(venv)
    except (OSError, ValueError):
        return False


# Guard: only attempt re-exec once (env var prevents infinite loop).
if not _in_venv() and not os.environ.get("_LOCI_BOOTSTRAP"):
    os.environ["_LOCI_BOOTSTRAP"] = "1"
    vp = _find_venv_python()
    if vp is None:
        # Venv missing — try running setup.sh to create it
        setup = _PLUGIN_DIR / "setup" / "setup.sh"
        if setup.is_file():
            subprocess.run(
                ["bash", str(setup)],
                capture_output=True, timeout=300,
            )
            vp = _find_venv_python()
    if vp:
        result = subprocess.run([vp] + sys.argv)
        sys.exit(result.returncode)
    else:
        print(json.dumps({
            "error": "LOCI venv not found and setup failed. "
                     "Run setup.sh manually, or install uv and retry.",
        }))
        sys.exit(1)

# ---------------------------------------------------------------------------
# Normal imports (now guaranteed to run inside the venv)
# ---------------------------------------------------------------------------
import argparse
import csv
import io
import logging
import re
import tempfile
import traceback

# Prepend the cxxfilt_dir detected by setup.sh (written to state/loci-paths.json).
# This ensures the GNU c++filt (which supports -r) is found before any
# system-installed version that may not (e.g. Apple's /usr/bin/c++filt).
_PATHS_FILE = _PLUGIN_DIR / "state" / "loci-paths.json"
try:
    _loci_paths = json.loads(_PATHS_FILE.read_text())
    _cxxfilt_dir = _loci_paths.get("cxxfilt_dir", "")
    if _cxxfilt_dir and _cxxfilt_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _cxxfilt_dir + os.pathsep + os.environ.get("PATH", "")
except (OSError, json.JSONDecodeError):
    pass

import pandas as pd

# ---------------------------------------------------------------------------
# Architecture mapping to timing backend
# ---------------------------------------------------------------------------
ARCH_TO_TIMING = {
    "aarch64": "aarch64",
    "cortexm": "armv7e-m",
    "tricore": "tc3xx",
}
TIMING_TO_ARCH = {v: k for k, v in ARCH_TO_TIMING.items()}

# Accepted architecture aliases (user input → canonical name)
ARCH_ALIASES = {
    "aarch64": "aarch64",
    "arm64": "aarch64",
    "cortex-a53": "aarch64",
    "armv8-a": "aarch64",
    "cortexm": "cortexm",
    "cortex-m": "cortexm",
    "cortex-m4": "cortexm",
    "armv7e-m": "cortexm",
    "thumb": "cortexm",
    "tricore": "tricore",
    "tc399": "tricore",
    "tc3xx": "tricore",
}


def resolve_arch(arch_input: str | None) -> str | None:
    """Resolve a user-provided architecture string to canonical name."""
    if arch_input is None:
        return None
    return ARCH_ALIASES.get(arch_input.lower().strip())


def timing_arch(arch: str) -> str:
    """Map architecture name to timing backend name."""
    return ARCH_TO_TIMING.get(arch, arch)


# ---------------------------------------------------------------------------
# Output type mappings
# ---------------------------------------------------------------------------
VALID_OUTPUT_TYPES = {"asm", "symbols", "blocks", "segments", "callgraph", "elfinfo"}

# Map output_type names to asm-analyze output file stems
OUTPUT_TYPE_TO_STEM = {
    "asm": "asm",
    "symbols": "symmap",
    "blocks": "blocks",
    "segments": "segments",
    "callgraph": "callgraph",
    "elfinfo": "elfinfo",
}

# Map output_type names to asm-analyze process() keyword argument names
OUTPUT_TYPE_TO_KWARG = {
    "asm": "out_asm_file",
    "symbols": "out_sym_map_file",
    "blocks": "blocks_file_path",
    "segments": "output_file_path",
    "callgraph": "out_plot_file",
    "elfinfo": "out_elfinfo_file",
}


# ---------------------------------------------------------------------------
# asm-analyze wrapper
# ---------------------------------------------------------------------------
def run_analysis(elf_path: str, architecture: str | None = None) -> dict:
    """Run asm-analyze process() and return {arch, files} with raw output content.

    Returns dict with:
        arch: detected/specified architecture (canonical name)
        files: dict mapping output type to file content string
    """
    from loci.service.asmslicer import asmslicer

    elf = Path(elf_path)
    if not elf.is_file():
        raise FileNotFoundError(f"ELF file not found: {elf_path}")

    with tempfile.TemporaryDirectory(prefix="loci-asm-analyze-") as tmpdir:
        kwargs = {
            "elf_file_path": str(elf),
            "log": logging.getLogger("loci.asm-analyze"),
        }
        if architecture:
            kwargs["architecture"] = architecture

        # Set individual output file paths for all output types
        for otype, kwarg in OUTPUT_TYPE_TO_KWARG.items():
            stem = OUTPUT_TYPE_TO_STEM[otype]
            kwargs[kwarg] = os.path.join(tmpdir, f"{stem}.csv")

        asmslicer.process(**kwargs)

        # Read all generated output files
        files = {}
        for f in Path(tmpdir).iterdir():
            if f.is_file():
                files[_file_key(f)] = f.read_text()

        # Detect architecture from elfinfo if not specified
        detected_arch = architecture
        if not detected_arch and "elfinfo" in files:
            elfinfo = files["elfinfo"]
            for arch_key in ARCH_TO_TIMING:
                if arch_key.lower() in elfinfo.lower():
                    detected_arch = arch_key
                    break

        return {"arch": detected_arch, "files": files}


# ---------------------------------------------------------------------------
# Assembly parsing helpers
# ---------------------------------------------------------------------------
FUNC_HEADER_RE = re.compile(r"^([0-9a-fA-F]+)\s+<(.+?)>:\s*$", re.MULTILINE)


def parse_functions_from_asm(asm_text: str) -> dict:
    """Parse objdump-style assembly into per-function blocks.

    Returns dict: {function_name: {"assembly": str, "start_address": str, "instructions": list}}
    """
    functions = {}
    headers = list(FUNC_HEADER_RE.finditer(asm_text))

    for i, match in enumerate(headers):
        addr = match.group(1)
        name = match.group(2)
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(asm_text)
        body = asm_text[start:end].rstrip("\n")

        # Filter out empty function bodies
        lines = [ln for ln in body.split("\n") if ln.strip()]
        if not lines:
            continue

        functions[name] = {
            "assembly": "\n".join(lines),
            "start_address": f"0x{addr}",
            "instructions": lines,
        }

    return functions


def parse_symbols(symmap_text: str) -> list:
    """Parse symmap CSV into list of symbol dicts."""
    symbols = []
    reader = csv.DictReader(io.StringIO(symmap_text))
    for row in reader:
        symbols.append({
            "name": row.get("name", ""),
            "long_name": row.get("long_name", ""),
            "start_address": row.get("start_address", ""),
            "size": int(row.get("size", 0)) if row.get("size", "").isdigit() else 0,
            "namespace": row.get("namespace", ""),
        })
    return symbols


def match_function(query: str, sym_name: str, sym_long_name: str) -> bool:
    """Check if a query matches a symbol's name or long_name.

    Supports exact match and prefix match (ignoring parameter lists).
    """
    if query == sym_name or query == sym_long_name:
        return True
    # Match demangled name without params: "calculate" matches "calculate(int)"
    if sym_long_name.startswith(query + "("):
        return True
    # Match short name without params
    if sym_name.startswith(query + "("):
        return True
    return False


def parse_blocks_to_timing_csv(blocks_text: str,
                                functions: list[str] | None = None) -> str:
    """Parse blocks CSV and produce timing-format CSV.

    Blocks CSV columns: s1.name, s1.long_name, r.from_addr, r.to_addr,
                        r.asm, db.block_ids, r.src_location

    Output CSV: function_name, assembly_code
        function_name = {s1.long_name}_{r.from_addr}
        assembly_code = r.asm (as-is)
    """
    reader = csv.DictReader(io.StringIO(blocks_text))

    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["function_name", "assembly_code"])

    for row in reader:
        long_name = row.get("s1.long_name", "")
        from_addr = row.get("r.from_addr", "")
        asm = row.get("r.asm", "")

        if not long_name or not asm:
            continue

        # Filter by function names if specified
        if functions:
            short_name = row.get("s1.name", "")
            if not any(match_function(f, short_name, long_name)
                       for f in functions):
                continue

        function_name = f"{long_name}_{from_addr}"
        writer.writerow([function_name, asm])

    return csv_buf.getvalue()


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------
def slice_elf(elf_path: str, architecture: str | None = None,
              output_types: list[str] | None = None,
              filter_functions: bool = False) -> dict:
    output_types = output_types or ["asm", "symbols"]

    # Validate output_types
    invalid = set(output_types) - VALID_OUTPUT_TYPES
    if invalid:
        return {"error": f"Invalid output_types: {sorted(invalid)}. Valid: {sorted(VALID_OUTPUT_TYPES)}"}

    arch = resolve_arch(architecture)
    result = run_analysis(elf_path, arch)
    detected_arch = result["arch"]
    files = result["files"]

    output = {}
    for otype in output_types:
        stem = OUTPUT_TYPE_TO_STEM.get(otype, otype)
        content = files.get(stem)
        if content is None:
            output[otype] = None
            continue

        if otype == "asm":
            funcs = parse_functions_from_asm(content)
            if filter_functions:
                funcs = {
                    k: v for k, v in funcs.items()
                    if not k.startswith("_") or k.startswith("_Z")
                }
            output[otype] = {
                fname: {
                    "assembly": fdata["assembly"],
                    "start_address": fdata["start_address"],
                    "instruction_count": len(fdata["instructions"]),
                }
                for fname, fdata in funcs.items()
            }
        elif otype == "symbols":
            output[otype] = parse_symbols(content)
        else:
            # Return raw text for blocks, segments, callgraph, elfinfo
            output[otype] = content

    output["architecture"] = detected_arch
    output["timing_architecture"] = timing_arch(detected_arch) if detected_arch else None

    return output


def extract_assembly(elf_path: str, functions: list[str] | None = None,
                     architecture: str | None = None,
                     blocks_file: str | None = None) -> dict:
    arch = resolve_arch(architecture)
    result = run_analysis(elf_path, arch)
    detected_arch = result["arch"]
    files = result["files"]

    asm_text = files.get("asm")
    if not asm_text:
        return {"error": "No assembly output produced by asm-analyze"}

    all_funcs = parse_functions_from_asm(asm_text)

    # Build symbol lookup for name matching
    symmap_text = files.get("symmap", "")
    symbols = parse_symbols(symmap_text) if symmap_text else []

    # Build a mapping from asm function name to symbol info
    sym_lookup = {}
    for sym in symbols:
        sym_lookup[sym["name"]] = sym
        if sym["long_name"]:
            sym_lookup[sym["long_name"]] = sym

    # Match requested functions (or all functions if no filter specified)
    if functions is None:
        # No filter: extract all functions
        matched = all_funcs.copy()
    else:
        # Filter by requested function names
        matched = {}
        for query in functions:
            # Try direct match in asm functions first
            if query in all_funcs:
                matched[query] = all_funcs[query]
                continue

            # Try matching via symbol names
            found = False
            for asm_name, asm_data in all_funcs.items():
                # Check against symbol lookup
                sym = sym_lookup.get(asm_name, {})
                sym_name = sym.get("name", asm_name) if sym else asm_name
                sym_long = sym.get("long_name", "") if sym else ""
                if match_function(query, sym_name, sym_long):
                    matched[query] = asm_data
                    found = True
                    break
                # Also try direct asm_name match
                if match_function(query, asm_name, asm_name):
                    matched[query] = asm_data
                    found = True
                    break

            if not found:
                matched[query] = {"error": f"Function '{query}' not found in ELF"}

    # Write blocks CSV to file if requested
    blocks_text = files.get("blocks", "")
    if blocks_file and blocks_text:
        Path(blocks_file).write_text(blocks_text)

    # Build output
    functions_out = {}
    csv_rows = []
    for fname, fdata in matched.items():
        if "error" in fdata:
            functions_out[fname] = fdata
            continue

        asm = fdata["assembly"]
        instruction_count = len(fdata["instructions"])
        # Calculate size from instruction count (approximate: varies by arch)
        size = instruction_count * 4  # ARM/AArch64 = 4 bytes, Tricore = 4 bytes

        functions_out[fname] = {
            "assembly": asm,
            "start_address": fdata["start_address"],
            "size": size,
            "instruction_count": instruction_count,
        }
        # CSV row: quote the assembly for proper CSV formatting
        csv_rows.append((fname, asm))

    # Build timing CSV — prefer per-block granularity when blocks available
    if blocks_text:
        timing_csv = parse_blocks_to_timing_csv(blocks_text, functions)
    else:
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf)
        writer.writerow(["function_name", "assembly_code"])
        for fname, asm in csv_rows:
            writer.writerow([fname, asm])
        timing_csv = csv_buf.getvalue()

    cfg_text = get_cfg_text(detected_arch, files, functions)

    output = {
        "architecture": detected_arch,
        "timing_architecture": timing_arch(detected_arch) if detected_arch else None,
        "functions": functions_out,
        "timing_csv": timing_csv,
        "control_flow_graph": cfg_text,
    }
    if blocks_file and blocks_text:
        output["blocks_file"] = blocks_file

    return output


def extract_symbols(elf_path: str, architecture: str | None = None) -> dict:
    arch = resolve_arch(architecture)
    result = run_analysis(elf_path, arch)
    files = result["files"]

    symmap_text = files.get("symmap")
    if not symmap_text:
        return {"error": "No symbol map output produced by asm-analyze"}

    symbols = parse_symbols(symmap_text)

    return {
        "architecture": result["arch"],
        "symbols": symbols,
    }


def diff_elfs(elf_path: str, comparing_elf_path: str,
              architecture: str | None = None) -> dict:
    from loci.service.asmslicer import asmslicer

    arch = resolve_arch(architecture)

    # Validate both files exist
    if not Path(elf_path).is_file():
        return {"error": f"Base ELF not found: {elf_path}"}
    if not Path(comparing_elf_path).is_file():
        return {"error": f"Comparing ELF not found: {comparing_elf_path}"}

    with tempfile.TemporaryDirectory(prefix="loci-asm-analyze-diff-") as tmpdir:
        diff_kwargs = {
            "elf_file_path": elf_path,
            "comparing_elf_file_path": comparing_elf_path,
            "compare_out": tmpdir,
            "log": logging.getLogger("loci.asm-analyze"),
        }
        if arch:
            diff_kwargs["architecture"] = arch

        asmslicer.process(**diff_kwargs)

        # Read diff output
        files = {}
        for f in Path(tmpdir).iterdir():
            if f.is_file():
                files[_file_key(f)] = f.read_text()

    # Parse diff CSV if available
    diff_text = files.get("diff", "")
    diff_entries = []
    summary = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}

    if diff_text:
        reader = csv.DictReader(io.StringIO(diff_text))
        for row in reader:
            status = row.get("status", "").lower()
            entry = {
                "status": status,
                "symbol": row.get("symbol", ""),
                "stt_type": row.get("stt_type", ""),
                "similarity_ratio": float(row.get("similarity_ratio", 0))
                if row.get("similarity_ratio", "").replace(".", "").isdigit()
                else 0.0,
                "reason": row.get("reason", ""),
            }
            diff_entries.append(entry)
            if status in summary:
                summary[status] += 1

    return {
        "diff": diff_entries,
        "summary": summary,
    }


def blocks_to_timing(blocks_file: str,
                     functions: list[str] | None = None) -> None:
    """Read blocks CSV and print timing-format CSV to stdout."""
    blocks_path = Path(blocks_file)
    if not blocks_path.is_file():
        print(json.dumps({"error": f"Blocks file not found: {blocks_file}"}))
        sys.exit(1)

    blocks_text = blocks_path.read_text()
    timing_csv = parse_blocks_to_timing_csv(blocks_text, functions)
    print(timing_csv, end="")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def extract_cfg(elf_path, architecture, functions):
    arch = resolve_arch(architecture)
    result = run_analysis(elf_path, arch)
    detected_arch = result["arch"]
    files = result["files"]

    cfg_text = get_cfg_text(detected_arch, files, functions)
    print(cfg_text)
    return "success"


def get_cfg_text(detected_arch, files, functions):
    blocks_text = files.get("blocks")
    string_io_object = io.StringIO(blocks_text.strip())  # strip() removes leading/trailing whitespace
    functions_list = []
    if functions is not None and type(functions) is list:
        functions_list = functions
    elif functions is not None and functions != "":
        functions_list = functions.split(",")
    # Load the data into a DataFrame
    df = pd.read_csv(string_io_object, sep=',')
    from loci.service.asmslicer.cfg_formatter import df_to_cfg_text
    cfg_text = df_to_cfg_text(
        work=df,
        functions=functions_list,
        arch=detected_arch,
    )
    return cfg_text


# ---------------------------------------------------------------------------
# memmap helpers
# ---------------------------------------------------------------------------

def _classify_section(sec) -> tuple:
    """Classify an ELF section into (type_str, region_str) or (None, None)."""
    from elftools.elf.constants import SH_FLAGS

    flags = sec['sh_flags']
    sh_type = sec['sh_type']

    if not (flags & SH_FLAGS.SHF_ALLOC):
        return (None, None)

    if sh_type == 'SHT_NOBITS':
        return ('bss', 'RAM')

    if sh_type == 'SHT_PROGBITS':
        if flags & SH_FLAGS.SHF_EXECINSTR:
            return ('code', 'ROM')
        elif flags & SH_FLAGS.SHF_WRITE:
            return ('data', 'RAM')
        else:
            return ('rodata', 'ROM')

    # Other types (INIT_ARRAY, FINI_ARRAY, etc.)
    if flags & SH_FLAGS.SHF_WRITE:
        return ('data', 'RAM')
    return ('rodata', 'ROM')


def _flags_to_string(flags: int) -> str:
    """Convert ELF section flags to human-readable string like 'WAX'."""
    from elftools.elf.constants import SH_FLAGS

    result = ''
    if flags & SH_FLAGS.SHF_WRITE:
        result += 'W'
    if flags & SH_FLAGS.SHF_ALLOC:
        result += 'A'
    if flags & SH_FLAGS.SHF_EXECINSTR:
        result += 'X'
    return result


def _parse_map_memory_config(map_path: str) -> dict | None:
    """Parse memory region configuration from a linker .map file.

    Supports multiple formats: GCC/GNU ld, IAR EWARM, Keil/ARM Compiler.
    Tries each parser in turn and returns the first successful result.
    Returns dict mapping region name to {origin, length, attrs}, or None on failure.
    """
    try:
        with open(map_path, 'r') as f:
            lines = f.readlines()
    except OSError:
        return None

    # Try each format parser in order
    for parser in (_parse_map_gcc, _parse_map_iar, _parse_map_keil):
        result = parser(lines)
        if result:
            return result
    return None


def _parse_map_gcc(lines: list[str]) -> dict | None:
    """Parse GCC/GNU ld format (also used by TI toolchains).

    Format:
        Memory Configuration

        Name             Origin             Length             Attributes
        FLASH            0x08000000         0x00200000         xr
        RAM              0x20000000         0x00040000         xrw
        *default*        0x00000000         0xffffffff
    """
    start = None
    for i, line in enumerate(lines):
        if 'Memory Configuration' in line:
            start = i
            break
    if start is None:
        return None

    regions = {}
    data_started = False
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped:
            if data_started:
                break
            continue
        if stripped.startswith('Name') and 'Origin' in stripped:
            data_started = True
            continue
        if stripped.startswith('Linker script'):
            break
        if not data_started:
            continue

        parts = stripped.split()
        if len(parts) < 3:
            continue

        name = parts[0]
        if name == '*default*':
            continue

        try:
            origin = int(parts[1], 16)
            length = int(parts[2], 16)
        except (ValueError, IndexError):
            continue

        attrs = parts[3] if len(parts) > 3 else ''
        regions[name] = {'origin': origin, 'length': length, 'attrs': attrs}

    return regions if regions else None


def _parse_map_iar(lines: list[str]) -> dict | None:
    """Parse IAR EWARM linker map format.

    Extracts regions from the PLACEMENT SUMMARY section:
        "P1":  place in [0x08000000-0x081fffff] { ro };
        "P2":  place in [0x20000000-0x2001ffff] { rw, block CSTACK, block HEAP };

    Also handles the "A0" form:
        "A0":  place at start of [0x08000000-0x081fffff] { ro section .intvec };
    """
    # Detect IAR format
    is_iar = False
    for line in lines[:50]:
        if 'IAR Linker' in line or 'PLACEMENT SUMMARY' in line:
            is_iar = True
            break
    if not is_iar:
        return None

    # Find PLACEMENT SUMMARY section
    start = None
    for i, line in enumerate(lines):
        if '*** PLACEMENT SUMMARY' in line or 'PLACEMENT SUMMARY' in line.strip():
            start = i
            break
    if start is None:
        return None

    # Pattern: "NAME": place in [0xSTART-0xEND] { ... };
    #      or: "NAME": place at start of [0xSTART-0xEND] { ... };
    place_re = re.compile(
        r'"([^"]+)":\s+place\s+(?:in|at\s+\w+\s+of)\s+'
        r'\[0x([0-9a-fA-F]+)-0x([0-9a-fA-F]+)\]\s*\{([^}]*)\}'
    )

    regions = {}
    past_header = False
    for line in lines[start + 1:]:
        stripped = line.strip()
        # Skip the *** closing line of the PLACEMENT SUMMARY header block
        if not past_header:
            if stripped == '***' or not stripped:
                continue
            past_header = True
        # Stop at next *** section header
        if stripped.startswith('***'):
            break

        m = place_re.search(stripped)
        if not m:
            continue

        name = m.group(1)
        range_start = int(m.group(2), 16)
        range_end = int(m.group(3), 16)
        content = m.group(4).strip()

        length = range_end - range_start + 1

        # Derive attrs from placement content
        attrs = ''
        if 'ro' in content:
            attrs = 'r'
        if 'rw' in content:
            attrs = 'rw'
        if 'code' in content or '.text' in content or '.intvec' in content:
            attrs += 'x'

        # Merge duplicate address ranges under the same region
        if name not in regions:
            regions[name] = {'origin': range_start, 'length': length, 'attrs': attrs}

    return regions if regions else None


def _parse_map_keil(lines: list[str]) -> dict | None:
    """Parse Keil/ARM Compiler (armlink) linker map format.

    Extracts regions from Execution Region entries:
        Execution Region ER_IROM1 (Exec base: 0x08000000, Load base: 0x08000000,
                                   Size: 0x00001200, Max: 0x00100000, ABSOLUTE)

        Load Region LR_IROM1 (Base: 0x08000000, Size: 0x00001234, Max: 0x00100000, ABSOLUTE)
    """
    # Detect Keil/ARM format
    is_keil = False
    for line in lines[:100]:
        if 'ARM Linker' in line or 'armlink' in line or 'Load Region' in line:
            is_keil = True
            break
    if not is_keil:
        return None

    # Pattern: Execution Region NAME (Exec base: 0xADDR, ..., Max: 0xMAX, ...)
    exec_re = re.compile(
        r'Execution Region\s+(\S+)\s+\('
        r'Exec base:\s*0x([0-9a-fA-F]+).*?'
        r'Max:\s*0x([0-9a-fA-F]+)'
    )

    regions = {}
    for line in lines:
        m = exec_re.search(line)
        if not m:
            continue

        name = m.group(1)
        origin = int(m.group(2), 16)
        max_size = int(m.group(3), 16)

        # Derive attrs from common naming conventions
        attrs = ''
        name_upper = name.upper()
        if 'ROM' in name_upper or 'FLASH' in name_upper or 'IROM' in name_upper:
            attrs = 'xr'
        elif 'RAM' in name_upper or 'IRAM' in name_upper:
            attrs = 'rw'

        regions[name] = {'origin': origin, 'length': max_size, 'attrs': attrs}

    return regions if regions else None


def _memmap_from_elf(elf_path: str, top_n: int = 10) -> dict:
    """Analyze a single ELF file for memory usage. Returns dict with sections,
    summary, top_consumers, all_symbols."""
    from elftools.elf.elffile import ELFFile

    E_MACHINE_MAP = {
        'EM_ARM': 'cortexm',
        'EM_AARCH64': 'aarch64',
        'EM_TRICORE': 'tricore',
    }

    with open(elf_path, 'rb') as f:
        elf = ELFFile(f)

        # ELF metadata
        e_type = elf.header['e_type']
        is_relocatable = (e_type == 'ET_REL')
        elf_type = 'relocatable' if is_relocatable else 'executable'

        e_machine = elf.header['e_machine']
        architecture = E_MACHINE_MAP.get(e_machine, e_machine)

        # Classify sections
        sections = []
        summary = {
            'rom_total': 0, 'ram_static_total': 0,
            'code_size': 0, 'rodata_size': 0,
            'data_size': 0, 'bss_size': 0,
        }

        for sec in elf.iter_sections():
            sec_type, sec_region = _classify_section(sec)
            if sec_type is None:
                continue

            size = sec['sh_size']
            addr = sec['sh_addr']
            flags = _flags_to_string(sec['sh_flags'])

            sections.append({
                'name': sec.name,
                'address': f"0x{addr:08x}",
                'size': size,
                'type': sec_type,
                'flags': flags,
                'memory_region': None if is_relocatable else sec_region,
            })

            # Accumulate summary
            if sec_type == 'code':
                summary['code_size'] += size
                summary['rom_total'] += size
            elif sec_type == 'rodata':
                summary['rodata_size'] += size
                summary['rom_total'] += size
            elif sec_type == 'data':
                summary['data_size'] += size
                summary['ram_static_total'] += size
                # .data also occupies ROM for initial values
                summary['rom_total'] += size
            elif sec_type == 'bss':
                summary['bss_size'] += size
                summary['ram_static_total'] += size

        # Find top consumers from symbol tables
        rom_symbols = []
        ram_symbols = []
        all_symbols = {}

        for sec in elf.iter_sections():
            if sec['sh_type'] not in ('SHT_SYMTAB', 'SHT_DYNSYM'):
                continue
            for sym in sec.iter_symbols():
                sym_type = sym['st_info']['type']
                sym_size = sym['st_size']
                sym_name = sym.name

                if not sym_name or sym_size == 0:
                    continue

                # Determine if ROM or RAM based on the section the symbol lives in
                sym_shndx = sym['st_shndx']
                if isinstance(sym_shndx, str) and sym_shndx in ('SHN_UNDEF', 'SHN_ABS', 'SHN_COMMON'):
                    continue

                try:
                    target_sec = elf.get_section(sym_shndx)
                    target_type, target_region = _classify_section(target_sec)
                except (IndexError, TypeError):
                    continue

                if target_type is None:
                    continue

                entry = {'name': sym_name, 'size': sym_size, 'type': sym_type}
                all_symbols[sym_name] = {
                    'size': sym_size,
                    'type': sym_type,
                    'region': target_region,
                    'section_type': target_type,
                }

                if target_region == 'ROM':
                    rom_symbols.append(entry)
                elif target_region == 'RAM':
                    ram_symbols.append(entry)

        rom_symbols.sort(key=lambda s: s['size'], reverse=True)
        ram_symbols.sort(key=lambda s: s['size'], reverse=True)

    return {
        'elf_path': elf_path,
        'elf_type': elf_type,
        'architecture': architecture,
        'sections': sections,
        'summary': summary,
        'top_consumers': {
            'rom': rom_symbols[:top_n],
            'ram': ram_symbols[:top_n],
        },
        'all_symbols': all_symbols,
    }


def memmap(elf_path: str,
           comparing_elf_path: str | None = None,
           map_file: str | None = None,
           top_n: int = 10) -> dict:
    """ROM/RAM memory usage report from ELF section and symbol analysis.

    Single report mode: analyzes one ELF, optionally with map file for region budgets.
    Delta mode: compares two ELFs and reports size changes.
    """
    if comparing_elf_path is None:
        # --- Single report mode ---
        report = _memmap_from_elf(elf_path, top_n)
        is_relocatable = (report['elf_type'] == 'relocatable')

        # Memory regions from map file
        memory_regions = None
        if map_file and not is_relocatable:
            regions_config = _parse_map_memory_config(map_file)
            if regions_config:
                memory_regions = {}
                for region_name, region_info in regions_config.items():
                    origin = region_info['origin']
                    length = region_info['length']
                    used = 0
                    for sec in report['sections']:
                        sec_addr = int(sec['address'], 16)
                        if origin <= sec_addr < origin + length:
                            used += sec['size']
                    usage_pct = round(used / length * 100, 1) if length > 0 else 0.0
                    memory_regions[region_name] = {
                        'origin': f"0x{origin:08x}",
                        'length': length,
                        'used': used,
                        'usage_pct': usage_pct,
                    }

        # Remove internal all_symbols from output
        report.pop('all_symbols', None)
        report['mode'] = 'report'
        report['memory_regions'] = memory_regions
        return report

    else:
        # --- Delta mode ---
        base = _memmap_from_elf(elf_path, top_n)
        current = _memmap_from_elf(comparing_elf_path, top_n)

        # Section-level deltas
        base_sections = {s['name']: s for s in base['sections']}
        current_sections = {s['name']: s for s in current['sections']}
        all_section_names = list(dict.fromkeys(
            [s['name'] for s in base['sections']] +
            [s['name'] for s in current['sections']]
        ))

        section_deltas = []
        for name in all_section_names:
            b = base_sections.get(name)
            c = current_sections.get(name)
            base_size = b['size'] if b else 0
            current_size = c['size'] if c else 0
            delta = current_size - base_size
            delta_pct = round(delta / base_size * 100, 1) if base_size > 0 else (100.0 if delta > 0 else 0.0)
            sec_type = (c or b)['type']
            sec_region = (c or b).get('memory_region')
            section_deltas.append({
                'name': name,
                'base_size': base_size,
                'current_size': current_size,
                'delta': delta,
                'delta_pct': delta_pct,
                'type': sec_type,
                'memory_region': sec_region,
            })

        # Summary deltas
        summary_delta = {}
        for key in ('rom_total', 'ram_static_total', 'code_size', 'rodata_size', 'data_size', 'bss_size'):
            b_val = base['summary'][key]
            c_val = current['summary'][key]
            delta = c_val - b_val
            delta_pct = round(delta / b_val * 100, 1) if b_val > 0 else (100.0 if delta > 0 else 0.0)
            summary_delta[key] = {
                'base': b_val,
                'current': c_val,
                'delta': delta,
                'delta_pct': delta_pct,
            }

        # Symbol-level deltas
        base_syms = base['all_symbols']
        current_syms = current['all_symbols']

        rom_sym_deltas = []
        ram_sym_deltas = []

        # Added symbols (in current but not in base)
        for name, info in current_syms.items():
            if name not in base_syms:
                entry = {'name': name, 'status': 'added', 'size': info['size']}
                if info['region'] == 'ROM':
                    rom_sym_deltas.append(entry)
                else:
                    ram_sym_deltas.append(entry)

        # Removed symbols (in base but not in current)
        for name, info in base_syms.items():
            if name not in current_syms:
                entry = {'name': name, 'status': 'removed', 'size': info['size']}
                if info['region'] == 'ROM':
                    rom_sym_deltas.append(entry)
                else:
                    ram_sym_deltas.append(entry)

        # Changed symbols (in both but different sizes)
        for name in base_syms:
            if name in current_syms:
                b_size = base_syms[name]['size']
                c_size = current_syms[name]['size']
                if b_size != c_size:
                    region = current_syms[name]['region']
                    entry = {
                        'name': name,
                        'status': 'changed',
                        'base_size': b_size,
                        'current_size': c_size,
                        'delta': c_size - b_size,
                    }
                    if region == 'ROM':
                        rom_sym_deltas.append(entry)
                    else:
                        ram_sym_deltas.append(entry)

        # Sort by absolute delta descending, take top_n
        rom_sym_deltas.sort(key=lambda s: abs(s.get('delta', s.get('size', 0))), reverse=True)
        ram_sym_deltas.sort(key=lambda s: abs(s.get('delta', s.get('size', 0))), reverse=True)

        # Memory regions delta
        memory_regions_delta = None
        is_relocatable = (base['elf_type'] == 'relocatable')
        if map_file and not is_relocatable:
            regions_config = _parse_map_memory_config(map_file)
            if regions_config:
                memory_regions_delta = {}
                for region_name, region_info in regions_config.items():
                    origin = region_info['origin']
                    length = region_info['length']
                    base_used = 0
                    current_used = 0
                    for sec in base['sections']:
                        sec_addr = int(sec['address'], 16)
                        if origin <= sec_addr < origin + length:
                            base_used += sec['size']
                    for sec in current['sections']:
                        sec_addr = int(sec['address'], 16)
                        if origin <= sec_addr < origin + length:
                            current_used += sec['size']
                    delta = current_used - base_used
                    base_pct = round(base_used / length * 100, 1) if length > 0 else 0.0
                    current_pct = round(current_used / length * 100, 1) if length > 0 else 0.0
                    memory_regions_delta[region_name] = {
                        'base_used': base_used,
                        'current_used': current_used,
                        'delta': delta,
                        'length': length,
                        'base_pct': base_pct,
                        'current_pct': current_pct,
                    }

        return {
            'mode': 'delta',
            'base_elf': elf_path,
            'current_elf': comparing_elf_path,
            'architecture': current['architecture'],
            'section_deltas': section_deltas,
            'summary_delta': summary_delta,
            'symbol_deltas': {
                'rom': rom_sym_deltas[:top_n],
                'ram': ram_sym_deltas[:top_n],
            },
            'memory_regions_delta': memory_regions_delta,
        }


def stack_depth(elf_path: str | None = None,
                asm_path: str | None = None,
                callgraph_dot_path: str | None = None,
                architecture: str | None = None,
                entry_functions: list[str] | None = None,
                stack_budget: int | None = None,
                threshold: int = 50,
                max_recursion_depth: int = 1,
                unknown_callee_size: int = 64) -> dict:
    """Run stack depth analysis via the wheel's stack_depth module.

    Two paths:
      - Full ELF (elf_path): runs full disassembly + call-graph extraction
      - Fast/incremental (asm_path): reuses existing .asm and optional .callgraph.dot files
    """
    from loci.service.asmslicer.stack_depth import (
        analyze_stack_depth as _analyze_elf,
        analyze_from_files as _analyze_files,
    )

    if asm_path:
        # Fast path: reuse existing asmslicer output files
        arch = resolve_arch(architecture)
        if not arch:
            return {"error": "Architecture is required when using --asm-path. "
                    f"Supported: {', '.join(sorted(ARCH_ALIASES.keys()))}"}
        return _analyze_files(
            asm_path=asm_path,
            architecture=arch,
            callgraph_dot_path=callgraph_dot_path,
            entry_functions=entry_functions,
            stack_budget=stack_budget,
            threshold_pct=threshold,
            max_recursion_depth=max_recursion_depth,
            unknown_callee_size=unknown_callee_size,
        )
    elif elf_path:
        # Full ELF path
        arch = resolve_arch(architecture)
        return _analyze_elf(
            elf_path=elf_path,
            architecture=arch,
            entry_functions=entry_functions,
            stack_budget=stack_budget,
            threshold_pct=threshold,
            max_recursion_depth=max_recursion_depth,
            unknown_callee_size=unknown_callee_size,
        )
    else:
        return {"error": "Either --elf-path or --asm-path is required"}


def main():
    parser = argparse.ArgumentParser(
        prog="asm-analyze",
        description="LOCI asm-analyze — local ELF binary analysis tool",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # slice-elf
    p_slice = subparsers.add_parser(
        "slice-elf",
        help="Full ELF analysis (asm, symbols, blocks, segments, callgraph, elfinfo)",
    )
    p_slice.add_argument("--elf-path", required=True, help="Path to the ELF binary")
    p_slice.add_argument("--arch", default=None, help="Target architecture (auto-detected if omitted)")
    p_slice.add_argument("--output-types", default="asm,symbols",
                         help="Comma-separated output types (default: asm,symbols)")
    p_slice.add_argument("--filter-functions", action="store_true",
                         help="Filter compiler-generated functions")

    # extract-assembly
    p_extract = subparsers.add_parser(
        "extract-assembly",
        help="Per-function assembly in timing-backend-ready format",
    )
    p_extract.add_argument("--elf-path", required=True, help="Path to the ELF binary")
    p_extract.add_argument("--functions", required=False,
                           help="Comma-separated function names to extract (omit to extract all functions)")
    p_extract.add_argument("--arch", default=None, help="Target architecture (auto-detected if omitted)")
    p_extract.add_argument("--blocks", default=None, metavar="FILE",
                           help="Write basic blocks CSV to this file")

    # extract-symbols
    p_symbols = subparsers.add_parser(
        "extract-symbols",
        help="Extract symbol map from an ELF binary",
    )
    p_symbols.add_argument("--elf-path", required=True, help="Path to the ELF binary")
    p_symbols.add_argument("--arch", default=None, help="Target architecture (auto-detected if omitted)")

    # diff-elfs
    p_diff = subparsers.add_parser(
        "diff-elfs",
        help="Compare two ELF binaries",
    )
    p_diff.add_argument("--elf-path", required=True, help="Path to the base ELF binary")
    p_diff.add_argument("--comparing-elf-path", required=True, help="Path to the changed ELF binary")
    p_diff.add_argument("--arch", default=None, help="Target architecture (auto-detected if omitted)")

    # blocks-to-timing
    p_blocks = subparsers.add_parser(
        "blocks-to-timing",
        help="Transform blocks CSV to timing-backend CSV format",
    )
    p_blocks.add_argument("--blocks", required=True, metavar="FILE",
                          help="Path to blocks CSV file")
    p_blocks.add_argument("--functions", default=None,
                          help="Comma-separated function names to filter")

    # extract-cfg
    p_cfg = subparsers.add_parser(
        "extract-cfg",
        help="Extract CFG (function Control Flow Graph) map from an ELF binary",
    )
    p_cfg.add_argument("--elf-path", required=True, help="Path to the ELF binary")
    p_cfg.add_argument("--arch", default=None, help="Target architecture (auto-detected if omitted)")
    p_cfg.add_argument("--functions", required=False,
                           help="Comma-separated function names to extract (omit to extract all functions)")

    # stack-depth
    p_stack = subparsers.add_parser(
        "stack-depth",
        help="Worst-case stack depth analysis via call-graph traversal",
    )
    p_stack_input = p_stack.add_mutually_exclusive_group(required=True)
    p_stack_input.add_argument("--elf-path", default=None,
                               help="Path to a linked ELF binary (full call-graph analysis)")
    p_stack_input.add_argument("--asm-path", default=None,
                               help="Path to .asm file from asmslicer (fast incremental path)")
    p_stack.add_argument("--callgraph-dot-path", default=None,
                         help="Path to .callgraph.dot file (used with --asm-path)")
    p_stack.add_argument("--arch", default=None,
                         help="Target architecture (required with --asm-path, auto-detected with --elf-path)")
    p_stack.add_argument("--entry-functions", default=None,
                         help="Comma-separated entry-point function names (auto-detect roots if omitted)")
    p_stack.add_argument("--stack-budget", type=int, default=None,
                         help="Configured stack size in bytes (enables usage %% and verdict)")
    p_stack.add_argument("--threshold", type=int, default=50,
                         help="Max allowed usage as percentage of budget (default: 50)")
    p_stack.add_argument("--max-recursion-depth", type=int, default=1,
                         help="Bounded recursion estimate depth (default: 1)")
    p_stack.add_argument("--unknown-callee-size", type=int, default=64,
                         help="Assumed frame size in bytes for unknown/external callees (default: 64)")

    # memmap
    p_memmap = subparsers.add_parser(
        "memmap",
        help="ROM/RAM memory usage report from ELF section and symbol analysis",
    )
    p_memmap.add_argument("--elf-path", required=True, help="Path to the ELF binary or .o file")
    p_memmap.add_argument("--comparing-elf-path", default=None,
                           help="Path to a second ELF to compare against (enables delta report)")
    p_memmap.add_argument("--map-file", default=None,
                           help="Path to GCC linker map file (enables region budgets)")
    p_memmap.add_argument("--top-n", type=int, default=10,
                           help="Number of top consumers to report per category (default: 10)")

    args = parser.parse_args()

    try:
        if args.command == "blocks-to-timing":
            funcs = ([f.strip() for f in args.functions.split(",")]
                     if args.functions else None)
            blocks_to_timing(blocks_file=args.blocks, functions=funcs)
            sys.exit(0)

        if args.command == "slice-elf":
            output_types = [t.strip() for t in args.output_types.split(",")]
            result = slice_elf(
                elf_path=args.elf_path,
                architecture=args.arch,
                output_types=output_types,
                filter_functions=args.filter_functions,
            )
        elif args.command == "extract-assembly":
            funcs = ([f.strip() for f in args.functions.split(",")]
                     if args.functions else None)
            result = extract_assembly(
                elf_path=args.elf_path,
                functions=funcs,
                architecture=args.arch,
                blocks_file=args.blocks,
            )
        elif args.command == "extract-symbols":
            result = extract_symbols(
                elf_path=args.elf_path,
                architecture=args.arch,
            )
        elif args.command == "diff-elfs":
            result = diff_elfs(
                elf_path=args.elf_path,
                comparing_elf_path=args.comparing_elf_path,
                architecture=args.arch,
            )
        elif args.command == "extract-cfg":
            result = extract_cfg(
                elf_path=args.elf_path,
                architecture=args.arch,
                functions=args.functions,
            )
        elif args.command == "stack-depth":
            entry_funcs = ([f.strip() for f in args.entry_functions.split(",")]
                           if args.entry_functions else None)
            result = stack_depth(
                elf_path=args.elf_path,
                asm_path=args.asm_path,
                callgraph_dot_path=args.callgraph_dot_path,
                architecture=args.arch,
                entry_functions=entry_funcs,
                stack_budget=args.stack_budget,
                threshold=args.threshold,
                max_recursion_depth=args.max_recursion_depth,
                unknown_callee_size=args.unknown_callee_size,
            )
        elif args.command == "memmap":
            result = memmap(
                elf_path=args.elf_path,
                comparing_elf_path=args.comparing_elf_path,
                map_file=args.map_file,
                top_n=args.top_n,
            )
        else:
            result = {"error": f"Unknown command: {args.command}"}

        print(json.dumps(result, indent=2))
        sys.exit(1 if "error" in result else 0)

    except Exception as e:
        print(json.dumps({
            "error": str(e),
            "traceback": traceback.format_exc(),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
