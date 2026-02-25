import { useState } from "react";

// ─── V3.1 Color System ───
const P = {
  bg: "#06070c", s1: "#0c0d16", s2: "#12131f", bd: "#1e2035",
  t: "#b8bdd0", tm: "#636a80", tb: "#e8ecf5", tw: "#ffffff",
  // Strategy colors
  g: "#22c55e", b: "#3b82f6", v: "#8b5cf6", o: "#f59e0b",
  r: "#ef4444", p: "#ec4899", c: "#06b6d4", w: "#f97316",
};

// ─── Shared Components ───
const Box = ({ children, s, glow }) => (
  <div style={{
    background: P.s1, borderRadius: 10, border: `1px solid ${P.bd}`,
    padding: "14px 16px",
    ...(glow ? { boxShadow: `0 0 20px ${glow}15, inset 0 1px 0 ${glow}10` } : {}),
    ...s,
  }}>{children}</div>
);

const Hd = ({ children, c = P.b }) => (
  <div style={{ fontWeight: 800, color: P.tb, fontSize: 15, margin: "24px 0 10px",
    paddingBottom: 8, borderBottom: `2px solid ${c}30`,
    display: "flex", alignItems: "center", gap: 8 }}>
    <div style={{ width: 3, height: 18, background: c, borderRadius: 2 }} />
    {children}
  </div>
);

const Note = ({ c, icon, title, children }) => (
  <div style={{ background: `${c}08`, border: `1px solid ${c}20`, borderRadius: 10,
    padding: "12px 14px", margin: "12px 0" }}>
    <div style={{ color: c, fontWeight: 700, fontSize: 13, marginBottom: 4 }}>{icon} {title}</div>
    <div style={{ color: P.t, fontSize: 12, lineHeight: 1.75 }}>{children}</div>
  </div>
);

const Tag = ({ children, c = P.b }) => (
  <span style={{ background: `${c}15`, color: c, padding: "2px 8px", borderRadius: 5,
    fontSize: 10, fontFamily: "monospace", fontWeight: 600 }}>{children}</span>
);

const Code = ({ children }) => (
  <pre style={{ color: P.g, fontSize: 9.5, lineHeight: 1.55,
    fontFamily: "'JetBrains Mono','Fira Code','Consolas',monospace",
    margin: 0, overflowX: "auto", whiteSpace: "pre", padding: "12px 14px",
    background: "#050610", borderRadius: 8, border: `1px solid ${P.bd}` }}>{children}</pre>
);

const Row = ({ items }) => (
  <div style={{ display: "grid", gridTemplateColumns: `repeat(${items.length}, 1fr)`, gap: 8, margin: "8px 0" }}>
    {items.map((it, i) => (
      <Box key={i} glow={it.c}>
        <div style={{ color: it.c, fontSize: 10, fontWeight: 600, marginBottom: 4 }}>{it.label}</div>
        <div style={{ color: P.tw, fontSize: 18, fontWeight: 800 }}>{it.value}</div>
        {it.sub && <div style={{ color: P.tm, fontSize: 10, marginTop: 2 }}>{it.sub}</div>}
      </Box>
    ))}
  </div>
);

const Cmp = ({ items, h1, h2 }) => (
  <div style={{ borderRadius: 8, overflow: "hidden", border: `1px solid ${P.bd}`, margin: "8px 0" }}>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", background: P.s2,
      padding: "6px 10px", fontSize: 10, fontWeight: 700 }}>
      <span style={{ color: P.tm }}>항목</span>
      <span style={{ color: P.r }}>{h1}</span>
      <span style={{ color: P.g }}>{h2}</span>
    </div>
    {items.map((r, i) => (
      <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
        padding: "5px 10px", fontSize: 11, background: i % 2 === 0 ? P.s1 : "transparent",
        borderTop: `1px solid ${P.bd}08` }}>
        <span style={{ color: P.t, fontWeight: 600 }}>{r[0]}</span>
        <span style={{ color: P.tm }}>{r[1]}</span>
        <span style={{ color: P.g }}>{r[2]}</span>
      </div>
    ))}
  </div>
);

// ═══════════════════════════════════════
// TAB PAGES
// ═══════════════════════════════════════

