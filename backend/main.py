"""
Backend de La Quiniela Mundial Hub
-----------------------------------
Misma lógica de cálculo que la app de Streamlit (puntos, posiciones por grupo,
bracket, podio/premios), expuesta como API para que el frontend (HTML/CSS/JS
con diseño propio) la consuma por fetch().

Correr local:
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

La API queda en http://localhost:8000 y el frontend (carpeta ../frontend)
le hace fetch a esa URL.
"""

import os
import json
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ----------------------------------------------------------------------------
# CONFIGURACIÓN
# ----------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL_FILE = os.path.join(SCRIPT_DIR, "apuestas_extraidas.xlsx")
RESULTS_FILE = os.path.join(SCRIPT_DIR, "resultados_reales.json")
FINAL_FILE = os.path.join(SCRIPT_DIR, "resultado_final.json")
BRACKET_FILE = os.path.join(SCRIPT_DIR, "bracket_eliminatoria.json")
HISTORIAL_FILE = os.path.join(SCRIPT_DIR, "historial_cambios.json")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "polla2026")

# ----------------------------------------------------------------------------
# RESPALDO PERMANENTE EN HUGGING FACE (mismo patrón que la versión Streamlit)
# ----------------------------------------------------------------------------
try:
    from huggingface_hub import HfApi, hf_hub_download
    HF_HUB_DISPONIBLE = True
except Exception:
    HF_HUB_DISPONIBLE = False


def config_respaldo_hf():
    token = os.environ.get("HF_TOKEN")
    repo_id = os.environ.get("HF_REPO_ID")
    repo_type = os.environ.get("HF_REPO_TYPE", "dataset")
    return token, repo_id, repo_type


def respaldo_hf_activo():
    token, repo_id, _ = config_respaldo_hf()
    return HF_HUB_DISPONIBLE and bool(token) and bool(repo_id)


def subir_a_hf(ruta_local, nombre_archivo):
    if not respaldo_hf_activo():
        return
    token, repo_id, repo_type = config_respaldo_hf()
    try:
        api = HfApi(token=token)
        api.upload_file(
            path_or_fileobj=ruta_local,
            path_in_repo=nombre_archivo,
            repo_id=repo_id,
            repo_type=repo_type,
            commit_message=f"Actualizar {nombre_archivo}",
        )
    except Exception as e:
        print(f"[respaldo HF] Error subiendo {nombre_archivo}: {e}")


def descargar_de_hf(nombre_archivo, destino_local):
    if not respaldo_hf_activo():
        return
    token, repo_id, repo_type = config_respaldo_hf()
    try:
        ruta = hf_hub_download(repo_id=repo_id, filename=nombre_archivo, repo_type=repo_type, token=token)
        with open(ruta, "r", encoding="utf-8") as f_src, open(destino_local, "w", encoding="utf-8") as f_dst:
            f_dst.write(f_src.read())
    except Exception:
        pass


# Al arrancar el servidor, recuperamos lo último respaldado en HF (si está configurado)
if respaldo_hf_activo():
    descargar_de_hf("resultados_reales.json", RESULTS_FILE)
    descargar_de_hf("resultado_final.json", FINAL_FILE)
    descargar_de_hf("historial_cambios.json", HISTORIAL_FILE)
    descargar_de_hf("bracket_eliminatoria.json", BRACKET_FILE)

app = FastAPI(title="La Quiniela Mundial Hub - API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # en producción, restringe a tu dominio del frontend
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------------------------
# CARGA DEL EXCEL (idéntico a la versión Streamlit, sin st.cache_data:
# aquí cacheamos a mano en una variable global, se recarga al reiniciar el server)
# ----------------------------------------------------------------------------
_cache = {"preds": None, "podio": None, "premios": None, "partidos": None}


def cargar_predicciones():
    if not os.path.exists(EXCEL_FILE):
        return None, None, None
    preds = pd.read_excel(EXCEL_FILE, sheet_name="Predicciones partidos")
    try:
        podio = pd.read_excel(EXCEL_FILE, sheet_name="Podio final")
    except Exception:
        podio = pd.DataFrame()
    try:
        premios = pd.read_excel(EXCEL_FILE, sheet_name="Premios individuales")
    except Exception:
        premios = pd.DataFrame()
    return preds, podio, premios


def _parsear_fecha(f):
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(f), fmt)
        except Exception:
            continue
    return None


