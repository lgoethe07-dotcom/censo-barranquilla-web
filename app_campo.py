import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import re
import os
from datetime import datetime
from difflib import SequenceMatcher

# --- 0. CONFIGURACIÓN DE RUTAS ---
# Ajusta esta ruta a la ubicación real de tus fotos en tu PC
CARPETA_FOTOS = r"C:\Censo_Barranquilla\Fotos" 

# --- 1. CONFIGURACIÓN Y ESTILOS ---
st.set_page_config(page_title="Gestión de Precenso - Barranquilla", layout="wide")

st.markdown("""
    <style>
    .block-container {padding-top: 1rem; padding-bottom: 0rem;}
    .stMetric { background-color: #f0f2f6; padding: 5px 10px; border-radius: 5px; }
    .section-header { 
        background-color: #e1e4e8; 
        padding: 5px; 
        border-radius: 3px; 
        font-weight: bold; 
        margin-bottom: 10px;
        color: #1f2d3d;
    }
    .map-legend {
        position: absolute; bottom: 30px; left: 10px; z-index: 100;
        background-color: rgba(255, 255, 255, 0.8);
        padding: 10px; border-radius: 5px; font-size: 12px;
        border: 1px solid #ccc;
    }
    </style>
    """, unsafe_allow_html=True)

# Memoria de la aplicación
if 'base_campo' not in st.session_state: st.session_state['base_campo'] = []
if 'no_vinculados' not in st.session_state: st.session_state['no_vinculados'] = set()
if 'seleccion_id' not in st.session_state: st.session_state['seleccion_id'] = None
if 'temp_vinc' not in st.session_state: st.session_state['temp_vinc'] = None

# --- FUNCIONES DE APOYO ---
def calcular_similitud(a, b):
    return SequenceMatcher(None, str(a).upper(), str(b).upper()).ratio()

def extraer_via_principal(direccion):
    partes = str(direccion).upper().split()
    return " ".join(partes[:3]) if len(partes) >= 3 else str(direccion).upper()

def corregir_coordenada(valor):
    if pd.isna(valor): return np.nan
    s = str(valor).replace('.', '')
    try:
        if s.startswith('-'): return float(s[:3] + "." + s[3:])
        else: return float(s[:2] + "." + s[2:])
    except: return np.nan

def limpiar_nombre_busqueda(nombre):
    patron = r'\b(SAS|S\.A\.S|LTDA|GRUPO|TIENDA|PANADERIA|SOLUCIONES|SERVICIOS|LA|EL|LOS|LAS|DE|DEL)\b'
    nombre_limpio = re.sub(patron, '', str(nombre).upper())
    return [w for w in re.findall(r'\w+', nombre_limpio) if len(w) > 2]

@st.cache_data
def cargar_datos():
    # Rutas de las bases de datos
    df_p = pd.read_csv(r"C:\Censo_Barranquilla\Precenso\BASE_PRECENSO_LISTO.csv", sep=';', encoding='utf-8-sig')
    df_p.columns = df_p.columns.str.strip()
    df_p['ID_INT'] = range(len(df_p))
    df_p['lon'] = df_p['x'].apply(corregir_coordenada)
    df_p['lat'] = df_p['y'].apply(corregir_coordenada)
    
    df_c = pd.read_csv(r"C:\Censo_Barranquilla\data\BASE_CAMARA_COMERCIO.csv", sep=';', encoding='latin-1')
    df_c.columns = df_c.columns.str.strip()
    return df_p, df_c

def buscar_propietario_legal(hijo, df_full):
    nit_hijo = str(hijo.get('numero_identificacion', '')).strip()
    if nit_hijo != "" and nit_hijo != "nan" and nit_hijo != "None":
        return hijo.to_dict(), "Directo"
    f_mat = str(hijo.get('fecha_matricula', ''))
    dir_c = str(hijo.get('direccion_comercial', '')).strip().upper()
    mail = str(hijo.get('correo_comercial', '')).strip().lower()
    ciiu_hijo = str(hijo.get('ciiu', ''))
    padres = df_full[df_full['numero_identificacion'].notna()]
    
    res = padres[(padres['fecha_matricula'].astype(str) == f_mat) & (padres['direccion_comercial'].str.upper() == dir_c) & (padres['correo_comercial'].str.lower() == mail)]
    if not res.empty: return res.iloc[0].to_dict(), "Llave 1 (Matrícula+Dir+Mail)"
    res = padres[(padres['fecha_matricula'].astype(str) == f_mat) & (padres['correo_comercial'].str.lower() == mail)]
    if not res.empty: return res.iloc[0].to_dict(), "Llave 2 (Matrícula+Mail)"
    res = padres[(padres['ciiu'].astype(str) == ciiu_hijo) & (padres['correo_comercial'].str.lower() == mail)]
    if not res.empty: return res.iloc[0].to_dict(), "Llave 3 (CIIU+Mail)"
    res = padres[(padres['direccion_comercial'].str.upper() == dir_c) & (padres['correo_comercial'].str.lower() == mail)]
    if not res.empty: return res.iloc[0].to_dict(), "Llave 4 (Dir+Mail)"
    return None, "No encontrado"

