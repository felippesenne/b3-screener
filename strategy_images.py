from pathlib import Path
import unicodedata
import re

ASSETS_DIR = Path(__file__).parent / 'assets' / 'strategies'


def _normalize(text: str) -> str:
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = text.lower().strip()
    text = text.replace('—', '-').replace('–', '-')
    text = re.sub(r'\s+', ' ', text)
    return text


PRESET_IMAGE_ALIASES = {
    'pfr compra': 'pfr_compra.png',
    'stormer - pfr compra': 'pfr_compra.png',
    'pfr venda': 'pfr_venda.png',
    'stormer - pfr venda': 'pfr_venda.png',

    'setup 123 compra': 'setup_123_compra.png',
    'setup 123 venda': 'setup_123_venda.png',

    'ifr2 classico': 'ifr2_classico.png',
    'ifr2 classico do stormer': 'ifr2_classico.png',
    'stormer - ifr2 classico': 'ifr2_classico.png',

    'eden dos traders compra': 'eden_compra.png',
    'eden compra': 'eden_compra.png',
    'eden dos traders venda': 'eden_venda.png',
    'eden venda': 'eden_venda.png',

    'setup 9.1 classico - compra': 'setup_91_compra.png',
    'setup 9.1 classico — compra': 'setup_91_compra.png',
    'setup 9.1 compra': 'setup_91_compra.png',
    'setup 9.1 classico - venda': 'setup_91_venda.png',
    'setup 9.1 classico — venda': 'setup_91_venda.png',
    'setup 9.1 venda': 'setup_91_venda.png',

    'setup 9.2 compra': 'setup_92_compra.png',
    'setup 9.2 venda': 'setup_92_venda.png',
    'setup 9.3 compra': 'setup_93_compra.png',
    'setup 9.3 venda': 'setup_93_venda.png',

    'inside bar': 'inside_bar.png',
    'stormer - inside bar': 'inside_bar.png',

    'ifr2 < 25 + mme50 ascendente': 'ifr2_25_mme50.png',
    'ifr2<25 + mme50 ascendente': 'ifr2_25_mme50.png',

    'setup mme9 / mme80': 'mme9_mme80.png',
    'mme9 / mme80': 'mme9_mme80.png',
}


def get_preset_image_path(preset_name: str):
    if not preset_name:
        return None
    key = _normalize(preset_name)
    filename = PRESET_IMAGE_ALIASES.get(key)
    if not filename:
        return None
    path = ASSETS_DIR / filename
    return str(path) if path.exists() else None
