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
        # print("[RSI] generate_signal df info:", df.shape, df.columns, type(df.index))
        # print(df.tail(2))
        rsi = self.calculate_rsi(df['close'], period)
        # print("[RSI] RSI values:", rsi.tail(2))
        if rsi.iloc[-1] < oversold:
            # print(f"[RSI] BUY signal: rsi={rsi.iloc[-1]}, oversold={oversold}")
            return 'buy'
        elif rsi.iloc[-1] > overbought:
            # print(f"[RSI] SELL signal: rsi={rsi.iloc[-1]}, overbought={overbought}")
            return 'sell'
        # print(f"[RSI] NO signal: rsi={rsi.iloc[-1]}, overbought={overbought}, oversold={oversold}")
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
        if price_range == 0:  # 가격 범위가 0인 경우 처리
            return None, None
            
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
        
    def generate_signal(self, df, num_bins=10, volume_threshold=1000, volume_zscore_threshold=2.0, window_size=20):
        try:
            if len(df) < window_size + 1:
                return None
                
            # VWAP 계산
            vwap = self.calculate_vwap(df)
            current_vwap = vwap.iloc[-1]
            current_price = df['close'].iloc[-1]
            current_volume = df['volume'].iloc[-1]
            
            # 거래량 이동평균과 표준편차 계산
            volume_ma = df['volume'].rolling(window=window_size).mean()
            volume_std = df['volume'].rolling(window=window_size).std()
            
            # 거래량 Z-score 계산 (표준편차가 0인 경우 처리)
            if volume_std.iloc[-1] > 0:
                volume_zscore = (current_volume - volume_ma.iloc[-1]) / volume_std.iloc[-1]
            else:
                volume_zscore = 0
                
            # 거래량 프로파일 계산 (최근 window_size 기간 동안)
            recent_df = df.tail(window_size)
            bins, volume_profile = self.calculate_volume_profile(recent_df, num_bins)
            if bins is None or volume_profile is None:
                return None
                
            # 현재 가격이 속한 구간 찾기
            price_range = recent_df['high'].max() - recent_df['low'].min()
            if price_range == 0:
                return None
                
            bin_size = price_range / num_bins
            current_bin = int((current_price - recent_df['low'].min()) / bin_size)
            if not (0 <= current_bin < num_bins):
                return None
                
            # 거래량 프로파일 분석
            mean_volume = np.mean(volume_profile)
            current_bin_volume = volume_profile[current_bin]
            volume_ratio = current_bin_volume / mean_volume if mean_volume > 0 else 0
            
            # 가격 모멘텀 계산
            price_change = df['close'].pct_change()
            price_momentum = price_change.rolling(window=5).mean().iloc[-1]
            
            # 매매 신호 생성 (조건 완화)
            # 1. 현재 거래량이 이동평균보다 높음
            # 2. 현재 구간의 거래량이 평균보다 높음
            # 3. 가격이 VWAP를 기준으로 상/하향 이탈
            volume_condition = current_volume > volume_ma.iloc[-1] * 0.8  # 거래량 조건 완화
            profile_condition = volume_ratio > 0.8  # 거래량 프로파일 조건 완화
            
            if volume_condition and profile_condition:
                vwap_distance = abs(current_price - current_vwap) / current_vwap
                if vwap_distance > 0.001:  # 0.1% 이상 이탈
                    if current_price < current_vwap and price_momentum < 0:
                        return 'buy'  # 하락 추세에서 매수
                    elif current_price > current_vwap and price_momentum > 0:
                        return 'sell'  # 상승 추세에서 매도
                    
            return None
            
        except Exception as e:
            print(f"거래량 신호 생성 오류: {str(e)}")
            traceback.print_exc()
            return None

class MLStrategy(BaseStrategy):
    """머신러닝 전략"""
    def generate_signal(self, df, prediction_period=5, training_period=100):
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

