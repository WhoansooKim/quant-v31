# Lit review part 4/4: swing-horizon timing and rotation for indices, sector ETFs and leveraged ETFs (2021–2026)

Compiled 2026-11-14. About 47 web searches plus primary-page fetches (CXO, Quantpedia, NY Fed Liberty Street, arXiv, Concretum, and the Lou-Polk-Skouras 2026 PDF read in full text).
Out of scope here and covered by other parts: single-stock price anomalies, event signals, ML/LLM/replication.

**Context for the "fit" column.** The system already holds a 3x S&P 500 trend core: an SPY>SMA200 buffer ensemble that switches between UPRO and BIL. Any addition has to earn its keep after **0.25% per side** costs with **next-day-open fills**, and it must add something the core does not already capture.

**Verification flag (V column):**
- **P** = the number was read on the primary source or the full text.
- **F** = the number was read on a fetched secondary page (CXO, Quantpedia, Concretum, NY Fed).
- **S** = the number comes from search snippets or summaries only. Treat it as unverified.

**Fill flag:**
- **SC** = the study fills at the same close the signal is computed on, or fills intraday.
- **NO** = next open.
- **?** = the study does not say.

A rule tagged SC cannot be run as published under next-open fills.

Items dated before 2021 appear only as **baselines**, marked (B), when the 2021–2026 literature argues against them.

---

## A. Trend / moving-average timing of equity indices, including leveraged trend

