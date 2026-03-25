import streamlit as st
import pandas as pd
import pydeck as pdk
from datetime import datetime
from supabase import create_client

# --- 1. CONEXIÓN ---
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

st.set_page_config(page_title="Módulo Campo - Visualización", layout="wide")

# --- 2. CARGA DE DATOS ---
@st.cache_data(ttl=5)
def cargar_puntos_mapa():
    res = supabase.table("campo_censo").select("*").eq("tipo_encuesta", "NO VINCULADO").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        df['x'] = pd.to_numeric(df['x'])
        df['y'] = pd.to_numeric(df['y'])
    return df

st.title("🗺️ Módulo de Campo: Identificación")

df_nv = cargar_puntos_mapa()

if df_nv.empty:
    st.success("No hay puntos pendientes.")
else:
    col_mapa, col_formulario = st.columns([1.5, 1])

    # Inicializar punto seleccionado en session_state si no existe
    if 'pa' not in st.session_state:
        st.session_state['pa'] = None

    with col_mapa:
        opciones_puntos = ["- Seleccione un punto en la lista -"] + df_nv['nombre_comercial'].tolist()
        seleccion_manual = st.selectbox("Buscar punto específico:", opciones_puntos)
        
        # Lógica para cargar punto desde el selector manual
        df_seleccionado = pd.DataFrame()
        if seleccion_manual != "- Seleccione un punto en la lista -":
            punto_dict = df_nv[df_nv['nombre_comercial'] == seleccion_manual].iloc[0].to_dict()
            st.session_state['pa'] = punto_dict
            # Crear un dataframe pequeño con solo el seleccionado para la capa de enmarque
            df_seleccionado = pd.DataFrame([punto_dict])

        # --- CAPAS DEL MAPA ---
        # Capa 1: Todos los puntos (Más pequeños)
        layer_puntos = pdk.Layer(
            "ScatterplotLayer",
            df_nv,
            get_position='[x, y]',
            get_color='[230, 0, 0, 180]', # Rojo
            get_radius=8,  # Puntos más pequeños
            pickable=True
        )

        capas = [layer_puntos]

        # Capa 2: Círculo de enmarque (Solo si hay selección)
        if not df_seleccionado.empty:
            layer_seleccion = pdk.Layer(
                "ScatterplotLayer",
                df_seleccionado,
                get_position='[x, y]',
                get_color='[0, 120, 255, 100]', # Azul transparente
                get_radius=25, # Círculo más grande que envuelve al punto
                stroked=True,
                line_width_min_pixels=2,
                get_line_color=[0, 120, 255]
            )
            capas.append(layer_seleccion)

        # Configurar vista (centrar en selección o en el promedio)
        lat_view = df_seleccionado['y'].iloc[0] if not df_seleccionado.empty else df_nv['y'].mean()
        lon_view = df_seleccionado['x'].iloc[0] if not df_seleccionado.empty else df_nv['x'].mean()

        view_state = pdk.ViewState(
            latitude=lat_view,
            longitude=lon_view,
            zoom=17 if not df_seleccionado.empty else 15
        )

        r = pdk.Deck(
            layers=capas,
            initial_view_state=view_state,
            map_style="light",
            tooltip={"text": "{nombre_comercial}"}
        )

        st.pydeck_chart(r)

    with col_formulario:
        if st.session_state['pa']:
            pa = st.session_state['pa']
            st.success(f"📌 Editando: {pa['nombre_comercial']}")
            
            busq = st.text_input("Nombre o NIT para vincular:", key="search_box")
            
            if st.button("Consultar Cámara"):
                res_cc = supabase.table("camara_comercio").select("*") \
                    .or_(f"nombre_comercial.ilike.%{busq}%,numero_identificacion.eq.{busq}") \
                    .limit(5).execute()
                st.session_state['res_busqueda'] = res_cc.data

            if 'res_busqueda' in st.session_state:
                for r in st.session_state['res_busqueda']:
                    with st.expander(f"🏢 {r['razon_social']}"):
                        st.write(f"NIT: {r['numero_identificacion']}")
                        if st.button("Vincular", key=f"v_{r['numero_identificacion']}"):
                            update_data = {
                                "tipo_documento": r['tipo_identificacion'],
                                "numero_documento": r['numero_identificacion'],
                                "razon_social": r['razon_social'],
                                "tipo_encuesta": "EFECTIVA-DIRECTA",
                                "fecha_sincronizacion": datetime.now().isoformat()
                            }
                            supabase.table("campo_censo").update(update_data).eq("id_encuesta", pa['id_encuesta']).execute()
                            st.success("¡Vínculo exitoso!")
                            st.session_state['pa'] = None
                            st.cache_data.clear()
                            st.rerun()
        else:
            st.info("Selecciona un establecimiento de la lista.")
