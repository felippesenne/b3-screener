from pathlib import Path

ASSETS_DIR = Path(__file__).parent / "assets" / "strategies"

# Os nomes abaixo correspondem exatamente aos presets definidos em app.py.
# Usar correspondência exata evita falhas causadas por normalização de acentos
# e do travessão (—) presente nos nomes exibidos pelo Streamlit.
PRESET_IMAGES = {
    "Stormer — PFR Compra": "pfr_compra.png",
    "Stormer — PFR Venda": "pfr_venda.png",
    "Stormer — Setup 123 Compra": "setup_123_compra.png",
    "Stormer — Setup 123 Venda": "setup_123_venda.png",
    "Stormer — IFR2 clássico": "ifr2_classico.png",
    "Stormer — Éden dos Traders Compra": "eden_compra.png",
    "Stormer — Éden dos Traders Venda": "eden_venda.png",
    "Larry Williams — Setup 9.1 Compra": "setup_91_compra.png",
    "Larry Williams — Setup 9.1 Venda": "setup_91_venda.png",
    "Larry Williams — Setup 9.2 Compra": "setup_92_compra.png",
    "Larry Williams — Setup 9.2 Venda": "setup_92_venda.png",
    "Larry Williams — Setup 9.3 Compra": "setup_93_compra.png",
    "Larry Williams — Setup 9.3 Venda": "setup_93_venda.png",
    "Price Action — Inside Bar": "inside_bar.png",
    "Retorno à média — IFR2 < 25 + MME50 ascendente": "ifr2_25_mme50.png",
    "MME9 / MME80 ascendentes": "mme9_mme80.png",
}


def get_preset_image_path(preset_name: str):
    filename = PRESET_IMAGES.get(preset_name)
    if not filename:
        return None

    path = ASSETS_DIR / filename
    return str(path) if path.is_file() else None
