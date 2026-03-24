import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import re
from datetime import datetime
from difflib import SequenceMatcher
from supabase import create_client

# --- 1. CONFIGURACIÓN DE CONEXIÓN ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error("Error en credenciales de Supabase. Revisa los Secrets.")
        return None

supabase = init_connection()

# --- 2. CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Gestión de Precenso - Barranquilla", layout="wide")

# Inicialización robusta de estados
if 'autenticado' not in st.session_state:
    st.session_state['autenticado'] = False
if 'user_name' not in st.session_state:
    st.session_state['user_name'] = ""
if 'seleccion_id' not in st.session_state:
    st.session_state['seleccion_id'] = None
if 'temp_vinc' not in st.session_state:
    st.session_state['temp_vinc'] = None

# --- 3. FUNCIONES DE APOYO ---
def calcular_similitud(a, b):
    return SequenceMatcher(None, str(a).upper(), str(b).upper()).ratio()

def corregir_coordenada(valor):
    if pd.isna(valor) or valor == "": return np.nan
    s = str(valor).replace('.', '').replace(',', '')
    try:
        # Lógica para Barranquilla (Lat 10-11, Lon -74)
        if s.startswith('-'): return float(s[:3] + "." + s[3:])
        else: return float(s[:2] + "." + s[2:])
    except: return np.nan

def extraer_via_principal(direccion):
    partes = str(direccion).upper().split()
    return " ".join(partes[:3]) if len(partes) >= 3 else str(direccion).upper()

def limpiar_nombre_busqueda(nombre):
    patron = r'\b(SAS|S\.A\.S|LTDA|GRUPO|TIENDA|PANADERIA|SOLUCIONES|SERVICIOS|LA|EL|LOS|LAS|DE|DEL)\b'
    nombre_limpio = re.sub(patron, '', str(nombre).upper())
    return [w for w in re.findall(r'\w+', nombre_limpio) if len(w) > 2]

@st.cache_data(ttl=600)
def cargar_datos():
    # 1. Precenso
    res_p = supabase.table("precenso_pendientes").select("*").execute()
    df_p = pd.DataFrame(res_p.data)
    df_p.columns = df_p.columns.str.lower()
    df_p['id_int'] = range(len(df_p))
    df_p['lon'] = df_p['x'].apply(corregir_coordenada)
    df_p['lat'] = df_p['y'].apply(corregir_coordenada)
    
    # 2. Cámara de Comercio
    res_c = supabase.table("camara_comercio").select("*").execute()
    df_c = pd.DataFrame(res_c.data)
    df_c.columns = df_c.columns.str.lower()
    
    # 3. Registros en campo
    res_campo = supabase.table("campo_censo").select("id_encuesta, tipo_encuesta").execute()
    df_campo_db = pd.DataFrame(res_campo.data)
    
    return df_p, df_c, df_campo_db

def buscar_propietario_legal(hijo, df_full):
    nit = str(hijo.get('numero_identificacion', '')).strip()
    if nit not in ["", "nan", "None"]:
        return hijo.to_dict(), "Directo"
    
    # Lógica de llaves compuesta...
    f_mat = str(hijo.get('fecha_matricula', ''))
    dir_c = str(hijo.get('direccion_comercial', '')).strip().upper()
    mail = str(hijo.get('correo_comercial', '')).strip().lower()
    
    padres = df_full[df_full['numero_identificacion'].notna()]
    res = padres[(padres['fecha_matricula'].astype(str) == f_mat) & 
                 (padres['direccion_comercial'].str.upper() == dir_c) & 
                 (padres['correo_comercial'].str.lower() == mail)]
    
    if not res.empty: return res.iloc[0].to_dict(), "Vinculación por Datos"
    return None, "No encontrado"