function WhyV31() {
  return (<div>
    <Note c={P.w} icon="🔥" title="V3 → V3.1 업그레이드 배경">
      상용 AI 서비스(ProPicks AI, WarrenAI 등)는 "연 138~175%" 마케팅. 그러나 이는 2023~2025 AI/테크 불마켓의 특정 섹터 집중 결과. 4개 LLM(ChatGPT, Gemini, Grok, Claude) 합의: <b>지속 가능한 리스크 조정 수익</b>이 진짜 경쟁력.
    </Note>

    <Hd c={P.r}>상용 AI 서비스의 마케팅 해부</Hd>
    <Cmp h1="상용 AI 마케팅" h2="실제 분석"
      items={[
        ["수익률 기간", "론칭 후 2.3년 누적", "CAGR로 환산하면 50~60%"],
        ["섹터 집중", "AI/테크 90%+ 비중", "NVDA 한 종목이 전체 수익 견인"],
        ["MDD 공개", "미공개", "추정 -40% 이상 (2022년 type)"],
        ["전략 선별", "잘된 전략만 강조", "생존 편향 + 선택 보고"],
        ["비용 모델", "슬리피지 무시 또는 최소", "현실 반영 안 됨"],
        ["레짐 적응", "없음 (동일 로직 고정)", "하락장 방어 기능 無"],
      ]} />

    <Hd c={P.g}>4개 LLM 공통 합의 — V3.1 필수 추가 기능</Hd>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
      {[
        { icon: "🎯", title: "Regime Detection", desc: "HMM 기반 시장 국면 감지 → 전략 자동 스위칭", who: "ChatGPT ★ Gemini ★ Grok ★ Claude ★", c: P.r },
        { icon: "🛡️", title: "Drawdown Kill Switch", desc: "MDD 단계별 자동 방어 (-10%→-15%→-20%)", who: "ChatGPT ★ Grok ★ Claude ★", c: P.o },
        { icon: "📊", title: "동적 포지션 사이징", desc: "ATR + Vol 기반 포지션 크기 실시간 조절", who: "ChatGPT ★ Gemini ★ Grok ★ Claude ★", c: P.b },
        { icon: "🧠", title: "FinBERT 센티먼트", desc: "금융 특화 NLP 로컬 구동 → 실시간 심리 지수", who: "Gemini ★ Claude ★", c: P.v },
      ].map((f, i) => (
        <Box key={i} glow={f.c}>
          <div style={{ fontSize: 20, marginBottom: 4 }}>{f.icon}</div>
          <div style={{ color: f.c, fontWeight: 800, fontSize: 13 }}>{f.title}</div>
          <div style={{ color: P.t, fontSize: 11, margin: "4px 0", lineHeight: 1.5 }}>{f.desc}</div>
          <div style={{ color: P.tm, fontSize: 9 }}>{f.who}</div>
        </Box>
      ))}
    </div>

    <Hd c={P.c}>Claude의 독자 분석 — 왜 V3.1이 상용 AI를 이길 수 있는가</Hd>
    <Note c={P.c} icon="🔍" title="Claude 핵심 분석: 구조적 알파의 원천">
      상용 AI의 치명적 약점은 <b>"단일 레짐 의존성"</b>입니다. ProPicks가 138%를 달성한 2023~2025는 역사상 가장 강력한 AI/테크 불마켓이었고, 이 기간 NVDA 한 종목이 +800% 상승했습니다. 이런 환경에서는 단순히 대형 테크를 사는 것만으로도 높은 수익이 가능했습니다.
      <br /><br />
      V3.1의 핵심 우위는 <b>"레짐 적응형 멀티스트래티지"</b>입니다. 2022년 같은 하락장(-33% S&P)에서 상용 AI는 동일 로직으로 매수를 계속하지만, V3.1은 HMM이 Bear 레짐을 감지하면 자동으로 현금 비중 70%+로 전환하고, 페어즈 트레이딩(Market Neutral)에 집중합니다.
      <br /><br />
      학술적으로도 검증됩니다. Gupta et al. (2025, Data Science in Finance)의 앙상블-HMM 투표 프레임워크는 3-state HMM이 시장 전환점을 효과적으로 포착함을 보였고, MDPI 연구에서는 HMM 레짐 스위칭 팩터 투자가 단일 전략 대비 Treynor Ratio를 유의미하게 개선했습니다.
      <br /><br />
      추가로, FinBERT를 로컬(Dell 서버 32GB)에서 구동하면 Claude API 의존 없이도 실시간 뉴스 센티먼트를 분석할 수 있어, <b>월 $20~50 API 비용을 절감</b>하면서 더 빠른 반응이 가능합니다. FinBERT는 HuggingFace에서 무료로 제공되며, CPU 환경에서도 초당 10~50건 처리가 가능합니다.
    </Note>

    <Hd c={P.o}>V3 vs V3.1 핵심 변경 요약</Hd>
    <Cmp h1="V3 (기존)" h2="V3.1 (업그레이드)"
      items={[
        ["레짐 감지", "단순 VIX 참조", "HMM 3-State + 앙상블"],
        ["드로다운 방어", "MDD -20% 비상 청산", "3단계 킬 스위치 (-10/-15/-20)"],
        ["센티먼트", "Claude API only ($20~50/월)", "FinBERT 로컬 + Claude 보조 ($0+α)"],
        ["포지션 사이징", "Kelly Half 고정", "ATR + Vol 역가중 동적 사이징"],
        ["전략 배분", "고정 비중", "레짐별 동적 배분"],
        ["목표 수익", "17% CAGR 고정", "레짐별: 강세40% 횡보12% 약세-5%"],
        ["대체 데이터", "없음", "Reddit/WSB 언급량 + 옵션 내재변동성"],
        ["설명가능성", "없음", "Feature Importance 시각화"],
      ]} />
  </div>);
}

