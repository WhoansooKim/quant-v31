"""
V3.1 Phase 1 — 15년 OHLCV 데이터 수집
PostgreSQL symbols 테이블의 종목들 → yfinance → Parquet + PostgreSQL 이중 적재
"""
import yfinance as yf
import psycopg
import polars as pl
import numpy as np
from pathlib import Path
from datetime import datetime
import time
import sys

PG_DSN = "postgresql://quant:QuantV31!Secure@localhost:5432/quantdb"
PARQUET_DIR = Path("/home/quant/quant-v31/data/parquet/ohlcv")
BATCH_SIZE = 50   # yfinance 동시 다운로드 수
MIN_DAYS = 252    # 최소 1년 데이터 필요


def get_symbols_from_db() -> list[str]:
    """DB에서 활성 종목 리스트 조회"""
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT ticker FROM symbols WHERE is_active = true ORDER BY ticker"
        ).fetchall()
    return [r[0] for r in rows]


def get_existing_symbols() -> set[str]:
    """이미 DB에 데이터가 있는 종목 확인 (중복 적재 방지)"""
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM daily_prices"
        ).fetchall()
    return {r[0] for r in rows}


def download_batch(symbols: list[str], period: str = "15y") -> dict:
    """yfinance 배치 다운로드"""
    try:
        data = yf.download(
            symbols, period=period,
            group_by="ticker", threads=True,
            progress=False, timeout=30
        )
        return data
    except Exception as e:
        print(f"  ⚠️ 배치 다운로드 실패: {e}")
        return None


def extract_single(data, symbol: str, is_single: bool = False):
    """배치 데이터에서 단일 종목 추출"""
    try:
        if is_single:
            df = data.copy()
        else:
            df = data[symbol].copy()
        
        df = df.dropna(subset=['Close'])
        df = df.reset_index()
        
        if len(df) < MIN_DAYS:
            return None
        
        # 컬럼 정리
        if 'Date' in df.columns:
            df = df.rename(columns={'Date': 'time'})
        elif 'Datetime' in df.columns:
            df = df.rename(columns={'Datetime': 'time'})
        
        return df
    except Exception:
        return None


def save_parquet(df, symbol: str):
    """Parquet 파일 저장"""
    path = PARQUET_DIR / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        pl_df = pl.from_pandas(df)
        pl_df.write_parquet(path)
        return True
    except Exception:
        return False


def save_postgres(df, symbol: str):
    """PostgreSQL daily_prices 테이블에 벌크 INSERT"""
    records = []
    for _, row in df.iterrows():
        try:
            records.append({
                "time": row['time'],
                "symbol": symbol,
                "open": float(row.get('Open', 0)),
                "high": float(row.get('High', 0)),
                "low": float(row.get('Low', 0)),
                "close": float(row.get('Close', 0)),
                "volume": int(row.get('Volume', 0)),
                "adj_close": float(row.get('Adj Close', row.get('Close', 0))),
            })
        except (ValueError, TypeError):
            continue
    
    if not records:
        return 0
    
    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO daily_prices 
                    (time, symbol, open, high, low, close, volume, adj_close)
                VALUES (%(time)s, %(symbol)s, %(open)s, %(high)s,
                        %(low)s, %(close)s, %(volume)s, %(adj_close)s)
                ON CONFLICT (time, symbol) DO UPDATE SET
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    adj_close = EXCLUDED.adj_close
            """, records)
        conn.commit()
    return len(records)


def main():
    print("=" * 60)
    print("📊 V3.1 Phase 1 — 15년 OHLCV 데이터 수집")
    print("=" * 60)
    
    # 종목 리스트
    all_symbols = get_symbols_from_db()
    if not all_symbols:
        print("❌ symbols 테이블이 비어있습니다. 01_build_universe.py를 먼저 실행하세요.")
        return
    
    # 이미 적재된 종목 제외 (재실행 시)
    existing = get_existing_symbols()
    if existing:
        remaining = [s for s in all_symbols if s not in existing]
        print(f"📋 전체: {len(all_symbols)}종목, 기존: {len(existing)}종목, 남은: {len(remaining)}종목")
        symbols = remaining
    else:
        symbols = all_symbols
        print(f"📋 수집 대상: {len(symbols)}종목")
    
    if not symbols:
        print("✅ 모든 종목 데이터가 이미 적재되어 있습니다.")
        return
    
    # 배치 처리
    total_records = 0
    total_symbols = 0
    failed = []
    start_time = time.time()
    
    batches = [symbols[i:i+BATCH_SIZE] for i in range(0, len(symbols), BATCH_SIZE)]
    
    print(f"🚀 {len(batches)}개 배치 ({BATCH_SIZE}종목씩) 시작")
    print(f"⏱️ 예상 소요: 약 {len(batches) * 2}~{len(batches) * 4}분\n")
    
    for bi, batch in enumerate(batches):
        batch_start = time.time()
        print(f"  배치 {bi+1}/{len(batches)}: {batch[0]}~{batch[-1]} ({len(batch)}종목)")
        
        is_single = len(batch) == 1
        
        if is_single:
            data = yf.download(batch[0], period="15y", progress=False, timeout=30)
        else:
            data = download_batch(batch)
        
        if data is None or len(data) == 0:
            failed.extend(batch)
            continue
        
        batch_count = 0
        for sym in batch:
            df = extract_single(data, sym, is_single)
            if df is None:
                failed.append(sym)
                continue
            
            # Parquet 저장
            save_parquet(df, sym)
            
            # PostgreSQL 저장
            n = save_postgres(df, sym)
            if n > 0:
                total_records += n
                total_symbols += 1
                batch_count += 1
        
        elapsed = time.time() - batch_start
        total_elapsed = time.time() - start_time
        remaining_batches = len(batches) - (bi + 1)
        eta = (total_elapsed / (bi + 1)) * remaining_batches
        
        print(f"    → {batch_count}종목 완료 ({elapsed:.1f}초) | "
              f"누적: {total_symbols}종목, {total_records:,}레코드 | "
              f"ETA: {eta/60:.0f}분")
        
        # Rate limiting
        time.sleep(1)
    
    # 결과 요약
    elapsed_total = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"✅ OHLCV 수집 완료!")
    print(f"  종목: {total_symbols}개")
    print(f"  레코드: {total_records:,}건")
    print(f"  소요 시간: {elapsed_total/60:.1f}분")
    print(f"  실패: {len(failed)}종목")
    
    if failed:
        print(f"  실패 목록: {failed[:20]}{'...' if len(failed) > 20 else ''}")
    
    # DB 통계
    with psycopg.connect(PG_DSN) as conn:
        stats = conn.execute("""
            SELECT 
                count(DISTINCT symbol) AS symbols,
                count(*) AS total_records,
                min(time)::date AS earliest,
                max(time)::date AS latest
            FROM daily_prices
        """).fetchone()
        
        print(f"\n📊 DB 통계:")
        print(f"  종목 수: {stats[0]}")
        print(f"  총 레코드: {stats[1]:,}")
        print(f"  데이터 범위: {stats[2]} ~ {stats[3]}")
        
        # Parquet 크기
        total_size = sum(f.stat().st_size for f in PARQUET_DIR.glob("*.parquet"))
        print(f"  Parquet 크기: {total_size / 1024 / 1024:.1f} MB")
    
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