class BBRSIStrategy(BaseStrategy):
    """볼린저 밴드와 RSI 복합 전략"""
    def generate_signal(self, df, bb_period=20, bb_std=2, rsi_period=14, rsi_high=70, rsi_low=30):
        try:
            # 볼린저 밴드 계산
            upper, middle, lower = self.calculate_bollinger_bands(df['close'], bb_period, bb_std)
            
            # RSI 계산
            rsi = self.calculate_rsi(df['close'], rsi_period)
            
            current_price = df['close'].iloc[-1]
            current_rsi = rsi.iloc[-1]
            
            # 매매 신호 생성
            if current_price < lower.iloc[-1] and current_rsi < rsi_low:
                return 'buy'  # 가격이 하단밴드 아래이고 RSI가 과매도일 때 매수
            elif current_price > upper.iloc[-1] and current_rsi > rsi_high:
                return 'sell'  # 가격이 상단밴드 위이고 RSI가 과매수일 때 매도
                
            return None
            
        except Exception as e:
            print(f"BB+RSI 신호 생성 오류: {str(e)}")
            traceback.print_exc()
            return None

class MACDEMAStrategy(BaseStrategy):
    """MACD와 EMA 복합 전략"""
    def calculate_ema(self, prices, period):
        return prices.ewm(span=period, adjust=False).mean()
        
    def generate_signal(self, df, macd_fast=12, macd_slow=26, macd_signal=9, ema_period=20):
        try:
            # MACD 계산
            macd_line, signal_line = self.calculate_macd(df['close'], macd_fast, macd_slow, macd_signal)
            
            # EMA 계산
            ema = self.calculate_ema(df['close'], ema_period)
            
            current_price = df['close'].iloc[-1]
            current_ema = ema.iloc[-1]
            
            # MACD 골든/데드 크로스 확인
            macd_cross_up = (macd_line.iloc[-2] <= signal_line.iloc[-2] and 
                           macd_line.iloc[-1] > signal_line.iloc[-1])
            macd_cross_down = (macd_line.iloc[-2] >= signal_line.iloc[-2] and 
                             macd_line.iloc[-1] < signal_line.iloc[-1])
            
            # 매매 신호 생성
            if macd_cross_up and current_price > current_ema:
                return 'buy'  # MACD 골든크로스이고 가격이 EMA 위일 때 매수
            elif macd_cross_down and current_price < current_ema:
                return 'sell'  # MACD 데드크로스이고 가격이 EMA 아래일 때 매도
                
            return None
            
        except Exception as e:
            print(f"MACD+EMA 신호 생성 오류: {str(e)}")
            traceback.print_exc()
            return None

