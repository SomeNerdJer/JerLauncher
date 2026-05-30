"""
Read the EA Desktop / EA app install cache (``ProgramData\\EA Desktop\\...\\IS``).

Decryption matches GameFinder / EA Desktop (AES-256-CBC, hardware-derived key).
See: https://github.com/erri120/GameFinder/wiki/EA-Desktop
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Any

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
except ImportError:  # pragma: no cover
    AES = None  # type: ignore
    unpad = None  # type: ignore

# EA Desktop ProgramData layout (GameFinder.EADesktopHandler)
_EA_DESKTOP_DATA = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "EA Desktop"
_ALL_USERS_FOLDER = "530c11479fe252fc5aabc24935b9776d4900eb3ba58fdc271e0d6229413ad40e"
_IS_FILE = "IS"

# IV: first 16 bytes of SHA3-256("allUsersGenericId" + "IS") — constant per GameFinder
_PRECOMPUTED_IV = bytes(
    [
        0x84,
        0xEF,
        0xC4,
        0xB8,
        0x36,
        0x11,
        0x9C,
        0x20,
        0x41,
        0x93,
        0x98,
        0xC3,
        0xF3,
        0xF2,
        0xBC,
        0xEF,
    ]
)

_ALL_ID = "allUsersGenericId"
_IS_LITERAL = "IS"


def _ea_desktop_is_path() -> Path:
    return _EA_DESKTOP_DATA / _ALL_USERS_FOLDER / _IS_FILE


def _volume_serial_c_drive() -> str:
    serial = wintypes.DWORD()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ok = kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p("C:\\"),
        None,
        0,
        ctypes.byref(serial),
        None,
        None,
        None,
        0,
    )
    if not ok:
        return "0"
    return f"{serial.value:X}"


def _wmi_hardware_strings() -> dict[str, str] | None:
    """
    Match GameFinder's ``ManagementObjectSearcher`` — same WQL queries and first result.
    (``Get-CimInstance`` can enumerate Win32_VideoController in a different order.)
    """
    ps = r"""
Add-Type -AssemblyName System.Management
function FirstProp([string]$className, [string]$propName) {
  $q = "SELECT $propName FROM $className"
  $searcher = New-Object System.Management.ManagementObjectSearcher($q)
  foreach ($o in $searcher.Get()) {
    $v = $o.Properties[$propName].Value
    if ($null -ne $v) { return [string]$v }
  }
  return ""
}
$o = [ordered]@{
  BaseBoardManufacturer = (FirstProp "Win32_BaseBoard" "Manufacturer")
  BaseBoardSerialNumber = (FirstProp "Win32_BaseBoard" "SerialNumber")
  BIOSManufacturer = (FirstProp "Win32_BIOS" "Manufacturer")
  BIOSSerialNumber = (FirstProp "Win32_BIOS" "SerialNumber")
  VideoPNPDeviceId = (FirstProp "Win32_VideoController" "PNPDeviceId")
  ProcessorManufacturer = (FirstProp "Win32_Processor" "Manufacturer")
  ProcessorId = (FirstProp "Win32_Processor" "ProcessorId")
  ProcessorName = (FirstProp "Win32_Processor" "Name")
}
$o | ConvertTo-Json -Compress
"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        raw = json.loads(proc.stdout)
        if not isinstance(raw, dict):
            return None
        out = {k: str(v) if v is not None else "" for k, v in raw.items()}
        return out
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        return None


def _hardware_string_gamefinder(wmi: dict[str, str], volume_hex: str) -> str:
    # Must match GameFinder HardwareInformation: trailing ';' after processor name.
    parts = [
        wmi.get("BaseBoardManufacturer", ""),
        wmi.get("BaseBoardSerialNumber", ""),
        wmi.get("BIOSManufacturer", ""),
        wmi.get("BIOSSerialNumber", ""),
        volume_hex,
        wmi.get("VideoPNPDeviceId", ""),
        wmi.get("ProcessorManufacturer", ""),
        wmi.get("ProcessorId", ""),
        wmi.get("ProcessorName", ""),
    ]
    return ";".join(parts) + ";"


def _sha1_hex_lower_ascii(s: str) -> str:
    return hashlib.sha1(s.encode("ascii", errors="replace")).hexdigest()


def _sha3_256_bytes_from_string(s: str) -> bytes:
    return hashlib.sha3_256(s.encode("ascii", errors="replace")).digest()


def _key_from_wmi(wmi: dict[str, str], volume_hex: str) -> bytes:
    hw = _hardware_string_gamefinder(wmi, volume_hex)
    hw_hash = _sha1_hex_lower_ascii(hw)
    key_input = _ALL_ID + _IS_LITERAL + hw_hash
    return _sha3_256_bytes_from_string(key_input)


