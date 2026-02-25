"""
V3.1 Phase 1 — 유니버스 구축 (수정본)
Wikipedia User-Agent 추가 + 하드코딩 폴백
"""
import yfinance as yf
import psycopg
import time
import json
import urllib.request

PG_DSN = "postgresql://quant:QuantV31!Secure@localhost:5432/quantdb"


def get_sp500_from_wikipedia() -> list[str]:
    """Wikipedia에서 S&P 500 종목 (User-Agent 포함)"""
    try:
        import pandas as pd
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) QuantV31/1.0"})
        html = urllib.request.urlopen(req).read().decode("utf-8")
        tables = pd.read_html(html)
        symbols = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"  📊 S&P 500: {len(symbols)}종목")
        return symbols
    except Exception as e:
        print(f"  ⚠️ S&P 500 Wikipedia 실패: {e}")
        return []


def get_sp400_from_wikipedia() -> list[str]:
    """Wikipedia에서 S&P 400 종목"""
    try:
        import pandas as pd
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) QuantV31/1.0"})
        html = urllib.request.urlopen(req).read().decode("utf-8")
        tables = pd.read_html(html)
        symbols = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"  📊 S&P 400: {len(symbols)}종목")
        return symbols
    except Exception as e:
        print(f"  ⚠️ S&P 400 Wikipedia 실패: {e}")
        return []


def get_sp600_from_wikipedia() -> list[str]:
    """Wikipedia에서 S&P 600 종목"""
    try:
        import pandas as pd
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) QuantV31/1.0"})
        html = urllib.request.urlopen(req).read().decode("utf-8")
        tables = pd.read_html(html)
        symbols = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"  📊 S&P 600: {len(symbols)}종목")
        return symbols
    except Exception as e:
        print(f"  ⚠️ S&P 600 Wikipedia 실패: {e}")
        return []


