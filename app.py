"""
Mortalidad en Colombia 2019 - Aplicación web dinámica con Dash y Plotly
=======================================================================
Fuente: DANE - Estadísticas Vitales (EEVV) 2019, defunciones no fetales.

Ejecución local:   python app.py      -> http://127.0.0.1:8050
Producción:        gunicorn app:server
"""
import json
import os
import urllib.request
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, dash_table, dcc, html

# ---------------------------------------------------------------------------
# 1. Carga de datos
# ---------------------------------------------------------------------------
DATA = Path(__file__).parent / "data"

mort = pd.read_csv(
    DATA / "mortalidad_2019.csv.gz",
    dtype={"COD_DANE": str, "COD_DEPARTAMENTO": str, "COD_MUERTE": str},
)
causas = pd.read_csv(DATA / "causas_muerte.csv", dtype=str)
divipola = pd.read_csv(DATA / "divipola.csv", dtype=str)
centroides = pd.read_csv(DATA / "centroides_departamentos.csv", dtype={"COD_DEPARTAMENTO": str})

# Nombres de departamentos (versión corta para San Andrés, para que quepa en los ejes)
deptos = divipola.drop_duplicates("COD_DEPARTAMENTO")[["COD_DEPARTAMENTO", "DEPARTAMENTO"]].copy()
deptos["DEPARTAMENTO"] = deptos["DEPARTAMENTO"].replace(
    {"ARCHIPIÉLAGO DE SAN ANDRÉS, PROVIDENCIA Y SANTA CATALINA": "SAN ANDRÉS Y PROVIDENCIA"}
)
municipios = divipola[["COD_DANE", "MUNICIPIO", "COD_MUNICIPIO"]]

mort = mort.merge(deptos, on="COD_DEPARTAMENTO", how="left").merge(municipios, on="COD_DANE", how="left")
mort["CIUDAD"] = mort["MUNICIPIO"].str.title() + " (" + mort["DEPARTAMENTO"].str.title() + ")"
# En la DIVIPOLA el código de municipio 001 corresponde a la capital del departamento
# (excepto Cundinamarca: su capital es Bogotá D.C., que ya tiene su propio código 11001)
mort["ES_CAPITAL"] = (mort["COD_MUNICIPIO"] == "001") & (mort["COD_DEPARTAMENTO"] != "25")

SEXO = {1: "Hombre", 2: "Mujer", 3: "Indeterminado"}
mort["SEXO_TXT"] = mort["SEXO"].map(SEXO)

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

# Agrupación de GRUPO_EDAD1 según la tabla de referencia de la actividad
GRUPOS_EDAD = [
    ("Mortalidad neonatal", "< 1 mes", range(0, 5)),
    ("Mortalidad infantil", "1 a 11 meses", range(5, 7)),
    ("Primera infancia", "1 a 4 años", range(7, 9)),
    ("Niñez", "5 a 14 años", range(9, 11)),
    ("Adolescencia", "15 a 19 años", range(11, 12)),
    ("Juventud", "20 a 29 años", range(12, 14)),
    ("Adultez temprana", "30 a 44 años", range(14, 17)),
    ("Adultez intermedia", "45 a 59 años", range(17, 20)),
    ("Vejez", "60 a 84 años", range(20, 25)),
    ("Longevidad / Centenarios", "85 a 100+ años", range(25, 29)),
    ("Edad desconocida", "Sin información", range(29, 30)),
]
MAPA_EDAD = {cod: f"{cat}<br>({rango})" for cat, rango, codigos in GRUPOS_EDAD for cod in codigos}
ORDEN_EDAD = [f"{cat}<br>({rango})" for cat, rango, _ in GRUPOS_EDAD]
mort["CATEGORIA_EDAD"] = mort["GRUPO_EDAD1"].map(MAPA_EDAD)

# ---------------------------------------------------------------------------
# 2. GeoJSON de departamentos (para el mapa coroplético)
# ---------------------------------------------------------------------------
GEOJSON_PATH = DATA / "colombia_departamentos.geojson"
GEOJSON_URL = "https://gist.githubusercontent.com/john-guerra/43c7656821069d00dcbc/raw/Colombia.geo.json"


