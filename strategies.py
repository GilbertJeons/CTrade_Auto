import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import pyupbit
import traceback
from datetime import datetime

class BaseStrategy:
    """기본 전략 클래스"""
    def __init__(self):
        pass
        
    def calculate_rsi(self, prices, period=14):
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
        
    def calculate_macd(self, prices, fast_period=12, slow_period=26, signal_period=9):
        exp1 = prices.ewm(span=fast_period, adjust=False).mean()
        exp2 = prices.ewm(span=slow_period, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=signal_period, adjust=False).mean()
        return macd, signal
        
    def calculate_bollinger_bands(self, prices, period=20, std=2):
        ma = prices.rolling(window=period).mean()
        std_dev = prices.rolling(window=period).std()
        upper = ma + (std_dev * std)
        lower = ma - (std_dev * std)
        return upper, ma, lower

class RSIStrategy(BaseStrategy):
    """RSI 전략"""
    def generate_signal(self, df, period=14, overbought=70, oversold=30):
        rsi = self.calculate_rsi(df['close'], period)
        if rsi.iloc[-1] < oversold:
            return 'buy'
        elif rsi.iloc[-1] > overbought:
            return 'sell'
        return None

class BollingerBandsStrategy(BaseStrategy):
    """볼린저 밴드 전략"""
    def generate_signal(self, df, period=20, std=2):
        upper, middle, lower = self.calculate_bollinger_bands(df['close'], period, std)
        if df['close'].iloc[-1] < lower.iloc[-1]:
            return 'buy'
        elif df['close'].iloc[-1] > upper.iloc[-1]:
            return 'sell'
        return None

class MACDStrategy(BaseStrategy):
    """MACD 전략"""
    def generate_signal(self, df, fast_period=12, slow_period=26, signal_period=9):
        macd, signal = self.calculate_macd(df['close'], fast_period, slow_period, signal_period)
        if macd.iloc[-1] > signal.iloc[-1] and macd.iloc[-2] <= signal.iloc[-2]:
            return 'buy'
        elif macd.iloc[-1] < signal.iloc[-1] and macd.iloc[-2] >= signal.iloc[-2]:
            return 'sell'
        return None

class VolumeProfileStrategy(BaseStrategy):
    """거래량 프로파일 전략"""
    def calculate_vwap(self, df):
        vwap = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
        return vwap
        
    def calculate_volume_profile(self, df, num_bins=10):
        price_range = df['high'].max() - df['low'].min()
        bin_size = price_range / num_bins
        bins = np.arange(df['low'].min(), df['high'].max() + bin_size, bin_size)
        volume_profile = np.zeros(num_bins)
        
        for i in range(len(df)):
            price = df['close'].iloc[i]
            volume = df['volume'].iloc[i]
            bin_idx = int((price - df['low'].min()) / bin_size)
            if 0 <= bin_idx < num_bins:
                volume_profile[bin_idx] += volume
                
        return bins, volume_profile
        
    def generate_signal(self, df):
        try:
            vwap = self.calculate_vwap(df)
            current_vwap = vwap.iloc[-1]
            current_price = df['close'].iloc[-1]
            current_volume = df['volume'].iloc[-1]
            
            volume_ma = df['volume'].rolling(window=20).mean()
            volume_std = df['volume'].rolling(window=20).std()
            volume_zscore = (current_volume - volume_ma.iloc[-1]) / volume_std.iloc[-1]
            
            if current_price < current_vwap and volume_zscore > 2:
                return 'buy'
            elif current_price > current_vwap and volume_zscore > 2:
                return 'sell'
                
            return None
            
        except Exception as e:
            print(f"거래량 신호 생성 오류: {str(e)}")
            return None