def _all_video_pnp_device_ids() -> list[str] | None:
    """All adapters; EA may match a non-first device (e.g. real GPU vs Microsoft Basic Display)."""
    ps = r"""
Add-Type -AssemblyName System.Management
$q = "SELECT PNPDeviceId FROM Win32_VideoController"
$s = New-Object System.Management.ManagementObjectSearcher($q)
$ids = New-Object System.Collections.Generic.List[string]
foreach ($o in $s.Get()) {
  $v = $o.Properties['PNPDeviceId'].Value
  if ($null -ne $v) { $ids.Add([string]$v) }
}
$ids | ConvertTo-Json -Compress
"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        data = json.loads(proc.stdout)
        if isinstance(data, str):
            return [data]
        if isinstance(data, list):
            out = [str(x) for x in data if str(x).strip()]
            return out or None
        return None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        return None


def _create_decryption_key() -> bytes | None:
    vol = _volume_serial_c_drive()
    wmi = _wmi_hardware_strings()
    if wmi is None:
        return None
    return _key_from_wmi(wmi, vol)


def _decrypt_is_file(raw: bytes, key: bytes) -> str | None:
    if AES is None or unpad is None or len(raw) <= 64:
        return None
    ciphertext = raw[64:]
    try:
        cipher = AES.new(key, AES.MODE_CBC, _PRECOMPUTED_IV)
        plain = unpad(cipher.decrypt(ciphertext), AES.block_size)
        text = plain.decode("utf-8")
        if not text.lstrip().startswith("{"):
            return None
        return text
    except (ValueError, UnicodeDecodeError):
        return None


def _decrypt_is_file_try_keys(raw: bytes, wmi_base: dict[str, str], volume_hex: str) -> str | None:
    """Try each video controller PnP id; fall back to the first-wmi key only."""
    if AES is None or unpad is None or len(raw) <= 64:
        return None
    video_ids = _all_video_pnp_device_ids()
    if video_ids:
        for pnp in video_ids:
            w = dict(wmi_base)
            w["VideoPNPDeviceId"] = pnp
            key = _key_from_wmi(w, volume_hex)
            text = _decrypt_is_file(raw, key)
            if text is not None:
                return text
    key = _key_from_wmi(wmi_base, volume_hex)
    return _decrypt_is_file(raw, key)


_BRACKET_RE = re.compile(r"^\[(.+)\](.+)$")


def _hive_and_subkey_from_keypath(key_full: str) -> tuple[int, str] | None:
    k = key_full.strip()
    if k.upper().startswith("HKEY_LOCAL_MACHINE\\"):
        return winreg.HKEY_LOCAL_MACHINE, k[len("HKEY_LOCAL_MACHINE\\") :]
    if k.upper().startswith("HKLM\\"):
        return winreg.HKEY_LOCAL_MACHINE, k[len("HKLM\\") :]
    if k.upper().startswith("HKEY_CURRENT_USER\\"):
        return winreg.HKEY_CURRENT_USER, k[len("HKEY_CURRENT_USER\\") :]
    if k.upper().startswith("HKCU\\"):
        return winreg.HKEY_CURRENT_USER, k[len("HKCU\\") :]
    return None


def _resolve_bracket_exe(token: str) -> Path | None:
    """
    EA uses ``[HKEY_...\\...\\Install Dir]Some.exe`` — registry folder + relative exe.
    """
    if winreg is None:
        return None
    m = _BRACKET_RE.match(token.strip())
    if not m:
        return None
    inner, exe_name = m.group(1), m.group(2).strip()
    for suf in (r"\Install Dir", r"\InstallDir"):
        if inner.endswith(suf):
            key_full = inner[: -len(suf)]
            parsed = _hive_and_subkey_from_keypath(key_full)
            if parsed is None:
                return None
            hive, sub = parsed
            try:
                with winreg.OpenKey(hive, sub) as key:
                    for vn in ("Install Dir", "InstallDir"):
                        try:
                            raw, _ = winreg.QueryValueEx(key, vn)
                            root = Path(str(raw).strip().strip('"'))
                            cand = root / exe_name
                            if cand.is_file():
                                return cand
                        except OSError:
                            continue
            except OSError:
                pass
            return None
    return None


def _slug_to_title(base_slug: str) -> str:
    s = base_slug.strip()
    if not s:
        return "EA Game"
    parts = [p for p in s.replace("_", "-").split("-") if p]
    if not parts:
        return "EA Game"
    return " ".join(w.capitalize() for w in parts)


def _pick_launcher_exe(info: dict[str, Any], base_install: Path) -> Path | None:
    lip = info.get("localInstallProperties")
    if isinstance(lip, dict):
        launchers = lip.get("launchers")
        if isinstance(launchers, list) and launchers:
            non_trial: list[dict[str, Any]] = []
            trial: list[dict[str, Any]] = []
            for L in launchers:
                if not isinstance(L, dict):
                    continue
                ep = str(L.get("exePath") or "").strip()
                if not ep:
                    continue
                if L.get("isTimedTrial"):
                    trial.append(L)
                else:
                    non_trial.append(L)
            for pool in (non_trial, trial):
                for L in pool:
                    ep = str(L.get("exePath") or "").strip()
                    if ep.startswith("[") and "]" in ep:
                        got = _resolve_bracket_exe(ep)
                        if got and got.is_file():
                            return got
                    p = Path(ep)
                    if p.is_file():
                        return p
    # Fallback: executableCheck / installCheck strings (multiple bracket refs may be concatenated)
    for key in ("executableCheck", "installCheck", "contentManifestLaunchers"):
        raw = info.get(key)
        if not isinstance(raw, str):
            continue
        for m in re.finditer(r"(\[HKEY[^]]+\][^[\]]+\.(?:exe|EXE))", raw):
            got = _resolve_bracket_exe(m.group(1))
            if got and got.is_file():
                return got
    return None


def _install_status_installed(info: dict[str, Any]) -> bool:
    """EA ``detailedState.installStatus`` — 5 is completed install in typical manifests."""
    ds = info.get("detailedState")
    if not isinstance(ds, dict):
        return True
    st = ds.get("installStatus")
    if st is None:
        return True
    try:
        n = int(st)
    except (TypeError, ValueError):
        return True
    # 0 = not installed; 5 = ready; others may be updating/partial — accept if folder exists
    if n == 0:
        return False
    if n == 5:
        return True
    return True


def parse_ea_desktop_install_infos(plaintext: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(plaintext)
    except json.JSONDecodeError:
        return []
    infos = data.get("installInfos")
    if not isinstance(infos, list):
        return []
    out: list[dict[str, Any]] = []
    for info in infos:
        if not isinstance(info, dict):
            continue
        base_path = str(info.get("baseInstallPath") or "").strip()
        slug = str(info.get("baseSlug") or "").strip()
        sw_id = str(info.get("softwareId") or "").strip()
        if not base_path or not slug:
            continue
        install_dir = Path(base_path)
        if not install_dir.is_dir():
            continue
        if not _install_status_installed(info):
            continue

        title = _slug_to_title(slug)
        library_key = f"ea:{re.sub(r'[^\w.\-]+', '_', slug)[:80]}"
        exe = _pick_launcher_exe(info, install_dir)
        if exe is None:
            from services.ea_library import _pick_launch_exe

            exe = _pick_launch_exe(install_dir)
        if exe is None:
            continue

        header = _find_cover_near(install_dir)
        out.append(
            {
                "title": title,
                "appid": 0,
                "store": "ea",
                "library_key": library_key,
                "command": str(exe),
                "args": [],
                "cwd": str(exe.parent),
                "header_image": str(header) if header else "",
                "ea_software_id": sw_id,
                "ea_base_slug": slug,
                "ea_source": "ea_desktop_is",
            }
        )
    return out


def _find_cover_near(install: Path) -> Path | None:
    for pat in (
        "CoverArt*.jpg",
        "CoverArt*.png",
        "**/CoverArt*.jpg",
        "**/CoverArt*.png",
    ):
        try:
            for p in install.glob(pat):
                if p.is_file():
                    return p
        except OSError:
            continue
    return None


def try_load_ea_desktop_games() -> tuple[list[dict[str, Any]], str]:
    """
    Returns (games, mode). ``ea_desktop`` means the EA app ``IS`` file was decrypted and parsed.
    ``decrypt_failed`` triggers legacy registry fallback in ``ea_library``.
    """
    if winreg is None or AES is None:
        return [], "decrypt_failed"

    path = _ea_desktop_is_path()
    if not path.is_file():
        return [], "decrypt_failed"

    try:
        raw = path.read_bytes()
    except OSError:
        return [], "decrypt_failed"

    wmi = _wmi_hardware_strings()
    if wmi is None:
        return [], "decrypt_failed"
    vol = _volume_serial_c_drive()
    plain = _decrypt_is_file_try_keys(raw, wmi, vol)
    if plain is None:
        return [], "decrypt_failed"

    games = parse_ea_desktop_install_infos(plain)
    # De-dupe by library_key (first wins)
    by_k: dict[str, dict[str, Any]] = {}
    for g in games:
        lk = str(g.get("library_key") or "")
        if lk and lk not in by_k:
            by_k[lk] = g
    merged = sorted(by_k.values(), key=lambda x: str(x.get("title", "")).casefold())
    return merged, "ea_desktop"