def cargar_geojson():
    """Usa el archivo local; si no existe, intenta descargarlo una vez."""
    if not GEOJSON_PATH.exists():
        try:
            with urllib.request.urlopen(GEOJSON_URL, timeout=15) as r:
                GEOJSON_PATH.write_bytes(r.read())
        except Exception as e:  # sin internet -> se usa el mapa de burbujas
            print(f"[aviso] No se pudo descargar el GeoJSON ({e}). Se usará mapa de burbujas.")
            return None
    with open(GEOJSON_PATH, encoding="utf-8") as f:
        geo = json.load(f)
    # Detecta qué propiedad del GeoJSON contiene el código DANE del departamento
    # y la normaliza en 'COD_DPTO' (2 dígitos), para que funcione con cualquier fuente.
    codigos = set(deptos["COD_DEPARTAMENTO"])
    props = geo["features"][0]["properties"].keys()
    mejor = max(props, key=lambda k: sum(str(f["properties"].get(k, "")).zfill(2) in codigos
                                          for f in geo["features"]))
    for f in geo["features"]:
        f["properties"]["COD_DPTO"] = str(f["properties"].get(mejor, "")).zfill(2)
    return geo


GEOJSON = cargar_geojson()

# ---------------------------------------------------------------------------
# 3. Estilo
# ---------------------------------------------------------------------------
COLOR_PRIMARIO = "#1f4e79"
COLOR_H, COLOR_M, COLOR_I = "#2a6fb0", "#d1495b", "#9e9e9e"
PLANTILLA = "plotly_white"
FUENTE = dict(family="Segoe UI, Roboto, Arial, sans-serif", size=12)


def estilo(fig, titulo=None, alto=420):
    fig.update_layout(
        template=PLANTILLA, font=FUENTE, height=alto,
        margin=dict(l=10, r=10, t=50 if titulo else 20, b=10),
        title=dict(text=titulo, x=0.01, font=dict(size=15)) if titulo else None,
    )
    return fig


def tarjeta(titulo, hijos, ancho="mitad"):
    return html.Div(className=f"tarjeta {ancho}", children=[html.H3(titulo), *hijos])


def filtrar(depto, sexo):
    df = mort
    if depto and depto != "TODOS":
        df = df[df["COD_DEPARTAMENTO"] == depto]
    if sexo and sexo != 0:
        df = df[df["SEXO"] == sexo]
    return df


# ---------------------------------------------------------------------------
# 4. Layout
# ---------------------------------------------------------------------------
opciones_depto = [{"label": "Todo el país", "value": "TODOS"}] + [
    {"label": r.DEPARTAMENTO.title(), "value": r.COD_DEPARTAMENTO}
    for r in deptos.sort_values("DEPARTAMENTO").itertuples()
]

app = Dash(__name__, title="Mortalidad Colombia 2019")
server = app.server  # <- lo usa gunicorn en el despliegue

app.layout = html.Div(className="contenedor", children=[
    html.Header(className="encabezado", children=[
        html.H1("Mortalidad en Colombia · 2019"),
        html.P("Defunciones no fetales registradas por el DANE (Estadísticas Vitales). "
               "Use los filtros para explorar los datos por departamento y sexo."),
    ]),

    html.Div(className="filtros", children=[
        html.Div([html.Label("Departamento"),
                  dcc.Dropdown(id="f-depto", options=opciones_depto, value="TODOS", clearable=False)]),
        html.Div([html.Label("Sexo"),
                  dcc.RadioItems(id="f-sexo", inline=True, value=0,
                                 options=[{"label": "Todos", "value": 0},
                                          {"label": "Hombres", "value": 1},
                                          {"label": "Mujeres", "value": 2}])]),
    ]),

    html.Div(id="kpis", className="kpis"),

    html.Div(className="rejilla", children=[
        tarjeta("Total de muertes por departamento", [
            html.P("El mapa siempre muestra todo el país (responde al filtro de sexo).", className="nota"),
            dcc.Graph(id="g-mapa")], "mitad"),
        tarjeta("Total de muertes por mes", [dcc.Graph(id="g-lineas")], "mitad"),

        tarjeta("Las 5 ciudades más violentas (homicidios X95)", [
            html.P("Agresión con disparo de armas de fuego (CIE-10 X950–X959, incluye casos no especificados).",
                   className="nota"),
            dcc.Graph(id="g-violentas")], "mitad"),
        tarjeta("Las 10 ciudades con menor mortalidad", [
            dcc.RadioItems(id="f-universo", inline=True, value="capitales", className="nota",
                           options=[{"label": "Capitales de departamento", "value": "capitales"},
                                    {"label": "Todos los municipios", "value": "todos"}]),
            dcc.Graph(id="g-menor")], "mitad"),

        tarjeta("Las 10 principales causas de muerte", [html.Div(id="t-causas")], "completo"),

        tarjeta("Muertes por sexo en cada departamento", [
            html.P("El gráfico siempre muestra todos los departamentos.", className="nota"),
            dcc.Graph(id="g-sexo")], "completo"),

        tarjeta("Distribución de muertes por ciclo de vida (GRUPO_EDAD1)", [dcc.Graph(id="g-edad")], "completo"),
    ]),

    html.Footer("Fuente: DANE – Estadísticas Vitales 2019 · Elaborado con Python, Plotly y Dash"),
])


