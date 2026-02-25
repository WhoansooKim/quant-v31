import { useState } from "react";

// ─── Design System (DevPlan.jsx 통일) ───
const C = {
  bg: "#05060b", s1: "#0a0c15", s2: "#0f111c", s3: "#141729",
  bd: "#1c2040", t: "#a8afc4", tm: "#555d78", tb: "#dde1ed", tw: "#f0f2f8",
  emerald: "#10b981", blue: "#3b82f6", violet: "#8b5cf6",
  amber: "#f59e0b", rose: "#f43f5e", cyan: "#06b6d4",
  orange: "#f97316", lime: "#84cc16", pink: "#ec4899",
};

const Card = ({ children, s, accent }) => (
  <div style={{ background: C.s1, borderRadius: 10, border: `1px solid ${C.bd}`, padding: "14px 16px",
    ...(accent ? { borderLeft: `3px solid ${accent}` } : {}), ...s }}>{children}</div>
);
const Sec = ({ children, c = C.blue }) => (
  <div style={{ fontWeight: 800, color: C.tb, fontSize: 14, margin: "22px 0 10px", paddingBottom: 7,
    borderBottom: `2px solid ${c}28`, display: "flex", alignItems: "center", gap: 8 }}>
    <div style={{ width: 3, height: 16, background: c, borderRadius: 2 }} />{children}
  </div>
);
const Info = ({ c, icon, title, children }) => (
  <div style={{ background: `${c}06`, border: `1px solid ${c}18`, borderRadius: 10, padding: "12px 14px", margin: "10px 0" }}>
    <div style={{ color: c, fontWeight: 700, fontSize: 13, marginBottom: 4 }}>{icon} {title}</div>
    <div style={{ color: C.t, fontSize: 11.5, lineHeight: 1.75 }}>{children}</div>
  </div>
);
const Warn = ({ children }) => (
  <div style={{ background: "#f59e0b08", border: "1px solid #f59e0b20", borderRadius: 8, padding: "10px 12px",
    margin: "8px 0", fontSize: 11, color: C.amber, lineHeight: 1.7 }}>⚠️ {children}</div>
);
const Tag = ({ children, c = C.blue }) => (
  <span style={{ background: `${c}14`, color: c, padding: "1px 7px", borderRadius: 4,
    fontSize: 9.5, fontFamily: "monospace", fontWeight: 700 }}>{children}</span>
);
const Pre = ({ children }) => (
  <pre style={{ color: C.emerald, fontSize: 9.5, lineHeight: 1.5,
    fontFamily: "'JetBrains Mono','Fira Code','Consolas',monospace",
    margin: "6px 0", overflowX: "auto", whiteSpace: "pre", padding: "12px 14px",
    background: "#04050a", borderRadius: 8, border: `1px solid ${C.bd}` }}>{children}</pre>
);
const Step = ({ n, title, c = C.amber, tag }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "20px 0 8px" }}>
    <span style={{ background: c, color: "#fff", width: 26, height: 26, borderRadius: "50%",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: 12, fontWeight: 800, flexShrink: 0 }}>{n}</span>
    <span style={{ color: C.tw, fontWeight: 700, fontSize: 13 }}>{title}</span>
    {tag && <Tag c={c}>{tag}</Tag>}
  </div>
);
const Chk = ({ items, c = C.emerald }) => items.map((x, i) => (
  <div key={i} style={{ display: "flex", gap: 8, padding: "4px 0", fontSize: 11, color: C.t }}>
    <span style={{ color: c, flexShrink: 0 }}>☐</span><span>{x}</span>
  </div>
));
const Stat = ({ items }) => (
  <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(items.length, 4)}, 1fr)`, gap: 6, margin: "8px 0" }}>
    {items.map((it, i) => (
      <div key={i} style={{ background: C.s2, borderRadius: 8, padding: "10px 12px", border: `1px solid ${C.bd}`,
        boxShadow: `0 0 12px ${it.c}08` }}>
        <div style={{ color: it.c, fontSize: 9.5, fontWeight: 600, marginBottom: 2 }}>{it.label}</div>
        <div style={{ color: C.tw, fontSize: 16, fontWeight: 800 }}>{it.value}</div>
        {it.sub && <div style={{ color: C.tm, fontSize: 9, marginTop: 1 }}>{it.sub}</div>}
      </div>
    ))}
  </div>
);
const Tbl = ({ headers, rows, colors }) => (
  <div style={{ borderRadius: 8, overflow: "hidden", border: `1px solid ${C.bd}`, margin: "8px 0", fontSize: 11 }}>
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${headers.length}, 1fr)`, background: C.s3, padding: "6px 10px" }}>
      {headers.map((h, i) => <span key={i} style={{ color: colors?.[i] || C.tm, fontWeight: 700, fontSize: 10 }}>{h}</span>)}
    </div>
    {rows.map((r, i) => (
      <div key={i} style={{ display: "grid", gridTemplateColumns: `repeat(${headers.length}, 1fr)`,
        padding: "5px 10px", background: i % 2 === 0 ? C.s1 : "transparent", borderTop: `1px solid ${C.bd}06` }}>
        {r.map((cell, j) => <span key={j} style={{ color: j === 0 ? C.tb : C.t, fontWeight: j === 0 ? 600 : 400 }}>{cell}</span>)}
      </div>
    ))}
  </div>
);