class StrategyFactory:
    """전략 팩토리 클래스"""
    @staticmethod
    def create_strategy(strategy_name):
        strategies = {
            'RSI': RSIStrategy(),
            '볼린저밴드': BollingerBandsStrategy(),
            'MACD': MACDStrategy(),
            '이동평균선 교차': MovingAverageStrategy(),
            '스토캐스틱': StochasticStrategy(),
            'ATR 기반 변동성 돌파': ATRStrategy(),
            '거래량 프로파일': VolumeProfileStrategy(),
            '머신러닝': MLStrategy(),
            'BB+RSI': BBRSIStrategy(),
            'MACD+EMA': MACDEMAStrategy()
        }
        return strategies.get(strategy_name)

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
        
        # 수수료 계산
        total_fees = 0
        for trade in trades:
            if 'fee' in trade:
                total_fees += trade['fee']
            else:
                # 수수료가 없는 경우 계산
                amount = initial_capital / trade['price']
                fee = self.calculate_fee(amount, trade['price'])
                total_fees += fee
        
        final_capital = initial_capital
        for trade in trades:
            final_capital += trade['profit']
            
        profit_rate = ((final_capital - initial_capital) / initial_capital * 100)
        
        # --- 자본금 변화 기록 추가 ---
        daily_balance = []
        capital = initial_capital
        position = 0
        last_trade_idx = 0
        for i in range(len(df)):
            # position/capital 업데이트 (간단화: 마지막 매수/매도 이후로 position 유지)
            if last_trade_idx < len(trades):
                trade = trades[last_trade_idx]
                if 'date' in trade and df.index[i] >= trade['date']:
                    if trade['type'] == 'buy':
                        position = initial_capital / trade['price']
                        capital = 0
                    elif trade['type'] == 'sell':
                        capital = position * trade['price']
                        position = 0
                    last_trade_idx += 1
            balance = capital + position * df['close'].iloc[i]
            daily_balance.append({'date': df.index[i], 'balance': balance})
        
        # 수익 거래와 손실 거래 분석
        winning_trades_list = [t for t in trades if t['profit'] > 0]
        losing_trades_list = [t for t in trades if t['profit'] <= 0]
        
        avg_win = sum(t['profit'] for t in winning_trades_list) / len(winning_trades_list) if winning_trades_list else 0
        avg_loss = sum(t['profit'] for t in losing_trades_list) / len(losing_trades_list) if losing_trades_list else 0
        
        # 연속 수익/손실 계산
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_consecutive_wins = 0
        current_consecutive_losses = 0
        
        for trade in trades:
            if trade['profit'] > 0:
                current_consecutive_wins += 1
                current_consecutive_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, current_consecutive_wins)
            else:
                current_consecutive_losses += 1
                current_consecutive_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, current_consecutive_losses)
        
        return {
            'total_trades': total_trades,
            'win_rate': win_rate,
            'profit_rate': profit_rate,
            'final_capital': final_capital,
            'trades': trades,
            'daily_balance': daily_balance,
            'total_fees': total_fees,
            'fee_rate': (total_fees / initial_capital) * 100,
            'net_profit': final_capital - initial_capital - total_fees,
            'net_profit_rate': ((final_capital - initial_capital - total_fees) / initial_capital) * 100,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': abs(avg_win / avg_loss) if avg_loss != 0 else float('inf'),
            'max_consecutive_wins': max_consecutive_wins,
            'max_consecutive_losses': max_consecutive_losses
        }
        
    def backtest_strategy(self, strategy_name, params, df, interval, initial_capital):
        """전략별 백테스팅 실행"""
        try:
            if df is None or len(df) < 30:
                print("[Backtest] 데이터 없음 또는 30개 미만")
                return None
            # 전략 객체 생성
            strategy = StrategyFactory.create_strategy(strategy_name)
            if strategy is None:
                print("[Backtest] 전략 생성 실패")
                return None
            # 백테스팅 실행
            trades = []
            position = None
            entry_price = 0
            entry_time = None
            for i in range(30, len(df)):
                current_data = df.iloc[:i+1]
                # print(f"[Backtest] {strategy_name} {i}/{len(df)} current_data index: {current_data.index[-2:]}")
                signal = strategy.generate_signal(current_data, **params)
                # print(f"[Backtest] {strategy_name} {i} signal: {signal}")
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
            # 루프 끝난 뒤 포지션이 남아있으면 강제 청산
            if position == 'long':
                exit_price = df['close'].iloc[-1]
                profit = (exit_price - entry_price) * (initial_capital / entry_price)
                profit -= self.calculate_fee(initial_capital / entry_price, entry_price)
                profit -= self.calculate_fee(initial_capital / entry_price, exit_price)
                trades.append({
                    'date': entry_time,
                    'type': 'buy',
                    'price': entry_price,
                    'exit_date': df.index[-1],
                    'exit_price': exit_price,
                    'profit': profit,
                    'profit_rate': (profit / (initial_capital / entry_price * entry_price)) * 100
                })
                print(f"[Backtest] 강제 청산: entry={entry_price}, exit={exit_price}, profit={profit}")
            print(f"[Backtest] 총 거래 수: {len(trades)}")
            return self.calculate_backtest_results(df, trades, initial_capital)
        except Exception as e:
            print(f"백테스팅 오류: {str(e)}")
            traceback.print_exc()
            return None
     
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