def get_datos():
    """Carga (con cache en memoria) preds_df, podio_df, premios_df, partidos_df."""
    if _cache["preds"] is None:
        preds, podio, premios = cargar_predicciones()
        if preds is None:
            raise HTTPException(
                status_code=500,
                detail=f"No encuentro apuestas_extraidas.xlsx en {SCRIPT_DIR}. Súbelo junto a main.py.",
            )
        conteo = (
            preds.groupby(["Equipo local", "Equipo visitante", "Grupo", "Fecha"])
            .size().reset_index(name="n_personas")
        )
        umbral = preds["Persona"].nunique() * 0.5
        partidos = (
            conteo[conteo["n_personas"] >= umbral]
            [["Equipo local", "Equipo visitante", "Grupo", "Fecha"]]
            .reset_index(drop=True)
        )
        partidos["Partido"] = partidos["Equipo local"] + " vs " + partidos["Equipo visitante"] + " (" + partidos["Fecha"] + ")"
        partidos["_fecha_dt"] = partidos["Fecha"].apply(_parsear_fecha)

        _cache["preds"] = preds
        _cache["podio"] = podio
        _cache["premios"] = premios
        _cache["partidos"] = partidos

    return _cache["preds"], _cache["podio"], _cache["premios"], _cache["partidos"]


# ----------------------------------------------------------------------------
# PERSISTENCIA EN JSON (idéntico patrón que la versión Streamlit)
# ----------------------------------------------------------------------------
def _cargar_json(ruta, default):
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def _guardar_json(ruta, data):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cargar_resultados():
    return _cargar_json(RESULTS_FILE, {})


def guardar_resultados(data):
    _guardar_json(RESULTS_FILE, data)
    subir_a_hf(RESULTS_FILE, "resultados_reales.json")


def cargar_resultado_final():
    return _cargar_json(FINAL_FILE, {})


def guardar_resultado_final(data):
    _guardar_json(FINAL_FILE, data)
    subir_a_hf(FINAL_FILE, "resultado_final.json")


def cargar_bracket():
    return _cargar_json(BRACKET_FILE, {})


def guardar_bracket(data):
    _guardar_json(BRACKET_FILE, data)
    subir_a_hf(BRACKET_FILE, "bracket_eliminatoria.json")


def registrar_historial(accion):
    historial = _cargar_json(HISTORIAL_FILE, [])
    historial.insert(0, {"fecha": datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "accion": accion})
    historial = historial[:300]
    _guardar_json(HISTORIAL_FILE, historial)
    subir_a_hf(HISTORIAL_FILE, "historial_cambios.json")


# ----------------------------------------------------------------------------
# LÓGICA DE PUNTOS (idéntica a la versión Streamlit, función por función)
# ----------------------------------------------------------------------------
def calcular_categoria(gl_pred, gv_pred, gl_real, gv_real):
    if gl_pred == gl_real and gv_pred == gv_real:
        return "Marcador exacto", 6
    resultado_pred = "L" if gl_pred > gv_pred else ("V" if gl_pred < gv_pred else "E")
    resultado_real = "L" if gl_real > gv_real else ("V" if gl_real < gv_real else "E")
    if resultado_pred == resultado_real:
        return "Ganador/Empate sin exacto", 3
    if gl_pred == gl_real or gv_pred == gv_real:
        return "Goles de un equipo", 1
    return "Fallo", 0


def calcular_puntos_podio(pred_row, real):
    if not real:
        return 0, False
    pred = [str(pred_row.get(c, "")).strip().lower() for c in ["Campeón", "Subcampeón", "Tercero", "Cuarto"]]
    reales = [str(real.get(c, "")).strip().lower() for c in ["campeon", "subcampeon", "tercero", "cuarto"]]
    if not all(reales):
        return 0, False
    if pred == reales:
        return 15, True
    if set(pred) == set(reales):
        return 8, True
    return 0, False