df_pre, df_cc = cargar_datos()

# --- 2. HEADER Y ESTADÍSTICAS ---
st.write("") 
col_t1, col_t2 = st.columns([0.8, 0.2])
with col_t1:
    st.title("🚀 Gestión de Precenso - Barranquilla")
with col_t2:
    st.write("###") 
    if st.button("🔄 Actualizar Bases", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

v_ids = [r['id_encuesta'] for r in st.session_state['base_campo']]
nv_ids = list(st.session_state['no_vinculados'])

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Cámara", f"{len(df_cc):,}")
m2.metric("Total Precenso", len(df_pre))
m3.metric("Vinculados", len(v_ids))
m4.metric("No Vinculados", len(nv_ids))
m5.metric("Pendientes", len(df_pre) - len(v_ids) - len(nv_ids))

st.markdown("---")

# --- 3. PANEL PRINCIPAL ---
col_map, col_audit = st.columns([1.6, 1])

with col_map:
    df_mapa = df_pre.dropna(subset=['lat', 'lon']).copy()
    def asignar_color(row):
        if row['ID_INT'] in v_ids: return [0, 114, 255, 200]
        elif row['ID_INT'] in nv_ids: return [255, 150, 0, 200]
        else: return [40, 167, 69, 160]

    df_mapa['color_dinamico'] = df_mapa.apply(asignar_color, axis=1)
    capa_puntos = pdk.Layer("ScatterplotLayer", df_mapa, get_position='[lon, lat]',
                            get_color='color_dinamico', get_radius=3.5, pickable=True)
    capas = [capa_puntos]
    if st.session_state['seleccion_id'] is not None:
        p_sel = df_pre[df_pre['ID_INT'] == st.session_state['seleccion_id']]
        capas.append(pdk.Layer("ScatterplotLayer", p_sel, get_position='[lon, lat]',
                               get_color='[255, 0, 0, 255]', get_radius=12, stroked=True, filled=False, line_width_min_pixels=2))

    st.pydeck_chart(pdk.Deck(layers=capas, initial_view_state=pdk.ViewState(latitude=11.003, longitude=-74.797, zoom=17),
                            map_style="light", height=480, tooltip={"text": "Local: {nombre_comercial}\nDir: {direccion_comercial}"}))
    
    st.markdown("""<div class="map-legend"><strong>Leyenda:</strong><br><span style="color:rgb(40,167,69)">●</span> Pendiente<br><span style="color:rgb(0,114,255)">●</span> Vinculado<br><span style="color:rgb(255,150,0)">●</span> No Vinculado<br><span style="color:red">○</span> Seleccionado</div>""", unsafe_allow_html=True)

with col_audit:
    st.markdown('<div class="section-header">🔍 BÚSQUEDA Y SELECCIÓN</div>', unsafe_allow_html=True)
    busqueda = st.text_input("Filtrar:", key="busqueda_global", label_visibility="collapsed", placeholder="Buscar establecimiento...")
    df_pendientes = df_pre[~df_pre['ID_INT'].isin(v_ids + nv_ids)]
    df_lista = df_pendientes[df_pendientes['nombre_comercial'].str.contains(busqueda, case=False, na=False)]
    sel = st.selectbox("Lista:", ["- Seleccionar -"] + df_lista['nombre_comercial'].tolist())
    
    if sel != "- Seleccionar -":
        id_n = df_pre[df_pre['nombre_comercial'] == sel]['ID_INT'].values[0]
        if st.session_state['seleccion_id'] != id_n:
            st.session_state['seleccion_id'] = id_n
            st.session_state['temp_vinc'] = None
            st.rerun()

    if st.session_state['seleccion_id'] is not None:
        local = df_pre.iloc[st.session_state['seleccion_id']]
        st.markdown('<div class="section-header">📍 DATOS DEL PRE-CENSO</div>', unsafe_allow_html=True)
        
        # --- SECCIÓN DE FOTO E INFO ---
        c_info, c_foto = st.columns([0.6, 0.4])
        with c_info:
            st.info(f"**Establecimiento:** {local['nombre_comercial']}\n\n**Dir:** {local['direccion_comercial']}")
        
        with c_foto:
            # Limpiamos el nombre del archivo del CSV
            foto_raw = str(local.get('nombre_foto', '')).strip()
            
            if foto_raw and foto_raw.lower() not in ['nan', 'none', '', '0']:
                # Extraemos solo el nombre (ej: 06.png) ignorando rutas previas
                nombre_archivo = os.path.basename(foto_raw)
                ruta_final = os.path.join(CARPETA_FOTOS, nombre_archivo)
                
                if os.path.exists(ruta_final):
                    st.image(ruta_final, use_container_width=True, caption=f"ID: {local.get('ID', 'S/N')}")
                else:
                    st.error("🚫 Foto no hallada")
                    st.caption(f"Buscado en: {nombre_archivo}")
            else:
                st.warning("⚪ Sin foto")
        # ------------------------------

        if st.session_state['temp_vinc'] is None:
            st.markdown('<div class="section-header">🏢 OPCIONES CÁMARA DE COMERCIO</div>', unsafe_allow_html=True)
            palabras = limpiar_nombre_busqueda(local['nombre_comercial'])
            if palabras:
                mascara = np.ones(len(df_cc), dtype=bool)
                for p in palabras: mascara &= df_cc['nombre_comercial'].str.contains(p, case=False, na=False)
                res_cc = df_cc[mascara].head(5).copy()
            else:
                res_cc = df_cc[df_cc['nombre_comercial'].str.contains(local['nombre_comercial'][:5], case=False, na=False)].head(5).copy()
            
            if not res_cc.empty:
                dir_pre_base = extraer_via_principal(local['direccion_comercial'])
                res_cc['sim_nom'] = res_cc['nombre_comercial'].apply(lambda x: calcular_similitud(x, local['nombre_comercial']))
                res_cc['sim_dir'] = res_cc['direccion_comercial'].apply(lambda x: calcular_similitud(extraer_via_principal(x), dir_pre_base))
                res_cc['sim_total'] = (res_cc['sim_nom'] + res_cc['sim_dir']) / 2
                idx_mejor = res_cc['sim_total'].idxmax()

                for i, r in res_cc.iterrows():
                    es_mejor = (i == idx_mejor)
                    bg_color = "#d4edda" if es_mejor else "#f8d7da"
                    border_color = "#28a745" if es_mejor else "#f5c6cb"
                    
                    # MODIFICACIÓN: Mostrar similitud de nombre y dirección por separado
                    st.markdown(f"""
                        <div style="background-color:{bg_color}; border: 2px solid {border_color}; padding: 8px; border-radius: 5px; margin-bottom: 5px;">
                            <strong>{r["nombre_comercial"]}</strong><br>
                            <small>S. Nombre: {r['sim_nom']:.0%} | S. Dirección: {r['sim_dir']:.0%}</small>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    with st.expander(f"Detalles..."):
                        st.write(f"**NIT:** {r.get('numero_identificacion', 'N/A')}")
                        # MODIFICACIÓN: Agregar dirección de CC en el detalle
                        st.write(f"**Dirección CC:** {r.get('direccion_comercial', 'N/A')}")
                        if st.button("Analizar Vinculación", key=f"v_{i}", type="primary", use_container_width=True):
                            padre, metodo = buscar_propietario_legal(r, df_cc)
                            if padre: st.session_state['temp_vinc'] = {"hijo": r.to_dict(), "padre": padre, "metodo": metodo}
                            else: st.error("No se detectó propietario legal.")
                            st.rerun()
            
            st.divider()
            if st.button("⚠️ NO SE ENCUENTRA EN CÁMARA", use_container_width=True):
                st.session_state['temp_vinc'] = 'CANCELAR_NO'
                st.rerun()
        else:
            if st.session_state['temp_vinc'] == 'CANCELAR_NO':
                st.error("### ¿Confirmar No Encontrado?")
                c1, c2 = st.columns(2)
                if c1.button("✅ SÍ", use_container_width=True):
                    st.session_state['no_vinculados'].add(st.session_state['seleccion_id'])
                    st.session_state['seleccion_id'] = None
                    st.session_state['temp_vinc'] = None
                    st.rerun()
                if c2.button("❌ Volver", use_container_width=True):
                    st.session_state['temp_vinc'] = None
                    st.rerun()
            else:
                vinc = st.session_state['temp_vinc']
                st.warning(f"### 🛡️ Ficha Unificada ({vinc['metodo']})")
                ciiu_final = vinc['hijo']['ciiu'] if pd.notna(vinc['hijo']['ciiu']) and str(vinc['hijo']['ciiu']) != 'nan' else vinc['padre']['ciiu']
                resumen = pd.DataFrame({
                    "Campo": ["RAZÓN SOCIAL", "NIT", "COMERCIAL", "DIRECCIÓN", "CIIU"],
                    "Valor": [vinc['padre']['razon_social'], vinc['padre']['numero_identificacion'], vinc['hijo']['nombre_comercial'], vinc['hijo']['direccion_comercial'], ciiu_final]
                })
                st.table(resumen)
                cf1, cf2 = st.columns(2)
                if cf1.button("🚀 MIGRAR A CAMPO", type="primary", use_container_width=True):
                    st.session_state['base_campo'].append({"id_encuesta": local['ID_INT'], "data": vinc})
                    st.session_state['seleccion_id'] = None
                    st.session_state['temp_vinc'] = None
                    st.rerun()
                if cf2.button("❌ Cancelar", use_container_width=True):
                    st.session_state['temp_vinc'] = None
                    st.rerun()