# ---------------------------------------------------------------------------
# 5. Callbacks
# ---------------------------------------------------------------------------
@app.callback(Output("kpis", "children"), Input("f-depto", "value"), Input("f-sexo", "value"))
def kpis(depto, sexo):
    df = filtrar(depto, sexo)
    hom = df["COD_MUERTE"].str.startswith("X95").sum()
    mes_max = df.groupby("MES").size()
    datos = [
        ("Total de muertes", f"{len(df):,}".replace(",", ".")),
        ("Hombres / Mujeres", f"{(df.SEXO == 1).mean():.0%} / {(df.SEXO == 2).mean():.0%}" if len(df) else "–"),
        ("Homicidios con arma de fuego", f"{hom:,}".replace(",", ".")),
        ("Mes con más muertes", MESES[mes_max.idxmax() - 1] if len(mes_max) else "–"),
    ]
    return [html.Div(className="kpi", children=[html.Span(v, className="valor"), html.Span(t)]) for t, v in datos]


@app.callback(Output("g-mapa", "figure"), Input("f-sexo", "value"))
def mapa(sexo):
    df = filtrar("TODOS", sexo)
    tot = df.groupby(["COD_DEPARTAMENTO", "DEPARTAMENTO"], as_index=False).size().rename(columns={"size": "MUERTES"})
    centro = dict(lat=4.6, lon=-73.5)
    if GEOJSON:
        fig = px.choropleth_mapbox(tot, geojson=GEOJSON, locations="COD_DEPARTAMENTO",
                                   featureidkey="properties.COD_DPTO", color="MUERTES",
                                   hover_name="DEPARTAMENTO", color_continuous_scale="Reds",
                                   mapbox_style="carto-positron", center=centro, zoom=4.1,
                                   opacity=0.85, labels={"MUERTES": "Muertes"})
        fig.update_traces(hovertemplate="<b>%{hovertext}</b><br>Muertes: %{z:,}<extra></extra>")
    else:  # Respaldo: burbujas en el centroide de cada departamento
        tot = tot.merge(centroides, on="COD_DEPARTAMENTO")
        fig = px.scatter_mapbox(tot, lat="LAT", lon="LON", size="MUERTES", color="MUERTES",
                                hover_name="DEPARTAMENTO", color_continuous_scale="Reds",
                                size_max=45, mapbox_style="carto-positron", center=centro,
                                zoom=4.1, labels={"MUERTES": "Muertes"})
        fig.update_traces(hovertemplate="<b>%{hovertext}</b><br>Muertes: %{marker.color:,}<extra></extra>")
    return estilo(fig, alto=460)


@app.callback(Output("g-lineas", "figure"), Input("f-depto", "value"), Input("f-sexo", "value"))
def lineas(depto, sexo):
    df = filtrar(depto, sexo)
    s = df.groupby("MES").size().reindex(range(1, 13), fill_value=0).reset_index(name="MUERTES")
    s["MES_TXT"] = [MESES[m - 1] for m in s["MES"]]
    fig = px.line(s, x="MES_TXT", y="MUERTES", markers=True, labels={"MES_TXT": "Mes", "MUERTES": "Muertes"})
    fig.update_traces(line=dict(color=COLOR_PRIMARIO, width=3), marker=dict(size=8),
                      hovertemplate="%{x}: %{y:,} muertes<extra></extra>")
    prom = s["MUERTES"].mean()
    fig.add_hline(y=prom, line_dash="dot", line_color="#888",
                  annotation_text=f"Promedio: {prom:,.0f}", annotation_position="bottom right")
    return estilo(fig, alto=460)


@app.callback(Output("g-violentas", "figure"), Input("f-depto", "value"), Input("f-sexo", "value"))
def violentas(depto, sexo):
    df = filtrar(depto, sexo)
    h = (df[df["COD_MUERTE"].str.startswith("X95")].groupby("CIUDAD").size()
         .nlargest(5).sort_values().reset_index(name="HOMICIDIOS"))
    fig = px.bar(h, x="HOMICIDIOS", y="CIUDAD", orientation="h", text="HOMICIDIOS",
                 labels={"HOMICIDIOS": "Homicidios por arma de fuego", "CIUDAD": ""})
    fig.update_traces(marker_color="#b22222", textposition="outside", cliponaxis=False,
                      hovertemplate="%{y}: %{x:,} homicidios<extra></extra>")
    return estilo(fig, alto=400)