class MLStrategy(BaseStrategy):
    """머신러닝 전략"""
    def generate_signal(self, df):
        try:
            df = df.copy()  # SettingWithCopyWarning 방지
            # 특성 생성
            df['returns'] = df['close'].pct_change()
            df['volume_change'] = df['volume'].pct_change()
            df['rsi'] = self.calculate_rsi(df['close'], 14)
            df['macd'], _ = self.calculate_macd(df['close'], 12, 26, 9)
            df['bb_upper'], df['bb_middle'], df['bb_lower'] = self.calculate_bollinger_bands(df['close'], 20, 2)
            # 타겟 변수 생성
            df['target'] = (df['close'].shift(-1) > df['close']).astype(int)
            features = ['returns', 'volume_change', 'rsi', 'macd', 
                       'bb_upper', 'bb_middle', 'bb_lower']
            X = df[features]
            y = df['target']
            X, y = X.align(y, join='inner', axis=0)
            X = X.dropna()
            y = y.loc[X.index]
            if len(X) < 20 or len(y) < 20 or len(X) != len(y):
                return None
            # fit은 한 번만, 예측은 최신 데이터로만
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            model = RandomForestClassifier(n_estimators=100, random_state=42)
            model.fit(X_scaled[:-1], y.values[:-1])
            current_features = X_scaled[[-1]]
            prediction = model.predict_proba(current_features)[0]
            if prediction[1] > 0.7:
                return 'buy'
            elif prediction[0] > 0.7:
                return 'sell'
            return None
        except Exception as e:
            print(f"머신러닝 신호 생성 오류: {str(e)}")
            return None

class MovingAverageStrategy(BaseStrategy):
    """이동평균선 교차 전략"""
    def generate_signal(self, df, short_period=5, long_period=20):
        short_ma = df['close'].rolling(window=short_period).mean()
        long_ma = df['close'].rolling(window=long_period).mean()
        if short_ma.iloc[-1] > long_ma.iloc[-1] and short_ma.iloc[-2] <= long_ma.iloc[-2]:
            return 'buy'
        elif short_ma.iloc[-1] < long_ma.iloc[-1] and short_ma.iloc[-2] >= long_ma.iloc[-2]:
            return 'sell'
        return None

class StochasticStrategy(BaseStrategy):
    """스토캐스틱 전략"""
    def generate_signal(self, df, period=14, k_period=3, d_period=3, overbought=80, oversold=20):
        low_min = df['low'].rolling(window=period).min()
        high_max = df['high'].rolling(window=period).max()
        k = 100 * ((df['close'] - low_min) / (high_max - low_min))
        d = k.rolling(window=d_period).mean()
        if k.iloc[-1] < oversold and d.iloc[-1] < oversold:
            return 'buy'
        elif k.iloc[-1] > overbought and d.iloc[-1] > overbought:
            return 'sell'
        return None

class StrategyFactory:
    """전략 팩토리 클래스"""
    @staticmethod
    def create_strategy(name):
        if name == 'RSI':
            return RSIStrategy()
        elif name == '볼린저밴드':
            return BollingerBandsStrategy()
        elif name == 'MACD':
            return MACDStrategy()
        elif name == '이동평균선 교차':
            return MovingAverageStrategy()
        elif name == '스토캐스틱':
            return StochasticStrategy()
        elif name == 'ATR 기반 변동성 돌파':
            return ATRStrategy()
        elif name == '거래량 프로파일':
            return VolumeProfileStrategy()
        elif name == '머신러닝':
            return MLStrategy()
        else:
            return None

