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

st.set_page_config(page_title="Rebound & Drawdown Tarayıcı", page_icon="🎯", layout="wide")

@st.cache_data(ttl=300)
def fetch_data(ticker, period, interval):
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    return df

def find_unclosed_levels(df, wick_ratio=1.5):
    if df.empty:
        return None, None, None

    current_price = float(df['Close'].iloc[-1])
    unclosed_bottoms = []
    unclosed_tops = []
    
    # Tüm veri setinde gezinerek uzun fitilli mumları bul
    for i in range(1, len(df) - 1):
        open_p = float(df['Open'].iloc[i])
        close_p = float(df['Close'].iloc[i])
        high_p = float(df['High'].iloc[i])
        low_p = float(df['Low'].iloc[i])
        
        body = abs(open_p - close_p)
        body = body if body > 0 else 0.0001 # Sıfıra bölme hatasını engelle
        
        lower_wick = min(open_p, close_p) - low_p
        upper_wick = high_p - max(open_p, close_p)
        
        # --- REBOUND (DİP) KONTROLÜ ---
        # Alt fitil gövdeden belirgin şekilde büyükse ve üst fitilden uzunsa
        if lower_wick >= body * wick_ratio and lower_wick > upper_wick:
            level = min(open_p, close_p) # Çizgiyi gövdenin en altına koy
            
            # Bu seviyenin altına gelecekte 'kapanış' gelmiş mi?
            future_closes = df['Close'].iloc[i+1:]
            if not future_closes.empty and float(future_closes.min()) >= level:
                dist_pts = current_price - level
                dist_pct = (dist_pts / current_price) * 100
                unclosed_bottoms.append({
                    'Tarih': df.index[i].strftime('%Y-%m-%d %H:%M'),
                    'Seviye': level,
                    'Uzaklık (Puan)': round(dist_pts, 2),
                    'Uzaklık (%)': round(dist_pct, 2)
                })
                
        # --- DRAWDOWN (TEPE) KONTROLÜ ---
        # Üst fitil gövdeden belirgin şekilde büyükse ve alt fitilden uzunsa
        if upper_wick >= body * wick_ratio and upper_wick > lower_wick:
            level = max(open_p, close_p) # Çizgiyi gövdenin en üstüne koy
            
            # Bu seviyenin üstüne gelecekte 'kapanış' gelmiş mi?
            future_closes = df['Close'].iloc[i+1:]
            if not future_closes.empty and float(future_closes.max()) <= level:
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

# --- ARAYÜZ ---
st.title("🎯 Saf Fiyat Hareketi: Rebound & Drawdown Tarayıcı")
st.markdown("Fitil (gölge) uzunluklarına dayalı saf fiyat hareketi analizi.")

st.sidebar.header("⚙️ Tarama Ayarları")
symbols = {
    'NASDAQ Futures (NQ=F)': 'NQ=F',
    'Altın (GC=F)': 'GC=F',
    'Ham Petrol (CL=F)': 'CL=F',
    'Gümüş (SI=F)': 'SI=F'
}
selected_name = st.sidebar.selectbox("Enstrüman Seç", list(symbols.keys()))
ticker = symbols[selected_name]

period = st.sidebar.selectbox("Geçmiş Periyot", ["5d", "1mo", "3mo", "6mo", "1y"], index=1)
interval = st.sidebar.selectbox("Zaman Dilimi", ["5m", "15m", "1h", "4h", "1d"], index=2)
wick_ratio = st.sidebar.slider("Fitil/Gövde Oranı", min_value=1.0, max_value=5.0, value=2.0, step=0.1, help="Fitil, gövdeden kaç kat uzun olmalı?")

if st.sidebar.button("Analizi Başlat 🚀", type="primary", use_container_width=True):
    with st.spinner(f"{selected_name} için veriler işleniyor..."):
        df = fetch_data(ticker, period, interval)
        
        if df.empty:
            st.error("Veri bulunamadı!")
        else:
            current_price, tops, bottoms = find_unclosed_levels(df, wick_ratio)
            
            st.metric(label=f"💰 Anlık Fiyat ({selected_name})", value=f"{current_price:.2f}")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("🔴 Kapanmamış Tepeler (Drawdown)")
                if tops:
                    st.dataframe(pd.DataFrame(tops).set_index('Tarih'), use_container_width=True)
                else:
                    st.info("Kriterlere uygun tepe bulunamadı.")
                    
            with col2:
                st.subheader("🟢 Kapanmamış Dipler (Rebound)")
                if bottoms:
                    st.dataframe(pd.DataFrame(bottoms).set_index('Tarih'), use_container_width=True)
                else:
                    st.info("Kriterlere uygun dip bulunamadı.")
            
            st.markdown("---")
            st.subheader("📈 Grafik Üzerinde İnceleme")
            
            fig = go.Figure(data=[go.Candlestick(x=df.index,
                            open=df['Open'], high=df['High'],
                            low=df['Low'], close=df['Close'],
                            name="Fiyat")])
            
            if tops:
                for t in tops:
                    fig.add_hline(y=t['Seviye'], line_dash="dash", line_color="rgba(255, 0, 0, 0.6)", 
                                  annotation_text=f"{t['Seviye']:.2f}", annotation_position="top right")
            
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