@app.callback(Output("g-menor", "figure"),
              Input("f-depto", "value"), Input("f-sexo", "value"), Input("f-universo", "value"))
def menor_mortalidad(depto, sexo, universo):
    df = filtrar(depto, sexo)
    if universo == "capitales":
        df = df[df["ES_CAPITAL"]]
    m = (df.groupby("CIUDAD").size().reset_index(name="MUERTES")
         .sort_values(["MUERTES", "CIUDAD"]).head(10))
    fig = px.pie(m, names="CIUDAD", values="MUERTES", hole=0.35,
                 color_discrete_sequence=px.colors.qualitative.Set3)
    fig.update_traces(textinfo="value", hovertemplate="%{label}<br>%{value:,} muertes<extra></extra>")
    fig.update_layout(legend=dict(font=dict(size=11)))
    return estilo(fig, alto=400)


@app.callback(Output("t-causas", "children"), Input("f-depto", "value"), Input("f-sexo", "value"))
def tabla_causas(depto, sexo):
    df = filtrar(depto, sexo)
    t = (df.groupby("COD_MUERTE").size().nlargest(10).reset_index(name="TOTAL")
         .merge(causas, on="COD_MUERTE", how="left"))
    t.insert(0, "#", range(1, len(t) + 1))
    t["PORCENTAJE"] = (t["TOTAL"] / len(df) * 100).round(2) if len(df) else 0
    t = t[["#", "COD_MUERTE", "DESCRIPCION", "TOTAL", "PORCENTAJE"]]
    return dash_table.DataTable(
        data=t.to_dict("records"),
        columns=[{"name": "#", "id": "#"},
                 {"name": "Código CIE-10", "id": "COD_MUERTE"},
                 {"name": "Causa de muerte", "id": "DESCRIPCION"},
                 {"name": "Total de casos", "id": "TOTAL", "type": "numeric",
                  "format": dash_table.FormatTemplate.Format(group=",")},
                 {"name": "% del total", "id": "PORCENTAJE", "type": "numeric"}],
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": COLOR_PRIMARIO, "color": "white", "fontWeight": "bold"},
        style_cell={"fontFamily": FUENTE["family"], "fontSize": 13, "padding": "8px",
                    "textAlign": "left", "whiteSpace": "normal", "height": "auto"},
        style_cell_conditional=[{"if": {"column_id": c}, "textAlign": "right"}
                                for c in ["TOTAL", "PORCENTAJE", "#"]],
        style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#f4f7fb"}],
    )


@app.callback(Output("g-sexo", "figure"), Input("f-depto", "value"))
def sexo_departamento(_):
    s = mort.groupby(["DEPARTAMENTO", "SEXO_TXT"]).size().reset_index(name="MUERTES")
    orden = s.groupby("DEPARTAMENTO")["MUERTES"].sum().sort_values(ascending=False).index.tolist()
    fig = px.bar(s, x="DEPARTAMENTO", y="MUERTES", color="SEXO_TXT", barmode="stack",
                 category_orders={"DEPARTAMENTO": orden, "SEXO_TXT": ["Hombre", "Mujer", "Indeterminado"]},
                 color_discrete_map={"Hombre": COLOR_H, "Mujer": COLOR_M, "Indeterminado": COLOR_I},
                 labels={"DEPARTAMENTO": "", "MUERTES": "Muertes", "SEXO_TXT": "Sexo"})
    fig.update_traces(hovertemplate="%{x}<br>%{fullData.name}: %{y:,}<extra></extra>")
    fig.update_layout(xaxis_tickangle=-45, legend=dict(orientation="h", y=1.08, x=1, xanchor="right"))
    return estilo(fig, alto=520)


@app.callback(Output("g-edad", "figure"), Input("f-depto", "value"), Input("f-sexo", "value"))
def histograma_edad(depto, sexo):
    df = filtrar(depto, sexo)
    fig = px.histogram(df, x="CATEGORIA_EDAD", category_orders={"CATEGORIA_EDAD": ORDEN_EDAD},
                       labels={"CATEGORIA_EDAD": "Ciclo de vida"})
    fig.update_traces(marker_color=COLOR_PRIMARIO, marker_line_color="white", marker_line_width=1,
                      hovertemplate="%{x}<br>%{y:,} muertes<extra></extra>")
    fig.update_layout(yaxis_title="Número de muertes", bargap=0.05)
    return estilo(fig, alto=480)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    app.run(host="0.0.0.0", port=port, debug=False)