# ─── 폴백: 핵심 종목 하드코딩 (Wikipedia 실패 시) ───
FALLBACK_SP500 = [
    "AAPL","ABBV","ABT","ACN","ADBE","ADI","ADM","ADP","ADSK","AEE","AEP","AES",
    "AFL","AIG","AIZ","AJG","AKAM","ALB","ALGN","ALK","ALL","ALLE","AMAT","AMCR",
    "AMD","AME","AMGN","AMP","AMT","AMZN","ANET","ANSS","AON","AOS","APA","APD",
    "APH","APTV","ARE","ATO","ATVI","AVB","AVGO","AVY","AWK","AXP","AZO",
    "BA","BAC","BAX","BBWI","BBY","BDX","BEN","BF-B","BIIB","BIO","BK","BKNG",
    "BKR","BLK","BMY","BR","BRK-B","BRO","BSX","BWA","BXP",
    "C","CAG","CAH","CARR","CAT","CB","CBOE","CBRE","CCI","CCL","CDAY","CDNS",
    "CDW","CE","CEG","CF","CFG","CHD","CHRW","CHTR","CI","CINF","CL","CLX","CMA",
    "CMCSA","CME","CMG","CMI","CMS","CNC","CNP","COF","COO","COP","COST","CPB",
    "CPRT","CPT","CRL","CRM","CSCO","CSGP","CSX","CTAS","CTLT","CTRA","CTSH",
    "CTVA","CVS","CVX","CZR",
    "D","DAL","DD","DE","DFS","DG","DGX","DHI","DHR","DIS","DISH","DLR","DLTR",
    "DOV","DOW","DPZ","DRI","DTE","DUK","DVA","DVN","DXC","DXCM",
    "EA","EBAY","ECL","ED","EFX","EIX","EL","EMN","EMR","ENPH","EOG","EPAM",
    "EQIX","EQR","EQT","ES","ESS","ETN","ETR","ETSY","EVRG","EW","EXC","EXPD",
    "EXPE","EXR",
    "F","FANG","FAST","FBHS","FCX","FDS","FDX","FE","FFIV","FIS","FISV","FITB",
    "FLT","FMC","FOX","FOXA","FRC","FRT",
    "GD","GE","GILD","GIS","GL","GLW","GM","GNRC","GOOG","GOOGL","GPC","GPN",
    "GRMN","GS","GWW",
    "HAL","HAS","HBAN","HCA","HD","HOLX","HON","HPE","HPQ","HRL","HSIC","HST","HSY",
    "HUM","HWM",
    "IBM","ICE","IDXX","IEX","IFF","ILMN","INCY","INTC","INTU","INVH","IP","IPG",
    "IQV","IR","IRM","ISRG","IT","ITW","IVZ",
    "J","JBHT","JCI","JKHY","JNJ","JNPR","JPM",
    "K","KDP","KEY","KEYS","KHC","KIM","KLAC","KMB","KMI","KMX","KO","KR",
    "L","LDOS","LEN","LH","LHX","LIN","LKQ","LLY","LMT","LNC","LNT","LOW",
    "LRCX","LUMN","LUV","LVS","LW","LYB","LYV",
    "MA","MAA","MAR","MAS","MCD","MCHP","MCK","MCO","MDLZ","MDT","MET","META",
    "MGM","MHK","MKC","MKTX","MLM","MMC","MMM","MNST","MO","MOH","MOS","MPC",
    "MPWR","MRK","MRNA","MRO","MS","MSCI","MSFT","MSI","MTB","MTCH","MTD","MU",
    "NCLH","NDAQ","NDSN","NEE","NEM","NFLX","NI","NKE","NOC","NOW","NRG","NSC",
    "NTAP","NTRS","NUE","NVDA","NVR","NWL","NWS","NWSA",
    "O","ODFL","OGN","OKE","OMC","ON","ORCL","ORLY","OTIS","OXY",
    "PARA","PAYC","PAYX","PCAR","PCG","PEAK","PEG","PEP","PFE","PFG","PG","PGR",
    "PH","PHM","PKG","PKI","PLD","PM","PNC","PNR","PNW","POOL","PPG","PPL","PRU",
    "PSA","PSX","PTC","PVH","PWR","PXD",
    "QCOM","QRVO",
    "RCL","RE","REG","REGN","RF","RHI","RJF","RL","RMD","ROK","ROL","ROP",
    "ROST","RSG","RTX",
    "SBAC","SBNY","SBUX","SCHW","SEE","SHW","SIVB","SJM","SLB","SNA","SNPS",
    "SO","SPG","SPGI","SRE","STE","STT","STX","STZ","SWK","SWKS","SYF","SYK","SYY",
    "T","TAP","TDG","TDY","TECH","TEL","TER","TFC","TFX","TGT","TMO","TMUS","TPR",
    "TRGP","TRMB","TROW","TRV","TSCO","TSLA","TSN","TT","TTWO","TXN","TXT","TYL",
    "UAL","UDR","UHS","ULTA","UNH","UNP","UPS","URI","USB",
    "V","VFC","VICI","VLO","VMC","VNO","VRSK","VRSN","VRTX","VTR","VTRS","VZ",
    "WAB","WAT","WBA","WBD","WDC","WEC","WELL","WFC","WHR","WM","WMB","WMT",
    "WRB","WRK","WST","WTW","WY","WYNN",
    "XEL","XOM","XRAY","XYL",
    "YUM",
    "ZBH","ZBRA","ZION","ZTS",
]

FALLBACK_SP400_SAMPLE = [
    "ACHC","ACIW","ACLS","AEIS","AGCO","ALKS","ALNY","AMED","AMKR","APA",
    "ASGN","ATKR","AVNT","AZEK","BCO","BECN","BJ","BRKR","BWXT","BWA",
    "CACC","CALM","CARG","CBSH","CCK","CFR","CHE","CIEN","CLF","CLS",
    "COKE","COLM","COMM","CRS","CRVL","CSL","CUBE","CVLT","CW","CWH",
    "DCI","DECK","DINO","DOCS","DT","DUOL","EBC","EEFT","EHC","ENSG",
    "ESAB","ESI","ETSY","EVR","EWBC","EXP","FAF","FCFS","FHN","FIX",
    "FLS","FNB","FSLR","GTES","GXO","HAE","HGV","HLI","HQY","HRB",
    "IART","IBP","IDCC","IIVI","INGR","IONS","IRTC","ITT","JAZZ","JBHT",
    "KNSL","LANC","LBRDK","LFUS","LITE","LIVN","LNTH","LSTR","MANH","MASI",
    "MATX","MEDP","MIDD","MKSI","MKTX","MMSI","MORN","MTDR","MTH","MTSI",
    "NBIX","NCLH","NFG","NOVT","NSA","NTRA","NXST","NYT","OGE","OLED",
    "OMCL","ONB","OSK","OVV","PAGA","PAYC","PCOR","PCTY","PEN","PFSI",
    "PLNT","PNR","POR","POST","POWI","PRGO","PSTG","PTC","PTEN","PVH",
    "QLYS","RBC","REXR","RGLD","RHP","RNR","RVMD","SAIA","SAM","SATS",
    "SCI","SITE","SKX","SLGN","SLM","SMTC","SNDR","SPSC","SSD","STAG",
    "STRA","TKO","TNET","TPX","TREX","TXRH","UFPI","UMBF","UNM","USFD",
    "VEEV","VIRT","VMI","VOYA","VVV","WBS","WEX","WH","WHD","WMS",
    "WPC","WSC","WTRG","X","XPO","YETI",
]