def calcular_puntos_premios(pred_row, real):
    if not real:
        return 0, 0
    pts = 0
    aciertos = 0
    pares = [("Balón de oro", "balon"), ("Bota de oro", "bota"), ("Guante de oro", "guante")]
    for col, clave in pares:
        pred_val = str(pred_row.get(col, "")).strip().lower()
        real_val = str(real.get(clave, "")).strip().lower()
        if real_val and pred_val == real_val:
            pts += 15
            aciertos += 1
    return pts, aciertos


def calcular_tabla(preds_df, podio_df, premios_df, resultados_reales, resultado_final):
    filas = []
    podio_dict = podio_df.set_index("Persona").to_dict(orient="index") if not podio_df.empty else {}
    premios_dict = premios_df.set_index("Persona").to_dict(orient="index") if not premios_df.empty else {}

    for persona, grupo_df in preds_df.groupby("Persona"):
        pj = pg = pe = pp = pts = 0
        for _, fila in grupo_df.iterrows():
            clave = f"{fila['Equipo local']}|{fila['Equipo visitante']}|{fila['Fecha']}"
            if clave not in resultados_reales:
                continue
            real = resultados_reales[clave]
            pj += 1
            categoria, puntos = calcular_categoria(
                int(fila["Goles local"]), int(fila["Goles visitante"]),
                int(real["gl"]), int(real["gv"])
            )
            pts += puntos
            if categoria == "Fallo":
                pp += 1
            elif categoria == "Goles de un equipo":
                pe += 1
            else:
                pg += 1

        pts_podio = 0
        if persona in podio_dict:
            pts_podio, _ = calcular_puntos_podio(podio_dict[persona], resultado_final.get("podio"))
        pts += pts_podio

        pts_premios = 0
        if persona in premios_dict:
            pts_premios, _ = calcular_puntos_premios(premios_dict[persona], resultado_final.get("premios"))
        pts += pts_premios

        filas.append({"usuario": persona, "pj": pj, "pg": pg, "pe": pe, "pp": pp,
                       "pts_podio": pts_podio, "pts_premios": pts_premios, "pts": pts})

    tabla = sorted(filas, key=lambda r: r["pts"], reverse=True)
    for i, fila in enumerate(tabla, start=1):
        fila["pos"] = i
    return tabla


def calcular_posiciones_grupo(partidos_df, resultados_reales, grupo):
    partidos_grupo = partidos_df[partidos_df["Grupo"] == grupo]
    equipos = sorted(set(partidos_grupo["Equipo local"]) | set(partidos_grupo["Equipo visitante"]))
    stats = {e: {"pj": 0, "pg": 0, "pe": 0, "pp": 0, "gf": 0, "gc": 0, "pts": 0} for e in equipos}

    for _, fila in partidos_grupo.iterrows():
        clave = f"{fila['Equipo local']}|{fila['Equipo visitante']}|{fila['Fecha']}"
        if clave not in resultados_reales:
            continue
        real = resultados_reales[clave]
        gl, gv = int(real["gl"]), int(real["gv"])
        local, visit = fila["Equipo local"], fila["Equipo visitante"]

        stats[local]["pj"] += 1
        stats[visit]["pj"] += 1
        stats[local]["gf"] += gl
        stats[local]["gc"] += gv
        stats[visit]["gf"] += gv
        stats[visit]["gc"] += gl

        if gl > gv:
            stats[local]["pg"] += 1
            stats[local]["pts"] += 3
            stats[visit]["pp"] += 1
        elif gl < gv:
            stats[visit]["pg"] += 1
            stats[visit]["pts"] += 3
            stats[local]["pp"] += 1
        else:
            stats[local]["pe"] += 1
            stats[visit]["pe"] += 1
            stats[local]["pts"] += 1
            stats[visit]["pts"] += 1

    filas = []
    for equipo, s in stats.items():
        dg = s["gf"] - s["gc"]
        filas.append({"equipo": equipo, **s, "dg": dg})

    filas.sort(key=lambda r: (r["pts"], r["dg"], r["gf"]), reverse=True)
    for i, fila in enumerate(filas, start=1):
        fila["pos"] = i
    return filas


