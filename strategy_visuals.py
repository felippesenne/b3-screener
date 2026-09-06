from __future__ import annotations

import base64
import io
from functools import lru_cache
from pathlib import Path

from PIL import Image
import streamlit as st

_ASSET_DIR = Path(__file__).parent / "assets" / "strategy_sprite_v2"
_CELL_W = 200
_CELL_H = 150
_COLS = 4

PRESET_CELL = {
    "Stormer — Éden dos Traders Compra": 0,
    "Stormer — Éden dos Traders Venda": 1,
    "Retorno à média — IFR2 < 25 + MME50 ascendente": 2,
    "Stormer — IFR2 clássico": 3,
    "Price Action — Inside Bar": 4,
    "MME9 / MME80 ascendentes": 5,
    "Stormer — PFR Compra": 6,
    "Stormer — PFR Venda": 7,
    "Stormer — Setup 123 Compra": 8,
    "Stormer — Setup 123 Venda": 9,
    "Larry Williams — Setup 9.1 Compra": 10,
    "Larry Williams — Setup 9.1 Venda": 11,
    "Larry Williams — Setup 9.2 Compra": 12,
    "Larry Williams — Setup 9.2 Venda": 13,
    "Larry Williams — Setup 9.3 Compra": 14,
    "Larry Williams — Setup 9.3 Venda": 15,
}

_installed = False
_current_preset: str | None = None
_image_rendered = False
_orig_selectbox = None
_orig_info = None


@lru_cache(maxsize=1)
def _load_sprite() -> Image.Image:
    parts = sorted(_ASSET_DIR.glob("part_*.txt"))
    if not parts:
        raise FileNotFoundError("Arquivos do sprite de estratégias não encontrados.")
    encoded = "".join(path.read_text(encoding="ascii").strip() for path in parts)
    image = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")
    expected = (_CELL_W * _COLS, _CELL_H * 4)
    if image.size != expected:
        raise ValueError(f"Sprite de estratégias inválido: {image.size}; esperado {expected}.")
    return image


def _image_for_preset(preset: str) -> Image.Image | None:
    index = PRESET_CELL.get(preset)
    if index is None:
        return None
    row, col = divmod(index, _COLS)
    left = col * _CELL_W
    top = row * _CELL_H
    return _load_sprite().crop((left, top, left + _CELL_W, top + _CELL_H))


def install_strategy_visuals() -> None:
    global _installed, _orig_selectbox, _orig_info
    if _installed:
        return

    _installed = True
    _orig_selectbox = st.selectbox
    _orig_info = st.info

    def selectbox(label, *args, **kwargs):
        global _current_preset, _image_rendered
        result = _orig_selectbox(label, *args, **kwargs)
        if label == "Atalho / preset":
            _current_preset = result
            _image_rendered = False
        return result

    def info(body, *args, **kwargs):
        global _image_rendered
        result = _orig_info(body, *args, **kwargs)
        if not _image_rendered and _current_preset in PRESET_CELL:
            try:
                image = _image_for_preset(_current_preset)
                if image is not None:
                    left, center, right = st.columns([1, 3, 1])
                    with center:
                        st.image(image, use_container_width=True)
                    _image_rendered = True
            except Exception:
                # Uma falha visual nunca deve impedir o funcionamento do screener.
                pass
        return result

    st.selectbox = selectbox
    st.info = info