FALLBACK_SP600_SAMPLE = [
    "AAON","ABCB","ABG","ABM","ACA","ACAD","ADMA","AEO","AFYA","AGYS",
    "AIMC","AIT","ALGT","ALMA","AMBA","AMN","AMPH","ANDE","APPF","APOG",
    "ARC","ARCB","ARES","AROC","ASB","ASGN","ASTE","ATEN","ATI","ATKR",
    "AUB","AX","AXNX","AZZ","BANF","BANR","BCRX","BDC","BJRI","BKE",
    "BL","BLKB","BMI","BOOT","BOX","BPMC","BRC","BRZE","BTU","BYD",
    "CAKE","CALX","CARG","CATY","CCRN","CDNA","CENX","CFFN","CHDN","CHEF",
    "CIVI","CJNA","CKH","CLB","CLDX","CLVT","CMD","CNK","CNO","CNXC",
    "COHU","COKE","COLB","COLL","CPRI","CPK","CPRX","CRAI","CRNX","CROX",
    "CRUS","CRK","CSGS","CSWI","CUZ","CVCO","CVGW","CWT","DAN","DBX",
    "DLX","DNLI","DOCN","DRH","DY","EBC","ECPG","EFSC","EGP","ELAN",
    "ENSG","ENS","EPRT","ESRT","ESE","EVTC","EXLS","EYE","FAF","FBMS",
    "FBP","FELE","FIZZ","FL","FLO","FLXS","FN","FORM","FOXF","FSS",
    "FULT","GEF","GEO","GFF","GHC","GKOS","GMS","GPOR","GVA","HA",
    "HAFC","HBI","HCC","HCI","HELE","HI","HLNE","HLX","HMN","HNST",
    "HONE","HP","HQY","HRMY","HSC","HUBG","HUN","HWKN","HXL",
    "IBTX","ICFI","ICLR","IDYA","IESC","IGT","IIPR","IMMR","INDB","INSW",
    "INST","IOSP","ITGR","JBT","JJSF","KALU","KFRC","KFY","KMT","KNF",
]

EXTRA = [
    "AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","BRK-B",
    "JPM","JNJ","V","PG","UNH","HD","MA",
]


def enrich_with_info(symbols: list[str]) -> list[dict]:
    """yfinance로 종목 정보 보강"""
    enriched = []
    total = len(symbols)
    
    for i, sym in enumerate(symbols):
        if (i + 1) % 100 == 0 or i == 0:
            print(f"  📡 종목 정보 수집 중... {i+1}/{total} ({len(enriched)}건 성공)")
        
        try:
            ticker = yf.Ticker(sym)
            info = ticker.info
            
            if not info or 'marketCap' not in info:
                continue
            
            mcap = info.get('marketCap', 0)
            if mcap is None or mcap == 0:
                continue
            
            enriched.append({
                "ticker": sym,
                "company_name": info.get('longName', info.get('shortName', '')),
                "sector": info.get('sector', 'Unknown'),
                "industry": info.get('industry', 'Unknown'),
                "market_cap": float(mcap),
                "exchange": info.get('exchange', 'Unknown'),
                "is_active": True,
                "meta": json.dumps({
                    "currency": info.get('currency', 'USD'),
                    "country": info.get('country', ''),
                }),
            })
            
        except Exception:
            pass
        
        if (i + 1) % 200 == 0:
            time.sleep(2)
    
    return enriched


