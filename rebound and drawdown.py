#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun 15 18:56:13 2026

@author: ayazmamedov
"""

import streamlit as st
import pandas as pd
import numpy as np
import xgboost as xgb
import ccxt.async_support as ccxt
import asyncio

# ==========================================
# 1. VERİ İŞLEME VE FORMASYON MANTIĞI
# ==========================================

def mum_ozelliklerini_cikar(df):
    """OHLCV verisinden gövde/gölge analizi ve Doji çıkarımı."""
    df = df.copy()
    
    df['Govde'] = abs(df['Close'] - df['Open'])
    df['Ust_Golge'] = df['High'] - df[['Open', 'Close']].max(axis=1)
    df['Alt_Golge'] = df[['Open', 'Close']].min(axis=1) - df['Low']
    df['Toplam_Boy'] = df['High'] - df['Low']
    
    # Gölge uzunluklarına göre net Doji sınıflandırması
    df['Is_Dragonfly'] = np.where(
        (df['Alt_Golge'] > (df['Govde'] * 3)) & (df['Ust_Golge'] < (df['Toplam_Boy'] * 0.1)), 1, 0
    )
    df['Is_Gravestone'] = np.where(
        (df['Ust_Golge'] > (df['Govde'] * 3)) & (df['Alt_Golge'] < (df['Toplam_Boy'] * 0.1)), 1, 0
    )
    return df

def hedefleri_ve_sinyalleri_belirle(df, lookforward=10):
    """Drawdown/Rebound oranlarını hesaplar ve spesifik AL/SAT hedefleri üretir."""
    df = df.copy()
    indexer = pd.api.indexers.FixedForwardWindowIndexer(window_size=lookforward)
    
    df['Future_Max'] = df['High'].shift(-1).rolling(window=indexer, min_periods=1).max()
    df['Future_Min'] = df['Low'].shift(-1).rolling(window=indexer, min_periods=1).min()
    
    df['Target_Rebound_Pct'] = ((df['Future_Max'] - df['Close']) / df['Close']) * 100
    df['Target_Drawdown_Pct'] = ((df['Close'] - df['Future_Min']) / df['Close']) * 100
    
    # Spesifik Al/Sat Kriterleri (Eğitim için etiketler)
    df['Hedef_Buy'] = np.where((df['Target_Rebound_Pct'] > 2.0) & (df['Target_Drawdown_Pct'] < 1.0), 1, 0)
    df['Hedef_Sell'] = np.where((df['Target_Drawdown_Pct'] > 2.0), 1, 0)
    
    df.drop(['Future_Max', 'Future_Min'], axis=1, inplace=True)
    df.dropna(subset=['Target_Rebound_Pct', 'Target_Drawdown_Pct'], inplace=True)
    return df

def veriyi_hazirla(df):
    """İndikatörleri ve hedefleri ekleyip hazır hale getirir."""
    df = mum_ozelliklerini_cikar(df)
    df = hedefleri_ve_sinyalleri_belirle(df)
    return df

# ==========================================
# 2. ÇİFT MOTORLU XGBOOST MODELİ
# ==========================================

class DualXGBoostModel:
    def __init__(self):
        self.model_buy = xgb.XGBClassifier(eval_metric='logloss')
        self.model_sell = xgb.XGBClassifier(eval_metric='logloss')
        self.is_trained = False
        self.features = ['Govde', 'Ust_Golge', 'Alt_Golge', 'Is_Dragonfly', 'Is_Gravestone']

    def egit(self, df):
        """Geçmiş veri üzerinden modelleri eğitir."""
        if len(df) < 50: # Veri çok azsa eğitme
            return
            
        X = df[self.features]
        y_buy = df['Hedef_Buy']
        y_sell = df['Hedef_Sell']
        
        # Sınıfların tek tip olup olmadığını kontrol et (hata almamak için)
        if len(y_buy.unique()) > 1 and len(y_sell.unique()) > 1:
            self.model_buy.fit(X, y_buy)
            self.model_sell.fit(X, y_sell)
            self.is_trained = True

    def tahmin_et(self, df_current):
        """Buy ve Sell olasılıklarını döndürür."""
        if not self.is_trained:
             return 0.0, 0.0
             
        X = df_current[self.features].iloc[-1:] 
        buy_prob = self.model_buy.predict_proba(X)[0][1] * 100
        sell_prob = self.model_sell.predict_proba(X)[0][1] * 100
        
        return round(buy_prob, 2), round(sell_prob, 2)

# ==========================================
# 3. ASENKRON PİYASA TARAYICI
# ==========================================

async def egitim_verisi_cek_ve_egit(borsa, model, zaman_dilimi):
    """Modelin tahminden önce öğrenebilmesi için BTC verisini çeker."""
    try:
        # Piyasayı genel olarak anlaması için BTC'nin geçmiş 1000 mumunu çekiyoruz
        mumlar = await borsa.fetch_ohlcv("BTC/USDT", timeframe=zaman_dilimi, limit=1000)
        df = pd.DataFrame(mumlar, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df = veriyi_hazirla(df)
        model.egit(df)
        return True
    except Exception as e:
        return False

async def sembol_getir_ve_analiz_et(borsa, sembol, zaman_dilimi, model):
    """Tek sembolü analiz eder."""
    try:
        mumlar = await borsa.fetch_ohlcv(sembol, timeframe=zaman_dilimi, limit=50)
        df = pd.DataFrame(mumlar, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        
        df = mum_ozelliklerini_cikar(df) # Sinyal tespiti için sadece özellikleri çıkarmak yeterli
        
        buy_prob, sell_prob = model.tahmin_et(df)
        
        son_mum = df.iloc[-1]
        formasyon = "Yok"
        if son_mum['Is_Dragonfly'] == 1: formasyon = "Dragonfly Doji"
        elif son_mum['Is_Gravestone'] == 1: formasyon = "Gravestone Doji"
        
        return {
            "Sembol": sembol,
            "Rebound (Al) %": buy_prob,
            "Drawdown (Sat) %": sell_prob,
            "Formasyon": formasyon,
            "Skor": round(buy_prob - sell_prob, 2)
        }
    except Exception as e:
        return None

async def piyasayi_tara_motoru(semboller, zaman_dilimi, model):
    """Asenkron ana fonksiyon."""
    borsa = ccxt.binance()
    
    # Model henüz eğitilmediyse önce eğit
    if not model.is_trained:
        await egitim_verisi_cek_ve_egit(borsa, model, zaman_dilimi)
        
    gorevler = [sembol_getir_ve_analiz_et(borsa, s, zaman_dilimi, model) for s in semboller]
    sonuclar = await asyncio.gather(*gorevler)
    await borsa.close()
    
    return pd.DataFrame([s for s in sonuclar if s is not None])

# ==========================================
# 4. STREAMLIT ARAYÜZÜ (APP)
# ==========================================

st.set_page_config(page_title="Doji Panel", layout="wide")

if 'model' not in st.session_state:
    st.session_state.model = DualXGBoostModel()

def main():
    st.title("⚡ Asenkron Piyasa Tarayıcı & Doji Panel")
    
    st.sidebar.header("Kontrol Paneli")
    zaman_dilimi = st.sidebar.selectbox("Zaman Dilimi", ["5m", "15m", "1h", "4h", "1d"], index=2)
    
    st.sidebar.markdown("---")
    zaman_skor_filtresi = st.sidebar.toggle("Zaman ve Skor Filtresi Aktif", value=False)
    min_skor = 0
    if zaman_skor_filtresi:
        min_skor = st.sidebar.slider("Minimum Net Skor Eşiği", 0, 100, 20)
    
    st.sidebar.markdown("---")
    tarama_baslat = st.sidebar.button("Taramayı Başlat", type="primary")
    
    if tarama_baslat:
        with st.spinner(f"{zaman_dilimi} zaman diliminde yapay zeka eğitiliyor ve piyasa taranıyor..."):
            # Örnek sembol listesi
            semboller = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "SOL/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT"]
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            df_sonuclar = loop.run_until_complete(piyasayi_tara_motoru(semboller, zaman_dilimi, st.session_state.model))
            
            if not df_sonuclar.empty:
                if zaman_skor_filtresi:
                    df_al = df_sonuclar[(df_sonuclar['Skor'] >= min_skor) & (df_sonuclar['Rebound (Al) %'] > df_sonuclar['Drawdown (Sat) %'])]
                    df_sat = df_sonuclar[(df_sonuclar['Drawdown (Sat) %'] > df_sonuclar['Rebound (Al) %']) & (df_sonuclar['Drawdown (Sat) %'] >= (min_skor + df_sonuclar['Rebound (Al) %']))]
                else:
                    df_al = df_sonuclar.sort_values(by="Rebound (Al) %", ascending=False)
                    df_sat = df_sonuclar.sort_values(by="Drawdown (Sat) %", ascending=False)
                
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("🔥 Rebound Fırsatları (AL)")
                    st.dataframe(df_al[["Sembol", "Rebound (Al) %", "Formasyon", "Skor"]].reset_index(drop=True), use_container_width=True)
                    
                with col2:
                    st.subheader("⚠️ Drawdown Riskleri (SAT)")
                    st.dataframe(df_sat[["Sembol", "Drawdown (Sat) %", "Formasyon", "Skor"]].reset_index(drop=True), use_container_width=True)
            else:
                st.error("Veri çekilemedi veya modeller yeterli örneklem bulamadı.")

if __name__ == "__main__":
    main()