| # | Item | Exact rule | Instruments | Hold / turnover | Sample | Performance | Costs | Fill | OOS / post-pub | Free data | V |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 (B) | Gayed & Bilello 2016, "Leverage for the Long Run", SSRN WP (summarized by CXO). https://www.cxoadvisory.com/volatility-effects/leveraging-the-u-s-stock-market-based-on-sma-rules/ | When the S&P 500 TR closes above its SMA200, hold 1.25x/2x/3x with daily-reset leverage. Otherwise hold T-bills. | Index (simulated LETF) | Daily signal; a few switches a year | Oct 1928 – Oct 2015 | **Gross Sharpe:** SMA200 1x 0.60 (MDD −50%); 2x LRS 0.51 (MDD −78%); B&H 1x 0.30 (MDD −86%); 2x constant 0.27 (MDD −99%). Terminal value on $10k: about $270M at 1.25x, $39B at 2x, $9T at 3x. | 1%/yr leverage cost. **Switching costs ignored.** | ? (close signals) | None beyond the sample | Yes: yfinance ^GSPC/SPY, FRED DTB3 | F |
| A2 (B) | Zakamulin, "Market timing with moving averages" (JAM 2014; book 2017); Alpha Architect 2023 note "Optimal trend following with transaction costs". https://link.springer.com/article/10.1057/jam.2014.25 · https://alphaarchitect.com/optimal-trend-following-with-transaction-costs/ | Many MA rules. Walk-forward rule selection. | S&P Composite and 3 other indices | Monthly / daily | 1860s–2012 (OOS from 1930) | Net OOS: SMA raised the S&P net Sharpe by about 10%. Only 3 of 8 strategy-index pairs beat B&H on net Sharpe. | **0.25% one way** (the same as our cost) | Monthly close | Data-mining-corrected OOS: the edge is "highly overstated" | Yes | S |
| A3 | Newfound Research, rebalance timing luck and trend ensembles (2013, 2019; Hoffstein et al. 2020 "Rebalance Timing Luck"). https://blog.thinknewfound.com/2013/08/the-luck-of-the-rebalance-timing/ · https://blog.thinknewfound.com/2019/07/ensemble-multi-asset-momentum/ | Faber 10M SMA run at 21 day-offsets on SPY. An ensemble of 1,023 trend specs (TR, price−MA, dual MA; 20–360 d lookbacks) plus 21 tranches. | SPY, multi-asset | Monthly, tranched daily | 1990s–2019 | Day-of-month choice alone moves results heavily (whipsaw). Timing luck often exceeds **100 bp/yr** in rules-based indices. | Varies | Close | Methodological rather than an alpha claim | Yes | S |
| A4 | Goulding, Harvey & Mazzoleni 2023, "Momentum turning points", JFE 149(3):378–406; Garg et al., "Breaking bad trends", FAJ 80(1) 2024. https://econpapers.repec.org/RePEc:eee:jfinec:v:149:y:2023:i:3:p:378-406 | Blend slow (12-month) and fast (1–2 month) momentum. When they disagree (state = Correction or Rebound), use an intermediate speed: slower after Corrections, faster after Rebounds. | Equity market, futures, factors | Monthly | 1926–2020s | Intermediate-speed blends beat both slow and fast on Sharpe. Figures not verified. | Gross in the main tests | Month-end close | Published 2023. Mechanism-based (reduces turning-point lag). | Yes | S |
| A5 | Zarattini 2025, Faber GTAA extension (Concretum). https://concretumgroup.com/global-tactical-asset-allocation/ · https://www.cxoadvisory.com/?p=46808 | Faber GTAA kept unchanged: 5 assets, each held if above its 200-day SMA at month end, else cash. Staggered 4-week tranches also tested. | SPY, EFA, IEF, VNQ, DBC style | Monthly | **True OOS: 2006 – Mar 2025** | OOS gross CAGR about **6.0%**, Sharpe **0.68**, against 11.7% / 0.81 in the original sample. Concretum gives MDD as 11.7%; CXO uses 11.7% as the original CAGR, so the number is in conflict. | Not stated | Month-end close | **About half the original return out of sample.** Tranching reduces timing risk. | Yes | S |
| A6 | Quantpedia 2025, "Leveraged ETFs in Asset Allocation: Opportunity or Trap?". https://quantpedia.com/leveraged-etfs-in-asset-allocation-opportunity-or-trap/ | 10M SMA or "within 95–100% of 12-month high" filter on 2x equity. Simulated 2x before SSO existed (2006). | SPY to SSO | Monthly | 1926–2025 (monthly) | **2x passive:** CAR 12.59%, vol 36.92%. **2x + 10M SMA:** CAR 13.54%, vol 25.30%. **1x + SMA:** 9.63%, vol 12.58%. **1x passive:** 10.20%, vol 18.23%. MDD and Sharpe only in images. | Fees and leverage cost deducted. **Trading costs not stated.** | Month-end close | Conclusion: "leverage is beneficial only when actively managed." | Yes | F |
| A7 | van Staden, Forsyth & Li 2024/25, "Smart leverage? Rethinking LETFs…", arXiv:2412.05431. https://arxiv.org/abs/2412.05431 | Information-ratio-optimal dynamic allocation between an LETF and 1x ETF, solved by a neural network on bootstrapped history. | Broad index LETF vs ETF | Dynamic | Bootstrapped | LETF strategies are more likely to beat the benchmark and show partial stochastic dominance. LETF payoff is "call-like". | Says "inexpensive leverage"; trading costs not quantified | n/a | Simulation only | n/a | F |
| A8 (B) | Hurst, Ooi & Pedersen 2017 (century of trend); Babu et al. 2020, JPM, "You can't always trend when you want". https://www.aqr.com/Insights/Research/Journal-Article/You-Cant-Always-Trend-When-You-Want | 1/3/12-month TSMOM, vol-scaled, across 67 futures | Futures | Monthly | 1880–2016 / 2010s | Positive in every decade. Max drawdown about 25%. Weak 2010s came from a lack of large moves, not a structural break. | 2/20 fees plus costs in Hurst | Close | 2022 was a strong year (A10) | Futures not free. Partial proxy via ETFs: DBMF 2019+, KMLM 2020+. | S |
| A9 (B) | Huang, Li, Wang & Zhou 2020, "Time series momentum: is it there?", JFE 135(3). https://econpapers.repec.org/RePEc:eee:jfinec:v:135:y:2020:i:3:p:774-794 | Asset-by-asset regressions of the next month's return on the past 12-month return, with bootstraps | 55 futures | Monthly | 1985–2015 | Little asset-level evidence in or out of sample. The pooled t-stat is upward-biased because means differ across assets. | — | — | Critique | — | S |
| A10 | 2022 cross-asset TSMOM performance (industry): HedgeNordic, Alpha-Week CTA review, Man Institute "Gaining momentum" 2022, Return Stacked (RSST). https://hedgenordic.com/2023/01/2022-the-year-of-traditional-trend-followers · https://www.man.com/maninstitute/gaining-momentum-trend | Diversified futures trend | SG Trend, CTA funds | Weeks to months | 2022 | One of trend's best years since 2008. Nordic managed-futures funds with positive 2022 averaged +14.4%. 100% equity + 100% managed-futures stacks lost less than the S&P in 2000–02, 2008 and 2022. | Net of fund fees | Live | **Live, after publication** | Fund NAVs or ETFs (DBMF, KMLM, CTA, RSST) on yfinance; short histories | S |

## B. Volatility management and volatility targeting (post-Cederburg)