def save_to_postgres(records: list[dict]):
    """PostgreSQL symbols 테이블에 저장"""
    with psycopg.connect(PG_DSN) as conn:
        inserted = 0
        for r in records:
            try:
                conn.execute("""
                    INSERT INTO symbols (ticker, company_name, sector, industry,
                                        market_cap, exchange, is_active, meta)
                    VALUES (%(ticker)s, %(company_name)s, %(sector)s, %(industry)s,
                            %(market_cap)s, %(exchange)s, %(is_active)s, %(meta)s::jsonb)
                    ON CONFLICT (ticker) DO UPDATE SET
                        company_name = EXCLUDED.company_name,
                        sector = EXCLUDED.sector,
                        industry = EXCLUDED.industry,
                        market_cap = EXCLUDED.market_cap,
                        exchange = EXCLUDED.exchange,
                        meta = EXCLUDED.meta,
                        updated_at = now()
                """, r)
                inserted += 1
            except Exception as e:
                print(f"  ⚠️ {r['ticker']} 저장 실패: {e}")
        conn.commit()
    return inserted


def main():
    print("=" * 60)
    print("🏗️ V3.1 유니버스 구축")
    print("=" * 60)
    
    all_symbols = set()
    
    # 1. Wikipedia (User-Agent 포함)
    print("\n📋 Step 1: Wikipedia에서 S&P 구성종목 수집")
    sp500 = get_sp500_from_wikipedia()
    sp400 = get_sp400_from_wikipedia()
    sp600 = get_sp600_from_wikipedia()
    
    all_symbols.update(sp500)
    all_symbols.update(sp400)
    all_symbols.update(sp600)
    
    # 2. Wikipedia 실패 시 폴백
    if len(sp500) == 0:
        print(f"  → S&P 500 폴백 사용: {len(FALLBACK_SP500)}종목")
        all_symbols.update(FALLBACK_SP500)
    if len(sp400) == 0:
        print(f"  → S&P 400 폴백 사용: {len(FALLBACK_SP400_SAMPLE)}종목")
        all_symbols.update(FALLBACK_SP400_SAMPLE)
    if len(sp600) == 0:
        print(f"  → S&P 600 폴백 사용: {len(FALLBACK_SP600_SAMPLE)}종목")
        all_symbols.update(FALLBACK_SP600_SAMPLE)
    
    # 3. 추가 종목
    all_symbols.update(EXTRA)
    
    # 정리 (유효한 심볼만)
    all_symbols = sorted([s for s in all_symbols 
                          if isinstance(s, str) and 1 <= len(s) <= 6
                          and s.replace("-", "").isalpha()])
    
    print(f"\n📊 총 후보: {len(all_symbols)}종목")
    
    # 4. 종목 정보 보강
    print("\n📡 Step 2: 종목 정보 수집 (시가총액, 섹터)")
    print(f"  ⏱️ 예상 소요: 약 {len(all_symbols) // 60}~{len(all_symbols) // 30}분")
    enriched = enrich_with_info(all_symbols)
    print(f"\n  → 정보 수집 완료: {len(enriched)}종목")
    
    # 5. 시가총액 통계
    small_mid = [r for r in enriched if 300e6 <= r['market_cap'] <= 10e9]
    large = [r for r in enriched if r['market_cap'] > 10e9]
    micro = [r for r in enriched if r['market_cap'] < 300e6]
    
    print(f"\n📊 시가총액 분포:")
    print(f"  Micro (<$300M):          {len(micro)}종목")
    print(f"  Small/Mid ($300M~$10B):  {len(small_mid)}종목 ← 메인 유니버스")
    print(f"  Large ($10B+):           {len(large)}종목 (참고용)")
    
    # 6. PostgreSQL 저장
    print(f"\n💾 Step 3: PostgreSQL 저장")
    inserted = save_to_postgres(enriched)
    print(f"  → {inserted}종목 저장 완료")
    
    # 7. 섹터 분포
    print(f"\n📊 섹터 분포:")
    sectors = {}
    for r in enriched:
        s = r['sector']
        sectors[s] = sectors.get(s, 0) + 1
    for s, c in sorted(sectors.items(), key=lambda x: -x[1]):
        print(f"  {s:30s}: {c}종목")
    
    # 8. DB 확인
    with psycopg.connect(PG_DSN) as conn:
        count = conn.execute("SELECT count(*) FROM symbols").fetchone()[0]
        print(f"\n✅ DB symbols 테이블: {count}종목")
    
    print("\n" + "=" * 60)
    print("🎉 유니버스 구축 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