# ----------------------------------------------------------------------------
# MODELOS DE ENTRADA (admin)
# ----------------------------------------------------------------------------
class ResultadoPartido(BaseModel):
    equipo_local: str
    equipo_visitante: str
    fecha: str
    gl: int
    gv: int


class ResultadoFinal(BaseModel):
    campeon: str = ""
    subcampeon: str = ""
    tercero: str = ""
    cuarto: str = ""
    balon: str = ""
    bota: str = ""
    guante: str = ""


class GanadorBracket(BaseModel):
    match_id: str
    ganador: str  # "A" o "B" -> qué slot gana (evita ambigüedad de nombres repetidos)


# ----------------------------------------------------------------------------
# ESTRUCTURA OFICIAL DEL BRACKET (Mundial 2026, cableado real FIFA, partidos 73-104)
# ----------------------------------------------------------------------------
CABLEADO_BRACKET = {
    "74": ("89", "A"), "77": ("89", "B"),
    "73": ("90", "A"), "75": ("90", "B"),
    "83": ("93", "A"), "84": ("93", "B"),
    "81": ("94", "A"), "82": ("94", "B"),
    "76": ("91", "A"), "78": ("91", "B"),
    "79": ("92", "A"), "80": ("92", "B"),
    "86": ("95", "A"), "88": ("95", "B"),
    "85": ("96", "A"), "87": ("96", "B"),
    "89": ("97", "A"), "90": ("97", "B"),
    "93": ("98", "A"), "94": ("98", "B"),
    "91": ("99", "A"), "92": ("99", "B"),
    "95": ("100", "A"), "96": ("100", "B"),
    "97": ("101", "A"), "98": ("101", "B"),
    "99": ("102", "A"), "100": ("102", "B"),
    "101": ("104", "A"), "102": ("104", "B"),
}
PERDEDOR_A_BRACKET = {"101": ("103", "A"), "102": ("103", "B")}

PARTIDOS_R32_IZQ = ["73", "74", "75", "77", "81", "82", "83", "84"]
PARTIDOS_R32_DER = ["76", "78", "79", "80", "85", "86", "87", "88"]

RONDA_DE_PARTIDO = {}
for _id in PARTIDOS_R32_IZQ + PARTIDOS_R32_DER:
    RONDA_DE_PARTIDO[_id] = "16avos"
for _id in ["89", "90", "91", "92", "93", "94", "95", "96"]:
    RONDA_DE_PARTIDO[_id] = "8avos"
for _id in ["97", "98", "99", "100"]:
    RONDA_DE_PARTIDO[_id] = "4tos"
for _id in ["101", "102"]:
    RONDA_DE_PARTIDO[_id] = "Semis"
RONDA_DE_PARTIDO["104"] = "Final"
RONDA_DE_PARTIDO["103"] = "3er puesto"


def bracket_vacio():
    todos = list(RONDA_DE_PARTIDO.keys())
    m = {}
    for pid in todos:
        siguiente = CABLEADO_BRACKET.get(pid)
        perdedor = PERDEDOR_A_BRACKET.get(pid)
        m[pid] = {
            "id": pid, "ronda": RONDA_DE_PARTIDO[pid],
            "teamA": None, "teamB": None, "winner": None,
            "nextId": siguiente[0] if siguiente else None,
            "nextSlot": siguiente[1] if siguiente else None,
            "loserNextId": perdedor[0] if perdedor else None,
            "loserNextSlot": perdedor[1] if perdedor else None,
        }
    return m


def bracket_limpiar_descendencia(bracket, match_id):
    m = bracket.get(match_id)
    if not m or not m.get("winner"):
        return
    if m["nextId"]:
        hijo = bracket[m["nextId"]]
        slot_key = f"team{m['nextSlot']}"
        if hijo.get(slot_key) and hijo[slot_key]["label"] == m["winner"]["label"]:
            if hijo.get("winner"):
                bracket_limpiar_descendencia(bracket, hijo["id"])
            hijo[slot_key] = None
    if m["loserNextId"]:
        caja = bracket[m["loserNextId"]]
        slot_key = f"team{m['loserNextSlot']}"
        if caja.get(slot_key):
            if caja.get("winner"):
                bracket_limpiar_descendencia(bracket, caja["id"])
            caja[slot_key] = None


