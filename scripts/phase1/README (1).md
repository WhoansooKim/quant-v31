# V3.1 Phase 1 — 데이터 수집 스크립트

## 사전 준비

```bash
# 추가 패키지 (Wikipedia 테이블 파싱용)
conda activate quant-v31
pip install lxml html5lib

# Docker 서비스 확인
docker ps  # quant-postgres, quant-redis 실행 중이어야 함
```

## 스크립트 배치

```bash
# VM에서 스크립트 폴더 생성 후 파일 복사
mkdir -p ~/quant-v31/scripts/phase1/
# 파일들을 이 폴더에 복사
```

## 실행 방법

### 방법 1: 전체 순서대로 실행 (권장)
```bash
cd ~/quant-v31
python scripts/phase1/run_phase1.py
```

### 방법 2: 개별 실행
```bash
cd ~/quant-v31

# Step 1: 유니버스 구축 (~10~30분)
python scripts/phase1/01_build_universe.py

# Step 2: 15년 OHLCV 수집 (~30분~2시간)
python scripts/phase1/02_collect_ohlcv.py

# Step 3: 벤치마크 + 매크로 (~5분)
python scripts/phase1/03_collect_benchmarks.py

# Step 4: HMM 프로토타입 (~1분)
python scripts/phase1/04_hmm_prototype.py
```

## 참고사항

- `02_collect_ohlcv.py`는 중단 후 재실행 가능 (이미 적재된 종목 자동 건너뜀)
- FRED API 키가 없어도 yfinance로 장단기 스프레드 대체 계산
- HMM 프로토타입은 SPY + VIX 데이터만으로 동작
- 전체 소요시간: 약 1~3시간
