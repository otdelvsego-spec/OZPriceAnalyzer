from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ozon_app import __version__  # noqa: E402


def windows_version_tuple(version: str) -> tuple[int, int, int, int]:
    core = version.split("+", 1)[0].split("-", 1)[0]
    parts = core.split(".")
    if not 1 <= len(parts) <= 4 or any(not part.isdigit() for part in parts):
        raise ValueError(f"Версия должна начинаться с 1–4 чисел через точку: {version}")
    values = [int(part) for part in parts]
    if any(value > 65_535 for value in values):
        raise ValueError("Каждая часть Windows-версии должна быть от 0 до 65535")
    return tuple((values + [0, 0, 0, 0])[:4])  # type: ignore[return-value]


def render_version_info(version: str) -> str:
    numeric = windows_version_tuple(version)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numeric},
    prodvers={numeric},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '041904B0',
        [
          StringStruct('CompanyName', 'OZ Price Analyzer'),
          StringStruct('FileDescription', 'Анализатор отчетов и доходности Ozon'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', 'OZPriceAnalyzer'),
          StringStruct('OriginalFilename', 'OZPriceAnalyzer.exe'),
          StringStruct('ProductName', 'OZ Price Analyzer'),
          StringStruct('ProductVersion', '{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1049, 1200])])
  ]
)
"""


def write_version_info(destination: str | Path, version: str = __version__) -> Path:
    output = Path(destination).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_version_info(version), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Создать Windows version resource для PyInstaller")
    parser.add_argument(
        "--output",
        default=PROJECT_ROOT / "build" / "windows_version_info.txt",
        type=Path,
    )
    args = parser.parse_args()
    output = write_version_info(args.output)
    print(f"Windows version resource {__version__}: {output}")


if __name__ == "__main__":
    main()