def verificar_admin(x_admin_password: Optional[str] = Header(None)):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Contraseña de admin inválida")
    return True


# ----------------------------------------------------------------------------
# ENDPOINTS PÚBLICOS (lectura)
# ----------------------------------------------------------------------------
@app.get("/api/grupos")
def listar_grupos():
    _, _, _, partidos = get_datos()
    return sorted(partidos["Grupo"].dropna().unique().tolist())


@app.get("/api/grupos/{grupo}/posiciones")
def posiciones_grupo(grupo: str):
    _, _, _, partidos = get_datos()
    resultados_reales = cargar_resultados()
    return calcular_posiciones_grupo(partidos, resultados_reales, grupo)


@app.get("/api/partidos")
def listar_partidos():
    _, _, _, partidos = get_datos()
    resultados_reales = cargar_resultados()
    filas = partidos.to_dict(orient="records")
    for f in filas:
        clave = f"{f['Equipo local']}|{f['Equipo visitante']}|{f['Fecha']}"
        f["tiene_resultado"] = clave in resultados_reales
        f.pop("_fecha_dt", None)
    return filas


@app.get("/api/posiciones")
def tabla_posiciones():
    preds_df, podio_df, premios_df, _ = get_datos()
    resultados_reales = cargar_resultados()
    resultado_final = cargar_resultado_final()
    return calcular_tabla(preds_df, podio_df, premios_df, resultados_reales, resultado_final)


@app.get("/api/pronosticos")
def pronosticos(equipo_local: Optional[str] = None, equipo_visitante: Optional[str] = None, fecha: Optional[str] = None):
    preds_df, _, _, _ = get_datos()
    vista = preds_df
    if equipo_local and equipo_visitante and fecha:
        vista = vista[
            (vista["Equipo local"] == equipo_local) &
            (vista["Equipo visitante"] == equipo_visitante) &
            (vista["Fecha"] == fecha)
        ]
    return vista[["Persona", "Equipo local", "Goles local", "Goles visitante", "Equipo visitante", "Fecha"]].to_dict(orient="records")


@app.get("/api/podio")
def podio_y_premios():
    _, podio_df, premios_df, _ = get_datos()
    return {
        "podio": podio_df.to_dict(orient="records") if not podio_df.empty else [],
        "premios": premios_df.to_dict(orient="records") if not premios_df.empty else [],
    }


@app.get("/api/resultados")
def resultados_reales_actuales():
    return cargar_resultados()


@app.get("/api/bracket")
def bracket_actual():
    bracket = cargar_bracket()
    if not bracket:
        return {}
    return bracket


@app.post("/api/admin/bracket/inicializar")
def bracket_inicializar(equipos: dict, x_admin_password: Optional[str] = Header(None)):
    """
    equipos: { "73": [{"label":"ECU","code":"ec"}, {"label":"PAR","code":"py"}], "74": [...], ... }
    Debe incluir los 16 partidos de Ronda de 32 (73-88).
    """
    verificar_admin(x_admin_password)
    bracket = bracket_vacio()
    for pid, equipo_par in equipos.items():
        if pid in bracket and len(equipo_par) == 2:
            bracket[pid]["teamA"] = equipo_par[0]
            bracket[pid]["teamB"] = equipo_par[1]
    guardar_bracket(bracket)
    registrar_historial("Bracket inicializado con los 32 equipos de la Ronda de 32.")
    return bracket