// ═══════════════════════════════════════════════════════════════
// PAGE 1: 개요 + 전제조건
// ═══════════════════════════════════════════════════════════════
function Overview() {
  return (<div>
    <Info c={C.amber} icon="🏗️" title="Phase 3: 시스템 통합 + Blazor Server 대시보드 + systemd (15~18개월차)">
      Phase 2에서 개발한 5개 전략 + HMM 레짐 + Kill Switch를 <b>8단계 오케스트레이터</b>로 통합하고,
      <b>Blazor Server 대시보드</b>로 실시간 모니터링하며, <b>systemd</b>로 자동 관리하는 단계입니다.
    </Info>

    <Sec c={C.amber}>Phase 3 전체 구조 (4주 × 4 = 16주)</Sec>
    <Stat items={[
      { c: C.rose, label: "Week 1~4", value: "오케스트레이터", sub: "8단계 파이프라인 통합" },
      { c: C.cyan, label: "Week 5~8", value: "Blazor Server", sub: "대시보드 + Npgsql + SignalR" },
      { c: C.violet, label: "Week 9~12", value: "gRPC + 연동", sub: "Telegram + SHAP + 스케줄러" },
      { c: C.emerald, label: "Week 13~16", value: "systemd + 검증", sub: "서비스 등록 + E2E 테스트" },
    ]} />

    <Sec c={C.blue}>Phase 2 완료 전제조건 확인</Sec>
    <Warn>
      Phase 3를 시작하기 전에 아래 항목이 모두 완료되어 있어야 합니다.
      하나라도 미완성이면 해당 모듈을 먼저 완료하세요.
    </Warn>
    <Chk c={C.blue} items={[
      "HMM 레짐 엔진 완성 + PG 직접 조회 + 15년 검증 통과 (engine/risk/regime.py)",
      "Kill Switch 3단계 + ATR 사이징 구현 완료 (engine/risk/kill_switch.py, position_sizer.py)",
      "① Low-Vol+Quality 전략 (SQL CTE 팩터 계산 연동)",
      "② Vol-Managed 모멘텀 전략 (Bull 레짐 풀 가동 확인)",
      "③ 페어즈 트레이딩 (mv_sector_correlations 물리뷰 동작)",
      "④ Vol-Targeting 오버레이 (레짐 스케일 연동)",
      "⑤ FinBERT+Claude 하이브리드 센티먼트",
      "PostgreSQL + TimescaleDB 정상 가동 (hypertable 7개 + 연속집계)",
      "Redis 7 캐시 정상 가동",
      "Alpaca Paper $100K 연동 확인",
    ]} />

    <Sec c={C.emerald}>Phase 3 산출물 목록</Sec>
    <Pre>{`quant-v31/
├── engine/
│   ├── api/
│   │   ├── main.py                 # ★ 8단계 오케스트레이터 (신규)
│   │   ├── routes/
│   │   │   ├── signals.py          # REST 시그널 엔드포인트
│   │   │   ├── portfolio.py        # 포트폴리오 API
│   │   │   ├── regime.py           # 레짐 상태 API
│   │   │   └── health.py           # 헬스체크
│   │   └── grpc_server.py          # ★ gRPC 서버 (신규)
│   ├── execution/
│   │   ├── scheduler.py            # ★ APScheduler 통합 (신규)
│   │   └── alerts.py               # ★ Telegram Bot (신규)
│   └── explain/
│       ├── feature_importance.py   # ★ SHAP 시각화 (신규)
│       └── regime_visualizer.py    # ★ 레짐 시각화 데이터 (신규)
├── dashboard/                      # ★ Blazor Server 전체 (신규)
│   └── QuantDashboard/
│       ├── Program.cs
│       ├── Components/Pages/
│       │   ├── Home.razor
│       │   ├── Regime.razor
│       │   ├── Risk.razor
│       │   ├── Strategies.razor
│       │   └── Sentiment.razor
│       └── Services/
│           ├── PostgresService.cs
│           ├── GrpcClient.cs
│           └── RealtimeHub.cs
├── proto/                          # ★ gRPC 프로토 (신규)
│   ├── signals.proto
│   ├── portfolio.proto
│   └── regime.proto
└── systemd/                        # ★ 서비스 파일 (신규)
    ├── quant-engine.service
    ├── quant-dashboard.service
    └── quant-scheduler.service`}</Pre>
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// PAGE 2: STEP 3.1 — 오케스트레이터
// ═══════════════════════════════════════════════════════════════
function Orchestrator() {
  return (<div>
    <Info c={C.rose} icon="🎯" title="Step 3.1 — 8단계 오케스트레이터 (Week 1~4)">
      Phase 2에서 개별적으로 작동하던 레짐 감지, Kill Switch, 5개 전략, 센티먼트, Vol-Targeting, 포지션 사이징, VWAP 실행을
      하나의 <b>일일 파이프라인</b>으로 통합합니다. 모든 데이터는 PostgreSQL에서 조회하고 결과를 기록합니다.
    </Info>

    <Sec c={C.rose}>8단계 파이프라인 흐름도</Sec>
    <Pre>{`┌─────────────────────────────────────────────────────┐
│            PortfolioOrchestrator.execute_daily()      │
│                                                       │
│  ① 레짐 감지 ─────────────────────────────────────┐  │
│     HMM → Bull/Sideways/Bear 확률                  │  │
│     → PG regime_history INSERT + Redis 캐시        │  │
│                                                     │  │
│  ② Kill Switch 업데이트 ───────────────────────┐   │  │
│     MDD 계산 → DefenseLevel 판정               │   │  │
│     EMERGENCY → 즉시 청산 + return              │   │  │
│                                                 │   │  │
│  ③ 레짐별 배분 매트릭스 ─────────────────┐     │   │  │
│     regime_allocator.get_allocation()     │     │   │  │
│     + exposure_limit 적용                 │     │   │  │
│                                           │     │   │  │
│  ④ 전략 시그널 생성 ──────────────┐      │     │   │  │
│     kill_switch.allowed_strategies │      │     │   │  │
│     → 허용된 전략만 실행          │      │     │   │  │
│     → PG signal_log INSERT        │      │     │   │  │
│                                    │      │     │   │  │
│  ⑤ 센티먼트 오버레이 ─────┐      │      │     │   │  │
│     FinBERT + Claude hybrid │      │      │     │   │  │
│     → 시그널 강도 조절      │      │      │     │   │  │
│                              │      │      │     │   │  │
│  ⑥ Vol-Targeting ────┐      │      │      │     │   │  │
│     vol_scale 적용    │      │      │      │     │   │  │
│                       │      │      │      │     │   │  │
│  ⑦ ATR 포지션 사이징  │      │      │      │     │   │  │
│     → 종목별 수량 결정 │      │      │      │     │   │  │
│                       │      │      │      │     │   │  │
│  ⑧ VWAP 분할 실행    │      │      │      │     │   │  │
│     → Alpaca 주문     │      │      │      │     │   │  │
│     → PG trades INSERT │      │      │      │     │   │  │
│     → PG snapshot INSERT│     │      │      │     │   │  │
│     → Telegram 알림    │      │      │      │     │   │  │
└─────────────────────────────────────────────────────┘`}</Pre>

    <Step n="1" title="engine/api/main.py — 핵심 오케스트레이터" tag="핵심" c={C.rose} />
    <Pre>{`# engine/api/main.py
"""V3.1 8-Step Daily Pipeline Orchestrator (PostgreSQL Edition)"""

from fastapi import FastAPI, BackgroundTasks
from contextlib import asynccontextmanager
import logging, asyncio
from datetime import datetime

from engine.config.settings import Settings
from engine.data.storage import PostgresStore, RedisCache
from engine.risk.regime import RegimeDetector
from engine.risk.regime_allocator import RegimeAllocator
from engine.risk.kill_switch import DrawdownKillSwitch, DefenseLevel
from engine.risk.position_sizer import DynamicPositionSizer
from engine.strategies.lowvol_quality import LowVolQuality
from engine.strategies.vol_momentum import VolManagedMomentum
from engine.strategies.pairs_trading import PairsTrading
from engine.strategies.vol_targeting import VolTargeting
from engine.strategies.llm_overlay import SentimentOverlay
from engine.execution.alpaca_client import AlpacaExecutor
from engine.execution.vwap import VWAPExecutor
from engine.execution.alerts import TelegramAlert

logger = logging.getLogger("orchestrator")
config = Settings()

# ─── Shared Resources ───
pg = PostgresStore(config.pg_dsn)
cache = RedisCache(config.redis_url)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 리소스 초기화"""
    logger.info("🚀 Quant V3.1 Engine starting...")
    app.state.orchestrator = PortfolioOrchestrator()
    yield
    logger.info("🛑 Engine shutting down")

app = FastAPI(title="Quant V3.1 Engine", lifespan=lifespan)

class PortfolioOrchestrator:
    """일일 8단계 파이프라인 — 모든 데이터 PostgreSQL 연동"""
    
    def __init__(self):
        # ─── 레짐 엔진 (PG에서 SPY 로드 후 학습) ───
        self.regime_detector = RegimeDetector(
            n_states=config.hmm_n_states,
            lookback_days=config.hmm_lookback_days
        )
        spy_data = pg.get_ohlcv("SPY", days=config.hmm_lookback_days)
        self.regime_detector.fit(spy_data)
        logger.info("✅ HMM 레짐 모델 로드 완료")
        
        # ─── 배분 + 방어 + 사이징 ───
        self.allocator = RegimeAllocator(self.regime_detector)
        self.kill_switch = DrawdownKillSwitch()
        self.sizer = DynamicPositionSizer(
            risk_per_trade=config.risk_per_trade,
            kelly_fraction=config.kelly_fraction,
            max_position=config.max_position_pct,
            max_sector=config.max_sector_pct
        )
        
        # ─── 5 전략 ───
        self.strategies = {
            "LowVolQuality": LowVolQuality(pg, config),
            "VolManagedMomentum": VolManagedMomentum(pg, config),
            "PairsTrading": PairsTrading(pg, config),
        }
        self.vol_targeting = VolTargeting(pg, config)
        self.sentiment = SentimentOverlay(pg, config)
        
        # ─── 실행 ───
        self.executor = AlpacaExecutor(config)
        self.vwap = VWAPExecutor(self.executor)
        self.telegram = TelegramAlert(config)
        
        # ─── 상태 ───
        self.current_alloc = {}
        self.last_regime = None
        
        # ─── 초기 PV로 peak 설정 ───
        pv = self.executor.get_portfolio_value()
        self.kill_switch.peak_value = pv
        logger.info(f"✅ 초기 포트폴리오: ${pv:,.2f}")
    
    async def execute_daily(self):
        """=== 일일 8단계 파이프라인 ==="""
        start = datetime.now()
        logger.info(f"{'='*50}")
        logger.info(f"🎯 일일 파이프라인 시작: {start.isoformat()}")
        
        try:
            # ══════════════════════════════════════
            # STEP 1: 레짐 감지
            # ══════════════════════════════════════
            spy_data = pg.get_ohlcv("SPY", days=config.hmm_lookback_days)
            regime = self.regime_detector.predict_current_regime(spy_data)
            
            # DB + Cache 기록
            is_transition = (self.last_regime and 
                           self.last_regime != regime["current"])
            pg.insert_regime({
                "regime": regime["current"],
                "bull": regime.get("bull", 0),
                "sideways": regime.get("sideways", 0),
                "bear": regime.get("bear", 0),
                "confidence": regime[regime["current"]],
                "prev": self.last_regime or "unknown",
                "transition": is_transition,
            })
            cache.set_regime(regime)
            
            if is_transition:
                await self.telegram.send(
                    f"🎯 레짐 전환: {self.last_regime} → {regime['current']}\\n"
                    f"확률: Bull {regime.get('bull',0):.1%} | "
                    f"Side {regime.get('sideways',0):.1%} | "
                    f"Bear {regime.get('bear',0):.1%}"
                )
            self.last_regime = regime["current"]
            logger.info(f"  ① 레짐: {regime['current']} "
                       f"(conf={regime[regime['current']]:.1%})")
            
            # ══════════════════════════════════════
            # STEP 2: Kill Switch
            # ══════════════════════════════════════
            pv = self.executor.get_portfolio_value()
            prev_level = self.kill_switch.current_level
            kill = self.kill_switch.update(pv)
            mdd = ((pv - self.kill_switch.peak_value) 
                   / self.kill_switch.peak_value)
            
            if kill != prev_level:
                pg.insert_kill_switch_event(
                    prev_level.name, kill.name, mdd, pv,
                    self.kill_switch.get_exposure_limit(),
                    self.kill_switch.cooldown_until
                )
                await self.telegram.send(
                    f"🛡️ Kill Switch: {prev_level.name} → {kill.name}\\n"
                    f"MDD: {mdd:.2%} | PV: ${pv:,.2f}"
                )
            
            if kill == DefenseLevel.EMERGENCY:
                logger.warning("🚨 EMERGENCY: 전량 청산 실행")
                await self._emergency_liquidate(pv, regime, kill)
                return
            
            logger.info(f"  ② Kill Switch: {kill.name} "
                       f"(MDD={mdd:.2%}, exp={self.kill_switch.get_exposure_limit():.0%})")
            
            # ══════════════════════════════════════
            # STEP 3: 레짐별 배분
            # ══════════════════════════════════════
            alloc = self.allocator.get_allocation(
                spy_data, self.current_alloc)
            exp_limit = self.kill_switch.get_exposure_limit()
            
            # Kill Switch exposure 제한 적용
            for key in alloc:
                if key.startswith("_"): continue
                if isinstance(alloc[key], (int, float)) and key != "cash":
                    alloc[key] = min(alloc[key], 
                                    alloc[key] * exp_limit)
            
            self.current_alloc = alloc
            logger.info(f"  ③ 배분: {dict((k,f'{v:.1%}') for k,v in alloc.items() if not k.startswith('_') and isinstance(v,float))}")
            
            # ══════════════════════════════════════
            # STEP 4: 전략 시그널 생성
            # ══════════════════════════════════════
            all_signals = {}
            allowed = self.kill_switch.get_allowed_strategies()
            
            for name, strat in self.strategies.items():
                if "all" not in allowed and name not in allowed:
                    logger.info(f"  ④ {name}: BLOCKED by Kill Switch")
                    continue
                
                try:
                    sigs = strat.generate_signals(
                        regime["current"], 
                        regime[regime["current"]]
                    )
                    all_signals[name] = sigs
                    
                    # 시그널 DB 기록
                    for sig in sigs:
                        pg.insert_signal(
                            sig["symbol"], sig["direction"],
                            sig["strength"], name, regime["current"]
                        )
                    logger.info(f"  ④ {name}: {len(sigs)} 시그널")
                except Exception as e:
                    logger.error(f"  ④ {name} ERROR: {e}")
            
            if not all_signals:
                logger.info("  → 시그널 없음, 스냅샷만 기록")
                self._record_snapshot(pv, regime, kill)
                return
            
            # ══════════════════════════════════════
            # STEP 5: 센티먼트 오버레이
            # ══════════════════════════════════════
            symbols_in_signals = set()
            for sigs in all_signals.values():
                for sig in sigs:
                    symbols_in_signals.add(sig["symbol"])
            
            sentiment_adj = {}
            if symbols_in_signals:
                sentiment_adj = await self.sentiment.overlay(
                    list(symbols_in_signals), regime["current"])
            logger.info(f"  ⑤ 센티먼트: {len(sentiment_adj)} 종목 조정")
            
            # 시그널 강도에 센티먼트 반영
            for name, sigs in all_signals.items():
                for sig in sigs:
                    sym = sig["symbol"]
                    if sym in sentiment_adj:
                        adj = sentiment_adj[sym]
                        sig["strength"] *= (1 + adj * alloc.get(
                            "sentiment_range", 0.15))
            
            # ══════════════════════════════════════
            # STEP 6: Vol-Targeting
            # ══════════════════════════════════════
            vol_scale = self.vol_targeting.calculate_scale(
                regime["current"])
            logger.info(f"  ⑥ Vol-Targeting: scale={vol_scale:.2f}x")
            
            # ══════════════════════════════════════
            # STEP 7: ATR 포지션 사이징
            # ══════════════════════════════════════
            orders = []
            for name, sigs in all_signals.items():
                strategy_weight = alloc.get(name, 0)
                for sig in sigs:
                    if abs(sig["strength"]) < 0.1:
                        continue
                    
                    atr_14 = pg.get_atr(sig["symbol"], period=14)
                    price = pg.get_latest_price(sig["symbol"])
                    
                    base_qty = self.sizer.atr_based_size(
                        price, atr_14, pv)
                    
                    # 전략 배분 + Vol Scale 적용
                    adj_qty = int(base_qty * strategy_weight 
                                 * vol_scale * sig["strength"])
                    
                    if adj_qty > 0:
                        orders.append({
                            "symbol": sig["symbol"],
                            "side": sig["direction"],
                            "qty": adj_qty,
                            "strategy": name,
                            "strength": sig["strength"],
                        })
            
            logger.info(f"  ⑦ 사이징: {len(orders)} 주문 준비")
            
            # ══════════════════════════════════════
            # STEP 8: VWAP 분할 실행
            # ══════════════════════════════════════
            results = []
            for order in orders:
                result = await self.vwap.execute(
                    order["symbol"], order["side"],
                    order["qty"], slices=5
                )
                if result:
                    # 거래 기록 → PG
                    pg.insert_trade({
                        "order_id": result["order_id"],
                        "symbol": order["symbol"],
                        "strategy": order["strategy"],
                        "side": order["side"],
                        "qty": result["filled_qty"],
                        "price": result["avg_price"],
                        "slippage": result.get("slippage", 0),
                        "commission": 0,
                        "regime": regime["current"],
                        "kill_level": kill.name,
                        "is_paper": config.alpaca_paper,
                    })
                    results.append(result)
            
            logger.info(f"  ⑧ VWAP 실행: {len(results)}/{len(orders)} 체결")
            
            # ─── 스냅샷 기록 ───
            pv_after = self.executor.get_portfolio_value()
            self._record_snapshot(pv_after, regime, kill, vol_scale)
            
            # ─── 결과 알림 ───
            elapsed = (datetime.now() - start).total_seconds()
            await self.telegram.send(
                f"✅ 일일 파이프라인 완료 ({elapsed:.1f}s)\\n"
                f"레짐: {regime['current']} | Kill: {kill.name}\\n"
                f"시그널: {sum(len(s) for s in all_signals.values())} | "
                f"체결: {len(results)}\\n"
                f"PV: ${pv_after:,.2f} (MDD: {mdd:.2%})"
            )
            
        except Exception as e:
            logger.error(f"🚨 파이프라인 오류: {e}", exc_info=True)
            await self.telegram.send(f"🚨 파이프라인 오류: {e}")
    
    def _record_snapshot(self, value, regime, kill, vol_scale=1.0):
        """포트폴리오 스냅샷 → PostgreSQL"""
        mdd = ((value - self.kill_switch.peak_value) 
               / self.kill_switch.peak_value)
        with pg.get_conn() as conn:
            conn.execute("""
                INSERT INTO portfolio_snapshots
                    (total_value, regime, regime_confidence,
                     kill_level, exposure_limit, vol_scale,
                     max_drawdown)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (value, regime["current"], 
                  regime[regime["current"]],
                  kill.name, 
                  self.kill_switch.get_exposure_limit(),
                  vol_scale, mdd))
            conn.commit()
    
    async def _emergency_liquidate(self, pv, regime, kill):
        """EMERGENCY: 전량 청산"""
        positions = self.executor.get_positions()
        for pos in positions:
            await self.executor.close_position(pos.symbol)
        
        self._record_snapshot(pv, regime, kill)
        await self.telegram.send(
            f"🚨 EMERGENCY 전량 청산 완료\\n"
            f"포지션 {len(positions)}개 → 현금 전환\\n"
            f"냉각기: 30일 (재진입 불가)"
        )

# ─── FastAPI Routes ───
@app.get("/health")
async def health():
    return {"status": "ok", "version": "3.1-ubuntu"}

@app.post("/run")
async def run_pipeline(bg: BackgroundTasks):
    bg.add_task(app.state.orchestrator.execute_daily)
    return {"status": "pipeline_started"}

@app.get("/regime")
async def get_regime():
    return cache.get_regime() or pg.get_latest_regime()

@app.get("/portfolio")
async def get_portfolio():
    return pg.get_latest_snapshot()`}</Pre>

    <Step n="2" title="storage.py 추가 메서드 (Phase 3 필요분)" tag="추가" c={C.cyan} />
    <Pre>{`# engine/data/storage.py — Phase 3 추가 메서드

class PostgresStore:
    # ... (Phase 1~2 기존 메서드 유지)
    
    def insert_signal(self, symbol, direction, strength,
                      strategy, regime):
        """시그널 기록 → signal_log hypertable"""
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO signal_log 
                    (symbol, direction, strength, strategy, regime)
                VALUES (%s, %s, %s, %s, %s)
            """, (symbol, direction, strength, strategy, regime))
            conn.commit()
    
    def insert_trade(self, trade: dict):
        """거래 기록 → trades 테이블"""
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO trades
                    (order_id, symbol, strategy, side, qty, price,
                     slippage, commission, regime, kill_level, is_paper, meta)
                VALUES (%(order_id)s, %(symbol)s, %(strategy)s,
                        %(side)s, %(qty)s, %(price)s, %(slippage)s,
                        %(commission)s, %(regime)s, %(kill_level)s,
                        %(is_paper)s, '{}'::jsonb)
            """, trade)
            conn.commit()
    
    def insert_kill_switch_event(self, from_level, to_level,
                                  mdd, pv, exp_limit, cooldown):
        """Kill Switch 이벤트 → kill_switch_log"""
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO kill_switch_log
                    (from_level, to_level, current_mdd,
                     portfolio_value, exposure_limit, cooldown_until)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (from_level, to_level, mdd, pv, 
                  exp_limit, cooldown))
            conn.commit()
    
    def get_atr(self, symbol, period=14):
        """ATR 계산 (TimescaleDB 활용)"""
        with self.get_conn() as conn:
            row = conn.execute("""
                WITH tr AS (
                    SELECT time,
                        GREATEST(
                            high - low,
                            ABS(high - LAG(close) OVER (ORDER BY time)),
                            ABS(low - LAG(close) OVER (ORDER BY time))
                        ) AS true_range
                    FROM daily_prices
                    WHERE symbol = %s
                    ORDER BY time DESC
                    LIMIT %s + 1
                )
                SELECT AVG(true_range) AS atr
                FROM tr WHERE true_range IS NOT NULL
            """, (symbol, period)).fetchone()
        return row["atr"] if row else 0
    
    def get_latest_price(self, symbol):
        """최신 종가"""
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT close FROM daily_prices
                WHERE symbol = %s
                ORDER BY time DESC LIMIT 1
            """, (symbol,)).fetchone()
        return row["close"] if row else 0
    
    def get_latest_snapshot(self):
        """최신 포트폴리오 스냅샷"""
        with self.get_conn() as conn:
            return conn.execute("""
                SELECT * FROM portfolio_snapshots
                ORDER BY time DESC LIMIT 1
            """).fetchone()`}</Pre>

    <Sec c={C.amber}>Week 1~4 체크리스트</Sec>
    <Chk c={C.amber} items={[
      "Week 1: PortfolioOrchestrator 클래스 스켈레톤 + Step 1~2 (레짐 + Kill Switch)",
      "Week 2: Step 3~5 (배분 + 시그널 + 센티먼트 오버레이)",
      "Week 3: Step 6~8 (Vol-Targeting + 사이징 + VWAP 실행)",
      "Week 4: 통합 테스트 — 수동 /run 호출로 전체 파이프라인 1회 실행 성공",
      "모든 INSERT 쿼리가 PG에 정상 기록되는지 확인 (psql로 SELECT)",
      "Telegram 알림 수신 확인 (레짐 전환, Kill Switch, 매매 완료)",
    ]} />
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// PAGE 3: STEP 3.2 — BLAZOR SERVER
// ═══════════════════════════════════════════════════════════════
function BlazorServer() {
  return (<div>
    <Info c={C.cyan} icon="🔷" title="Step 3.2 — Blazor Server 대시보드 (Week 5~8)">
      Ubuntu에서 .NET 8 Blazor Server WebApp을 생성하고, <b>Npgsql</b>로 PostgreSQL 직접 조회,
      <b>SignalR</b>로 실시간 푸시, <b>gRPC</b>로 Python 엔진 연동하는 대시보드를 구축합니다.
    </Info>

    <Step n="1" title="Blazor Server 프로젝트 생성 + NuGet 패키지" tag="Week 5" c={C.cyan} />
    <Pre>{`# Ubuntu VM에서 실행
cd ~/quant-v31/dashboard
dotnet new blazor -n QuantDashboard --interactivity Server
cd QuantDashboard

# ★ 필수 NuGet 패키지
dotnet add package Npgsql --version 8.0.6
dotnet add package Grpc.Net.Client --version 2.67.0
dotnet add package Google.Protobuf --version 3.28.3
dotnet add package Grpc.Tools --version 2.67.0

# (선택) DevExpress Blazor — 차트/그리드 
# 라이센스 필요, 대안: Radzen.Blazor (무료)
dotnet add package Radzen.Blazor --version 5.0.0

# 빌드 + 실행 테스트
dotnet build
dotnet run --urls "http://0.0.0.0:5000"
# → 브라우저: http://VM_IP:5000 접속 확인`}</Pre>

    <Step n="2" title="Program.cs — DI 서비스 등록" tag="Week 5" c={C.cyan} />
    <Pre>{`// dashboard/QuantDashboard/Program.cs
var builder = WebApplication.CreateBuilder(args);

// ─── Blazor Server ───
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

// ─── ★ PostgreSQL 서비스 (Npgsql 직접) ───
builder.Services.AddSingleton<PostgresService>(sp =>
    new PostgresService(
        builder.Configuration.GetConnectionString("Default")));

// ─── ★ gRPC Client (Python 엔진 연동) ───
builder.Services.AddSingleton<GrpcClient>(sp =>
    new GrpcClient(
        builder.Configuration["GrpcUrl"] ?? "http://localhost:50051"));

// ─── ★ SignalR Hub (실시간 푸시) ───
builder.Services.AddSignalR();

// ─── (선택) Radzen ───
builder.Services.AddRadzenComponents();

var app = builder.Build();

app.UseStaticFiles();
app.UseRouting();
app.UseAntiforgery();

// ─── ★ SignalR 엔드포인트 ───
app.MapHub<RealtimeHub>("/hubs/realtime");

app.MapRazorComponents<App>()
    .AddInteractiveServerRenderMode();

app.Run();`}</Pre>

    <Step n="3" title="appsettings.json — 연결 정보" tag="Week 5" c={C.blue} />
    <Pre>{`// dashboard/QuantDashboard/appsettings.json
{
  "ConnectionStrings": {
    "Default": "Host=localhost;Database=quantdb;Username=quant;Password=QuantV31!Secure"
  },
  "GrpcUrl": "http://localhost:50051",
  "Logging": {
    "LogLevel": { "Default": "Information" }
  },
  "AllowedHosts": "*",
  "Kestrel": {
    "Endpoints": {
      "Http": { "Url": "http://0.0.0.0:5000" }
    }
  }
}`}</Pre>

    <Step n="4" title="PostgresService.cs — 데이터 서비스" tag="Week 6" c={C.violet} />
    <Info c={C.violet} icon="💡" title="설계 원칙">
      DevPlan.jsx의 Step 3.3 코드를 기반으로 합니다. Npgsql로 PostgreSQL 직접 조회하며,
      Entity Framework 없이 Raw SQL로 TimescaleDB 전용 함수(time_bucket 등)를 최대한 활용합니다.
    </Info>
    <Pre>{`// Services/PostgresService.cs
// ★ DevPlan.jsx Step 3.3 의 전체 코드를 구현합니다
// GetCurrentRegimeAsync()     → regime_history 최신 1건
// GetKillSwitchAsync()        → kill_switch_log 최신 1건
// GetPerformanceAsync(days)   → portfolio_snapshots N일
// GetStrategyPerfAsync()      → strategy_performance 조회
// GetSentimentMapAsync()      → sentiment_scores 히트맵

// 추가 구현 필요 메서드:
public async Task<List<TradeRecord>> GetRecentTradesAsync(int limit = 50)
{
    await using var conn = new NpgsqlConnection(_connStr);
    await conn.OpenAsync();
    
    await using var cmd = new NpgsqlCommand($@"
        SELECT trade_id, symbol, strategy, side, qty, price,
               regime, kill_level, executed_at
        FROM trades
        ORDER BY executed_at DESC
        LIMIT {limit}", conn);
    
    var results = new List<TradeRecord>();
    await using var reader = await cmd.ExecuteReaderAsync();
    while (await reader.ReadAsync())
    {
        results.Add(new TradeRecord {
            TradeId = reader.GetInt64(0),
            Symbol = reader.GetString(1),
            Strategy = reader.GetString(2),
            Side = reader.GetString(3),
            Qty = reader.GetDecimal(4),
            Price = reader.GetDecimal(5),
            Regime = reader.GetString(6),
            KillLevel = reader.GetString(7),
            ExecutedAt = reader.GetDateTime(8),
        });
    }
    return results;
}

// 센티먼트 히트맵 (TimescaleDB time_bucket 활용)
public async Task<List<SentimentPoint>> GetSentimentHeatmapAsync(
    int days = 30)
{
    await using var conn = new NpgsqlConnection(_connStr);
    await conn.OpenAsync();
    
    await using var cmd = new NpgsqlCommand($@"
        SELECT time_bucket('1 day', time) AS day,
               symbol, 
               AVG(hybrid_score) AS avg_score,
               COUNT(*) AS headline_count
        FROM sentiment_scores
        WHERE time > now() - interval '{days} days'
        GROUP BY day, symbol
        ORDER BY day DESC, avg_score DESC", conn);
    
    // ... reader 로직
}`}</Pre>

    <Step n="5" title="SignalR Hub — 실시간 푸시" tag="Week 6" c={C.emerald} />
    <Pre>{`// Services/RealtimeHub.cs
using Microsoft.AspNetCore.SignalR;

public class RealtimeHub : Hub
{
    /// 클라이언트 그룹: "dashboard" (모든 대시보드 연결)
    public override async Task OnConnectedAsync()
    {
        await Groups.AddToGroupAsync(Context.ConnectionId, "dashboard");
        await base.OnConnectedAsync();
    }
    
    /// Python 엔진에서 호출 (gRPC → Hub)
    public async Task BroadcastRegimeChange(string regime, 
        double confidence)
    {
        await Clients.Group("dashboard").SendAsync(
            "RegimeChanged", regime, confidence);
    }
    
    public async Task BroadcastKillSwitch(string level, 
        double mdd)
    {
        await Clients.Group("dashboard").SendAsync(
            "KillSwitchChanged", level, mdd);
    }
    
    public async Task BroadcastTradeExecuted(string symbol,
        string side, decimal qty, decimal price)
    {
        await Clients.Group("dashboard").SendAsync(
            "TradeExecuted", symbol, side, qty, price);
    }
}`}</Pre>

    <Step n="6" title="Regime.razor — 레짐 대시보드 페이지" tag="Week 7" c={C.rose} />
    <Info c={C.rose} icon="📊" title="DevPlan.jsx Step 3.4 기반">
      레짐 게이지 + Kill Switch 패널 + SignalR 실시간 갱신을 구현합니다.
      DevPlan.jsx의 Regime.razor 코드를 기반으로 하되, <b>SignalR 실시간 연동</b>을 추가합니다.
    </Info>
    <Pre>{`@* Components/Pages/Regime.razor *@
@page "/regime"
@inject PostgresService Db
@inject NavigationManager Nav
@rendermode InteractiveServer
@implements IAsyncDisposable

<h3>🎯 시장 레짐 모니터</h3>

@if (regime != null)
{
    <div class="regime-card @GetRegimeClass()">
        <h2>@regime.Current.ToUpper()</h2>
        <p>신뢰도: @(regime.Confidence.ToString("P0"))</p>
        <p>감지: @regime.DetectedAt.ToString("yyyy-MM-dd HH:mm")</p>
    </div>
    
    @* 확률 바 *@
    <div class="prob-bar bull" style="width:@(regime.BullProb*100)%">
        🟢 Bull @(regime.BullProb.ToString("P1"))
    </div>
    <div class="prob-bar sideways" style="width:@(regime.SidewaysProb*100)%">
        🟡 Sideways @(regime.SidewaysProb.ToString("P1"))
    </div>
    <div class="prob-bar bear" style="width:@(regime.BearProb*100)%">
        🔴 Bear @(regime.BearProb.ToString("P1"))
    </div>
}

@if (killSwitch != null)
{
    <div class="kill-panel @GetKillClass()">
        <h4>🛡️ Kill Switch: @killSwitch.Level</h4>
        <p>MDD: @(killSwitch.CurrentMdd.ToString("P2"))</p>
        <p>Exposure 한도: @(killSwitch.ExposureLimit.ToString("P0"))</p>
    </div>
}

@code {
    private RegimeState? regime;
    private KillSwitchState? killSwitch;
    private HubConnection? hubConnection;
    
    protected override async Task OnInitializedAsync()
    {
        // 초기 데이터 로드
        regime = await Db.GetCurrentRegimeAsync();
        killSwitch = await Db.GetKillSwitchAsync();
        
        // ★ SignalR 실시간 연결
        hubConnection = new HubConnectionBuilder()
            .WithUrl(Nav.ToAbsoluteUri("/hubs/realtime"))
            .WithAutomaticReconnect()
            .Build();
        
        hubConnection.On<string, double>("RegimeChanged", 
            async (newRegime, confidence) =>
        {
            // 실시간 갱신
            regime = await Db.GetCurrentRegimeAsync();
            killSwitch = await Db.GetKillSwitchAsync();
            await InvokeAsync(StateHasChanged);
        });
        
        hubConnection.On<string, double>("KillSwitchChanged",
            async (level, mdd) =>
        {
            killSwitch = await Db.GetKillSwitchAsync();
            await InvokeAsync(StateHasChanged);
        });
        
        await hubConnection.StartAsync();
    }
    
    private string GetRegimeClass() => regime?.Current switch {
        "bull" => "regime-bull",
        "bear" => "regime-bear",
        _ => "regime-sideways"
    };
    
    private string GetKillClass() => killSwitch?.Level switch {
        "EMERGENCY" => "kill-emergency",
        "DEFENSIVE" => "kill-defensive",
        "WARNING" => "kill-warning",
        _ => "kill-normal"
    };
    
    public async ValueTask DisposeAsync()
    {
        if (hubConnection is not null)
            await hubConnection.DisposeAsync();
    }
}`}</Pre>

    <Step n="7" title="Home.razor — 메인 P&L 대시보드" tag="Week 7" c={C.amber} />
    <Pre>{`@* Components/Pages/Home.razor *@
@page "/"
@inject PostgresService Db
@rendermode InteractiveServer

<h3>📈 포트폴리오 현황</h3>

@if (snapshot != null)
{
    <div class="stat-grid">
        <div class="stat-card">
            <span class="label">총 자산</span>
            <span class="value">$@(snapshot.TotalValue.ToString("N2"))</span>
        </div>
        <div class="stat-card">
            <span class="label">Sharpe</span>
            <span class="value">@(snapshot.Sharpe.ToString("F2"))</span>
        </div>
        <div class="stat-card">
            <span class="label">MDD</span>
            <span class="value @(snapshot.MaxDrawdown < -0.10 ? "text-danger" : "")">
                @(snapshot.MaxDrawdown.ToString("P2"))
            </span>
        </div>
        <div class="stat-card">
            <span class="label">레짐</span>
            <span class="value">@snapshot.Regime</span>
        </div>
    </div>
}

@* 최근 거래 *@
<h4>최근 거래</h4>
<table>
    <thead>
        <tr><th>시각</th><th>종목</th><th>전략</th><th>방향</th>
            <th>수량</th><th>가격</th><th>레짐</th></tr>
    </thead>
    <tbody>
    @foreach (var t in trades)
    {
        <tr>
            <td>@t.ExecutedAt.ToString("MM-dd HH:mm")</td>
            <td><b>@t.Symbol</b></td>
            <td>@t.Strategy</td>
            <td class="@(t.Side == "buy" ? "text-green" : "text-red")">
                @t.Side.ToUpper()
            </td>
            <td>@t.Qty</td>
            <td>$@t.Price.ToString("F2")</td>
            <td>@t.Regime</td>
        </tr>
    }
    </tbody>
</table>

@code {
    private DailySnapshot? snapshot;
    private List<TradeRecord> trades = new();
    
    protected override async Task OnInitializedAsync()
    {
        var perf = await Db.GetPerformanceAsync(1);
        snapshot = perf.FirstOrDefault();
        trades = await Db.GetRecentTradesAsync(20);
    }
}`}</Pre>

    <Sec c={C.emerald}>Week 5~8 체크리스트</Sec>
    <Chk c={C.cyan} items={[
      "dotnet new blazor → 프로젝트 생성 + NuGet 패키지 설치",
      "Program.cs DI 등록 (PostgresService, GrpcClient, SignalR)",
      "PostgresService.cs — 6개+ 조회 메서드 구현 (Npgsql Raw SQL)",
      "RealtimeHub.cs — SignalR Hub 3개 이벤트 (Regime, Kill, Trade)",
      "Home.razor — 메인 P&L + 최근 거래 테이블",
      "Regime.razor — 레짐 게이지 + Kill Switch + SignalR 실시간",
      "Risk.razor — Kill Switch 히스토리 + MDD 차트",
      "Strategies.razor — 전략별 현황 + 배분 비중",
      "Sentiment.razor — 센티먼트 히트맵",
      "브라우저 http://VM_IP:5000 접속 → 모든 페이지 렌더링 확인",
    ]} />
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// PAGE 4: STEP 3.3 — gRPC + TELEGRAM + SHAP
// ═══════════════════════════════════════════════════════════════
function Integration() {
  return (<div>
    <Info c={C.violet} icon="🔗" title="Step 3.3 — gRPC + Telegram + SHAP + 스케줄러 (Week 9~12)">
      Python 엔진과 Blazor Server 간 <b>gRPC</b> 양방향 통신, <b>Telegram Bot</b> 알림,
      <b>SHAP Feature Importance</b> 시각화, <b>APScheduler</b> 자동 실행을 연동합니다.
    </Info>

    <Step n="1" title="Proto 정의 — Python ↔ C# 인터페이스" tag="Week 9" c={C.violet} />
    <Pre>{`# proto/regime.proto
syntax = "proto3";
package quant;

service RegimeService {
  rpc GetCurrentRegime (Empty) returns (RegimeResponse);
  rpc StreamRegime (Empty) returns (stream RegimeResponse);
}

message Empty {}

message RegimeResponse {
  string current = 1;
  double bull_prob = 2;
  double sideways_prob = 3;
  double bear_prob = 4;
  double confidence = 5;
  string detected_at = 6;
}

# proto/portfolio.proto
syntax = "proto3";
package quant;

service PortfolioService {
  rpc GetSnapshot (Empty) returns (SnapshotResponse);
  rpc TriggerPipeline (Empty) returns (PipelineStatus);
}

message SnapshotResponse {
  double total_value = 1;
  double daily_return = 2;
  double sharpe_ratio = 3;
  double max_drawdown = 4;
  string regime = 5;
  string kill_level = 6;
}

message PipelineStatus {
  bool success = 1;
  string message = 2;
}

# proto/signals.proto
syntax = "proto3";
package quant;

service SignalService {
  rpc GetLatestSignals (SignalRequest) returns (SignalList);
}

message SignalRequest {
  string strategy = 1;   // 비어있으면 전체
  int32 limit = 2;
}

message Signal {
  string symbol = 1;
  string direction = 2;
  double strength = 3;
  string strategy = 4;
  string regime = 5;
}

message SignalList {
  repeated Signal signals = 1;
}`}</Pre>

    <Step n="2" title="Python gRPC 서버" tag="Week 9" c={C.violet} />
    <Pre>{`# Proto 컴파일 (Ubuntu)
pip install grpcio grpcio-tools
python -m grpc_tools.protoc -I./proto \\
    --python_out=./engine/api \\
    --grpc_python_out=./engine/api \\
    proto/regime.proto proto/portfolio.proto proto/signals.proto

# engine/api/grpc_server.py
import grpc
from concurrent import futures
import regime_pb2, regime_pb2_grpc
import portfolio_pb2, portfolio_pb2_grpc
import asyncio

class RegimeServicer(regime_pb2_grpc.RegimeServiceServicer):
    def __init__(self, pg_store, cache):
        self.pg = pg_store
        self.cache = cache
    
    def GetCurrentRegime(self, request, context):
        regime = self.cache.get_regime() or self.pg.get_latest_regime()
        if not regime:
            return regime_pb2.RegimeResponse(current="unknown")
        return regime_pb2.RegimeResponse(
            current=regime.get("current", "unknown"),
            bull_prob=regime.get("bull", 0),
            sideways_prob=regime.get("sideways", 0),
            bear_prob=regime.get("bear", 0),
            confidence=regime.get(regime.get("current",""), 0),
            detected_at=str(regime.get("detected_at", "")),
        )
    
    def StreamRegime(self, request, context):
        """레짐 변경 시 스트리밍 푸시"""
        last = None
        while context.is_active():
            regime = self.cache.get_regime()
            if regime and regime.get("current") != last:
                last = regime.get("current")
                yield regime_pb2.RegimeResponse(
                    current=regime.get("current", "unknown"),
                    bull_prob=regime.get("bull", 0),
                    sideways_prob=regime.get("sideways", 0),
                    bear_prob=regime.get("bear", 0),
                    confidence=regime.get(regime.get("current",""), 0),
                )
            asyncio.get_event_loop().run_until_complete(
                asyncio.sleep(5))

def start_grpc_server(pg_store, cache, port=50051):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    regime_pb2_grpc.add_RegimeServiceServicer_to_server(
        RegimeServicer(pg_store, cache), server)
    # ... 다른 서비스도 등록
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    return server`}</Pre>

    <Step n="3" title="Blazor gRPC 클라이언트" tag="Week 10" c={C.cyan} />
    <Pre>{`// Services/GrpcClient.cs
using Grpc.Net.Client;
using Quant;  // Proto 생성 네임스페이스

public class GrpcClient : IDisposable
{
    private readonly GrpcChannel _channel;
    private readonly RegimeService.RegimeServiceClient _regime;
    private readonly PortfolioService.PortfolioServiceClient _portfolio;
    
    public GrpcClient(string url)
    {
        _channel = GrpcChannel.ForAddress(url);
        _regime = new RegimeService.RegimeServiceClient(_channel);
        _portfolio = new PortfolioService.PortfolioServiceClient(_channel);
    }
    
    public async Task<RegimeResponse> GetRegimeAsync()
    {
        return await _regime.GetCurrentRegimeAsync(new Empty());
    }
    
    public async Task<PipelineStatus> TriggerPipelineAsync()
    {
        return await _portfolio.TriggerPipelineAsync(new Empty());
    }
    
    public void Dispose() => _channel?.Dispose();
}`}</Pre>

    <Step n="4" title="Telegram Bot 알림" tag="Week 10" c={C.emerald} />
    <Pre>{`# engine/execution/alerts.py
import asyncio
from telegram import Bot
from engine.config.settings import Settings

class TelegramAlert:
    """Telegram Bot 알림 (비동기)"""
    
    def __init__(self, config: Settings):
        self.bot = Bot(token=config.telegram_token) \\
            if config.telegram_token else None
        self.chat_id = config.telegram_chat_id
    
    async def send(self, message: str):
        """알림 전송 (실패해도 파이프라인 중단 안 함)"""
        if not self.bot or not self.chat_id:
            return
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=f"📊 Quant V3.1\\n{message}",
                parse_mode="HTML"
            )
        except Exception as e:
            pass  # 알림 실패는 로깅만

# ─── Telegram Bot 설정 방법 ───
# 1. @BotFather에게 /newbot → 토큰 발급
# 2. 본인 chat_id 확인: @userinfobot에게 메시지
# 3. .env에 추가:
#    TELEGRAM_TOKEN=your_bot_token
#    TELEGRAM_CHAT_ID=your_chat_id`}</Pre>

    <Step n="5" title="APScheduler — 자동 실행 스케줄" tag="Week 11" c={C.amber} />
    <Pre>{`# engine/execution/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

def setup_scheduler(orchestrator):
    """전체 스케줄 설정 (미국 동부시간 기준)"""
    et = pytz.timezone("US/Eastern")
    scheduler = AsyncIOScheduler(timezone=et)
    
    # ─── 메인 파이프라인: 미장 마감 30분 전 ───
    scheduler.add_job(
        orchestrator.execute_daily,
        CronTrigger(hour=15, minute=30, day_of_week="mon-fri"),
        id="daily_pipeline",
        name="일일 8단계 파이프라인",
        misfire_grace_time=300,
    )
    
    # ─── HMM 월간 재학습: 매월 첫 토요일 ───
    scheduler.add_job(
        orchestrator.regime_detector.retrain,
        CronTrigger(day_of_week="sat", week="1"),
        id="hmm_retrain",
        name="HMM 월간 재학습",
    )
    
    # ─── 데이터 수집: 매일 장 마감 후 ───
    scheduler.add_job(
        orchestrator.collect_daily_data,
        CronTrigger(hour=17, minute=0, day_of_week="mon-fri"),
        id="data_collection",
        name="일봉 데이터 수집",
    )
    
    # ─── 센티먼트 스캔: 장중 매시간 ───
    scheduler.add_job(
        orchestrator.sentiment.scan_hourly,
        CronTrigger(hour="9-16", minute=0, day_of_week="mon-fri"),
        id="sentiment_scan",
        name="FinBERT 센티먼트 스캔",
    )
    
    # ─── 물리뷰 갱신: 주 1회 ───
    scheduler.add_job(
        orchestrator.refresh_materialized_views,
        CronTrigger(day_of_week="sun", hour=2),
        id="mv_refresh",
        name="물리뷰 갱신 (sector_correlations 등)",
    )
    
    scheduler.start()
    return scheduler

# main.py lifespan에서 호출:
# scheduler = setup_scheduler(app.state.orchestrator)`}</Pre>

    <Step n="6" title="SHAP Feature Importance" tag="Week 12" c={C.pink} />
    <Pre>{`# engine/explain/feature_importance.py
import shap
import numpy as np
from engine.data.storage import PostgresStore

class FeatureExplainer:
    """SHAP 기반 포지션 설명 (Grok 제안)"""
    
    def __init__(self, pg: PostgresStore):
        self.pg = pg
    
    def explain_signal(self, symbol: str, strategy_model,
                        feature_names: list) -> dict:
        """왜 이 시그널이 나왔는지 설명"""
        # 최근 팩터 데이터 로드
        features = self.pg.get_factor_features(symbol)
        
        if features is None:
            return {"error": "no data"}
        
        X = np.array([features])
        
        # SHAP TreeExplainer (LightGBM 등)
        explainer = shap.TreeExplainer(strategy_model)
        shap_values = explainer.shap_values(X)
        
        # Top 5 영향력 피처
        importance = sorted(
            zip(feature_names, shap_values[0]),
            key=lambda x: abs(x[1]), reverse=True
        )[:5]
        
        return {
            "symbol": symbol,
            "top_features": [
                {"name": name, "impact": float(val)}
                for name, val in importance
            ],
            "base_value": float(explainer.expected_value),
            "prediction": float(
                explainer.expected_value + sum(shap_values[0]))
        }
    
    def regime_feature_importance(self) -> dict:
        """레짐 감지에 가장 중요한 피처"""
        # HMM은 SHAP 직접 적용 불가 → 피처 상관분석으로 대체
        regime_data = self.pg.query("""
            SELECT r.regime,
                   AVG(f.volatility) as avg_vol,
                   AVG(f.momentum_z) as avg_mom,
                   AVG(f.quality_z) as avg_qual,
                   AVG(f.sentiment) as avg_sent
            FROM regime_history r
            JOIN factor_scores f ON DATE(r.detected_at) = DATE(f.time)
            GROUP BY r.regime
        """)
        return regime_data`}</Pre>

    <Sec c={C.emerald}>Week 9~12 체크리스트</Sec>
    <Chk c={C.violet} items={[
      "Proto 파일 3개 작성 + Python/C# 코드 생성",
      "Python gRPC 서버 → port 50051 리스닝",
      "Blazor GrpcClient → Python 엔진 조회 성공",
      "Telegram Bot 생성 + .env 토큰 설정 + 알림 수신 확인",
      "APScheduler 5개 작업 등록 (파이프라인, HMM재학습, 데이터수집, 센티먼트, 물리뷰)",
      "SHAP explain_signal → Top 5 피처 JSON 반환",
      "gRPC StreamRegime → Blazor SignalR → 브라우저 실시간 갱신",
    ]} />
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// PAGE 5: STEP 3.4 — SYSTEMD + 검증
// ═══════════════════════════════════════════════════════════════
function SystemdVerify() {
  return (<div>
    <Info c={C.emerald} icon="⚙️" title="Step 3.4 — systemd 서비스 + E2E 검증 (Week 13~16)">
      Ubuntu <b>systemd</b>로 엔진/대시보드/스케줄러를 서비스로 등록하여 자동 시작/재시작을 보장하고,
      전체 시스템 End-to-End 테스트를 수행합니다.
    </Info>

    <Step n="1" title="systemd 서비스 파일 생성" tag="Week 13" c={C.emerald} />
    <Pre>{`# ─── systemd/quant-engine.service ───
[Unit]
Description=Quant V3.1 Python Engine (FastAPI + gRPC)
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=quant
WorkingDirectory=/home/quant/quant-v31
Environment="PATH=/home/quant/miniconda3/envs/quant-v31/bin"
ExecStart=/home/quant/miniconda3/envs/quant-v31/bin/uvicorn \\
    engine.api.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# 메모리 제한 (안전장치)
MemoryMax=8G
CPUQuota=200%

[Install]
WantedBy=multi-user.target

# ─── systemd/quant-dashboard.service ───
[Unit]
Description=Quant V3.1 Blazor Server Dashboard
After=quant-engine.service
Wants=quant-engine.service

[Service]
Type=simple
User=quant
WorkingDirectory=/home/quant/quant-v31/dashboard/QuantDashboard
Environment="DOTNET_ROOT=/home/quant/.dotnet"
Environment="ASPNETCORE_URLS=http://0.0.0.0:5000"
Environment="DOTNET_ENVIRONMENT=Production"
ExecStart=/home/quant/.dotnet/dotnet run --no-build
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target

# ─── systemd/quant-scheduler.service ───
[Unit]
Description=Quant V3.1 APScheduler (cron jobs)
After=quant-engine.service
Requires=quant-engine.service

[Service]
Type=simple
User=quant
WorkingDirectory=/home/quant/quant-v31
Environment="PATH=/home/quant/miniconda3/envs/quant-v31/bin"
ExecStart=/home/quant/miniconda3/envs/quant-v31/bin/python \\
    -m engine.execution.scheduler
Restart=always
RestartSec=15
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target`}</Pre>

    <Step n="2" title="서비스 설치 + 관리 명령" tag="Week 13" c={C.emerald} />
    <Pre>{`# ─── 서비스 파일 복사 + 활성화 ───
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# 부팅 시 자동 시작 등록
sudo systemctl enable quant-engine
sudo systemctl enable quant-dashboard
sudo systemctl enable quant-scheduler

# 서비스 시작
sudo systemctl start quant-engine
sudo systemctl start quant-dashboard
sudo systemctl start quant-scheduler

# ─── 상태 확인 ───
sudo systemctl status quant-engine
sudo systemctl status quant-dashboard
sudo systemctl status quant-scheduler

# ─── 로그 모니터링 ───
# 실시간 엔진 로그
journalctl -u quant-engine -f

# 대시보드 로그
journalctl -u quant-dashboard -f

# 오늘 스케줄러 로그만
journalctl -u quant-scheduler --since today

# ─── 서비스 재시작/중지 ───
sudo systemctl restart quant-engine
sudo systemctl stop quant-dashboard

# ─── 자동 재시작 테스트 (프로세스 강제 종료) ───
sudo kill $(pidof uvicorn)
# → 10초 후 자동 재시작 확인
systemctl status quant-engine`}</Pre>

    <Step n="3" title="E2E 통합 테스트 스크립트" tag="Week 14~15" c={C.rose} />
    <Pre>{`# scripts/test_phase3.py
"""Phase 3 End-to-End 검증 스크립트"""
import requests, psycopg, time, sys

PG_DSN = "postgresql://quant:QuantV31!Secure@localhost:5432/quantdb"
ENGINE_URL = "http://localhost:8000"
DASHBOARD_URL = "http://localhost:5000"

def test(name, fn):
    try:
        fn()
        print(f"  ✅ {name}")
        return True
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        return False

results = []
print("\\n🧪 Phase 3 E2E 테스트 시작\\n")

# ── 1. 인프라 확인 ──
print("━━━ 1. 인프라 ━━━")
results.append(test("PostgreSQL 연결", lambda: 
    psycopg.connect(PG_DSN).execute("SELECT 1")))
results.append(test("TimescaleDB 확장", lambda:
    psycopg.connect(PG_DSN).execute(
        "SELECT extversion FROM pg_extension WHERE extname='timescaledb'"
    ).fetchone()))
results.append(test("FastAPI 헬스체크", lambda:
    assert requests.get(f"{ENGINE_URL}/health").status_code == 200))
results.append(test("Blazor Server 접속", lambda:
    assert requests.get(DASHBOARD_URL).status_code == 200))

# ── 2. 파이프라인 ──
print("\\n━━━ 2. 오케스트레이터 ━━━")
results.append(test("파이프라인 트리거", lambda:
    assert requests.post(f"{ENGINE_URL}/run").json()["status"] == "pipeline_started"))
time.sleep(30)  # 파이프라인 완료 대기

results.append(test("레짐 API", lambda:
    assert requests.get(f"{ENGINE_URL}/regime").json().get("current")))
results.append(test("포트폴리오 API", lambda:
    assert requests.get(f"{ENGINE_URL}/portfolio").json()))

# ── 3. DB 기록 확인 ──
print("\\n━━━ 3. DB 기록 ━━━")
with psycopg.connect(PG_DSN) as conn:
    results.append(test("regime_history 기록", lambda:
        assert conn.execute("SELECT COUNT(*) FROM regime_history").fetchone()[0] > 0))
    results.append(test("portfolio_snapshots 기록", lambda:
        assert conn.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0] > 0))
    results.append(test("signal_log 기록", lambda:
        assert conn.execute("SELECT COUNT(*) FROM signal_log").fetchone()[0] > 0))

# ── 4. gRPC ──
print("\\n━━━ 4. gRPC ━━━")
import grpc
import regime_pb2, regime_pb2_grpc
results.append(test("gRPC 레짐 조회", lambda: (
    stub := regime_pb2_grpc.RegimeServiceStub(
        grpc.insecure_channel("localhost:50051")),
    assert stub.GetCurrentRegime(regime_pb2.Empty()).current != ""
)))

# ── 5. systemd ──
print("\\n━━━ 5. systemd ━━━")
import subprocess
for svc in ["quant-engine", "quant-dashboard", "quant-scheduler"]:
    results.append(test(f"systemd {svc} active", lambda:
        assert "active (running)" in subprocess.run(
            ["systemctl", "is-active", svc], 
            capture_output=True, text=True).stdout))

# ── 6. 브라우저 접속 ──
print("\\n━━━ 6. 대시보드 페이지 ━━━")
for page in ["/", "/regime", "/risk", "/strategies", "/sentiment"]:
    results.append(test(f"Blazor {page}", lambda:
        assert requests.get(f"{DASHBOARD_URL}{page}").status_code == 200))

# ── 결과 ──
passed = sum(results)
total = len(results)
print(f"\\n{'='*50}")
print(f"🏁 결과: {passed}/{total} 통과")
if passed == total:
    print("🎉 Phase 3 E2E 테스트 전체 통과!")
else:
    print(f"⚠️  {total-passed}개 실패 — 수정 후 재실행")
sys.exit(0 if passed == total else 1)`}</Pre>

    <Step n="4" title="모바일 + PC 접속 테스트" tag="Week 16" c={C.blue} />
    <Pre>{`# ─── PC 브라우저 접속 (호스트 Windows에서) ───
# VirtualBox 포트포워딩이 설정되어 있다면:
http://localhost:5000

# 또는 VM IP 직접 접속:
http://192.168.56.xxx:5000

# ─── 모바일 접속 (같은 네트워크) ───
# 1. VirtualBox → 설정 → 네트워크 → 브릿지 어댑터
# 2. VM에서 ip addr → 192.168.x.x 확인
# 3. 모바일 브라우저: http://192.168.x.x:5000

# ─── 반응형 확인 포인트 ───
# - 레짐 게이지: 모바일에서 세로 스택
# - Kill Switch 패널: 색상 코드 가독성
# - 거래 테이블: 가로 스크롤 동작
# - 실시간 갱신: SignalR 모바일 연결 유지

# ─── (선택) nginx 리버스 프록시 + HTTPS ───
sudo apt install -y nginx certbot
# nginx.conf:
# server {
#     listen 80;
#     location / { proxy_pass http://localhost:5000; }
#     location /hubs/ {
#         proxy_pass http://localhost:5000;
#         proxy_http_version 1.1;
#         proxy_set_header Upgrade $http_upgrade;
#         proxy_set_header Connection "upgrade";
#     }
# }`}</Pre>

    <Sec c={C.amber}>Phase 3 최종 체크리스트</Sec>
    <Chk c={C.emerald} items={[
      "8단계 오케스트레이터 (레짐→Kill→배분→시그널→센티먼트→Vol→사이징→VWAP)",
      "모든 전략이 PostgreSQL에서 직접 데이터 조회 + 결과 기록",
      "Blazor Server 프로젝트 생성 + Npgsql 연동",
      "레짐 게이지 + Kill Switch 패널 Razor 페이지",
      "gRPC Python↔C# 연동 정상 동작",
      "SignalR 실시간 푸시 (레짐 변경 시 즉시 갱신)",
      "systemd 서비스 등록 (engine + dashboard + scheduler 자동 시작)",
      "브라우저에서 http://서버IP:5000 접속 확인 (PC + 모바일)",
      "APScheduler 전체 스케줄 자동 실행 테스트",
      "Telegram 알림 (레짐 전환, Kill Switch, 매매 완료)",
      "SHAP Feature Importance JSON 반환 확인",
      "E2E 테스트 스크립트 전체 통과",
      "systemd 자동 재시작 테스트 (kill → 10초 후 복구)",
    ]} />

    <Info c={C.lime} icon="🎉" title="Phase 3 완료 → Phase 4 진입 조건">
      위 체크리스트를 모두 통과하면 Phase 4(백테스트 검증 + Paper Trading)로 진입합니다.<br />
      <b>Phase 4 핵심:</b> Walk-Forward + DSR + Monte Carlo + 레짐 스트레스 4건 + Kill Switch 검증 + Granger 센티먼트.<br />
      모든 검증을 PostgreSQL 데이터 기반으로 수행합니다.
    </Info>
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// PAGE 6: 트러블슈팅
// ═══════════════════════════════════════════════════════════════
function Troubleshooting() {
  return (<div>
    <Info c={C.rose} icon="🔧" title="Phase 3 예상 트러블슈팅">
      Phase 3에서 자주 발생하는 이슈와 해결 방법입니다.
    </Info>

    <Tbl headers={["이슈", "증상", "해결법"]}
      colors={[C.rose, C.t, C.emerald]}
      rows={[
        ["gRPC 연결 실패", "Blazor → Python 50051 timeout", "방화벽 확인: sudo ufw allow 50051. docker-compose에서 ports 확인"],
        ["SignalR 끊김", "모바일 30초 후 연결 해제", "WithAutomaticReconnect() 필수. nginx WebSocket 설정 확인"],
        ["Npgsql 타임아웃", "장시간 쿼리 시 연결 끊김", "연결 문자열에 Timeout=60;Command Timeout=120 추가"],
        ["systemd 즉시 종료", "Active: failed (Result: exit-code)", "ExecStart 경로 확인. journalctl -u 서비스명 으로 상세 로그"],
        ["FinBERT OOM", "메모리 부족 (8GB VM)", "batch_size=16으로 축소. MemoryMax=6G systemd 설정"],
        ["APScheduler 미실행", "장 마감 후 파이프라인 안 돌아감", "타임존 확인 (US/Eastern). misfire_grace_time 충분히 설정"],
        ["Blazor 느림", "페이지 로딩 3초+", "Npgsql 커넥션 풀링. PostgreSQL에 적절한 인덱스 확인"],
        ["proto 컴파일 에러", "import 경로 오류", "python -m grpc_tools.protoc에서 -I 경로 정확히. __init__.py 확인"],
      ]} />

    <Sec c={C.amber}>PostgreSQL 성능 모니터링 쿼리</Sec>
    <Pre>{`-- 느린 쿼리 Top 10
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;

-- hypertable 압축 상태
SELECT hypertable_name,
       pg_size_pretty(before_compression_total_bytes) AS before,
       pg_size_pretty(after_compression_total_bytes) AS after,
       ROUND(100 - (after_compression_total_bytes::numeric / 
             before_compression_total_bytes * 100), 1) AS savings_pct
FROM hypertable_compression_stats('daily_prices');

-- 연속 집계 상태
SELECT view_name, completed_threshold, refresh_lag
FROM timescaledb_information.continuous_aggregate_stats;

-- 현재 연결 수
SELECT count(*) FROM pg_stat_activity
WHERE state = 'active';`}</Pre>

    <Sec c={C.cyan}>유용한 디버깅 명령</Sec>
    <Pre>{`# systemd 서비스 전체 상태
sudo systemctl list-units --type=service | grep quant

# 포트 사용 확인
sudo ss -tlnp | grep -E '(5000|8000|50051|5432|6379)'

# Docker 컨테이너 상태
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Python 엔진 로그 (실시간)
journalctl -u quant-engine -f --no-pager

# Blazor 빌드 + 실행 (개발 모드)
cd ~/quant-v31/dashboard/QuantDashboard
dotnet watch run --urls "http://0.0.0.0:5000"

# gRPC 테스트 (grpcurl 설치 필요)
grpcurl -plaintext localhost:50051 quant.RegimeService/GetCurrentRegime`}</Pre>
  </div>);
}

// ═══════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════
const tabs = [
  { id: "overview", icon: "📋", label: "개요", c: C.amber },
  { id: "orch", icon: "🎯", label: "3.1 오케스트레이터", c: C.rose },
  { id: "blazor", icon: "🔷", label: "3.2 Blazor Server", c: C.cyan },
  { id: "integ", icon: "🔗", label: "3.3 gRPC+연동", c: C.violet },
  { id: "systemd", icon: "⚙️", label: "3.4 systemd+검증", c: C.emerald },
  { id: "trouble", icon: "🔧", label: "트러블슈팅", c: C.rose },
];
const pages = {
  overview: Overview, orch: Orchestrator, blazor: BlazorServer,
  integ: Integration, systemd: SystemdVerify, trouble: Troubleshooting,
};

export default function App() {
  const [active, setActive] = useState("overview");
  const Page = pages[active];
  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.t,
      fontFamily: "'Pretendard',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif" }}>
      <link href="https://cdnjs.cloudflare.com/ajax/libs/pretendard/1.3.9/static/pretendard.min.css" rel="stylesheet" />

      <div style={{ background: "linear-gradient(180deg,#0d0e1a,#05060b)",
        borderBottom: `1px solid ${C.bd}`, padding: "16px 16px 10px", textAlign: "center" }}>
        <div style={{ display: "flex", justifyContent: "center", gap: 6, marginBottom: 6 }}>
          <span style={{ background: `${C.amber}15`, color: C.amber, padding: "2px 10px",
            borderRadius: 20, fontSize: 9, fontWeight: 800, border: `1px solid ${C.amber}30` }}>Phase 3</span>
          <span style={{ background: `${C.cyan}15`, color: C.cyan, padding: "2px 10px",
            borderRadius: 20, fontSize: 9, fontWeight: 800, border: `1px solid ${C.cyan}30` }}>15~18개월</span>
          <span style={{ background: `${C.rose}15`, color: C.rose, padding: "2px 10px",
            borderRadius: 20, fontSize: 9, fontWeight: 800, border: `1px solid ${C.rose}30` }}>통합+대시보드</span>
        </div>
        <h1 style={{ fontSize: 18, fontWeight: 900, margin: "2px 0",
          background: "linear-gradient(135deg,#f59e0b,#f43f5e,#8b5cf6,#06b6d4,#10b981)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
          Phase 3 구현 가이드
        </h1>
        <p style={{ color: C.tm, fontSize: 10, margin: 0 }}>
          8단계 오케스트레이터 + Blazor Server + gRPC + SignalR + systemd
        </p>
      </div>

      <div style={{ display: "flex", overflowX: "auto", gap: 2, padding: "6px 8px",
        borderBottom: `1px solid ${C.bd}`, background: "#080a12" }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setActive(t.id)}
            style={{
              background: active === t.id ? `${t.c}15` : "transparent",
              border: active === t.id ? `1px solid ${t.c}30` : "1px solid transparent",
              borderRadius: 7, padding: "5px 9px", cursor: "pointer",
              color: active === t.id ? t.c : C.tm,
              fontSize: 11, fontWeight: active === t.id ? 700 : 500,
              whiteSpace: "nowrap", fontFamily: "inherit",
            }}>
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      <div style={{ padding: "10px 12px", maxWidth: 880, margin: "0 auto" }}>
        <Page />
      </div>

      <div style={{ textAlign: "center", padding: "14px", borderTop: `1px solid ${C.bd}`,
        color: "#333846", fontSize: 9 }}>
        Quant V3.1 Ubuntu Ed. Phase 3 Guide | 오케스트레이터 + Blazor Server + systemd
      </div>
    </div>
  );
}