| # | Item | Rule | Instruments | Hold / turnover | Sample | Performance | Costs | Fill | OOS / post-pub | Free data | V |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 (B) | Cederburg, O'Doherty, Wang & Yan 2020, JFE 138:95–117. https://www.lehigh.edu/~xuy219/research/COWY.pdf | Scale weight by c / last month's realized variance (Moreira-Muir) | 103 equity strategies | Monthly | 1926–2015 | Managed Sharpe beats unmanaged in only **53/103** (8 significant). Real-time combinations lose Sharpe in 72/103. The in-sample alphas (77/103) need look-ahead scaling. | Gross | Month-end | **The key negative OOS result** | Yes | S |
| B2 | Barroso & Detzel 2021, JFE 140:744–767. https://econpapers.repec.org/RePEc:eee:jfinec:v:140:y:2021:i:3:p:744-767 | Vol-managed factors with 6 cost-mitigation schemes | Market and factors | Monthly | 1926–2010s | Net of costs, non-market factors give about zero alpha. **The vol-managed market portfolio stays profitable net**, but only when sentiment is high. | Realistic, stock-level | Month-end | — | Yes | S |
| B3 | Wang & Yan 2021, "Downside risk and the performance of volatility-managed portfolios", JBF 131:106198. https://ideas.repec.org/a/eee/jbfina/v131y2021ics0378426621001576.html | Scale by **downside** semivariance instead of total variance | 9 factors and 94 anomalies | Monthly | — | Positive alpha in 89/94 anomalies. Beats total-vol scaling in real time. | Gross. Schwarz 2021 finds the gain largely offset by costs internationally. | Month-end | — | Yes | S |
| B4 | DeMiguel, Martín-Utrera & Uppal 2024, JF 79(6):3859–3891. https://econpapers.repec.org/RePEc:bla:jfinan:v:79:y:2024:i:6:p:3859-3891 | Conditional multifactor mean-variance with vol-managed factors and trade netting | 9 factors | Monthly | — | OOS net Sharpe about **16%** above the unconditional portfolio (working-paper figure) | Net, with trading diversification | Month-end | Answers Cederburg for multifactor portfolios, not for a single index | No (factor data from Ken French is free, but the ETFs differ) | S |
| B5 | Bongaerts, Kang & van Dijk 2020, "Conditional volatility targeting", FAJ 76(4):54–71. https://econpapers.repec.org/RePEc:taf:ufajxx:v:76:y:2020:i:4:p:54-71 | Change exposure **only in extreme high or low vol states**, otherwise hold 1x | 10 equity markets, momentum | Daily/monthly; lower turnover than plain vol targeting | — | Plain vol targeting can deepen drawdowns. The conditional version improves Sharpe in all markets and cuts MDD and tails with lower turnover. | Lower turnover reported | ? | — | Yes | S |
| B6 (B) | Harvey et al. 2018, "The impact of volatility targeting", JPM 45(1). https://quantpedia.com/the-impact-of-volatility-targeting-on-equities-bonds-commodities-and-currencies | Target constant vol using EWMA estimates | 60+ assets | Daily | 1926–2016 | US equity Sharpe 0.40 → 0.48–0.51. Vol-of-vol 4.6% → 1.8%. Left tail cut. No gain for bonds, FX or commodities. | Gross; maintenance frictions noted | Close | — | Yes | S |
| B7 | Zarattini, Mele & Aziz 2025, "The Volatility Edge" (VIX ETNs); Quantpedia 2025 "Leveraged ETFs in Low-Volatility Environments"; QuantSeeker Sep 2025. https://quantpedia.com/leveraged-etfs-in-low-volatility-environments/ | Hold SPXL when MA_Y(VIX) > annualized X-day realized vol of SPY (a positive implied-minus-realized spread); otherwise out. Base X=10, Y=60. Swept X∈{5,10,20}, Y∈{10…120}. VIX lagged 1 day. Re-evaluated daily. | SPXL (3x), SPY, VIX | **Daily evaluation**; turnover not reported | 2013 – Jul 2025 | Base case: return about **2x the SPY benchmark** with higher vol and DD, and Sharpe slightly below SPY. X=20: Sharpe > 1, Calmar > 0.8. Y=10: Sharpe about 1, Calmar about 0.9. Exact tables are images only. | **No costs stated** | ? | Parameter sweep inside a single bull-heavy sample. **No out-of-sample test.** | Yes: ^VIX, SPY, SPXL/UPRO | F |

## C. Leveraged-ETF flows, intraday momentum and gamma (mostly not implementable under next-open fills)