# --- 4. MÓDULO DE LOGIN ---
def mostrar_login():
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.write("#")
        st.markdown("""
            <div style='text-align: center; background-color: #f8f9fa; padding: 30px; border-radius: 15px; border: 1px solid #dee2e6'>
                <h2 style='margin-bottom: 0;'>🔐 Acceso</h2>
                <p style='color: #6c757d;'>GOETHE Data Solutions</p>
            </div>
        """, unsafe_allow_html=True)
        
        with st.form("login_form"):
            user = st.text_input("Usuario")
            pw = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Ingresar", use_container_width=True):
                res = supabase.table("usuarios").select("*").eq("usuario", user).eq("clave", pw).execute()
                if res.data:
                    st.session_state['autenticado'] = True
                    st.session_state['user_name'] = res.data[0]['nombre']
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas")

# --- 5. APP PRINCIPAL ---
def main_app():
    # Sidebar con botón de salir siempre visible
    with st.sidebar:
        st.image("https://via.placeholder.com/150x50?text=GOETHE+DATA", use_container_width=True)
        st.write(f"👤 **{st.session_state['user_name']}**")
        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            st.session_state['autenticado'] = False
            st.session_state['user_name'] = ""
            st.rerun()

    df_pre, df_cc, df_campo = cargar_datos()

    # Procesar IDs trabajados
    v_ids = []
    nv_ids = []
    if not df_campo.empty:
        v_ids = df_campo[df_campo['tipo_encuesta'] != 'NO VINCULADO']['id_encuesta'].astype(int).tolist()
        nv_ids = df_campo[df_campo['tipo_encuesta'] == 'NO VINCULADO']['id_encuesta'].astype(int).tolist()

    # --- MÉTRICAS Y MAPA ---
    m1, m2, m3 = st.columns(3)
    m1.metric("Pendientes", len(df_pre) - len(v_ids) - len(nv_ids))
    m2.metric("Vinculados", len(v_ids))
    m3.metric("No en Cámara", len(nv_ids))

    col_left, col_right = st.columns([1.5, 1])

    with col_left:
        # Lógica del mapa Pydeck
        df_map = df_pre.dropna(subset=['lat', 'lon']).copy()
        def get_color(row):
            if int(row['id_int']) in v_ids: return [0, 114, 255, 180]
            if int(row['id_int']) in nv_ids: return [255, 150, 0, 180]
            return [40, 167, 69, 180]
        
        df_map['color'] = df_map.apply(get_color, axis=1)
        
        view = pdk.ViewState(latitude=11.003, longitude=-74.797, zoom=15)
        layer = pdk.Layer("ScatterplotLayer", df_map, get_position='[lon, lat]',
                          get_color='color', get_radius=5, pickable=True)
        
        st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, tooltip=True))

    with col_right:
        st.subheader("🔍 Auditoría")
        # Filtro de búsqueda
        search = st.text_input("Buscar establecimiento:", placeholder="Nombre...")
        df_filtered = df_pre[~df_pre['id_int'].isin(v_ids + nv_ids)]
        if search:
            df_filtered = df_filtered[df_filtered['nombre_comercial'].str.contains(search, case=False, na=False)]
        
        seleccion = st.selectbox("Seleccione para procesar:", ["-"] + df_filtered['nombre_comercial'].tolist())
        
        if seleccion != "-":
            local_data = df_pre[df_pre['nombre_comercial'] == seleccion].iloc[0]
            st.session_state['seleccion_id'] = int(local_data['id_int'])
            
            st.info(f"**Dirección:** {local_data['direccion_comercial']}")
            
            # Aquí iría el resto de tu lógica de vinculación (botones de migrar, etc)
            if st.button("Marcar como NO ENCONTRADO EN CC"):
                # Lógica de insert en Supabase para no vinculados...
                st.success("Marcado correctamente")
                st.rerun()

# --- 6. CONTROL DE FLUJO ---
if __name__ == "__main__":
    if not st.session_state['autenticado']:
        mostrar_login()
    else:
        main_app()