function RegimeDetection() {
  return (<div>
    <Note c={P.r} icon="🎯" title="시장 국면 감지 — V3.1 최대 업그레이드">
      4개 LLM 전원 합의 1순위. Hidden Markov Model(HMM)으로 Bull/Bear/Sideways 3-State 감지 → 전략별 배분 자동 조절. 학술 근거: Gupta et al. (2025), Kim et al. (2019), Hamilton (1989).
    </Note>

    <Hd c={P.r}>HMM 3-State 레짐 모델</Hd>
    <Row items={[
      { c: P.g, label: "State 0: Bull", value: "강세장", sub: "높은 수익, 낮은 변동성" },
      { c: P.o, label: "State 1: Sideways", value: "횡보장", sub: "낮은 수익, 중간 변동성" },
      { c: P.r, label: "State 2: Bear", value: "약세장", sub: "음의 수익, 높은 변동성" },
    ]} />

    <Hd c={P.v}>HMM 구현 코드</Hd>
    <Code>{`# engine/risk/regime.py
from hmmlearn.hmm import GaussianHMM
import numpy as np
import polars as pl

class RegimeDetector:
    """Hidden Markov Model 기반 시장 국면 감지
    학술근거: Hamilton (1989), Gupta et al. (2025)
    3-State: Bull(0) / Sideways(1) / Bear(2)
    """
    
    def __init__(self, n_states=3, lookback_days=504):
        self.n_states = n_states
        self.lookback = lookback_days  # 2년 일봉
        self.model = None
        self.state_map = {}  # 학습 후 상태 매핑
    
    def prepare_features(self, prices: pl.DataFrame):
        """관측 변수: 수익률 + 변동성 (2차원)"""
        df = prices.sort("date")
        returns = df["close"].pct_change().drop_nulls()
        
        # 21일 롤링 변동성
        vol_21d = (returns.rolling_std(21) 
                   * np.sqrt(252)).drop_nulls()
        
        # 동일 길이로 맞춤
        n = min(len(returns), len(vol_21d), self.lookback)
        X = np.column_stack([
            returns.tail(n).to_numpy(),
            vol_21d.tail(n).to_numpy()
        ])
        return X[~np.isnan(X).any(axis=1)]
    
    def fit(self, prices: pl.DataFrame):
        """HMM 학습 (월 1회 재학습 권장)"""
        X = self.prepare_features(prices)
        
        self.model = GaussianHMM(
            n_components=self.n_states,
            covariance_type="full",
            n_iter=200,
            random_state=42,
            tol=0.01
        )
        self.model.fit(X)
        
        # 상태 매핑: 평균 수익률 기준 정렬
        means = self.model.means_[:, 0]  # 수익률 평균
        sorted_idx = np.argsort(means)[::-1]
        # sorted_idx[0]=가장 높은 수익→Bull
        self.state_map = {
            sorted_idx[0]: "bull",
            sorted_idx[1]: "sideways", 
            sorted_idx[2]: "bear"
        }
        return self
    
    def predict_current_regime(self, prices) -> dict:
        """현재 레짐 확률 반환"""
        X = self.prepare_features(prices)
        
        # Forward algorithm → 마지막 시점 필터링 확률
        log_prob, posteriors = self.model.score_samples(X)
        last_probs = posteriors[-1]
        
        result = {}
        for state_idx, regime_name in self.state_map.items():
            result[regime_name] = float(last_probs[state_idx])
        
        # 가장 높은 확률의 레짐
        result["current"] = max(result, key=result.get)
        return result
    
    def get_regime_history(self, prices) -> list:
        """전체 기간 레짐 히스토리"""
        X = self.prepare_features(prices)
        states = self.model.predict(X)
        return [self.state_map.get(s, "unknown") for s in states]`}</Code>

    <Hd c={P.o}>레짐별 전략 배분 매트릭스 (핵심!)</Hd>
    <div style={{ borderRadius: 8, overflow: "hidden", border: `1px solid ${P.bd}`, margin: "8px 0" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", background: P.s2,
        padding: "8px 10px", fontSize: 10, fontWeight: 700 }}>
        <span style={{ color: P.tm }}>전략</span>
        <span style={{ color: P.g }}>🟢 Bull</span>
        <span style={{ color: P.o }}>🟡 Sideways</span>
        <span style={{ color: P.r }}>🔴 Bear</span>
      </div>
      {[
        ["① Low-Vol+Quality", "20%", "35%", "40%"],
        ["② Vol-Momentum", "35%", "20%", "5%"],
        ["③ 페어즈(Market Neutral)", "15%", "25%", "35%"],
        ["④ Vol-Targeting 스케일", "1.2x", "0.9x", "0.5x"],
        ["⑤ LLM/FinBERT 오버레이", "±20%", "±15%", "±10%"],
        ["💰 현금 비중", "0~10%", "15~30%", "40~70%"],
        ["📈 목표 CAGR", "30~45%", "8~15%", "-5~+5%"],
      ].map((r, i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr",
          padding: "6px 10px", fontSize: 11, background: i % 2 === 0 ? P.s1 : "transparent",
          borderTop: `1px solid ${P.bd}08` }}>
          <span style={{ color: P.tb, fontWeight: 600 }}>{r[0]}</span>
          <span style={{ color: P.g, fontWeight: 600 }}>{r[1]}</span>
          <span style={{ color: P.o, fontWeight: 600 }}>{r[2]}</span>
          <span style={{ color: P.r, fontWeight: 600 }}>{r[3]}</span>
        </div>
      ))}
    </div>

    <Note c={P.g} icon="📊" title="레짐별 기대 수익 시뮬레이션 (ChatGPT 모델)">
      <b>3년 시나리오:</b> 강세 1년(+40%) + 횡보 1년(+12%) + 약세 1년(-5%)<br />
      = 기하평균 CAGR ≈ <b>14.8%</b> (V3 목표 17%와 부합)<br />
      <b>핵심:</b> "약세장에서 -5%만 잃는 것"이 전체 CAGR을 결정. 상용 AI는 약세장에서 -30~40% 손실 → CAGR 급락.
    </Note>

    <Code>{`# engine/risk/regime_allocator.py
class RegimeAllocator:
    """레짐별 전략 배분 자동 조절"""
    
    ALLOCATION_MATRIX = {
        "bull": {
            "LowVolQuality": 0.20,
            "VolManagedMomentum": 0.35,
            "PairsTrading": 0.15,
            "cash": 0.05,
            "vol_scale": 1.2,
            "sentiment_range": 0.20,
        },
        "sideways": {
            "LowVolQuality": 0.35,
            "VolManagedMomentum": 0.20,
            "PairsTrading": 0.25,
            "cash": 0.20,
            "vol_scale": 0.9,
            "sentiment_range": 0.15,
        },
        "bear": {
            "LowVolQuality": 0.40,
            "VolManagedMomentum": 0.05,
            "PairsTrading": 0.35,
            "cash": 0.55,  # 최소 현금 (kill switch에 의해 더 증가 가능)
            "vol_scale": 0.5,
            "sentiment_range": 0.10,
        },
    }
    
    def __init__(self, regime_detector):
        self.detector = regime_detector
        self.transition_speed = 0.3  # 급변 방지 (30%/일 최대 변경)
    
    def get_allocation(self, prices, 
                       current_alloc: dict) -> dict:
        """현재 레짐 기반 목표 배분 (부드러운 전환)"""
        regime = self.detector.predict_current_regime(prices)
        current_regime = regime["current"]
        confidence = regime[current_regime]
        
        target = self.ALLOCATION_MATRIX[current_regime].copy()
        
        # 확률 가중: confidence < 0.6이면 보수적으로
        if confidence < 0.6:
            # sideways에 가깝게 블렌딩
            safe = self.ALLOCATION_MATRIX["sideways"]
            for k in target:
                if isinstance(target[k], (int, float)):
                    target[k] = (target[k] * confidence + 
                                safe[k] * (1-confidence))
        
        # 급변 방지: 하루 최대 30% 변경
        smoothed = {}
        for k in target:
            if k in current_alloc and isinstance(target[k], (int,float)):
                diff = target[k] - current_alloc[k]
                max_change = abs(current_alloc[k]) * self.transition_speed
                smoothed[k] = current_alloc[k] + np.clip(
                    diff, -max_change, max_change)
            else:
                smoothed[k] = target[k]
        
        smoothed["_regime"] = current_regime
        smoothed["_confidence"] = confidence
        return smoothed`}</Code>
  </div>);
}