| # | Item | Rule | Instruments | Hold | Sample | Performance | Costs | Fill | OOS / post-pub | Free data | V |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 (B) | Cheng & Madhavan 2009, JOIM, "Dynamics of leveraged and inverse ETFs" | LETF rebalancing demand ∝ L(L−1)·r·AUM, executed MOC | S&P 500 | Last 30 min | 2006–09 | A 5% market day could make LETFs about 50% of MOC volume | — | **SC** | A later S&P study calls the link "spurious". Credit Suisse puts LETFs at about 2% of EOD volume. | — | S |
| C2 | Barbon, Beckmeyer, Buraschi & Moerke 2022, SFI RP 22-40, "Liquidity provision to LETFs and equity options rebalancing flows". https://papers.ssrn.com/abstract=3925725 | Signed LETF rebalancing and option gamma imbalance relative to ADV predict EOD momentum or reversal | Stocks | Intraday | 2010s | LETF channel larger than the option channel. **The LETF effect has weakened over time and dissipates within the next day.** | — | **SC** | Decaying | No | S |
| C3 (B) | Gao, Han, Li & Zhou 2018, "Market intraday momentum", JFE 129(2):394–414; Rosa 2022 J. Forecasting; Li, Sakkas & Urquhart 2022 JFM. https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414 | First half-hour return (from prior close) predicts last half-hour; trade the last 30 min | SPY + 10 ETFs | 30 min | 1993–2013 | About 6.67%/yr timing. R² about 1.6%. | Gross | **SC (intraday)** | QuantConnect replication: lower. Rosa 2022: the overnight→last-30 version **disappears OOS**. Li et al.: OOS in 12/16 countries. | Intraday data needed | S |
| C4 | Baltussen, Da, Lammers & Martens 2021, "Hedging demand and market intraday momentum", JFE 142(1):377–403. https://econpapers.repec.org/RePEc:eee:jfinec:v:142:y:2021:i:1:p:377-403 | Rest-of-day return predicts the last 30 min. Stronger when dealer gamma is negative. | 60+ futures | 30 min | 1974–2020 | Robust over time. **Reverses over the following days.** | — | **SC** | The multi-day reversal matters for swing traders: a late-day trend leg tends to give back | No (gamma data is paid) | S |
| C5 | Zarattini, Aziz & Barbon 2024/25, "Beat the Market: an effective intraday momentum strategy for SPY", SFI RP 24-97. https://www.sfi.ch/de/publications/n-24-97-beat-the-market-an-effective-intraday-momentum-strategy-for-s-p500-etf-spy | Noise-area breakout checked every 30 min, VWAP trailing stop, flat at close, vol-sized | SPY | Intraday | May 2007 – Apr 2024 | **Net** 19.6%/yr, Sharpe 1.33, MDD about −25% | Commissions and slippage included | **Intraday** | Quantpedia Award 2025. No independent live record. | Needs minute bars | S |
| C6 | 0DTE / dealer-gamma studies (2024–25), as summarized by Quantpedia "Do S&P500 0DTEs increase market volatility?" https://quantpedia.com/do-sp500-0dtes-options-increase-market-volatility/ | Net dealer gamma predicts intraday reversal in E-mini order flow | SPX, ES | Under 1 hour | 2022–2025 | Negative link between 0DTE days and realized vol. The effect fades within an hour. | — | **SC** | A competing paper argues 0DTE amplifies moves | No | S |

## D. Sector / industry ETF rotation

| # | Item | Rule | Instruments | Hold / turnover | Sample | Performance | Costs | Fill | OOS / post-pub | Free data | V |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D1 | Zarattini & Antonacci 2024/25, "A Century of Profitable Industry Trends" (Dow Award 2025). https://concretumgroup.com/a-century-of-profitable-industry-trends/ | Long-only trend following on each of 48 industries (channel breakout with trailing stop, vol-sized). Exposure varies and can go to cash. | 48 FF industries; check on 31 SSGA sector ETFs | Daily signals, multi-week holds | 1926–2024 | Avg return **18.5%**, vol 12.1%, **Sharpe 1.46** (market 0.63), alpha 11.2%. MDD about 60% lower than passive. An earlier version reported 18.2% and Sharpe 1.39. | Commissions and slippage "relatively high"; not quantified on the page | ? | The ETF replication over 20 years is said to match the profile, but no metrics are given | Yes: Ken French industries; SPDR sector ETFs | F |
| D2 | Massaad et al. 2024, arXiv:2412.14361, "Refining and robust backtesting of A Century of Profitable Industry Trends". https://arxiv.org/abs/2412.14361v1 | Re-implements D1 and questions the T-bill fallback | Same | Same | Same | Robustness re-check, not independent confirmation | — | — | — | Yes | S |
| D3 | CXO tests of simple sector-ETF momentum. https://www.cxoadvisory.com/momentum-investing/simple-sector-etf-momentum-strategy-robustnesssensitivity-tests/ | Top 1–3 of 9 SPDR sectors by 6-1 (and other) momentum, monthly | 9 SPDR sector ETFs | Monthly | 1999–2010s | Does not beat equal-weight sectors. Some ranking intervals **lose money after friction**. | 0.1–0.25%/trade | Close | Negative | Yes | S |
| D4 | Quantpedia 2026, "Sectoral intramonth momentum cycle". https://quantpedia.com/tag/sector-momentum/ | Long/short sectors on 252-day momentum, only on TOM day 1, a reversal on days 2–3, and a window 10–5 days before month end | 9 SPDR sectors vs SPY | Under half of days invested | Dec 1998 – Jun 2026 | Long-short 5.99%/yr, Sharpe 0.55. Market-neutral 3.77%, Sharpe 0.54. | Unknown | ? | New (Aug 2026). High turnover. | Yes | S |
| D5 (B) | Gayed & Bilello 2014, "An intermarket approach to beta rotation" (XLU vs SPY, 4-week relative strength). https://www.cxoadvisory.com/equity-premium/utilities-sector-as-stock-market-tell | Hold utilities if XLU has beaten SPY over 4 weeks, else SPY | XLU/SPY, VTI | Weekly | 2001–2013 | CAGR 6.7% vs SPY 5.3% (Jul 2001 – Mar 2014) | **Break-even friction about 0.37% one way** | Weekly close | No published live OOS | Yes | S |