@app.post("/api/admin/bracket/ganador")
def bracket_set_ganador(g: GanadorBracket, x_admin_password: Optional[str] = Header(None)):
    """g.ganador debe ser 'A' o 'B' (qué slot del partido avanza)."""
    verificar_admin(x_admin_password)
    bracket = cargar_bracket()
    if g.match_id not in bracket:
        raise HTTPException(status_code=404, detail="Partido no encontrado en el bracket")
    m = bracket[g.match_id]
    if g.ganador not in ("A", "B") or not m["teamA"] or not m["teamB"]:
        raise HTTPException(status_code=400, detail="Partido incompleto o slot inválido")

    equipo_ganador = m[f"team{g.ganador}"]
    equipo_perdedor = m["teamB"] if g.ganador == "A" else m["teamA"]

    if m.get("winner") and m["winner"]["label"] == equipo_ganador["label"]:
        # clic sobre el mismo ganador -> deshacer
        bracket_limpiar_descendencia(bracket, g.match_id)
        m["winner"] = None
    else:
        if m.get("winner"):
            bracket_limpiar_descendencia(bracket, g.match_id)
        m["winner"] = equipo_ganador
        if m["nextId"]:
            bracket[m["nextId"]][f"team{m['nextSlot']}"] = equipo_ganador
        if m["loserNextId"]:
            bracket[m["loserNextId"]][f"team{m['loserNextSlot']}"] = equipo_perdedor

    guardar_bracket(bracket)
    registrar_historial(f"Bracket: {g.match_id} -> ganador {equipo_ganador['label'] if m['winner'] else 'deshecho'}")
    return bracket


@app.delete("/api/admin/bracket")
def bracket_reiniciar(x_admin_password: Optional[str] = Header(None)):
    verificar_admin(x_admin_password)
    guardar_bracket({})
    registrar_historial("Se reinició por completo el bracket de eliminatoria.")
    return {"ok": True}


@app.get("/api/resultado-final")
def resultado_final_actual():
    return cargar_resultado_final()


@app.get("/api/historial")
def historial_cambios():
    return _cargar_json(HISTORIAL_FILE, [])


# ----------------------------------------------------------------------------
# ENDPOINTS DE ADMIN (escritura, requieren header X-Admin-Password)
# ----------------------------------------------------------------------------
@app.post("/api/admin/login")
def admin_login(password: str):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    return {"ok": True}


@app.post("/api/admin/resultado")
def guardar_resultado_partido(r: ResultadoPartido, ok: bool = None, _=None, x_admin_password: Optional[str] = Header(None)):
    verificar_admin(x_admin_password)
    resultados = cargar_resultados()
    clave = f"{r.equipo_local}|{r.equipo_visitante}|{r.fecha}"
    resultados[clave] = {
        "gl": r.gl, "gv": r.gv,
        "equipo_local": r.equipo_local, "equipo_visitante": r.equipo_visitante, "fecha": r.fecha,
    }
    guardar_resultados(resultados)
    registrar_historial(f"Resultado registrado: {r.equipo_local} {r.gl} - {r.gv} {r.equipo_visitante} ({r.fecha})")
    return {"ok": True, "resultados": resultados}


@app.delete("/api/admin/resultados")
def borrar_resultados(x_admin_password: Optional[str] = Header(None)):
    verificar_admin(x_admin_password)
    guardar_resultados({})
    registrar_historial("Se borraron TODOS los resultados registrados.")
    return {"ok": True}


@app.post("/api/admin/resultado-final")
def guardar_final(rf: ResultadoFinal, x_admin_password: Optional[str] = Header(None)):
    verificar_admin(x_admin_password)
    nuevo = {
        "podio": {"campeon": rf.campeon, "subcampeon": rf.subcampeon, "tercero": rf.tercero, "cuarto": rf.cuarto},
        "premios": {"balon": rf.balon, "bota": rf.bota, "guante": rf.guante},
    }
    guardar_resultado_final(nuevo)
    registrar_historial(f"Resultado final actualizado: Campeón={rf.campeon}, Subcampeón={rf.subcampeon}")
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/configuracion/reglamento")
def reglamento():
    return {
        "por_partido": [
            {"icono": "🎯", "regla": "Marcador exacto", "puntos": 6},
            {"icono": "✅", "regla": "Ganador o empate correcto (sin marcador exacto)", "puntos": 3},
            {"icono": "🔢", "regla": "Acertó los goles de uno de los dos equipos", "puntos": 1},
            {"icono": "❌", "regla": "No acertó nada", "puntos": 0},
        ],
        "podio": [
            {"icono": "🏆", "regla": "Campeón, Subcampeón, 3° y 4° en orden exacto", "puntos": 15},
            {"icono": "🔀", "regla": "Los mismos 4 equipos, en cualquier orden", "puntos": 8},
        ],
        "premios": [
            {"icono": "🥇", "regla": "Balón / Bota / Guante de oro correcto (cada uno)", "puntos": 15},
        ],
    }
