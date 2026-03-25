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

# --- CARGA DE DATOS (NO VINCULADOS) ---
@st.cache_data(ttl=10)
def cargar_puntos_mapa():
    res = supabase.table("campo_censo").select("*").eq("tipo_encuesta", "NO VINCULADO").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        # Asegurar que las coordenadas sean numéricas
        df['x'] = pd.to_numeric(df['x'])
        df['y'] = pd.to_numeric(df['y'])
    return df

st.title("🗺️ Módulo de Campo: Identificación y Registro")
df_nv = cargar_puntos_mapa()

if df_nv.empty:
    st.success("No hay puntos pendientes por censar.")
else:
    col_mapa, col_formulario = st.columns([1.5, 1])

    with col_mapa:
        st.subheader("Seleccione un punto en el mapa")
        
        # Configuración del estado inicial del mapa (centrado en los puntos)
        view_state = pdk.ViewState(
            latitude=df_nv['y'].mean(),
            longitude=df_nv['x'].mean(),
            zoom=14,
            pitch=0
        )

        # Capa de puntos (Capa interactiva)
        layer = pdk.Layer(
            "ScatterplotLayer",
            df_nv,
            get_position='[x, y]',
            get_color='[230, 0, 0, 160]', # Rojo para pendientes
            get_radius=15,
            pickable=True, # IMPORTANTE: Permite interactuar
        )

        # Renderizar mapa con evento de clic
        mapa_interactivo = pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            map_style="mapbox://styles/mapbox/light-v9",
            tooltip={"text": "{nombre_comercial}\n{direccion_completa}"}
        )

        # Capturar el evento de selección
        evento_clic = st.pydeck_chart(mapa_interactivo, on_select="rerun")
        
        # Lógica de detección de clic
        if evento_clic and 'selection' in evento_clic and evento_clic['selection']['indices']:
            idx = evento_clic['selection']['indices'][0]
            st.session_state['pa'] = df_nv.iloc[idx].to_dict()
            st.session_state['vinc'] = None # Reset vinculación anterior

    with col_formulario:
        if 'pa' in st.session_state and st.session_state['pa']:
            pa = st.session_state['pa']
            st.markdown(f"### 📋 Formulario: {pa['nombre_comercial']}")
            st.caption(f"📍 Dirección: {pa['direccion_completa']}")
            
            # --- PRIORIDADES DE BÚSQUEDA ---
            st.divider()
            tab1, tab2 = st.tabs(["🔍 Por Nombre (Aviso)", "🆔 Por NIT/ID"])
            
            with tab1:
                busq_nombre = st.text_input("Nombre visto en el establecimiento:", key="in_nom")
                if st.button("Buscar en Cámara", key="btn_nom"):
                    res = supabase.table("camara_comercio").select("*").ilike("nombre_comercial", f"%{busq_nombre}%").limit(5).execute()
                    st.session_state['resultados'] = res.data

            with tab2:
                busq_nit = st.text_input("Número de identificación:", key="in_nit")
                if st.button("Validar NIT", key="btn_nit"):
                    res = supabase.table("camara_comercio").select("*").eq("numero_identificacion", busq_nit).execute()
                    st.session_state['resultados'] = res.data

            # --- RESULTADOS PARA VINCULAR ---
            if 'resultados' in st.session_state and st.session_state['resultados']:
                for r in st.session_state['resultados']:
                    with st.expander(f"📌 {r['razon_social']}"):
                        st.write(f"NIT: {r['numero_identificacion']}")
                        if st.button("Vincular este registro", key=f"v_{r['numero_identificacion']}"):
                            st.session_state['vinc'] = r

            # --- GUARDADO FINAL ---
            if 'vinc' in st.session_state and st.session_state['vinc']:
                v = st.session_state['vinc']
                st.success(f"Listo para vincular con: **{v['razon_social']}**")
                
                with st.form("finalizar"):
                    st.write("📌 **Validar Coordenada Real**")
                    c1, c2 = st.columns(2)
                    lat_r = c1.number_input("Latitud GPS", value=float(pa['y']), format="%.6f")
                    lon_r = c2.number_input("Longitud GPS", value=float(pa['x']), format="%.6f")
                    
                    if st.form_submit_button("✅ GUARDAR Y CERRAR PUNTO"):
                        # Sincronización a Supabase
                        data_upd = {
                            "tipo_documento": v['tipo_identificacion'],
                            "numero_documento": v['numero_identificacion'],
                            "razon_social": v['razon_social'],
                            "lat_real": lat_r,
                            "lon_real": lon_r,
                            "tipo_encuesta": "EFECTIVA-DIRECTA",
                            "fecha_sincronizacion": datetime.now().isoformat()
                        }
                        supabase.table("campo_censo").update(data_upd).eq("id_encuesta", pa['id_encuesta']).execute()
                        
                        st.success("Sincronizado con éxito.")
                        st.session_state['pa'] = None
                        st.cache_data.clear()
                        st.rerun()
        else:
            st.info("Seleccione un punto rojo en el mapa para cargar su información.")