## E. Calendar effects at index level

| # | Item | Rule | Instruments | Hold / turnover | Sample | Performance | Costs | Fill | OOS / post-pub | Free data | V |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 (B) | Cieslak, Morse & Vissing-Jorgensen 2019, "Stock returns over the FOMC cycle", JF 74(5):2201–2248. https://papers.ssrn.com/abstract=2687614 · CXO: https://www.cxoadvisory.com/calendar-effects/hold-stocks-only-during-fomc-even-weeks | Long the market in FOMC-cycle weeks 0, 2, 4, 6 (week 0 starts the day before the announcement); T-bills in odd weeks | US index | **About 26 round trips/yr** | 1994–2015 | **Gross** excess: 11.8%/yr, vol 13.3%, **Sharpe 0.88**, against B&H 8.3% / 19.1% / 0.43. Long-even/short-odd: 14.8%, Sharpe 0.70. About half the premium is mean-reversion after declines. | **Gross**; 26 round trips not costed | Close | A Swedish thesis on 2017–2022 finds the even-week pattern **"distorted"**. No clean OOS confirmation. | Yes (FOMC dates are public) | F |
| E2 | Kurov, Wolfe & Gilbert 2021, "The disappearing pre-FOMC announcement drift", FRL 40; Lucca & Moench 2018 Liberty Street update. https://ideas.repec.org/a/eee/finlet/v40y2021ics1544612320315956.html | Long from the prior close until 2 pm on FOMC day | SPX/ES | 1 day | 1994–2019 | The drift was about 40 bp/meeting historically and has **essentially vanished since 2016** | — | Intraday exit | **Dead post-publication** | Yes | S |
| E3 | Hu, Pan, Wang & Zhu 2022, "Premium for heightened uncertainty", JFE 145(3):909–936. https://econpapers.repec.org/RePEc:eee:jfinec:v:145:y:2022:i:3:p:909-936 | Large **overnight** returns before NFP, ISM and GDP releases; bigger after VIX run-ups | SPX | Overnight | 1990s–2010s | Pre-announcement overnight premium (figures not verified) | — | **Close→open** | — | Yes (macro calendar) | S |
| E4 | Turn-of-month: McConnell & Xu 2008 (B); **Han, Han & Tian 2025, "The disappearing turn-of-month effect", FRL 71**; QuantSeeker 2025 replication; Etula et al. 2020 RFS "Dash for cash". https://ideas.repec.org/a/eee/finlet/v71y2025ics1544612324014909.html · https://www.quantseeker.com/p/turn-of-the-month-strategies-do-they · https://ideas.repec.org/a/oup/rfinst/v33y2020i1p75-111..html | Classic: long days [−1, +3]. QuantSeeker: long from close of day −4 to close of day +3 (window [−3, +3]). | SPY, QQQ, IWM, sectors, international | 7 days/month, **12 round trips/yr** | 1926–2025 | Han et al.: classic TOM **vanishes after 2001**. QuantSeeker: classic [0:3] gone in the last decade in US ETFs. Wider [−3:+3] still +5–12 bp/day vs other days, declining. As a strategy it lowers CAGR and Sharpe is at best comparable, though MDD is lower. Etula: month-end liquidity selling with a reversal around T−4, tied to **T+3 settlement** (US moved to **T+1 in May 2024**, which shifts the window). | QuantSeeker: 5 bp one way, cash at 0% | Close | **Decayed** | Yes | F |
| E5 | Harvey, Mazzoleni & Melone 2025, "The unintended consequences of rebalancing", NBER w33554; CXO futures implementation; L&G 2025 rebuttal. https://www.nber.org/papers/w33554 · https://www.cxoadvisory.com/calendar-effects/exploiting-predictable-institutional-portfolio-rebalancing | Predict 60/40 rebalancing from threshold drift (0–2.5%) and calendar (last week of month). Short the winning asset and long the loser ahead of the flow. | ES and 10y T-note futures | Weekly / monthly | Sep 1997 – Mar 2023 | **Gross Sharpe 1.08** (stocks 0.38, bonds 0.50). When equities are overweight, the next day returns −17 bp. Cost to pensions about 8 bp/yr. | **Gross**, in-sample calibration | Close | L&G finds **no relation in Jan 2020 – Jun 2025** | Yes: SPY/IEF approximation | F |
| E6 | Zhang & Jacobsen 2021, "The Halloween indicator… everywhere and all the time", JIMF 110. https://ideas.repec.org/a/eee/jimfin/v110y2021ics0261560620302242.html | Hold equities Nov–Apr, cash May–Oct | 114 markets | 2 trades/yr | Up to 300+ years | Beats the market in more than 80% of 5-year windows. Reliability has risen over the last 50 years (per the authors). | Low turnover | Month-end | Published 2021; ongoing | Yes | S |
| E7 | Pre-holiday: CXO holiday series (data to 2022). https://www.cxoadvisory.com/calendar-effects/stock-returns-around-labor-day | Long the day (or two) before US holidays | SPX | About 9 days/yr | 1950–2022 | Strength is concentrated 1 day before the holiday. **Weakening; noise dominates** in recent data. | — | Close | Weakening | Yes | S |
| E8 | Options-expiration week: Stivers & Sun (B); Quantified Strategies (decay); Garcia-Ares & Muravyev 2025. https://quantpedia.com/strategies/option-expiration-week-effect | Long during monthly OPEX week | SPX, S&P 100 | 12 weeks/yr | 1983–2010 | Higher OPEX-week returns historically | — | Close | **Deteriorated** over the last few years (practitioner) | Yes | S |

