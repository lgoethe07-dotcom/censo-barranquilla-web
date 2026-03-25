import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
from datetime import datetime
from difflib import SequenceMatcher
from supabase import create_client

# --- 1. CONEXIÓN Y FUNCIONES DE APOYO ---
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

def calcular_similitud(a, b):
    return SequenceMatcher(None, str(a).upper(), str(b).upper()).ratio()

def extraer_via_principal(direccion):
    partes = str(direccion).upper().split()
    return " ".join(partes[:3]) if len(partes) >= 3 else str(direccion).upper()

def limpiar_valor(v):
    if isinstance(v, (np.int64, np.int32)): return int(v)
    if isinstance(v, (np.float64, np.float32)): return float(v)
    if pd.isna(v): return None
    return v

# --- LÓGICA DE PADRE/HIJO (MISMA DEL MODULO 1) ---
def buscar_propietario_legal(hijo, df_full):
    nit_hijo = str(hijo.get('numero_identificacion', '')).strip()
    if nit_hijo not in ["", "nan", "None", "0"]:
        return hijo, "Relación 1 a 1"
    
    # Búsqueda por matriz de llaves
    f_mat = str(hijo.get('fecha_matricula', ''))
    dir_c = str(hijo.get('direccion_comercial', '')).strip().upper()
    mail = str(hijo.get('correo_comercial', '')).strip().lower()
    
    padres = df_full[df_full['numero_identificacion'].notna()]
    res = padres[(padres['fecha_matricula'].astype(str) == f_mat) & 
                 (padres['direccion_comercial'].str.upper() == dir_c) & 
                 (padres['correo_comercial'].str.lower() == mail)]
    
    if not res.empty: return res.iloc[0].to_dict(), "Vinculación por Matriz (Hijo -> Padre)"
    return None, "No encontrado"

# --- 2. CONFIGURACIÓN UI ---
st.set_page_config(page_title="Módulo Campo - Validación Pro", layout="wide")

@st.cache_data(ttl=10)
def cargar_todo():
    # Cargar pendientes de campo
    res_campo = supabase.table("campo_censo").select("*").eq("tipo_encuesta", "NO VINCULADO").execute()
    # Cargar cámara de comercio completa para la lógica de padres
    res_cc = supabase.table("camara_comercio").select("*").execute()
    return pd.DataFrame(res_campo.data), pd.DataFrame(res_cc.data)

df_nv, df_cc_full = cargar_todo()

st.title("📋 Módulo de Campo: Validación y Vínculo")

if df_nv.empty:
    st.success("No hay puntos pendientes.")
else:
    col_mapa, col_form = st.columns([1.2, 1])

    with col_mapa:
        # Selector y Mapa (Manteniendo tu lógica visual previa)
        opciones = ["- Seleccione -"] + df_nv['nombre_comercial'].tolist()
        sel_p = st.selectbox("Punto a validar:", opciones)
        
        if sel_p != "- Seleccione -":
            pa = df_nv[df_nv['nombre_comercial'] == sel_p].iloc[0].to_dict()
            st.session_state['pa'] = pa
            
            # Vista Mapa Pro
            view = pdk.ViewState(latitude=float(pa['y']), longitude=float(pa['x']), zoom=17)
            capa = pdk.Layer("ScatterplotLayer", [pa], get_position='[x, y]', 
                             get_color='[230, 0, 0, 200]', get_radius=10)
            st.pydeck_chart(pdk.Deck(layers=[capa], initial_view_state=view, map_style="light"))

    with col_form:
        if 'pa' in st.session_state and st.session_state['pa']:
            pa = st.session_state['pa']
            st.markdown(f"### Validando: {pa['nombre_comercial']}")
            
            # BÚSQUEDA CON LÓGICA DE SIMILITUD
            busq = st.text_input("Buscar por Nombre o NIT:", placeholder="Ej: Tienda La 70")
            
            if busq:
                # Consulta a Supabase con OR
                res_busq = supabase.table("camara_comercio").select("*").or_(f"nombre_comercial.ilike.%{busq}%,numero_identificacion.eq.{busq}").limit(10).execute()
                res_df = pd.DataFrame(res_busq.data)

                if not res_df.empty:
                    st.write("---")
                    # Calcular Similitud igual que Modulo 1
                    dir_base = extraer_via_principal(pa['direccion_completa'])
                    res_df['s_nom'] = res_df['nombre_comercial'].apply(lambda x: calcular_similitud(x, pa['nombre_comercial']))
                    res_df['s_dir'] = res_df['direccion_comercial'].apply(lambda x: calcular_similitud(extraer_via_principal(x), dir_base))
                    
                    for _, r in res_df.sort_values(by='s_nom', ascending=False).iterrows():
                        # Diseño de tarjetas de similitud
                        score = (r['s_nom'] + r['s_dir']) / 2
                        color = "#d4edda" if score > 0.7 else "#fff3cd"
                        
                        with st.container():
                            st.markdown(f"""
                            <div style="background:{color}; padding:10px; border-radius:5px; border:1px solid #ccc; margin-bottom:5px">
                                <b>{r['nombre_comercial']}</b><br>
                                <small>📍 {r['direccion_comercial']}</small><br>
                                <small>🎯 Similitud: {r['s_nom']:.0%} Nombre | {r['s_dir']:.0%} Dir</small>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            if st.button(f"Analizar Vínculo: {r['numero_identificacion'] if r['numero_identificacion'] else 'HIJO'}", key=f"btn_{r.name}"):
                                # APLICAR LÓGICA PADRE/HIJO
                                socio_legal, metodo = buscar_propietario_legal(r, df_cc_full)
                                
                                if socio_legal:
                                    st.info(f"🛡️ **Vínculo Detectado:** {metodo}")
                                    
                                    # PREPARAR DATOS (Usando la función limpiar_valor para evitar el APIError)
                                    update_data = {
                                        "tipo_documento": str(socio_legal.get('tipo_identificacion', '')),
                                        "numero_documento": str(socio_legal.get('numero_identificacion', '')),
                                        "razon_social": str(socio_legal.get('razon_social', '')),
                                        "act_economica_primaria": str(r.get('ciiu', '')),
                                        "tipo_encuesta": "EFECTIVA-DIRECTA",
                                        "estado_encuesta": "COMPLETO",
                                        "fecha_sincronizacion": datetime.now().isoformat(),
                                        "editor": st.session_state.get('user_name', 'CAMPO_APP')
                                    }

                                    try:
                                        # LIMPIEZA DE DATOS ANTES DE ENVIAR
                                        clean_upd = {k: limpiar_valor(v) for k, v in update_data.items()}
                                        id_target = limpiar_valor(pa['id_encuesta'])
                                        
                                        supabase.table("campo_censo").update(clean_upd).eq("id_encuesta", id_target).execute()
                                        st.success("✅ ¡Vinculación Exitosa y Punto Cerrado!")
                                        st.cache_data.clear()
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error técnico al actualizar: {e}")
                                else:
                                    st.error("No se pudo determinar un NIT/Padre para este registro.")
