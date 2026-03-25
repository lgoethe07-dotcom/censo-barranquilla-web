import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
from datetime import datetime
from difflib import SequenceMatcher
from supabase import create_client

# --- 1. CONEXIÓN ---
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except:
    st.error("Error de conexión. Verifica los Secrets de Supabase.")

# --- 2. CONFIGURACIÓN E INTERFAZ ---
st.set_page_config(page_title="Censo Campo - Registro Directo", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stButton>button { width: 100%; border-radius: 5px; }
    .status-box { padding: 10px; border-radius: 5px; margin-bottom: 10px; border: 1px solid #ddd; }
    .user-tag { position: fixed; top: 10px; left: 10px; z-index: 999; background: #1f2d3d; color: white; padding: 5px 12px; border-radius: 20px; font-size: 12px; }
    </style>
    """, unsafe_allow_html=True)

if 'user_name' not in st.session_state: st.session_state['user_name'] = "ENCUESTADOR_PRO"
st.markdown(f'<div class="user-tag">👤 {st.session_state["user_name"]}</div>', unsafe_allow_html=True)

# --- 3. FUNCIONES DE LÓGICA ---
def calcular_similitud(a, b):
    return SequenceMatcher(None, str(a).upper(), str(b).upper()).ratio()

@st.cache_data
def obtener_pendientes():
    # Solo traemos los registros que no han sido censados efectivamente
    res = supabase.table("campo_censo").select("*").eq("tipo_encuesta", "NO VINCULADO").execute()
    return pd.DataFrame(res.data)

# --- 4. PANEL DE CONTROL ---
st.title("📋 Módulo de Campo: Identificación y Registro")

df_pendientes = obtener_pendientes()

if df_pendientes.empty:
    st.success("✅ No hay puntos 'No Vinculados' pendientes de procesar.")
else:
    col_izq, col_der = st.columns([1, 1.2])

    with col_izq:
        st.subheader("📍 Selección de Punto")
        busqueda_lista = st.text_input("Buscar en lista de pendientes:", placeholder="Nombre o dirección...")
        
        df_ver = df_pendientes
        if busqueda_lista:
            df_ver = df_pendientes[df_pendientes['nombre_comercial'].str.contains(busqueda_lista, case=False, na=False)]
        
        # Lista de selección
        opciones = ["- Seleccione un punto -"] + df_ver['nombre_comercial'].tolist()
        seleccion = st.selectbox("Puntos cercanos:", opciones)

        if seleccion != "- Seleccione un punto -":
            item = df_ver[df_ver['nombre_comercial'] == seleccion].iloc[0].to_dict()
            st.session_state['punto_actual'] = item
            
            # Mapa de referencia (Precenso)
            st.write("**Ubicación Precenso:**")
            view_state = pdk.ViewState(latitude=item['y'], longitude=item['x'], zoom=17)
            capa = pdk.Layer("ScatterplotLayer", pd.DataFrame([item]), get_position='[x, y]', get_color='[255, 0, 0]', get_radius=10)
            st.pydeck_chart(pdk.Deck(layers=[capa], initial_view_state=view_state, map_style="light"))

    with col_der:
        if 'punto_actual' in st.session_state:
            pa = st.session_state['punto_actual']
            st.subheader(f"🔍 Identificación: {pa['nombre_comercial']}")
            
            # --- FLUJO DE PRIORIDAD ---
            with st.expander("1️⃣ Prioridad: Búsqueda por Nombre / Aviso", expanded=True):
                nombre_aviso = st.text_input("Nombre visible en el aviso o informado:")
                if st.button("Buscar coincidencias en Cámara"):
                    # Lógica de búsqueda en base de datos de Cámara de Comercio
                    res_cc = supabase.table("camara_comercio").select("*").ilike("nombre_comercial", f"%{nombre_aviso}%").limit(5).execute()
                    if res_cc.data:
                        st.session_state['resultados_cc'] = res_cc.data
                    else:
                        st.warning("No se encontraron coincidencias exactas. Intente con otra palabra clave.")

            with st.expander("2️⃣ Prioridad: Búsqueda por NIT / ID"):
                nit_informado = st.text_input("NIT o Cédula (Si el establecimiento lo facilita):")
                if st.button("Validar ID"):
                    res_nit = supabase.table("camara_comercio").select("*").eq("numero_identificacion", nit_informado).execute()
                    if res_nit.data:
                        st.session_state['resultados_cc'] = res_nit.data
                        st.success("¡Registro encontrado por ID!")
                    else:
                        st.error("ID no encontrado en la base de referencia.")

            # Mostrar resultados de búsqueda para vincular
            if 'resultados_cc' in st.session_state:
                st.write("### Seleccione el registro correcto:")
                for res in st.session_state['resultados_cc']:
                    col_res, col_btn = st.columns([3, 1])
                    col_res.markdown(f"**{res['nombre_comercial']}** - {res['numero_identificacion']}\n*{res['direccion_comercial']}*")
                    if col_btn.button("Vincular", key=f"vinc_{res['numero_identificacion']}"):
                        st.session_state['vinc_final'] = res
                        st.info(f"Seleccionado: {res['nombre_comercial']}")

            # --- FORMULARIO DE CIERRE ---
            if 'vinc_final' in st.session_state or st.checkbox("El negocio es totalmente nuevo / No está en Cámara"):
                st.divider()
                st.write("### 📸 Registro Fotográfico y GPS")
                
                # GPS - En Web es manual o por browser, en Nativa será automático
                c_gps1, c_gps2 = st.columns(2)
                lat_real = c_gps1.number_input("Latitud GPS Real", value=float(pa['y']), format="%.6f")
                lon_real = c_gps2.number_input("Longitud GPS Real", value=float(pa['x']), format="%.6f")

                # FOTOS
                f1 = st.file_uploader("1. Fachada (OBLIGATORIO)", type=['jpg', 'png', 'jpeg'])
                f2 = st.file_uploader("2. Comprobante de Visita (OPCIONAL)", type=['jpg', 'png', 'jpeg'])
                f3 = st.file_uploader("3. Copia de RUT (OPCIONAL)", type=['jpg', 'png', 'jpeg'])

                if st.button("🚀 FINALIZAR CENSO Y SINCRONIZAR", type="primary"):
                    if not f1:
                        st.error("La fotografía de la fachada es obligatoria para continuar.")
                    else:
                        # Aquí iría el proceso de:
                        # 1. Subir fotos a Supabase Storage
                        # 2. Actualizar campo_censo con los nuevos datos y coordenadas
                        # 3. Cambiar tipo_encuesta a 'EFECTIVA-DIRECTA'
                        st.success("Procesando sincronización... (Simulado)")
                        st.balloons()
                        # Limpiar estados
                        for key in ['punto_actual', 'resultados_cc', 'vinc_final']:
                            if key in st.session_state: del st.session_state[key]
                        st.rerun()
