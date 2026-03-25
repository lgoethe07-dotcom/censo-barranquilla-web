import streamlit as st
import pandas as pd
import pydeck as pdk
from datetime import datetime
from supabase import create_client

# --- CONEXIÓN ---
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

st.set_page_config(page_title="Módulo Campo - Mapa", layout="wide")

# --- CARGA DE DATOS ---
@st.cache_data(ttl=10)
def cargar_puntos_mapa():
    res = supabase.table("campo_censo").select("*").eq("tipo_encuesta", "NO VINCULADO").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        df['x'] = pd.to_numeric(df['x'])
        df['y'] = pd.to_numeric(df['y'])
    return df

st.title("🗺️ Módulo de Campo: Identificación y Registro")

df_nv = cargar_puntos_mapa()

if df_nv.empty:
    st.success("No hay puntos pendientes.")
else:
    # --- ESTADO DE SELECCIÓN ---
    if 'pa' not in st.session_state:
        st.session_state['pa'] = None

    col_mapa, col_formulario = st.columns([1.5, 1])

    with col_mapa:
        st.subheader("Seleccione un punto rojo")
        
        view_state = pdk.ViewState(
            latitude=df_nv['y'].mean(),
            longitude=df_nv['x'].mean(),
            zoom=15,
            pitch=0
        )

        layer = pdk.Layer(
            "ScatterplotLayer",
            df_nv,
            get_position='[x, y]',
            get_color='[230, 0, 0, 200]',
            get_radius=12,
            pickable=True,
            auto_highlight=True # Ayuda visual al pasar el mouse
        )

        r = pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            # CAMBIO: Estilo abierto para que no salga en blanco
            map_style="light", 
            tooltip={"text": "Establecimiento: {nombre_comercial}"}
        )

        # CAPTURA DE SELECCIÓN
        # Usamos on_select para detectar el clic
        map_data = st.pydeck_chart(r, on_select="rerun", selection_mode="single")

        if map_data and map_data.selection and map_data.selection['indices']:
            selected_index = map_data.selection['indices'][0]
            st.session_state['pa'] = df_nv.iloc[selected_index].to_dict()

    with col_formulario:
        if st.session_state['pa']:
            pa = st.session_state['pa']
            st.success(f"📌 Seleccionado: {pa['nombre_comercial']}")
            
            with st.expander("📝 Formulario de Registro", expanded=True):
                st.write(f"**Dirección:** {pa['direccion_completa']}")
                
                # --- LÓGICA DE BÚSQUEDA ---
                busq = st.text_input("Buscar en Cámara (Nombre o NIT):", key="search_box")
                
                if st.button("Consultar"):
                    # Buscamos por nombre o nit simultáneamente
                    res_cc = supabase.table("camara_comercio").select("*") \
                        .or_(f"nombre_comercial.ilike.%{busq}%,numero_identificacion.eq.{busq}") \
                        .limit(5).execute()
                    st.session_state['res_busqueda'] = res_cc.data

                # Mostrar resultados
                if 'res_busqueda' in st.session_state:
                    for r in st.session_state['res_busqueda']:
                        if st.button(f"Vincular: {r['razon_social']}", key=f"v_{r['numero_identificacion']}"):
                            # Aquí iría el guardado
                            update_data = {
                                "tipo_documento": r['tipo_identificacion'],
                                "numero_documento": r['numero_identificacion'],
                                "razon_social": r['razon_social'],
                                "tipo_encuesta": "EFECTIVA-DIRECTA",
                                "fecha_sincronizacion": datetime.now().isoformat()
                            }
                            supabase.table("campo_censo").update(update_data).eq("id_encuesta", pa['id_encuesta']).execute()
                            st.success("¡Sincronizado!")
                            st.session_state['pa'] = None
                            st.rerun()
        else:
            st.info("Haga clic en un punto del mapa para ver los detalles.")