## F. Overnight vs intraday index returns

| # | Item | Rule | Instruments | Hold | Sample | Performance | Costs | Fill | OOS / post-pub | Free data | V |
|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 | Bondarenko & Muravyev 2023, "Market return around the clock: a puzzle", JFQA 58(3):939–967. https://ideas.repec.org/a/cup/jfinqa/v58y2023i3p939-967_1.html | Hold ES only during the 4 hours around the European open | E-mini S&P | 4 hours/day | 2006–2018 | That window equals 100% of the market return: **7.6%/yr, Sharpe 1.67**, t = 6.4 | Gross | Futures intraday | See F2 (fading) | No (intraday futures) | S |
| F2 | Boyarchenko, Larsen & Whelan 2023, "The overnight drift", RFS 36(9):3502–3547; **NY Fed Liberty Street, Jul 2026, "The disappearing overnight drift"**. https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/ | Long ES 2:00–3:00 am ET, sized by the prior close's order imbalance | E-mini S&P/NQ/Dow | 1 hour | 1998–2020; then 2021–2025 | **About 3.7%/yr before 2021 (over 60% of the 5.9% close-to-close return). About 0 in 2021–2025.** Imbalance dispersion fell from 6.5% to 2.9%. | — | Intraday | **Dead after publication** (the authors' own update) | No | F |
| F3 | Lou, Polk & Skouras, "The day destroys the night, night extends the day" (LSE WP, May/Jun 2026). https://personal.lse.ac.uk/POLK/research/LPS_ClientelePerspectiveOnEquityPremium_20260603.pdf | **Smoothed overnight SPY return** (EWMA, **about 7-year half-life**) negatively forecasts the next quarter's excess return through intraday reversal | SPY, CRSP, ES | **Quarterly** | 1997Q1–2023Q4 (96 quarters) | In-sample R² 15.5% (t = −5.44). OOS R² about 16%. OOS timing strategies: mean **7–20%/yr, Sharpe 0.5–0.7** (benchmarks 0.1–0.4). Turnover 24–57%/qtr, implying **break-even cost of 4–13%**. | Break-even reported | Quarterly | Works in both sample halves. Outperforms on almost all dates after 2004. | **Yes (SPY OHLC from yfinance)** | **P** |
| F4 | Overnight-only SPY ETF (NSPY) live record, via CXO intraday/overnight guide. https://www.cxoadvisory.com/guides/intraday-overnight/ | Hold SPY close→open only | NSPY | Daily | Jun 2022 – Jul 2023 | Negative average daily return; trailed SPY | ETF fees and spreads | Close/open | **The live product failed** | Yes | S |

## G. Short-term mean reversion in index ETFs

| # | Item | Rule | Instruments | Hold | Sample | Performance | Costs | Fill | OOS / post-pub | Free data | V |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G1 (B) | Baltussen, van Bekkum & Da 2019, "Indexing and stock market serial dependence around the world", JFE 132(1):26–48. https://econpapers.repec.org/RePEc:eee:jfinec:v:132:y:2019:i:1:p:26-48 | Trade against MAC(5) (multi-day autocorrelation). Index serial dependence turned negative with the growth of indexing. | 20 indices, S&P 500 | Daily to weekly | To 2016 | Sharpe **0.63** (all indices) / **0.67** (S&P 500 alone) after indexing. S&P weekly AR moved from +0.026 to −0.087 after futures. | Gross | Close | Mechanism: index products. The 2020s has even more indexing. | Yes | S |
| G2 | Lewellen, "Autocorrelations" WP (2000–2019 update). https://faculty.tuck.dartmouth.edu/images/uploads/faculty/jonathan-lewellen/Autocorrelations.pdf | Regress 10-day returns on past returns | S&P 500, size portfolios | 10 days | 2000–2019 | S&P 500 10-day slope **−0.17**, a stronger reversal than micro-caps (−0.12) | — | — | Consistent with G1 | Yes | S |
| G3 | Connors RSI(2)/IBS family: practitioner backtests (Quantified Strategies 2024, 2015–2024 SPY dip study). https://quantifiedstrategies.substack.com/p/s-and-p-500-mean-reversion-using-19a | Buy SPY when RSI(2) is under about 10 (or IBS is low) and above SMA200; exit on a close above the prior high or SMA5 | SPY | 2–5 days, about 28% time in market | 1993–2024 | Claimed CAGR about 9%, MDD about −34% (unverified). **Degraded in 2022.** | Usually none or small | **Mostly SC (enter at the close)** | Original 1995–2007 rules with no data-mining correction | Yes | S |

