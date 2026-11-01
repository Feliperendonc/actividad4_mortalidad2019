"""
prepare_data.py
---------------
Convierte los archivos Excel originales del DANE (carpeta data/raw/) en archivos
livianos (CSV comprimidos) que la aplicación Dash carga al iniciar.

Se ejecuta UNA sola vez en local (los archivos resultantes se suben al repositorio):

    python prepare_data.py

Así el servidor en la nube no necesita leer Excel de ~19 MB en cada arranque,
lo que ahorra memoria y tiempo (importante en planes gratuitos de Render).
"""
from pathlib import Path

import pandas as pd

BASE = Path(__file__).parent
RAW = BASE / "data" / "raw"
OUT = BASE / "data"

F_MORT = RAW / "NoFetal2019.xlsx"
F_COD = RAW / "CodigosDeMuerte.xlsx"
F_DIV = RAW / "Divipola.xlsx"


def main():
    # 1. Mortalidad no fetal 2019 --------------------------------------------
    print("Leyendo mortalidad (puede tardar ~10 s)...")
    mort = pd.read_excel(F_MORT, sheet_name="No_Fetales_2019", dtype=str)
    cols = ["COD_DANE", "COD_DEPARTAMENTO", "MES", "SEXO", "GRUPO_EDAD1",
            "MANERA_MUERTE", "COD_MUERTE"]
    mort = mort[cols].copy()
    mort["COD_DANE"] = mort["COD_DANE"].str.zfill(5)
    mort["COD_DEPARTAMENTO"] = mort["COD_DEPARTAMENTO"].str.zfill(2)
    for c in ["MES", "SEXO", "GRUPO_EDAD1"]:
        mort[c] = mort[c].astype(int)
    mort.to_csv(OUT / "mortalidad_2019.csv.gz", index=False, compression="gzip")
    print(f"  -> mortalidad_2019.csv.gz ({len(mort):,} registros)")

    # 2. Códigos de causas de muerte (CIE-10) ---------------------------------
    cod = pd.read_excel(F_COD, sheet_name="Final", header=8, dtype=str)
    cod.columns = ["CAPITULO", "NOMBRE_CAPITULO", "COD3", "DESC3", "COD4", "DESC4"]
    cod = cod.dropna(subset=["COD4"])
    for c in cod.columns:
        cod[c] = cod[c].str.strip()
    # Un mismo diccionario para códigos de 4 caracteres y de 3 caracteres
    c4 = cod[["COD4", "DESC4"]].rename(columns={"COD4": "COD_MUERTE", "DESC4": "DESCRIPCION"})
    c3 = (cod[["COD3", "DESC3"]].drop_duplicates("COD3")
          .rename(columns={"COD3": "COD_MUERTE", "DESC3": "DESCRIPCION"}))
    causas = pd.concat([c4, c3]).drop_duplicates("COD_MUERTE")
    causas.to_csv(OUT / "causas_muerte.csv", index=False)
    print(f"  -> causas_muerte.csv ({len(causas):,} códigos)")

    # 3. Divipola: municipios y departamentos ---------------------------------
    div = pd.read_excel(F_DIV, sheet_name="Hoja1", dtype=str)
    div = div[["COD_DANE", "COD_DEPARTAMENTO", "DEPARTAMENTO", "COD_MUNICIPIO", "MUNICIPIO"]]
    div["COD_DANE"] = div["COD_DANE"].str.zfill(5)
    div["COD_DEPARTAMENTO"] = div["COD_DEPARTAMENTO"].str.zfill(2)
    div.to_csv(OUT / "divipola.csv", index=False)
    print(f"  -> divipola.csv ({len(div):,} municipios)")

    # 4. Centroides de departamentos (para el mapa de respaldo) --------------
    geo = pd.read_excel(F_DIV, sheet_name="Hoja3", header=None, skiprows=2, dtype=str)
    geo = geo.iloc[:, [0, 5, 6]]
    geo.columns = ["COD_DEPARTAMENTO", "LON", "LAT"]
    geo = geo.dropna()
    geo["COD_DEPARTAMENTO"] = geo["COD_DEPARTAMENTO"].str.zfill(2)
    for c in ["LON", "LAT"]:
        geo[c] = pd.to_numeric(geo[c].str.replace(",", "."), errors="coerce")
    cent = geo.groupby("COD_DEPARTAMENTO", as_index=False)[["LAT", "LON"]].mean()
    cent.to_csv(OUT / "centroides_departamentos.csv", index=False)
    print(f"  -> centroides_departamentos.csv ({len(cent)} departamentos)")


if __name__ == "__main__":
    main()
