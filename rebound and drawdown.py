#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun 15 18:56:13 2026

@author: ayazmamedov
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# Sayfa Ayarları
st.set_page_config(page_title="Rebound & Drawdown Tarayıcı", page_icon="🎯", layout="wide")

# --- YARDIMCI FONKSİYONLAR ---
@st.cache_data(ttl=300) # Veriyi hızlı yüklemek için 5 dakika önbellekte tutar
def fetch_data(ticker, period, interval):
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    # yfinance çoklu index düzeltmesi
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    return df

def find_unclosed_levels(df, window=2):
    if df.empty:
        return None, None, None

    current_price = float(df['Close'].iloc[-1])
    unclosed_bottoms = []
    unclosed_tops = []
    
    # Tüm veri setinde gezinerek tepe ve dipleri bul
    for i in range(window, len(df) - window):
        is_bottom = True
        is_top = True
        
        # Lokal Dip ve Tepe kontrolü
        for j in range(1, window + 1):
            if df['Low'].iloc[i] >= df['Low'].iloc[i - j] or df['Low'].iloc[i] >= df['Low'].iloc[i + j]:
                is_bottom = False
            if df['High'].iloc[i] <= df['High'].iloc[i - j] or df['High'].iloc[i] <= df['High'].iloc[i + j]:
                is_top = False
                
        # KAPANMAMIŞ DİP KONTROLÜ
        if is_bottom:
            level = float(df['Low'].iloc[i])
            future_min = float(df['Low'].iloc[i+1:].min())
            
            if future_min > level:  # Fiyat bu dibin altına hiç inmemiş
                dist_pts = current_price - level
                dist_pct = (dist_pts / current_price) * 100
                unclosed_bottoms.append({
                    'Tarih': df.index[i].strftime('%Y-%m-%d %H:%M'),
                    'Seviye': level,
                    'Uzaklık (Puan)': round(dist_pts, 2),
                    'Uzaklık (%)': round(dist_pct, 2)
                })
                
        # KAPANMAMIŞ TEPE KONTROLÜ
        if is_top:
            level = float(df['High'].iloc[i])
            future_max = float(df['High'].iloc[i+1:].max())
            
            if future_max < level:  # Fiyat bu tepenin üstüne hiç çıkmamış
                dist_pts = level - current_price
                dist_pct = (dist_pts / current_price) * 100
                unclosed_tops.append({
                    'Tarih': df.index[i].strftime('%Y-%m-%d %H:%M'),
                    'Seviye': level,
                    'Uzaklık (Puan)': round(dist_pts, 2),
                    'Uzaklık (%)': round(dist_pct, 2)
                })

    # Sonuçları en yakından uzağa doğru sırala
    unclosed_tops = sorted(unclosed_tops, key=lambda x: x['Uzaklık (Puan)'])
    unclosed_bottoms = sorted(unclosed_bottoms, key=lambda x: x['Uzaklık (Puan)'])
    
    return current_price, unclosed_tops, unclosed_bottoms

# --- ARAYÜZ (UI) ---
st.title("🎯 Saf Fiyat Hareketi: Rebound & Drawdown Tarayıcı")
st.markdown("Bu araç, fiyatın bir daha geri dönmediği **kapanmamış dipleri (Rebound Potansiyeli)** ve **kapanmamış tepeleri (Drawdown Potansiyeli)** tespit eder.")

# Sol Menü (Sidebar)
st.sidebar.header("⚙️ Tarama Ayarları")
symbols = {
    'NASDAQ Futures (NQ=F)': 'NQ=F',
    'Altın (GC=F)': 'GC=F',
    'Ham Petrol (CL=F)': 'CL=F',
    'Gümüş (SI=F)': 'SI=F'
}
selected_name = st.sidebar.selectbox("Enstrüman Seç", list(symbols.keys()))
ticker = symbols[selected_name]

period = st.sidebar.selectbox("Geçmiş Periyot", ["5d", "1mo", "3mo", "6mo", "1y"], index=1, help="Ne kadar geriye gidilecek?")
interval = st.sidebar.selectbox("Zaman Dilimi (Mum Tipi)", ["5m", "15m", "1h", "4h", "1d"], index=2)
window = st.sidebar.slider("Hassasiyet (Sağ/Sol Mum Sayısı)", min_value=1, max_value=10, value=2, help="Değer ne kadar yüksekse, sadece o kadar büyük tepeler/dipler alınır.")

if st.sidebar.button("Analizi Başlat 🚀", type="primary", use_container_width=True):
    with st.spinner(f"{selected_name} için veriler işleniyor..."):
        df = fetch_data(ticker, period, interval)
        
        if df.empty:
            st.error("Seçilen periyot/zaman dilimi kombinasyonu için veri bulunamadı! Lütfen ayarları değiştirin.")
        else:
            current_price, tops, bottoms = find_unclosed_levels(df, window)
            
            st.metric(label=f"💰 Anlık Fiyat ({selected_name})", value=f"{current_price:.2f}")
            
            # Tablolar
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("🔴 Kapanmamış Tepeler (Drawdown)")
                if tops:
                    st.dataframe(pd.DataFrame(tops).set_index('Tarih'), use_container_width=True)
                else:
                    st.info("Bu periyotta kapanmamış tepe bulunamadı.")
                    
            with col2:
                st.subheader("🟢 Kapanmamış Dipler (Rebound)")
                if bottoms:
                    st.dataframe(pd.DataFrame(bottoms).set_index('Tarih'), use_container_width=True)
                else:
                    st.info("Bu periyotta kapanmamış dip bulunamadı.")
            
            # Grafik Çizimi (Plotly)
            st.markdown("---")
            st.subheader("📈 Grafik Üzerinde İnceleme")
            
            fig = go.Figure(data=[go.Candlestick(x=df.index,
                            open=df['Open'], high=df['High'],
                            low=df['Low'], close=df['Close'],
                            name="Fiyat")])
            
            # Tepeleri Grafiğe Kırmızı Kesikli Çizgi Olarak Ekle
            if tops:
                for t in tops:
                    fig.add_hline(y=t['Seviye'], line_dash="dash", line_color="rgba(255, 0, 0, 0.6)", 
                                  annotation_text=f"{t['Seviye']:.2f}", annotation_position="top right")
            
            # Dipleri Grafiğe Yeşil Kesikli Çizgi Olarak Ekle
            if bottoms:
                for b in bottoms:
                    fig.add_hline(y=b['Seviye'], line_dash="dash", line_color="rgba(0, 255, 0, 0.6)", 
                                  annotation_text=f"{b['Seviye']:.2f}", annotation_position="bottom right")
                                  
            fig.update_layout(
                height=600, 
                margin=dict(l=0, r=0, t=30, b=0), 
                xaxis_rangeslider_visible=False,
                template="plotly_dark"
            )
            
            st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Taramayı başlatmak için sol menüden 'Analizi Başlat' butonuna tıklayın.")