class OptunaOptimizer:
    """Optuna를 사용한 전략 최적화 클래스"""
    def __init__(self, strategy, strategy_name, df, n_trials=100, fee_rate=0.0005):
        self.strategy = strategy
        self.strategy_name = strategy_name
        self.df = df
        self.n_trials = n_trials
        self.fee_rate = fee_rate
        self.best_params = None
        self.best_value = None
        
    def objective(self, trial):
        """Optuna 최적화 목적 함수"""
        try:
            # 전략별 파라미터 정의
            if isinstance(self.strategy, RSIStrategy):
                params = {
                    'period': trial.suggest_int('period', 5, 30),
                    'overbought': trial.suggest_int('overbought', 60, 90),
                    'oversold': trial.suggest_int('oversold', 10, 40)
                }
            elif isinstance(self.strategy, BollingerBandsStrategy):
                params = {
                    'period': trial.suggest_int('period', 10, 50),
                    'std': trial.suggest_float('std', 1.0, 3.0)
                }
            elif isinstance(self.strategy, MACDStrategy):
                fast_period = trial.suggest_int('fast_period', 8, 20)
                slow_period = trial.suggest_int('slow_period', fast_period + 4, 50)
                params = {
                    'fast_period': fast_period,
                    'slow_period': slow_period,
                    'signal_period': trial.suggest_int('signal_period', 9, 20)
                }
            elif isinstance(self.strategy, MovingAverageStrategy):
                params = {
                    'short_period': trial.suggest_int('short_period', 5, 20),
                    'long_period': trial.suggest_int('long_period', 20, 50)
                }
            elif isinstance(self.strategy, StochasticStrategy):
                params = {
                    'period': trial.suggest_int('period', 5, 30),
                    'k_period': trial.suggest_int('k_period', 1, 5),
                    'd_period': trial.suggest_int('d_period', 1, 5),
                    'overbought': trial.suggest_int('overbought', 70, 90),
                    'oversold': trial.suggest_int('oversold', 10, 30)
                }
            elif isinstance(self.strategy, ATRStrategy):
                params = {
                    'period': trial.suggest_int('period', 5, 30),
                    'multiplier': trial.suggest_float('multiplier', 1.0, 3.0),
                    'trend_period': trial.suggest_int('trend_period', 10, 50),
                    'stop_loss_multiplier': trial.suggest_float('stop_loss_multiplier', 1.0, 3.0),
                    'position_size_multiplier': trial.suggest_float('position_size_multiplier', 0.5, 2.0)
                }
            elif isinstance(self.strategy, VolumeProfileStrategy):
                params = {
                    'num_bins': trial.suggest_int('num_bins', 5, 30),
                    'volume_threshold': trial.suggest_int('volume_threshold', 100, 5000),
                    'volume_zscore_threshold': trial.suggest_float('volume_zscore_threshold', 1.5, 3.0),
                    'window_size': trial.suggest_int('window_size', 10, 50)
                }
            elif isinstance(self.strategy, BBRSIStrategy):
                params = {
                    'bb_period': trial.suggest_int('bb_period', 10, 50),
                    'bb_std': trial.suggest_float('bb_std', 1.0, 3.0),
                    'rsi_period': trial.suggest_int('rsi_period', 5, 30),
                    'rsi_high': trial.suggest_int('rsi_high', 60, 90),
                    'rsi_low': trial.suggest_int('rsi_low', 10, 40)
                }
            elif isinstance(self.strategy, MACDEMAStrategy):
                fast_period = trial.suggest_int('macd_fast', 8, 20)
                slow_period = trial.suggest_int('macd_slow', fast_period + 4, 50)
                params = {
                    'macd_fast': fast_period,
                    'macd_slow': slow_period,
                    'macd_signal': trial.suggest_int('macd_signal', 5, 20),
                    'ema_period': trial.suggest_int('ema_period', 10, 50)
                }
            else:
                print('지원하지 않는 전략입니다.')
                return 0.0
            # 백테스팅 실행
            backtest_engine = BacktestEngine(fee_rate=self.fee_rate)
            result = backtest_engine.backtest_strategy(
                self.strategy_name,
                params,
                self.df,
                '1분봉',
                1000000  # 초기 자본금 100만원
            )
            if result is None:
                print(f"[Optuna][{self.strategy_name}] result is None for params: {params}")
                return 0.0
            if result.get('total_trades', 0) == 0:
                print(f"[Optuna][{self.strategy_name}] 거래 없음. params: {params}")
                return 0.0
            print(f"[Optuna][{self.strategy_name}] params: {params}, profit_rate: {result['profit_rate']}, win_rate: {result['win_rate']}, total_trades: {result['total_trades']}")
            return result['profit_rate'] * (result['win_rate'] / 100)
        except Exception as e:
            print(f"최적화 오류: {str(e)}")
            return 0.0
            
    def optimize(self):
        """최적화 실행"""
        try:
            import optuna
            
            study = optuna.create_study(direction='maximize')
            study.optimize(self.objective, n_trials=self.n_trials)
            
            self.best_params = study.best_params
            self.best_value = study.best_value
            
            return {
                'best_params': self.best_params,
                'best_value': self.best_value,
                'study': study
            }
            
        except Exception as e:
            print(f"최적화 실행 오류: {str(e)}")
            return None 