## H. VIX term structure, VRP and VIX-based timing

| # | Item | Rule | Instruments | Hold | Sample | Performance | Costs | Fill | OOS / post-pub | Free data | V |
|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | VRP predictability: Bollerslev-Tauchen-Zhou 2009 (B); Pyun 2016 (weak OOS); "comprehensive look" VRP WPs. https://law-journals-books.vlex.com/vid/comprehensive-look-at-the-855673978 | VIX² − realized variance predicts the 1–6 month excess return | SPX | Monthly to quarterly | 1990–2010s | Predictability peaks at about 3–6 months. OOS evidence is **mixed** (Pyun: weak). | — | Month-end | Mixed | Yes (^VIX, SPY) | S |
| H2 | VIX term structure: Fassas 2012 (B); Johnson 2017 JFQA "Risk premia and the VIX term structure". https://www.cxoadvisory.com/volatility-effects/vix-term-structure-slope-and-variance-asset-future-returns/ | Slope of the VIX futures curve | SPX, variance assets | Weekly / monthly | 2004–2015 | The slope predicts **variance-asset** returns (variance swaps, VIX futures, straddles), **not the SPX index**. Fassas: weak negative weekly relation, dominated by 2008. | — | — | — | Yes (^VIX, ^VIX3M from 2007/2011) | S |
| H3 | Quantpedia 2025, "Hedging tail risk with robust VIXY models"; QuantConnect replication of Zarattini-Mele-Aziz dual VIX signal. https://quantpedia.com/hedging-tail-risk-with-robust-vixy-models/ | 20% VIXY when VRP ≤ 0 and VIX > VIX3M, else 100% SPY | SPY, VIXY | Days to weeks | 2007 – Jul 2025 | Hedged: **6.25%/yr, Sharpe 0.38** vs SPY 10.5% / 0.56. Lower risk, **worse return and Sharpe**. The QC short-VIXY version: Sharpe 0.73 vs 0.58 (2016–2026), with in-sample parameters. | — | ? | One test finds VIX > VIX3M as a bearish SPY trigger **does not reproduce 2016–2025** | Yes | S |
| H4 (B) | Kozyra & Lento 2011, "Using VIX data to enhance technical trading signals" (CXO). https://www.cxoadvisory.com/volatility-effects/use-vix-technical-signals-to-trade-stock-indexes | MA, filter and channel rules applied to VIX, traded on indices | US indices | Days | 1999–2009 | Beat B&H in 22/27 cases, but only **2/27 in calm 2003–07** | Gross | Close | Regime-dependent | Yes | S |

## I. Breadth and sentiment

| # | Item | Rule | Instruments | Hold | Sample | Performance | Costs | Fill | OOS / post-pub | Free data | V |
|---|---|---|---|---|---|---|---|---|---|---|---|
| I1 | Breadth divergence studies (LPL Research, SentimenTrader). https://www.lpl.com/research/blog/the-message-from-market-breadth.html | Index within 3% of a 52-week or 5-year high while fewer than 52–55% of members are above SMA200 | S&P 500 | 1–12 months | 1991–2024 | 21 events. Forward 1/3/6/12-month returns +0.4/+1.7/+3.8/+6.3% (still positive, but hit rate below normal). | — | — | Event counts too small to test | **Not free** (constituent breadth needs survivorship-free member data) | S |
| I2 | Upside breadth thrusts (MarketBeat 2023 summary of breadth-cross events) | Breadth crosses up from oversold | S&P 500 | 6 months | — | +7% average over 6 months, about 90% positive; weak in the short term | — | — | Small n | Not free | S |

---

## Notes and synthesis

### What survives the system's constraints (0.25% per side, next-open fills, existing 3x SMA200 core)

The cost arithmetic eliminates most of the catalog before any statistics are needed:
- A rule with **N round trips per year** costs about **0.5%·N** of the position each year. With UPRO, the drag on equity is the same 0.5%·N while the gross edge is multiplied by 3, so a 3x vehicle helps.
- FOMC cycle (N≈26) costs about 13%/yr. TOM (N=12) costs about 6%/yr. Pre-holiday (N≈9) costs about 4.5%/yr. OPEX (N=12) costs about 6%/yr.
- The *gross* edges of those rules (FOMC cycle about +3.5%/yr above B&H on 1x, before decay; TOM +5–12 bp/day over 84 days, about 4–10%/yr gross, now decaying) **do not clear these costs as standalone switches**. They could only work as **zero-extra-trade tilts on when an already-required switch is executed**.

### Ranked candidates for the existing 3x trend core