function KillSwitch() {
  return (<div>
    <Note c={P.o} icon="🛡️" title="3단계 Drawdown Kill Switch — V3.1 생존 엔진">
      ChatGPT: "이 기능 없으면 30% 전략은 반드시 붕괴". Grok: "MDD -30% 넘으면 대부분 퇴장". V3.1은 3단계 자동 방어 + 레짐 연동으로 포트폴리오 생존율 극대화.
    </Note>

    <Hd c={P.o}>3단계 자동 방어 체계</Hd>
    <div style={{ display: "grid", gap: 10, margin: "8px 0" }}>
      {[
        { level: "⚠️ Level 1: 경고", trigger: "MDD -10%", action: "전체 익스포저 50%로 축소, Telegram 경고", c: P.o,
          detail: "모멘텀 전략 비중 절반 → Low-Vol/페어즈로 재배분. 신규 매수 중단, 기존 포지션 유지." },
        { level: "🔴 Level 2: 방어", trigger: "MDD -15%", action: "현금 70%+, 방어주만 유지", c: P.r,
          detail: "모멘텀 전략 완전 청산. 페어즈(Market Neutral)만 유지. Vol-Targeting 0.3x로 축소. 레짐 Bear 강제 전환." },
        { level: "🚨 Level 3: 비상", trigger: "MDD -20%", action: "전량 청산, 냉각기 30일", c: "#dc2626",
          detail: "모든 포지션 즉시 청산. 30일간 매매 중단(냉각기). 전략 전체 재검토 필수. 재진입 시 Half-Kelly의 절반(Quarter-Kelly)로 시작." },
      ].map((l, i) => (
        <Box key={i} glow={l.c} s={{ borderLeft: `4px solid ${l.c}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <span style={{ color: l.c, fontWeight: 800, fontSize: 14 }}>{l.level}</span>
            <Tag c={l.c}>{l.trigger}</Tag>
          </div>
          <div style={{ color: P.tb, fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{l.action}</div>
          <div style={{ color: P.tm, fontSize: 11, lineHeight: 1.6 }}>{l.detail}</div>
        </Box>
      ))}
    </div>

    <Hd c={P.b}>Kill Switch 구현 코드</Hd>
    <Code>{`# engine/risk/kill_switch.py
from enum import Enum
from datetime import datetime, timedelta

class DefenseLevel(Enum):
    NORMAL = 0
    WARNING = 1    # MDD -10%
    DEFENSIVE = 2  # MDD -15%
    EMERGENCY = 3  # MDD -20%

class DrawdownKillSwitch:
    """3단계 Drawdown Kill Switch
    ChatGPT: '이 기능 없으면 30% 전략은 반드시 붕괴'
    Grok: 'MDD -30% 넘으면 대부분 퇴장'
    """
    
    THRESHOLDS = {
        DefenseLevel.WARNING:   -0.10,  # -10%
        DefenseLevel.DEFENSIVE: -0.15,  # -15%
        DefenseLevel.EMERGENCY: -0.20,  # -20%
    }
    
    def __init__(self):
        self.peak_value = 0
        self.current_level = DefenseLevel.NORMAL
        self.cooldown_until = None  # 냉각기 종료일
        self.level_history = []
    
    def update(self, portfolio_value: float) -> DefenseLevel:
        """포트폴리오 가치 업데이트 → 방어 레벨 결정"""
        # 냉각기 체크
        if self.cooldown_until and datetime.now() < self.cooldown_until:
            return DefenseLevel.EMERGENCY
        
        self.peak_value = max(self.peak_value, portfolio_value)
        drawdown = (portfolio_value - self.peak_value) / self.peak_value
        
        # 레벨 판단 (상향만, 하향은 회복 시)
        if drawdown <= self.THRESHOLDS[DefenseLevel.EMERGENCY]:
            new_level = DefenseLevel.EMERGENCY
            self.cooldown_until = datetime.now() + timedelta(days=30)
        elif drawdown <= self.THRESHOLDS[DefenseLevel.DEFENSIVE]:
            new_level = DefenseLevel.DEFENSIVE
        elif drawdown <= self.THRESHOLDS[DefenseLevel.WARNING]:
            new_level = DefenseLevel.WARNING
        else:
            # 회복 조건: 피크 대비 -5% 이내로 복구
            if drawdown > -0.05:
                new_level = DefenseLevel.NORMAL
            else:
                new_level = self.current_level  # 유지
        
        if new_level != self.current_level:
            self.level_history.append({
                "from": self.current_level.name,
                "to": new_level.name,
                "drawdown": drawdown,
                "time": datetime.now().isoformat()
            })
            self.current_level = new_level
        
        return self.current_level
    
    def get_exposure_limit(self) -> float:
        """현재 레벨에 따른 최대 익스포저"""
        limits = {
            DefenseLevel.NORMAL: 1.0,
            DefenseLevel.WARNING: 0.50,
            DefenseLevel.DEFENSIVE: 0.30,
            DefenseLevel.EMERGENCY: 0.0,
        }
        return limits[self.current_level]
    
    def get_allowed_strategies(self) -> list:
        """현재 레벨에 따른 허용 전략"""
        allowed = {
            DefenseLevel.NORMAL: ["all"],
            DefenseLevel.WARNING: ["LowVolQuality", "PairsTrading",
                                   "VolTargeting"],
            DefenseLevel.DEFENSIVE: ["PairsTrading"],  # Market Neutral만
            DefenseLevel.EMERGENCY: [],
        }
        return allowed[self.current_level]`}</Code>

    <Hd c={P.v}>ATR 기반 동적 포지션 사이징 (ChatGPT 핵심 요구)</Hd>
    <Note c={P.v} icon="📐" title="ChatGPT: '진짜 수익은 무엇을 사느냐가 아니라 얼마를 사느냐에서 결정'">
      V3의 Kelly Half는 "얼마"만 결정. V3.1은 ATR(Average True Range)로 종목별 변동성을 측정하고, 변동성이 높은 종목은 적게, 낮은 종목은 많이 배분하는 <b>변동성 역가중(Inverse Volatility Weighting)</b>을 추가합니다.
    </Note>
    <Code>{`# engine/risk/position_sizer.py
import numpy as np

class DynamicPositionSizer:
    """ATR + Vol 역가중 + Kelly 통합 사이징
    ChatGPT: 진짜 수익은 '얼마를 사느냐'에서 결정
    """
    
    def __init__(self, risk_per_trade=0.02, kelly_fraction=0.5,
                 max_position=0.10, max_sector=0.25):
        self.risk_per_trade = risk_per_trade  # 거래당 2% 리스크
        self.kelly_frac = kelly_fraction
        self.max_pos = max_position
        self.max_sector = max_sector
    
    def atr_based_size(self, price: float, atr_14: float,
                       portfolio_value: float) -> int:
        """ATR 기반: 변동성 높으면 적게, 낮으면 많이"""
        if atr_14 <= 0: return 0
        risk_amount = portfolio_value * self.risk_per_trade
        stop_distance = atr_14 * 2  # 2×ATR 손절
        shares = int(risk_amount / stop_distance)
        
        # 최대 포지션 한도
        max_shares = int(portfolio_value * self.max_pos / price)
        return min(shares, max_shares)
    
    def inverse_vol_weights(self, volatilities: dict) -> dict:
        """변동성 역가중 (Risk Parity 스타일)"""
        inv_vols = {sym: 1.0/vol for sym, vol in volatilities.items()
                    if vol > 0}
        total = sum(inv_vols.values())
        return {sym: iv/total for sym, iv in inv_vols.items()}
    
    def kelly_adjusted_size(self, win_rate: float,
                            avg_win: float, avg_loss: float,
                            atr_size: int) -> int:
        """Kelly × ATR 통합"""
        if avg_loss == 0: return 0
        kelly = (win_rate / abs(avg_loss)) - ((1-win_rate) / avg_win)
        kelly = max(kelly * self.kelly_frac, 0)
        kelly = min(kelly, 0.25)  # 최대 25% (안전)
        return int(atr_size * kelly * 4)  # 스케일링
    
    def concentration_hybrid(self, scores: dict,
                             portfolio_value: float) -> dict:
        """Risk Parity + 집중 하이브리드 (ChatGPT)
        상위 5개 60%, 나머지 10개 40%
        """
        sorted_syms = sorted(scores.items(), 
                            key=lambda x: x[1], reverse=True)
        weights = {}
        for i, (sym, score) in enumerate(sorted_syms[:15]):
            if i < 5:
                weights[sym] = 0.60 / 5  # 상위 5개 = 12% each
            else:
                weights[sym] = 0.40 / 10  # 나머지 = 4% each
        return weights`}</Code>
  </div>);
}

function FinBERTPage() {
  return (<div>
    <Note c={P.v} icon="🧠" title="FinBERT 로컬 센티먼트 엔진 — Gemini 핵심 제안">
      Gemini: "가격 데이터는 이미 과거의 정보. 시장 심리를 남들보다 빨리 읽는 것이 핵심." FinBERT를 Dell 서버(32GB RAM)에서 로컬 구동 → Claude API 비용 절감 + 지연시간 최소화.
    </Note>

    <Hd c={P.v}>FinBERT vs Claude API 비교</Hd>
    <Cmp h1="Claude API (V3)" h2="FinBERT 로컬 (V3.1)"
      items={[
        ["비용", "$20~50/월", "$0 (로컬 구동)"],
        ["지연시간", "0.5~2초 (네트워크)", "0.02~0.1초 (로컬)"],
        ["처리량", "분당 ~60건 (rate limit)", "분당 600~3000건"],
        ["금융 특화", "범용 LLM", "금융 코퍼스 fine-tuned"],
        ["컨텍스트", "긴 텍스트 분석 가능", "512토큰 제한"],
        ["오프라인", "인터넷 필수", "오프라인 가능"],
        ["정밀 분석", "높음 (긴 문서)", "보통 (짧은 텍스트)"],
      ]} />

    <Note c={P.b} icon="💡" title="V3.1 하이브리드 접근">
      <b>1차: FinBERT 로컬</b> — 대량 뉴스 헤드라인 실시간 스캔 (초당 10~50건)<br />
      <b>2차: Claude API</b> — FinBERT가 감지한 고신호 뉴스만 정밀 분석 (비용 90% 절감)<br />
      이 하이브리드로 월 API 비용 $2~5로 축소 가능.
    </Note>

    <Hd c={P.g}>FinBERT 로컬 구현</Hd>
    <Code>{`# engine/data/finbert_local.py
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import numpy as np

class FinBERTSentiment:
    """FinBERT 로컬 구동 센티먼트 분석기
    Gemini: 'Xeon 3.49GHz + 32GB RAM이면 충분'
    학술: Araci (2019), Ruan & Jiang (2025)
    """
    
    MODEL_NAME = "ProsusAI/finbert"
    
    def __init__(self, device="cpu", batch_size=32):
        self.device = device
        self.batch_size = batch_size
        self.tokenizer = AutoTokenizer.from_pretrained(self.MODEL_NAME)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            self.MODEL_NAME).to(device)
        self.model.eval()
        self.labels = ["positive", "negative", "neutral"]
    
    def analyze_batch(self, texts: list[str]) -> list[dict]:
        """배치 센티먼트 분석 (CPU에서 32건 ~0.5초)"""
        results = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i+self.batch_size]
            inputs = self.tokenizer(batch, padding=True,
                                     truncation=True, max_length=512,
                                     return_tensors="pt").to(self.device)
            
            with torch.no_grad():
                outputs = self.model(**inputs)
                probs = torch.softmax(outputs.logits, dim=-1)
            
            for j, text in enumerate(batch):
                p = probs[j].cpu().numpy()
                score = float(p[0] - p[1])  # positive - negative
                results.append({
                    "text": text[:100],
                    "positive": float(p[0]),
                    "negative": float(p[1]),
                    "neutral": float(p[2]),
                    "score": score,  # -1.0 ~ +1.0
                    "label": self.labels[np.argmax(p)],
                })
        return results
    
    def daily_sentiment_index(self, headlines: list[str]) -> dict:
        """일일 센티먼트 지수 계산"""
        results = self.analyze_batch(headlines)
        scores = [r["score"] for r in results]
        
        return {
            "mean_score": np.mean(scores),
            "median_score": np.median(scores),
            "positive_ratio": np.mean([1 for r in results 
                                       if r["label"]=="positive"]),
            "negative_ratio": np.mean([1 for r in results 
                                       if r["label"]=="negative"]),
            "strong_signals": [r for r in results 
                              if abs(r["score"]) > 0.7],
            "count": len(results),
        }`}</Code>

    <Hd c={P.o}>Claude API 정밀 분석 (2차 필터)</Hd>
    <Code>{`# engine/data/sentiment_hybrid.py
class HybridSentiment:
    """FinBERT(1차 스캔) + Claude API(2차 정밀)
    비용: $20~50/월 → $2~5/월 (90% 절감)
    """
    
    def __init__(self, finbert: FinBERTSentiment,
                 claude_client, threshold=0.7):
        self.finbert = finbert
        self.claude = claude_client
        self.threshold = threshold  # Claude 분석 트리거
    
    def analyze_pipeline(self, headlines: list[str],
                         symbol: str) -> dict:
        """하이브리드 파이프라인"""
        # 1차: FinBERT 대량 스캔 (무료, 빠름)
        finbert_results = self.finbert.analyze_batch(headlines)
        
        # 2차: 강한 신호만 Claude 정밀 분석
        strong = [r for r in finbert_results 
                  if abs(r["score"]) > self.threshold]
        
        if not strong:
            return {"score": np.mean([r["score"] 
                                      for r in finbert_results]),
                    "source": "finbert_only"}
        
        # Claude에게 강한 신호 뉴스만 전달
        strong_texts = "\\n".join([r["text"] for r in strong])
        claude_score = self._claude_analyze(symbol, strong_texts)
        
        # 가중 평균: FinBERT 60% + Claude 40%
        finbert_avg = np.mean([r["score"] for r in finbert_results])
        combined = finbert_avg * 0.6 + claude_score * 0.4
        
        return {"score": combined, "source": "hybrid",
                "finbert": finbert_avg, "claude": claude_score,
                "strong_count": len(strong)}`}</Code>

    <Hd c={P.c}>대체 데이터 소스 (Gemini + Grok 제안)</Hd>
    {[
      { name: "Reddit/WSB 언급량", desc: "밈스톡 조기 감지. Reddit API + PRAW 라이브러리", cost: "$0", diff: "★★☆" },
      { name: "옵션 내재변동성(IV)", desc: "Put/Call Ratio, Skew → 시장 공포 선행 지표", cost: "$0~29 (Polygon)", diff: "★★☆" },
      { name: "SEC EDGAR Form 4", desc: "내부자 매수/매도 → 6~12개월 초과수익 상관", cost: "$0", diff: "★☆☆" },
      { name: "FRED 매크로 지표", desc: "금리, CPI, 실업률, 장단기 스프레드", cost: "$0", diff: "★☆☆" },
    ].map((d, i) => (
      <div key={i} style={{ display: "grid", gridTemplateColumns: "160px 1fr 60px 50px", gap: 8,
        padding: "6px 10px", background: i % 2 === 0 ? P.s1 : "transparent", borderRadius: 4,
        fontSize: 11, alignItems: "center" }}>
        <span style={{ color: P.c, fontWeight: 700 }}>{d.name}</span>
        <span style={{ color: P.tm }}>{d.desc}</span>
        <span style={{ color: P.g, fontFamily: "monospace" }}>{d.cost}</span>
        <span style={{ color: P.o }}>{d.diff}</span>
      </div>
    ))}
  </div>);
}

function DevPlan() {
  return (<div>
    <Note c={P.b} icon="🗺️" title="V3.1 수정된 개발 로드맵">
      V3 대비 주요 변경: Phase 1에 FinBERT 환경 추가, Phase 2에 HMM 레짐 모듈 선행 개발, Phase 3에 Kill Switch 통합. 전체 기간 변경 없음(30개월+).
    </Note>

    <Hd c={P.b}>Phase 1 수정 (1~4개월): +FinBERT 환경</Hd>
    {[
      { w: "1주", task: "기존 환경 + hmmlearn, transformers, torch 추가 설치", status: "추가", c: P.o },
      { w: "2주", task: "FinBERT 모델 다운로드 + 로컬 CPU 추론 속도 벤치마크", status: "신규", c: P.r },
      { w: "2~3주", task: "기존 데이터 파이프라인 + Reddit/SEC EDGAR 수집기", status: "확장", c: P.o },
      { w: "4주", task: "HMM 3-State 프로토타입 (SPY 15년 데이터로 학습)", status: "신규", c: P.r },
    ].map((t, i) => (
      <div key={i} style={{ display: "grid", gridTemplateColumns: "50px 1fr 50px", gap: 8,
        padding: "6px 10px", background: i % 2 === 0 ? P.s1 : "transparent", borderRadius: 4,
        fontSize: 11, alignItems: "center" }}>
        <span style={{ color: P.b, fontWeight: 700, fontFamily: "monospace" }}>{t.w}</span>
        <span style={{ color: P.t }}>{t.task}</span>
        <Tag c={t.c}>{t.status}</Tag>
      </div>
    ))}

    <Hd c={P.v}>Phase 2 수정 (5~14개월): 레짐 선행 + 전략 적응</Hd>
    {[
      { w: "5~6월", task: "HMM 레짐 모듈 완성 + 15년 백테스트 레짐 히스토리 검증", status: "신규 선행", c: P.r },
      { w: "6~7월", task: "Kill Switch 3단계 + ATR 포지션 사이저 구현", status: "신규 선행", c: P.r },
      { w: "7~9월", task: "① Low-Vol+Quality (레짐별 배분 연동)", status: "수정", c: P.o },
      { w: "9~10월", task: "④ Vol-Targeting (레짐별 스케일 팩터 연동)", status: "수정", c: P.o },
      { w: "10~11월", task: "② Vol-Managed 모멘텀 (Bull에서만 풀 가동)", status: "수정", c: P.o },
      { w: "11~12월", task: "⑤ FinBERT 하이브리드 센티먼트 + Claude 2차", status: "대폭 수정", c: P.r },
      { w: "12~14월", task: "③ 페어즈 트레이딩 (Bear 레짐 핵심 전략)", status: "수정", c: P.o },
    ].map((t, i) => (
      <div key={i} style={{ display: "grid", gridTemplateColumns: "60px 1fr 80px", gap: 8,
        padding: "6px 10px", background: i % 2 === 0 ? P.s1 : "transparent", borderRadius: 4,
        fontSize: 11, alignItems: "center" }}>
        <span style={{ color: P.v, fontWeight: 700, fontFamily: "monospace" }}>{t.w}</span>
        <span style={{ color: P.t }}>{t.task}</span>
        <Tag c={t.c}>{t.status}</Tag>
      </div>
    ))}

    <Hd c={P.o}>Phase 3 수정 (15~18개월): 통합 + 설명가능성</Hd>
    {[
      { w: "15월", task: "레짐 기반 오케스트레이터 (5전략 + 레짐 배분 매트릭스)", status: "핵심 수정", c: P.r },
      { w: "16월", task: "Kill Switch ↔ 레짐 ↔ Vol-Targeting 3중 연동", status: "신규", c: P.r },
      { w: "17월", task: "Feature Importance 시각화 (왜 이 포지션? 설명)", status: "신규 (Grok)", c: P.r },
      { w: "18월", task: "MAUI 대시보드: 레짐 게이지 + Kill Switch 상태 + 센티먼트 히트맵", status: "확장", c: P.o },
    ].map((t, i) => (
      <div key={i} style={{ display: "grid", gridTemplateColumns: "50px 1fr 90px", gap: 8,
        padding: "6px 10px", background: i % 2 === 0 ? P.s1 : "transparent", borderRadius: 4,
        fontSize: 11, alignItems: "center" }}>
        <span style={{ color: P.o, fontWeight: 700, fontFamily: "monospace" }}>{t.w}</span>
        <span style={{ color: P.t }}>{t.task}</span>
        <Tag c={t.c}>{t.status}</Tag>
      </div>
    ))}

    <Hd c={P.p}>Phase 4 수정 (19~30개월): 레짐 전환 스트레스 테스트</Hd>
    <Note c={P.p} icon="🧪" title="V3.1 Paper Trading 추가 검증 항목">
      <b>기존 V3:</b> Sharpe, MDD, DSR, Monte Carlo<br />
      <b>V3.1 추가:</b><br />
      • <b>레짐 전환 스트레스:</b> 2020 COVID(Bull→Bear 4주), 2022 금리인상(Bull→Bear 6개월) 시뮬레이션<br />
      • <b>Kill Switch 발동 테스트:</b> 의도적 MDD -10%, -15%, -20% 시나리오에서 방어 동작 확인<br />
      • <b>센티먼트 신호 지연 테스트:</b> FinBERT 신호가 실제 가격에 선행하는지 Granger Causality 검증<br />
      • <b>레짐 오탐률:</b> HMM이 Bull을 Bear로 오판하는 빈도 측정 (False Positive Rate &lt; 15% 목표)
    </Note>

    <Hd c={P.g}>V3.1 추가 패키지</Hd>
    <Code>{`# V3.1 추가 requirements
hmmlearn>=0.3.2          # HMM 레짐 감지
transformers>=4.40.0     # FinBERT 로컬 구동
torch>=2.2.0             # PyTorch (CPU only)
praw>=7.7.0              # Reddit API
shap>=0.45.0             # Feature Importance 설명
plotly>=5.22.0           # 인터랙티브 시각화
gradio>=4.0.0            # 프로토타입 UI (개발 중)

# 설치 (CPU 전용, GPU 없는 Dell 서버)
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install transformers hmmlearn praw shap`}</Code>

    <Hd c={P.c}>V3.1 월간 운영 비용 (수정)</Hd>
    <div style={{ borderRadius: 8, overflow: "hidden", border: `1px solid ${P.bd}` }}>
      {[
        ["Alpaca", "$0", "커미션 프리 + Paper 무료"],
        ["Claude API", "$2~5", "FinBERT 1차 필터로 90% 절감 (기존 $20~50)"],
        ["Polygon.io", "$0~29", "옵션 IV 데이터 (Basic plan)"],
        ["Reddit API", "$0", "PRAW 무료 (rate limit 내)"],
        ["Dell 서버", "$0", "기존 32GB RAM + FinBERT CPU 구동"],
        ["합계", "$2~34/월", "V3 대비 $18~45 절감"],
      ].map((r, i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: "100px 70px 1fr",
          padding: "6px 10px", fontSize: 11,
          background: i === 5 ? `${P.g}10` : i % 2 === 0 ? P.s1 : "transparent",
          fontWeight: i === 5 ? 700 : 400 }}>
          <span style={{ color: P.tb }}>{r[0]}</span>
          <span style={{ color: P.g, fontFamily: "monospace" }}>{r[1]}</span>
          <span style={{ color: P.tm }}>{r[2]}</span>
        </div>
      ))}
    </div>
  </div>);
}

function Architecture() {
  return (<div>
    <Note c={P.c} icon="🏗️" title="V3.1 시스템 아키텍처 (수정)">
      V3 대비 추가: HMM 레짐 엔진, Kill Switch 모듈, FinBERT 로컬 엔진, Feature Importance 모듈. 데이터 흐름에 레짐→배분 피드백 루프 추가.
    </Note>

    <Hd c={P.c}>V3.1 전체 데이터 흐름</Hd>
    <Code>{`[데이터 수집 레이어]
  yfinance(일봉) ──────┐
  Alpaca(실시간) ──────┤
  FRED(매크로) ────────┤──▶ Parquet + Redis + MSSQL
  EDGAR(내부자+재무) ──┤         │
  Reddit/WSB ──────────┤    ┌────┴────────────────────────┐
  News Headlines ──────┘    │  🧠 FinBERT 로컬 (1차 스캔)  │
                            │  → Claude API (2차 정밀)     │
                            └────┬────────────────────────┘
                                 │ 센티먼트 스코어
  ┌──────────────────────────────┼──────────────────────────┐
  │         🎯 HMM 레짐 감지 엔진                          │
  │  SPY + VIX + 채권수익률 → 3-State (Bull/Side/Bear)     │
  │  → 레짐 확률 + 전환 신호                                │
  └────────────┬───────────────────────────────────────────┘
               │ 레짐 상태
  ┌────────────┴───────────────────────────────────────────┐
  │              전략 엔진 (레짐 적응형)                     │
  │  ┌─────────────────────────────────────────────────┐   │
  │  │  레짐 배분 매트릭스                               │   │
  │  │  Bull:  Mmtm 35% LV 20% Pairs 15% Cash 5%      │   │
  │  │  Side:  LV 35% Pairs 25% Mmtm 20% Cash 20%     │   │
  │  │  Bear:  LV 40% Pairs 35% Mmtm 5% Cash 55%      │   │
  │  └─────────────────────────────────────────────────┘   │
  │  ① Low-Vol+Quality ──┐                                 │
  │  ② Vol-Momentum ─────┤──▶ 시그널 종합                  │
  │  ③ Pairs Trading ────┘    ← ⑤ FinBERT/Claude 오버레이  │
  │              │                                          │
  │         ④ Vol-Targeting 오버레이                        │
  │              │                                          │
  │  ┌───────────┴─────────────────────────────────────┐   │
  │  │  🛡️ 3단계 Kill Switch                           │   │
  │  │  MDD -10% → 50% 축소                            │   │
  │  │  MDD -15% → 70% 현금 (Pairs만 유지)             │   │
  │  │  MDD -20% → 전량 청산 + 30일 냉각               │   │
  │  └───────────┬─────────────────────────────────────┘   │
  │              │                                          │
  │  ┌───────────┴─────────────────────────────────────┐   │
  │  │  📐 ATR 동적 포지션 사이징                       │   │
  │  │  Vol 역가중 + Kelly Half + 집중 하이브리드       │   │
  │  │  → VWAP 분할 실행                               │   │
  │  └───────────┬─────────────────────────────────────┘   │
  └──────────────┼─────────────────────────────────────────┘
     ┌───────────┼──────────────┐
     ▼           ▼              ▼
  [Alpaca]   [MSSQL 로그]   [MAUI 대시보드]
  주문실행   거래/성과기록    레짐 게이지
                              Kill Switch 상태
                              센티먼트 히트맵
                              Feature Importance
                              Telegram 알림`}</Code>

    <Hd c={P.v}>V3 → V3.1 디렉토리 구조 변경</Hd>
    <Code>{`quant-v3/engine/
  ├── data/
  │   ├── ... (기존 유지)
+ │   ├── finbert_local.py    # FinBERT 로컬 엔진
+ │   ├── sentiment_hybrid.py # FinBERT+Claude 하이브리드
+ │   ├── reddit_collector.py # Reddit/WSB 수집기
+ │   └── options_iv.py       # 옵션 내재변동성
  ├── risk/
  │   ├── manager.py          # 통합 리스크 (수정)
+ │   ├── regime.py           # HMM 레짐 감지
+ │   ├── regime_allocator.py # 레짐별 배분 매트릭스
+ │   ├── kill_switch.py      # 3단계 Kill Switch
+ │   ├── position_sizer.py   # ATR 동적 사이징
  │   ├── kelly.py            # (기존, position_sizer로 흡수)
  │   └── stop_loss.py        # (기존 유지)
  ├── strategies/
  │   ├── ... (기존 5전략 유지, 레짐 연동 수정)
  ├── explain/
+ │   ├── feature_importance.py # SHAP 기반 설명
+ │   └── regime_dashboard.py   # 레짐 시각화 데이터
  └── backtest/
      ├── ... (기존 유지)
+     ├── regime_stress.py    # 레짐 전환 스트레스 테스트
+     └── granger_test.py     # 센티먼트 선행성 검증`}</Code>

    <Hd c={P.g}>성공 벤치마크 (수정)</Hd>
    <Row items={[
      { c: P.g, label: "V3.1 목표 CAGR", value: "15~20%", sub: "레짐 평균 (강세40 횡보12 약세-5)" },
      { c: P.b, label: "목표 Sharpe", value: "1.3~1.9", sub: "레짐 적응 + Kill Switch 효과" },
      { c: P.o, label: "목표 MDD", value: "-12%~-18%", sub: "Kill Switch가 -20% 차단" },
      { c: P.v, label: "월 비용", value: "$2~34", sub: "V3 대비 40~60% 절감" },
    ]} />

    <Note c={P.r} icon="⚠️" title="4개 LLM 통합 경고">
      <b>Grok:</b> "몇백% 마케팅을 이기는 건 불가능. 지속 가능한 리스크 조정 수익이 진짜 경쟁력."<br />
      <b>ChatGPT:</b> "30% 10년 지속은 매우 어려움. 하락장에서 덜 잃는 것이 핵심."<br />
      <b>Gemini:</b> "남들이 다 보는 Yahoo Finance 데이터로는 초과수익 불가. 대체 데이터 필수."<br />
      <b>Claude:</b> "상용 AI의 치명적 약점은 단일 레짐 의존성. V3.1의 레짐 적응이 구조적 우위."
    </Note>
  </div>);
}

// ═══════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════
const tabs = [
  { id: "why", icon: "🔄", label: "V3→V3.1", c: P.w },
  { id: "regime", icon: "🎯", label: "레짐 감지", c: P.r },
  { id: "kill", icon: "🛡️", label: "Kill Switch", c: P.o },
  { id: "finbert", icon: "🧠", label: "FinBERT", c: P.v },
  { id: "dev", icon: "🗺️", label: "개발 로드맵", c: P.b },
  { id: "arch", icon: "🏗️", label: "아키텍처", c: P.c },
];

const pages = { why: WhyV31, regime: RegimeDetection, kill: KillSwitch, finbert: FinBERTPage, dev: DevPlan, arch: Architecture };

export default function App() {
  const [active, setActive] = useState("why");
  const Page = pages[active];

  return (
    <div style={{ minHeight: "100vh", background: P.bg, color: P.t,
      fontFamily: "'Pretendard',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif" }}>
      <link href="https://cdnjs.cloudflare.com/ajax/libs/pretendard/1.3.9/static/pretendard.min.css" rel="stylesheet" />

      {/* Header */}
      <div style={{ background: "linear-gradient(180deg,#0e0f1a 0%,#06070c 100%)",
        borderBottom: `1px solid ${P.bd}`, padding: "18px 16px 12px", textAlign: "center" }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <span style={{ background: `${P.r}20`, color: P.r, padding: "2px 10px",
            borderRadius: 20, fontSize: 10, fontWeight: 700, border: `1px solid ${P.r}40` }}>V3.1 UPDATE</span>
        </div>
        <h1 style={{ fontSize: 20, fontWeight: 900, margin: "4px 0",
          background: "linear-gradient(135deg,#ef4444,#f59e0b,#22c55e,#3b82f6,#8b5cf6)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
          레짐 적응형 퀀트 시스템
        </h1>
        <p style={{ color: P.tm, fontSize: 11, margin: 0 }}>
          4 LLM 합의: Regime Detection + Kill Switch + FinBERT + Dynamic Sizing
        </p>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", overflowX: "auto", gap: 2, padding: "6px 10px",
        borderBottom: `1px solid ${P.bd}`, background: "#090a12" }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setActive(t.id)}
            style={{
              background: active === t.id ? `${t.c}18` : "transparent",
              border: active === t.id ? `1px solid ${t.c}35` : "1px solid transparent",
              borderRadius: 8, padding: "5px 10px", cursor: "pointer",
              color: active === t.id ? t.c : P.tm,
              fontSize: 11, fontWeight: active === t.id ? 700 : 500,
              whiteSpace: "nowrap", fontFamily: "inherit",
              transition: "all 0.15s ease",
            }}>
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ padding: "12px 14px", maxWidth: 860, margin: "0 auto" }}>
        <Page />
      </div>

      {/* Footer */}
      <div style={{ textAlign: "center", padding: "16px", borderTop: `1px solid ${P.bd}`,
        color: "#3a3d50", fontSize: 9 }}>
        Quant V3.1 | ChatGPT + Gemini + Grok + Claude 통합 | 레짐 적응형 17% CAGR
      </div>
    </div>
  );
}
