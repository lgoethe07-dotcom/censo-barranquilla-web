import streamlit as st
import pandas as pd
import pydeck as pdk
from datetime import datetime
from supabase import create_client

# --- 1. CONEXIÓN ---
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

st.set_page_config(page_title="Módulo Campo - Estable", layout="wide")

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

    with col_mapa:
        # --- RESPALDO: Selector manual si el clic falla ---
        opciones_puntos = ["- Seleccione un punto en el mapa o aquí -"] + df_nv['nombre_comercial'].tolist()
        seleccion_manual = st.selectbox("Buscar punto específico:", opciones_puntos)
        
        # Lógica para cargar punto desde el selector manual
        if seleccion_manual != "- Seleccione un punto en el mapa o aquí -":
            st.session_state['pa'] = df_nv[df_nv['nombre_comercial'] == seleccion_manual].iloc[0].to_dict()

        # --- CONFIGURACIÓN DEL MAPA ---
        view_state = pdk.ViewState(
            latitude=df_nv['y'].mean(),
            longitude=df_nv['x'].mean(),
            zoom=15
        )

        layer = pdk.Layer(
            "ScatterplotLayer",
            df_nv,
            get_position='[x, y]',
            get_color='[230, 0, 0, 200]',
            get_radius=15,
            pickable=True,
            auto_highlight=True
        )

        # Renderizado básico sin parámetros experimentales
        r = pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            map_style=None, # Quitar Mapbox para evitar blanco
            tooltip={"text": "Punto: {nombre_comercial}\nDir: {direccion_completa}"}
        )

        st.pydeck_chart(r)
        st.caption("💡 Si el clic en el mapa no responde, usa el buscador de arriba.")

    with col_formulario:
        if 'pa' in st.session_state and st.session_state['pa']:
            pa = st.session_state['pa']
            st.success(f"📌 Editando: {pa['nombre_comercial']}")
            
            # --- BÚSQUEDA EN CÁMARA ---
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
                            # Actualización
                            update_data = {
                                "tipo_documento": r['tipo_identificacion'],
                                "numero_documento": r['numero_identificacion'],
                                "razon_social": r['razon_social'],
                                "tipo_encuesta": "EFECTIVA-DIRECTA"
                            }
                            supabase.table("campo_censo").update(update_data).eq("id_encuesta", pa['id_encuesta']).execute()
                            st.success("¡Vínculo exitoso!")
                            st.session_state['pa'] = None
                            st.rerun()
        else:
            st.info("Utiliza el buscador o selecciona un punto.")
