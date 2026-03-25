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

# --- LÓGICA DE PADRE/HIJO ---
def buscar_propietario_legal(hijo, df_full):
    nit_hijo = str(hijo.get('numero_identificacion', '')).strip()
    # Si ya tiene NIT, es una relación directa
    if nit_hijo not in ["", "nan", "None", "0"]:
        return hijo.to_dict() if hasattr(hijo, 'to_dict') else hijo, "Relación 1 a 1"
    
    # Búsqueda por matriz de llaves (Mismo comportamiento Módulo 1)
    f_mat = str(hijo.get('fecha_matricula', ''))
    dir_c = str(hijo.get('direccion_comercial', '')).strip().upper()
    mail = str(hijo.get('correo_comercial', '')).strip().lower()
    
    padres = df_full[df_full['numero_identificacion'].notna()]
    res = padres[(padres['fecha_matricula'].astype(str) == f_mat) & 
                 (padres['direccion_comercial'].str.upper() == dir_c) & 
                 (padres['correo_comercial'].str.lower() == mail)]
    
    if not res.empty: 
        return res.iloc[0].to_dict(), "Vinculación por Matriz (Hijo -> Padre)"
    return None, "No encontrado"

# --- 2. CONFIGURACIÓN UI ---
st.set_page_config(page_title="Módulo Campo - Validación Pro", layout="wide")

@st.cache_data(ttl=10)
def cargar_todo():
    res_campo = supabase.table("campo_censo").select("*").eq("tipo_encuesta", "NO VINCULADO").execute()
    res_cc = supabase.table("camara_comercio").select("*").execute()
    return pd.DataFrame(res_campo.data), pd.DataFrame(res_cc.data)

df_nv, df_cc_full = cargar_todo()

st.title("📋 Módulo de Campo: Validación y Vínculo")

if df_nv.empty:
    st.success("No hay puntos pendientes.")
else:
    col_mapa, col_form = st.columns([1.2, 1])

    with col_mapa:
        opciones = ["- Seleccione -"] + df_nv['nombre_comercial'].tolist()
        sel_p = st.selectbox("Punto a validar:", opciones)
        
        if sel_p != "- Seleccione -":
            pa = df_nv[df_nv['nombre_comercial'] == sel_p].iloc[0].to_dict()
            st.session_state['pa'] = pa
            
            view = pdk.ViewState(latitude=float(pa['y']), longitude=float(pa['x']), zoom=17)
            capa = pdk.Layer("ScatterplotLayer", [pa], get_position='[x, y]', 
                             get_color='[230, 0, 0, 200]', get_radius=10)
            st.pydeck_chart(pdk.Deck(layers=[capa], initial_view_state=view, map_style="light"))

    with col_form:
        if 'pa' in st.session_state and st.session_state['pa']:
            pa = st.session_state['pa']
            st.markdown(f"### 📍 {pa['nombre_comercial']}")
            st.caption(f"Dirección reportada: {pa['direccion_completa']}")
            
            # --- FORMULARIO DE BÚSQUEDA ---
            with st.form("busqueda_camara"):
                busq = st.text_input("Buscar por Nombre o NIT:", placeholder="Ej: Tienda La 70")
                submit_busqueda = st.form_submit_button("🔍 Consultar Cámara", use_container_width=True)

            if submit_busqueda and busq:
                res_busq = supabase.table("camara_comercio").select("*").or_(f"nombre_comercial.ilike.%{busq}%,numero_identificacion.eq.{busq}").limit(10).execute()
                st.session_state['res_df_campo'] = pd.DataFrame(res_busq.data)

            # Mostrar resultados si existen en sesión
            if 'res_df_campo' in st.session_state and not st.session_state['res_df_campo'].empty:
                res_df = st.session_state['res_df_campo']
                st.write("---")
                
                # Lógica de Similitud (Nombre y Dirección)
                dir_base = extraer_via_principal(pa['direccion_completa'])
                res_df['s_nom'] = res_df['nombre_comercial'].apply(lambda x: calcular_similitud(x, pa['nombre_comercial']))
                res_df['s_dir'] = res_df['direccion_comercial'].apply(lambda x: calcular_similitud(extraer_via_principal(x), dir_base))
                
                for idx, r in res_df.sort_values(by='s_nom', ascending=False).iterrows():
                    score = (r['s_nom'] + r['s_dir']) / 2
                    color = "#d4edda" if score > 0.7 else "#fff3cd"
                    
                    st.markdown(f"""
                        <div style="background:{color}; padding:10px; border-radius:5px; border:1px solid #ccc; margin-bottom:5px">
                            <b>{r['nombre_comercial']}</b><br>
                            <small>📍 {r['direccion_comercial']}</small><br>
                            <small>🎯 Similitud: {r['s_nom']:.0%} Nombre | {r['s_dir']:.0%} Dir</small>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    if st.button(f"Analizar Vínculo: {r['numero_identificacion'] if r['numero_identificacion'] else 'HIJO'}", key=f"btn_{idx}"):
                        # 1. Aplicar lógica Padre/Hijo (Matriz)
                        socio_legal, metodo = buscar_propietario_legal(r, df_cc_full)
                        
                        if socio_legal is not None:
                            # Asegurar que sea diccionario para evitar error de verdad ambigua
                            if isinstance(socio_legal, pd.DataFrame): socio_legal = socio_legal.iloc[0].to_dict()

                            st.info(f"🛡️ **Vínculo:** {metodo}")
                            
                            # --- BLOQUE DE GUARDADO CORREGIDO ---
                            update_data = {
                                "tipo_documento": str(socio_legal.get('tipo_identificacion', '')),
                                "numero_documento": str(socio_legal.get('numero_identificacion', '')),
                                "razon_social": str(socio_legal.get('razon_social', '')),
                                "act_economica_primaria": str(r.get('ciiu', '')),
                                "tipo_encuesta": "EFECTIVA-DIRECTA",
                                "estado_encuesta": "COMPLETO",
                                "editor": st.session_state.get('user_name', 'CAMPO_APP')
                                # Se eliminó 'fecha_sincronizacion' para evitar el error PGRST204
                            }

                            try:
                                # 1. Limpieza estricta de datos
                                clean_upd = {k: limpiar_valor(v) for k, v in update_data.items() if v not in ['', None, 'nan']}
                                
                                # 2. Forzar ID a entero para evitar fallos de caché de esquema
                                id_target = int(pa['id_encuesta']) 
                                
                                # 3. Ejecutar actualización
                                response = supabase.table("campo_censo").update(clean_upd).eq("id_encuesta", id_target).execute()
                                
                                if response.data:
                                    st.success("✅ ¡Vinculación Exitosa!")
                                    st.cache_data.clear()
                                    if 'res_df_campo' in st.session_state: 
                                        del st.session_state['res_df_campo']
                                    st.rerun()
                                else:
                                    st.error("No se recibió confirmación de la base de datos.")
                                    
                            except Exception as e:
                                st.error(f"Error al actualizar: {e}")
