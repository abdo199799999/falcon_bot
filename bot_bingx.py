# --- !!! هذه هي الدالة التشخيصية الجديدة !!! ---
def analyze_symbol(symbol):
    try:
        klines = get_klines(symbol, interval="15m", limit=100)
        if len(klines) < 35: # Increased for MACD calculation later
            # logger.info(f"[DIAGNOSTIC] {symbol}: Not enough klines ({len(klines)})")
            return 'HOLD', None
        
        df = pd.DataFrame(klines, columns=['open','close','high','low','volume','timestamp'])
        df[['open','close','high','low']] = df[['open','close','high','low']].apply(pd.to_numeric)
        
        # --- حساب المؤشرات ---
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        last_candle = df.iloc[-1]
        prev_candle = df.iloc[-2]
        current_price = last_candle['close']

        # --- حساب الشروط ---
        rsi_is_oversold = last_candle['RSI'] < 30
        is_bullish_engulfing = (last_candle['close'] > last_candle['open'] and 
                                prev_candle['close'] < prev_candle['open'] and 
                                last_candle['close'] > prev_candle['open'] and 
                                last_candle['open'] < prev_candle['close'])

        # --- !!! الطباعة التشخيصية الهامة !!! ---
        # سنطبع هذه المعلومات فقط للعملات التي قد تكون مثيرة للاهتمام
        if last_candle['RSI'] < 40: # نطبع فقط إذا كان RSI منخفضًا لتجنب إغراق السجلات
            logger.info(f"[DIAGNOSTIC] {symbol} | RSI: {last_candle['RSI']:.2f} | Oversold? {rsi_is_oversold} | Engulfing? {is_bullish_engulfing}")

        # --- منطق القرار ---
        if rsi_is_oversold and is_bullish_engulfing:
            logger.info(f"✅✅✅ [BINGX] FOUND A BUY SIGNAL FOR {symbol} ✅✅✅")
            return 'BUY', current_price

        rsi_is_overbought = last_candle['RSI'] > 70
        if rsi_is_overbought:
            return 'SELL', current_price
            
    except Exception as e:
        logger.error(f"[BingX] خطأ فادح أثناء فحص {symbol}: {e}")
    
    return 'HOLD', None