class BacktestEngine:
    """백테스팅 엔진 클래스"""
    def __init__(self, fee_rate=0.0005):
        self.fee_rate = fee_rate
        
    def calculate_fee(self, amount, price):
        """수수료 계산"""
        return amount * price * self.fee_rate
        
    def calculate_backtest_results(self, df, trades, initial_capital):
        """백테스팅 결과 계산"""
        if not trades:
            return None
            
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t['profit'] > 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        final_capital = initial_capital
        for trade in trades:
            final_capital += trade['profit']
            
        profit_rate = ((final_capital - initial_capital) / initial_capital * 100)
        
        return {
            'total_trades': total_trades,
            'win_rate': win_rate,
            'profit_rate': profit_rate,
            'final_capital': final_capital,
            'trades': trades
        }
        
    def backtest_strategy(self, strategy_name, params, start_date, end_date, interval, initial_capital):
        """전략별 백테스팅 실행"""
        try:
            # 데이터 가져오기
            df = self._fetch_historical_data(start_date, end_date, interval)
            if df is None or len(df) < 30:
                return None
                
            # 전략 객체 생성
            strategy = StrategyFactory.create_strategy(strategy_name)
            if strategy is None:
                return None
                
            # 백테스팅 실행
            trades = []
            position = None
            entry_price = 0
            entry_time = None
            
            for i in range(30, len(df)):
                current_data = df.iloc[:i+1]
                signal = strategy.generate_signal(current_data, **params)
                
                if signal == 'buy' and position is None:
                    position = 'long'
                    entry_price = df['close'].iloc[i]
                    entry_time = df.index[i]
                elif signal == 'sell' and position == 'long':
                    exit_price = df['close'].iloc[i]
                    profit = (exit_price - entry_price) * (initial_capital / entry_price)
                    profit -= self.calculate_fee(initial_capital / entry_price, entry_price)  # 매수 수수료
                    profit -= self.calculate_fee(initial_capital / entry_price, exit_price)   # 매도 수수료
                    
                    trades.append({
                        'date': entry_time,  # 진입 시간
                        'type': 'buy',       # 거래 유형
                        'price': entry_price,  # 진입 가격
                        'exit_date': df.index[i],  # 퇴출 시간
                        'exit_price': exit_price,  # 퇴출 가격
                        'profit': profit,    # 수익금
                        'profit_rate': (profit / (initial_capital / entry_price * entry_price)) * 100  # 수익률
                    })
                    
                    position = None
                    
            return self.calculate_backtest_results(df, trades, initial_capital)
            
        except Exception as e:
            print(f"백테스팅 오류: {str(e)}")
            traceback.print_exc()
            return None
            
    def _fetch_historical_data(self, start_date, end_date, interval):
        """과거 데이터 가져오기"""
        try:
            # interval 매핑
            interval_map = {
                "1분봉": "minute1",
                "3분봉": "minute3",
                "5분봉": "minute5",
                "15분봉": "minute15",
                "30분봉": "minute30",
                "1시간봉": "minute60",
                "4시간봉": "minute240",
                "일봉": "day",
                "주봉": "week",
                "월봉": "month"
            }
            
            # interval 변환
            upbit_interval = interval_map.get(interval, interval)
            
            # 시작일과 종료일을 datetime으로 변환
            start_datetime = datetime.combine(start_date, datetime.min.time())
            end_datetime = datetime.combine(end_date, datetime.max.time())
            
            print(f"데이터 요청: {start_datetime} ~ {end_datetime}, interval={upbit_interval}")
            
            # 데이터 가져오기
            df = pyupbit.get_ohlcv_from(
                ticker="KRW-BTC",
                interval=upbit_interval,
                fromDatetime=start_datetime,
                to=end_datetime
            )
            
            if df is None or df.empty:
                print("데이터가 없습니다.")
                return None
            
            print(f"가져온 데이터: {len(df)}개")
            return df
            
        except Exception as e:
            print(f"데이터 가져오기 오류: {str(e)}")
            traceback.print_exc()
            return None

    def backtest_volume_profile(self, num_bins, start_date, end_date, interval, initial_capital, fee_rate):
        df = self._fetch_historical_data(start_date, end_date, interval)
        if df is None or len(df) < 30:
            return None
        strategy = VolumeProfileStrategy()
        trades = []
        position = None
        entry_price = 0
        entry_time = None
        for i in range(30, len(df)):
            current_data = df.iloc[:i+1]
            signal = strategy.generate_signal(current_data)
            if signal == 'buy' and position is None:
                position = 'long'
                entry_price = df['close'].iloc[i]
                entry_time = df.index[i]
            elif signal == 'sell' and position == 'long':
                exit_price = df['close'].iloc[i]
                profit = (exit_price - entry_price) * (initial_capital / entry_price)
                profit -= self.calculate_fee(initial_capital / entry_price, entry_price)
                profit -= self.calculate_fee(initial_capital / entry_price, exit_price)
                trades.append({
                    'date': entry_time,
                    'type': 'buy',
                    'price': entry_price,
                    'exit_date': df.index[i],
                    'exit_price': exit_price,
                    'profit': profit,
                    'profit_rate': (profit / (initial_capital / entry_price * entry_price)) * 100
                })
                position = None
        return self.calculate_backtest_results(df, trades, initial_capital)

    def backtest_ml(self, n_estimators, random_state, start_date, end_date, interval, initial_capital, fee_rate):
        df = self._fetch_historical_data(start_date, end_date, interval)
        if df is None or len(df) < 30:
            return None
        strategy = MLStrategy()
        trades = []
        position = None
        entry_price = 0
        entry_time = None
        for i in range(30, len(df)):
            current_data = df.iloc[:i+1]
            signal = strategy.generate_signal(current_data)
            if signal == 'buy' and position is None:
                position = 'long'
                entry_price = df['close'].iloc[i]
                entry_time = df.index[i]
            elif signal == 'sell' and position == 'long':
                exit_price = df['close'].iloc[i]
                profit = (exit_price - entry_price) * (initial_capital / entry_price)
                profit -= self.calculate_fee(initial_capital / entry_price, entry_price)
                profit -= self.calculate_fee(initial_capital / entry_price, exit_price)
                trades.append({
                    'date': entry_time,
                    'type': 'buy',
                    'price': entry_price,
                    'exit_date': df.index[i],
                    'exit_price': exit_price,
                    'profit': profit,
                    'profit_rate': (profit / (initial_capital / entry_price * entry_price)) * 100
                })
                position = None
        return self.calculate_backtest_results(df, trades, initial_capital)

    def backtest_atr(self, period, multiplier, start_date, end_date, interval, initial_capital, fee_rate, trend_period=20, stop_loss_multiplier=1.5, position_size_multiplier=1.0):
        """
        ATR 기반 변동성 돌파 전략 백테스트
        :param period: ATR 계산 기간
        :param multiplier: ATR 승수
        :param start_date: 시작일
        :param end_date: 종료일
        :param interval: 시간단위
        :param initial_capital: 초기자본
        :param fee_rate: 수수료율
        :param trend_period: 추세 판단을 위한 이동평균선 기간
        :param stop_loss_multiplier: 스탑로스 ATR 승수
        :param position_size_multiplier: 포지션 사이징 승수
        :return: 백테스트 결과
        """
        with open('atr_debug.log', 'a', encoding='utf-8') as f:
            print('=== backtest_atr 시작 ===', file=f)
            print(f'파라미터: period={period}, multiplier={multiplier}, trend_period={trend_period}, stop_loss_multiplier={stop_loss_multiplier}, position_size_multiplier={position_size_multiplier}', file=f)
            
        df = self._fetch_historical_data(start_date, end_date, interval)
        if df is None or len(df) < max(period, trend_period):
            return None
            
        strategy = ATRStrategy()
        trades = []
        position = None
        entry_price = 0
        entry_time = None
        position_size = 1.0
        stop_loss = None
        
        for i in range(max(period, trend_period), len(df)):
            current_data = df.iloc[:i+1]
            signal = strategy.generate_signal(
                current_data,
                period=period,
                multiplier=multiplier,
                trend_period=trend_period,
                stop_loss_multiplier=stop_loss_multiplier,
                position_size_multiplier=position_size_multiplier
            )
            
            current_price = df['close'].iloc[i]
            
            # 스탑로스 체크
            if position == 'long' and stop_loss is not None:
                if current_price <= stop_loss:
                    # 스탑로스로 청산
                    exit_price = current_price
                    profit = (exit_price - entry_price) * (initial_capital * position_size / entry_price)
                    profit -= self.calculate_fee(initial_capital * position_size / entry_price, entry_price)
                    profit -= self.calculate_fee(initial_capital * position_size / entry_price, exit_price)
                    
                    trades.append({
                        'date': entry_time,
                        'type': 'buy',
                        'price': entry_price,
                        'exit_date': df.index[i],
                        'exit_price': exit_price,
                        'profit': profit,
                        'profit_rate': (profit / (initial_capital * position_size / entry_price * entry_price)) * 100,
                        'exit_type': 'stop_loss'
                    })
                    
                    position = None
                    position_size = 1.0
                    stop_loss = None
                    continue
            
            if signal == 'buy' and position is None:
                position = 'long'
                entry_price = current_price
                entry_time = df.index[i]
                position_size = strategy.position_size
                stop_loss = strategy.stop_loss
                
                with open('atr_debug.log', 'a', encoding='utf-8') as f:
                    print(f'매수 신호: date={entry_time}, price={entry_price}, position_size={position_size}, stop_loss={stop_loss}', file=f)
                    
            elif signal == 'sell' and position == 'long':
                exit_price = current_price
                profit = (exit_price - entry_price) * (initial_capital * position_size / entry_price)
                profit -= self.calculate_fee(initial_capital * position_size / entry_price, entry_price)
                profit -= self.calculate_fee(initial_capital * position_size / entry_price, exit_price)
                
                trades.append({
                    'date': entry_time,
                    'type': 'buy',
                    'price': entry_price,
                    'exit_date': df.index[i],
                    'exit_price': exit_price,
                    'profit': profit,
                    'profit_rate': (profit / (initial_capital * position_size / entry_price * entry_price)) * 100,
                    'exit_type': 'signal'
                })
                
                with open('atr_debug.log', 'a', encoding='utf-8') as f:
                    print(f'매도 신호: date={df.index[i]}, price={exit_price}, profit={profit}', file=f)
                
                position = None
                position_size = 1.0
                stop_loss = None
        
        return self.calculate_backtest_results(df, trades, initial_capital)

class ATRStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()
        self.name = "ATR 기반 변동성 돌파"
        self.description = "ATR을 이용한 변동성 돌파 전략"
        
    def generate_signal(self, data, period=14, multiplier=2.0, trend_period=20, stop_loss_multiplier=1.5, position_size_multiplier=1.0):
        """
        ATR 기반 변동성 돌파 전략 신호 생성
        :param data: OHLCV 데이터
        :param period: ATR 계산 기간
        :param multiplier: ATR 승수
        :param trend_period: 추세 판단을 위한 이동평균선 기간
        :param stop_loss_multiplier: 스탑로스 ATR 승수
        :param position_size_multiplier: 포지션 사이징 승수
        :return: 'buy', 'sell', None
        """
        try:
            if len(data) < max(period, trend_period):
                return None
                
            # ATR 계산
            high = data['high']
            low = data['low']
            close = data['close']
            
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean()
            
            # 추세 판단을 위한 이동평균선
            ma = close.rolling(window=trend_period).mean()
            
            # 현재 봉의 데이터
            current_close = close.iloc[-1]
            current_high = high.iloc[-1]
            current_low = low.iloc[-1]
            current_atr = atr.iloc[-1]
            current_ma = ma.iloc[-1]
            
            # 상단/하단 밴드 계산
            upper_band = close.iloc[-2] + (atr.iloc[-2] * multiplier)
            lower_band = close.iloc[-2] - (atr.iloc[-2] * multiplier)
            
            # 스탑로스 레벨 계산
            stop_loss_long = current_close - (current_atr * stop_loss_multiplier)
            stop_loss_short = current_close + (current_atr * stop_loss_multiplier)
            
            # 포지션 사이즈 계산 (ATR 기반)
            position_size = 1.0 / (current_atr * position_size_multiplier)
            position_size = min(position_size, 1.0)  # 최대 100%로 제한
            
            # 신호 생성
            signal = None
            
            # 상승 추세에서 매수 신호
            if current_close > current_ma:
                if current_high > upper_band:
                    signal = 'buy'
                    self.position_size = position_size
                    self.stop_loss = stop_loss_long
                    
            # 하락 추세에서 매도 신호
            elif current_close < current_ma:
                if current_low < lower_band:
                    signal = 'sell'
                    self.position_size = position_size
                    self.stop_loss = stop_loss_short
            
            return signal
            
        except Exception as e:
            print(f"ATR 신호 생성 오류: {str(e)}")
            return None 