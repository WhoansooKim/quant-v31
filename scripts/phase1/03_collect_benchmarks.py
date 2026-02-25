"""
V3.1 Phase 1 — 벤치마크 + 매크로 (수정본)
yfinance MultiIndex 컬럼 처리
"""
import yfinance as yf
import psycopg
import polars as pl
import pandas as pd
from pathlib import Path
import time
import os

PG_DSN = "postgresql://quant:QuantV31!Secure@localhost:5432/quantdb"
PARQUET_DIR = Path("/home/quant/quant-v31/data/parquet/benchmark")


def flatten_columns(df):
    """yfinance MultiIndex 컬럼 → 단순 컬럼으로 변환"""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
    return df


def collect_benchmarks():
    print("\n📊 벤치마크 데이터 수집")
    
    benchmarks = {
        "SPY": "S&P 500 ETF",
        "^VIX": "CBOE Volatility Index",
        "^TNX": "10-Year Treasury Yield",
        "^IRX": "3-Month Treasury Yield",
        "QQQ": "Nasdaq 100 ETF",
        "IWM": "Russell 2000 ETF",
        "TLT": "20+ Year Treasury Bond ETF",
        "GLD": "Gold ETF",
    }
    
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    
    for sym, name in benchmarks.items():
        try:
            print(f"  📡 {name} ({sym})...", end=" ")
            data = yf.download(sym, period="15y", progress=False, timeout=30)
            
            if len(data) < 100:
                print(f"⚠️ 데이터 부족 ({len(data)}건)")
                continue
            
            data = flatten_columns(data)
            data = data.reset_index()
            
            # Date 컬럼 정리
            date_col = [c for c in data.columns if 'date' in c.lower() or 'Date' in c][0]
            data = data.rename(columns={date_col: 'Date'})
            
            # Parquet 저장
            clean_name = sym.replace("^", "")
            path = PARQUET_DIR / f"{clean_name}.parquet"
            pl.from_pandas(data).write_parquet(path)
            
            # PostgreSQL 저장 (^VIX 등은 제외)
            if not sym.startswith("^"):
                records = []
                for _, row in data.iterrows():
                    try:
                        records.append((
                            row['Date'],
                            sym,
                            float(row['Open']),
                            float(row['High']),
                            float(row['Low']),
                            float(row['Close']),
                            int(row['Volume']),
                            float(row.get('Adj Close', row['Close'])),
                        ))
                    except (ValueError, TypeError, KeyError):
                        continue
                
                if records:
                    with psycopg.connect(PG_DSN) as conn:
                        with conn.cursor() as cur:
                            cur.executemany("""
                                INSERT INTO daily_prices 
                                    (time, symbol, open, high, low, close, volume, adj_close)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (time, symbol) DO UPDATE SET
                                    close = EXCLUDED.close, volume = EXCLUDED.volume
                            """, records)
                        conn.commit()
                    print(f"✅ {len(data)}일 → DB+Parquet")
                else:
                    print(f"✅ {len(data)}일 → Parquet only")
            else:
                print(f"✅ {len(data)}일 → Parquet")
            
        except Exception as e:
            print(f"❌ {e}")
        
        time.sleep(0.5)


def collect_yield_spread():
    """장단기 스프레드 계산"""
    print("\n📊 장단기 스프레드 계산")
    try:
        tnx_path = PARQUET_DIR / "TNX.parquet"
        irx_path = PARQUET_DIR / "IRX.parquet"
        
        if not tnx_path.exists() or not irx_path.exists():
            print("  ⚠️ TNX/IRX Parquet 없음")
            return
        
        tnx = pl.read_parquet(tnx_path)
        irx = pl.read_parquet(irx_path)
        
        # 컬럼명 확인 후 Close 찾기
        tnx_close_col = [c for c in tnx.columns if 'close' in c.lower() or 'Close' in c]
        irx_close_col = [c for c in irx.columns if 'close' in c.lower() or 'Close' in c]
        date_col_tnx = [c for c in tnx.columns if 'date' in c.lower() or 'Date' in c]
        
        if not tnx_close_col or not irx_close_col or not date_col_tnx:
            print(f"  ⚠️ 컬럼 매칭 실패. TNX: {tnx.columns}, IRX: {irx.columns}")
            return
        
        tnx = tnx.select([pl.col(date_col_tnx[0]).alias("Date"), pl.col(tnx_close_col[0]).alias("TNX")])
        irx = irx.select([pl.col(date_col_tnx[0]).alias("Date"), pl.col(irx_close_col[0]).alias("IRX")])
        
        spread = tnx.join(irx, on="Date", how="inner")
        spread = spread.with_columns((pl.col("TNX") - pl.col("IRX")).alias("spread"))
        
        macro_dir = Path("/home/quant/quant-v31/data/parquet/macro")
        macro_dir.mkdir(parents=True, exist_ok=True)
        spread.write_parquet(macro_dir / "YIELD_SPREAD_10Y3M.parquet")
        
        latest = spread.tail(1)
        print(f"  ✅ 10Y-3M Spread: {len(spread)}일, 최신: {latest['spread'][0]:.2f}%")
    except Exception as e:
        print(f"  ❌ 스프레드 실패: {e}")


def print_summary():
    print(f"\n{'=' * 60}")
    print("📊 벤치마크 + 매크로 수집 결과")
    
    for subdir in ["benchmark", "macro"]:
        d = Path(f"/home/quant/quant-v31/data/parquet/{subdir}")
        if d.exists():
            files = list(d.glob("*.parquet"))
            total_size = sum(f.stat().st_size for f in files) / 1024 / 1024
            print(f"  {subdir}/: {len(files)}파일 ({total_size:.1f}MB)")
            for f in sorted(files):
                print(f"    → {f.name} ({f.stat().st_size / 1024:.0f}KB)")
    
    with psycopg.connect(PG_DSN) as conn:
        stats = conn.execute("""
            SELECT count(DISTINCT symbol), count(*), min(time)::date, max(time)::date
            FROM daily_prices
        """).fetchone()
        print(f"  DB daily_prices: {stats[0]}종목, {stats[1]:,}건 ({stats[2]}~{stats[3]})")
        
        # SPY 확인
        spy = conn.execute("SELECT count(*) FROM daily_prices WHERE symbol='SPY'").fetchone()[0]
        print(f"  DB SPY 레코드: {spy}건")
    
    print(f"{'=' * 60}")


def main():
    print("=" * 60)
    print("🌍 V3.1 Phase 1 — 벤치마크 + 매크로 수집 (수정본)")
    print("=" * 60)
    
    collect_benchmarks()
    collect_yield_spread()
    print_summary()


if __name__ == "__main__":
    main()