1. **Volatility-state gate on 3x exposure** (B2, B5, B7, A6).
   - **Mechanism.** LETF decay is roughly L(L−1)/2·σ². It is a mechanical function of realized variance, not a return forecast. Cutting UPRO to SSO, SPY or BIL in extreme realized-vol states attacks the one cost the core certainly pays.
   - **Evidence.** Barroso-Detzel find the *market* vol-managed portfolio is the one case that survives costs. Bongaerts et al. find that acting only at extremes keeps turnover low and avoids the drawdown amplification of plain vol targeting. B7 (VIX MA > realized vol leads to holding SPXL) is the closest published 3x analog, but it has no costs and no OOS.
   - **Main risk.** Redundancy with SMA200, because high vol mostly occurs below the SMA. The test must be *incremental to the existing ensemble*, measured as per-trade edge at matched return.

2. **Replace BIL in the off-state with a trend sleeve** (managed futures or trend-filtered Treasuries; A8, A10, A5).
   - The core sits in cash in exactly the regimes where cross-asset trend has historically earned its "crisis alpha". 2022 was the live, post-publication confirmation.
   - Turnover is low: the switch happens only when the core flips.
   - **Caveats:** ETF proxies have short histories (DBMF 2019, KMLM 2020). Futures-based backtests are not free. Huang et al. show that per-asset TSMOM evidence is weak. GTAA's OOS return was about half of its in-sample return.

3. **Fast/slow trend blending for re-entry** (A4, A3).
   - Momentum turning points: when slow (SMA200) and fast (1–2 month) signals disagree after a correction, use intermediate exposure (for example SSO or partial UPRO) instead of all-or-nothing.
   - This reduces the lag cost of V-shaped recoveries (2020, 2023), where SMA200 rules re-enter late.
   - It is consistent with the existing buffer ensemble, which already diversifies timing luck in the A3 sense.
   - Cost: a few extra switches a year.

4. **Short-horizon index mean reversion used as an execution and re-entry tilt** (G1, G2, C4).
   - Index-level serial correlation has been negative since indexing grew: S&P 10-day slope −0.17 over 2000–2019, and MAC(5) Sharpe about 0.65.
   - Practical use under next-open fills:
     - Execute required core flips on a **down** day (delay a buy after a sharp up day, delay a sell after a sharp down day, within a bounded wait).
     - Possibly allow an early partial re-entry on deep oversold readings while the trend is off.
   - The standalone RSI(2) family assumes same-close entry and degraded in 2022, so do not run it as a separate strategy.

5. **Calendar effects only as zero-cost scheduling tilts** (E4, E5, E1).
   - If a core switch falls inside the [−3, +3] TOM window or the month-end rebalancing window, prefer the side that the flow pressure favours.
   - Re-derive the TOM window for **T+1 settlement (post May 2024)** before using Etula-style timing.
   - The expected gain is small, in single-digit bp per year, but it adds no trades.

### Main failure reasons for everything else

- **Needs same-close or intraday execution:** C1–C6 (LETF rebalancing, intraday momentum, gamma), F1–F2 (overnight windows), G3 as published, E2 (pre-FOMC intraday exit). None of these can be run with next-open fills.
- **Decayed after publication:**
  - The overnight drift went to about 0 in 2021–2025, per the authors' own 2026 update.
  - The pre-FOMC drift has been gone since 2016.
  - The classic TOM has been gone since 2001 (Han et al. 2025).
  - The OPEX week, the overnight→last-30-minutes signal (Rosa 2022), and LETF end-of-day effects (C2) have all faded.
  - The FOMC cycle has been "distorted" since 2017, with no clean OOS confirmation.
- **Turnover × 0.25% cost:** FOMC cycle, TOM, pre-holiday, OPEX, D4 sector intramonth cycle, and D5 utilities rotation (break-even friction 0.37%).
- **Gross-only or in-sample results:** Moreira-Muir-style vol management (B1: 53/103 wins, 8 significant), sector momentum (D3 negative net), the E5 rebalancing front-run (in-sample calibration, with a 2020–2025 rebuttal), and B7 (no costs, a single bull sample).
- **Wrong target or horizon:**
  - The VIX term-structure slope predicts variance assets, not SPX (H2).
  - VIXY hedges lower Sharpe (H3).
  - Lou-Polk-Skouras is a quarterly signal with a 7-year EWMA half-life (F3). It is real and cheap but slow, so it might serve as a low-frequency leverage dial, not a swing rule.
- **Data not free or small n:** breadth needs survivorship-free constituent data (I1, I2), and gamma/0DTE positioning data is paid (C4, C6).

### Data notes for free implementation

- yfinance: SPY, UPRO, SSO, SPXL, BIL, sector SPDRs, DBMF/KMLM, and ^VIX. ^VIX3M has been available since about 2007 as VXV.
- FRED: DTB3 for cash.
- FOMC and macro-release calendars are on federalreserve.gov and bls.gov.
- Ken French industry portfolios cover pre-ETF history.
- Leveraged-ETF history before 2009 must be simulated: daily L×r minus fees and financing (financing at the T-bill rate plus a spread).
