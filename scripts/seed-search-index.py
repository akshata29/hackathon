#!/usr/bin/env python3
"""
seed-search-index.py
====================
Creates and populates the Azure AI Search index with synthetic research documents.
This provides the RAG knowledge base used by specialist agents via AzureAISearchContextProvider.

The index uses BOTH keyword (BM25) and dense vector fields so hybrid + semantic reranking
works correctly.  The agent framework previously logged:
  "No vector fields found in index 'portfolio-research'. Using keyword-only search."
This script resolves that by adding a 'content_vector' field (1536-dim, HNSW).

Run ONCE after `azd up`:
    python scripts/seed-search-index.py

Environment variables:
    AZURE_SEARCH_ENDPOINT                 e.g. https://<name>.search.windows.net
    AZURE_SEARCH_INDEX                    index name (default: portfolio-research)
    AZURE_SEARCH_ADMIN_KEY                optional — falls back to DefaultAzureCredential
    AZURE_OPENAI_ENDPOINT                 e.g. https://<hub>.openai.azure.com
                                          (auto-derived from FOUNDRY_PROJECT_ENDPOINT if blank)
    AZURE_OPENAI_API_KEY                  optional — falls back to DefaultAzureCredential
    AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT    deployment name (default: text-embedding-3-small)
"""

import asyncio
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_dotenv() -> None:
    for candidate in [ROOT / ".env", ROOT / "backend" / ".env"]:
        if candidate.exists():
            with candidate.open() as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())
            return


_load_dotenv()

SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX", "portfolio-research")

# ---------------------------------------------------------------------------
# Azure OpenAI embedding settings
# ---------------------------------------------------------------------------
# Derive the OpenAI endpoint from FOUNDRY_PROJECT_ENDPOINT if not explicitly set.
# FOUNDRY_PROJECT_ENDPOINT format: https://<hub>.services.ai.azure.com/api/projects/<proj>
# Azure OpenAI endpoint format:    https://<hub>.openai.azure.com/
def _derive_openai_endpoint() -> str:
    explicit = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    if explicit:
        return explicit
    foundry = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")
    m = re.match(r"https://([^.]+)\.services\.ai\.azure\.com", foundry)
    if m:
        return f"https://{m.group(1)}.openai.azure.com"
    return ""


OPENAI_ENDPOINT = _derive_openai_endpoint()
OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
EMBEDDINGS_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small output size

if not SEARCH_ENDPOINT:
    print("ERROR: AZURE_SEARCH_ENDPOINT not set.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Synthetic research documents (replace with real docs in production)
# ---------------------------------------------------------------------------

# Each document has a rich text body that will be embedded into a 1536-dim vector
# for dense retrieval, in addition to the keyword-searchable content field.

RESEARCH_DOCS = [
    {
        "id": "doc-001",
        "title": "AI Sector Outlook 2025",
        "sector": "Technology",
        "content": (
            "The artificial intelligence sector continues to show exceptional growth in 2025. "
            "Major hyperscalers (MSFT, GOOG, AMZN) are increasing AI capex by 40-60% YoY. "
            "NVIDIA remains the dominant GPU supplier with 80%+ market share in AI accelerators. "
            "Key risks include regulatory scrutiny in the EU and potential commodity chip competition from AMD and startups. "
            "Recommendation: Overweight large-cap AI infrastructure plays. Watch for AI monetization inflection in H2 2025."
        ),
        "date": "2025-01-15",
        "source": "Internal Research",
    },
    {
        "id": "doc-002",
        "title": "Federal Reserve Rate Path Analysis",
        "sector": "Macroeconomics",
        "content": (
            "The Federal Reserve held rates at 4.25-4.50% at the January 2025 FOMC meeting, "
            "signalling a cautious approach to further cuts. Core PCE remains above the 2% target at 2.8%. "
            "Market consensus prices in 2 cuts in 2025 (June and December). "
            "Key watch points: NFP monthly data, CPI prints, and Fed Chair press conferences. "
            "Portfolio implication: Duration risk in long bonds; short-end Treasuries attractive for cash management."
        ),
        "date": "2025-01-30",
        "source": "Macro Strategy Desk",
    },
    {
        "id": "doc-003",
        "title": "Financial Sector Deep Dive: JPM, GS, BLK",
        "sector": "Financials",
        "content": (
            "Major US financials delivered strong Q4 2024 earnings. JPMorgan posted ROE of 17.5%, "
            "above the sector median of 12%. Goldman Sachs benefited from capital markets revival, "
            "with IB fees up 32% QoQ. BlackRock AUM exceeded $11T driven by ETF inflows. "
            "Rising rate environment is net positive for NIM at banks. "
            "Risk: Credit card delinquencies edging up to 3.2%, worth monitoring."
        ),
        "date": "2025-01-20",
        "source": "Equity Research",
    },
    {
        "id": "doc-004",
        "title": "Portfolio Diversification Best Practices",
        "sector": "Portfolio Management",
        "content": (
            "Modern portfolio theory recommends maintaining 20-30 positions across 6-8 sectors for optimal diversification. "
            "A technology weighting above 35% introduces idiosyncratic sector risk. "
            "Rebalancing quarterly reduces tracking error versus target allocation. "
            "Factor tilts (value, quality, low-vol) should complement sector allocation, not replace it. "
            "Cash allocation of 5-10% provides optionality during market dislocations."
        ),
        "date": "2025-01-01",
        "source": "Investment Policy Statement",
    },
    {
        "id": "doc-005",
        "title": "Energy Sector: Oil & Gas Transition Risks",
        "sector": "Energy",
        "content": (
            "ExxonMobil and Chevron maintained strong free cash flow in 2024 despite oil at $70-80/bbl. "
            "Long-term transition risk remains a concern as EV adoption accelerates. "
            "Near term: Middle East supply concerns and US production at record highs create a range-bound oil environment. "
            "XOM's Guyana assets provide lower-cost production growth through 2030. "
            "ESG constraints are reducing passive inflows to the sector but active managers are finding value."
        ),
        "date": "2025-01-10",
        "source": "Sector Research",
    },
    {
        "id": "doc-006",
        "title": "Healthcare Sector: Regulatory and Biotech Outlook",
        "sector": "Healthcare",
        "content": (
            "Drug pricing legislation risk persists with potential IRA Medicare negotiation expansion. "
            "UnitedHealth Group faces headwinds from elevated medical loss ratios (MLR at 85.3%). "
            "J&J's pipeline is strong with 90+ compounds in trials; oncology franchise growing 12% YoY. "
            "GLP-1 opportunity (LLY, NVO) is creating disruption in metabolic disease space. "
            "Valuation: Healthcare is trading at 17x forward P/E vs 5-year average of 16x — fairly valued."
        ),
        "date": "2025-01-25",
        "source": "Healthcare Equity Research",
    },
    {
        "id": "doc-007",
        "title": "NVIDIA Deep Dive: AI Infrastructure Supercycle",
        "sector": "Technology",
        "content": (
            "NVIDIA's data center segment revenue reached $18.4B in Q3 FY2025, up 112% YoY, driven by insatiable "
            "demand for H100 and H200 GPU clusters. Gross margins expanded to 74.6%, the highest in the company's "
            "history, reflecting pricing power in an undersupplied AI accelerator market. "
            "The Blackwell GB200 platform is entering mass production with 5x the performance-per-watt of Hopper. "
            "Key risks: China export controls reduce ~$4B of potential annual revenue; AMD MI300X gaining share "
            "in inference workloads; long-term threat from hyperscaler custom ASICs (TPU, Trainium, Maia). "
            "Bull case: NVIDIA's CUDA ecosystem moat remains the highest switching-cost asset in enterprise tech. "
            "Price target: $1,100. Rating: Overweight."
        ),
        "date": "2025-02-10",
        "source": "Semiconductor Research",
    },
    {
        "id": "doc-008",
        "title": "Microsoft Azure AI: Monetisation Inflection Analysis",
        "sector": "Technology",
        "content": (
            "Microsoft Azure revenue grew 28% YoY in Q2 FY2025, with 8 percentage points attributed to AI services. "
            "Copilot M365 reached 400M paid seats generating est. $6B ARR run-rate. "
            "Azure OpenAI Service now serves 65,000 enterprise customers, up from 18,000 a year ago. "
            "The GitHub Copilot franchise grew to 1.8M paid users with 40% YoY growth. "
            "Structural tailwind: Enterprise IT budgets are re-allocating 20-25% of software spend toward AI tooling. "
            "Key risk: OpenAI partnership dependency; competitive pressure from Anthropic/AWS and Google Gemini. "
            "FY2026 consensus EPS $15.20; P/E 27x — premium justified by compounding AI revenue mix shift. "
            "Rating: Overweight. 12-month price target $470."
        ),
        "date": "2025-02-05",
        "source": "Cloud & Enterprise Research",
    },
    {
        "id": "doc-009",
        "title": "Semiconductor Sector: AMAT, AVGO, QCOM supply-chain outlook",
        "sector": "Technology",
        "content": (
            "Applied Materials (AMAT) is the primary beneficiary of gate-all-around (GAA) transistor transitions "
            "at TSMC and Samsung. Equipment intensity per wafer is rising 15-20% with GAA, supporting 10%+ EPS "
            "growth through 2026. "
            "Broadcom (AVGO) custom ASIC business (XPUs for Google TPU, Meta MTIA) is scaling to a $10B+ revenue "
            "opportunity by FY2026. The VMware integration is ahead of synergy targets with $4B of cost saves. "
            "Qualcomm (QCOM) faces a bifurcated outlook: PC/AI device Snapdragon X is gaining design wins at "
            "Dell/HP/Lenovo; handset exposure is headwinds from Apple modem in-sourcing by 2026. "
            "Overall semiconductor sector: cycle recovery underway, with inventory normalisation complete in "
            "memory (MU, SAMSUNG) and lead times extending in leading-edge logic."
        ),
        "date": "2025-02-20",
        "source": "Semiconductor Research",
    },
    {
        "id": "doc-010",
        "title": "Consumer Staples: Defensive Value in an Uncertain Macro",
        "sector": "Consumer Staples",
        "content": (
            "Consumer staples offer a defensive dividend yield of 2.8% versus the S&P 500 at 1.3%, "
            "with historically lower drawdowns in recessionary environments. "
            "Procter & Gamble: Organic revenue growth of 3% driven by pricing rather than volume; margin recovery "
            "on track as commodity costs ease. Coca-Cola: International franchise model insulates from US wage "
            "inflation; EM revenue growing 7% in local currency. "
            "Key theme: Private label competition is intensifying at the lower end — premiumisation strategy is "
            "critical for brand premium sustainment (PG, PEP more insulated than Kellogg, Campbell). "
            "PepsiCo headwind: Frito-Lay volume softness as snack price elasticity re-emerges post-inflation. "
            "Sector recommendation: Market-weight with selective overweights in KO and PG."
        ),
        "date": "2025-02-15",
        "source": "Consumer Equity Research",
    },
    {
        "id": "doc-011",
        "title": "Eli Lilly and GLP-1 Revolution: Mounjaro, Zepbound Market Opportunity",
        "sector": "Healthcare",
        "content": (
            "Eli Lilly's GLP-1 franchise (Mounjaro for T2D, Zepbound for obesity) is on track for $25B+ in "
            "combined revenue by 2026, making it the fastest-growing pharmaceutical product line in history. "
            "The addressable market for obesity alone is estimated at 100M+ eligible patients in the US; "
            "current penetration is below 5%, indicating a multi-decade runway. "
            "Manufacturing bottleneck: Lilly has committed $9B in new manufacturing capacity (Ireland, US) "
            "to address supply shortfalls through 2025. "
            "Competitive dynamics: Novo Nordisk (Ozempic, Wegovy) is the primary competitor; oral GLP-1 "
            "(semaglutide pill) could expand the market further. Amgen, Pfizer, Roche are in Phase 2-3 trials. "
            "LLY FY2025 consensus revenue $50B (+32% YoY); P/E 45x reflects growth premium. Rating: Overweight."
        ),
        "date": "2025-02-28",
        "source": "Biotech & Pharma Research",
    },
    {
        "id": "doc-012",
        "title": "Financials: JPMorgan, Goldman Sachs Q4 2024 Earnings Deep Dive",
        "sector": "Financials",
        "content": (
            "JPMorgan Chase Q4 2024: Net income $14.0B (+21% YoY). Net interest income of $23.5B benefited "
            "from higher-for-longer rate environment. Consumer banking loan loss provisions ticking up ($2.7B) "
            "as subprime credit card delinquencies rise to 3.4%. Investment banking fees +49% QoQ driven by "
            "M&A advisory and leveraged finance resurgence. ROE 17.8%. CEO Dimon flagged geopolitical and "
            "fiscal deficit risks as key macro overhangs. "
            "Goldman Sachs Q4 2024: EPS $11.95, above $8.22 consensus. Marcus retail wind-down is complete, "
            "reducing drag. Asset & Wealth Management now $3.1T AUS, generating $3.8B revenue (+22%). "
            "Equities trading revenue +10% as volatility elevated. Rating: Overweight both. "
            "Key risk to banks sector: commercial real estate (CRE) office exposure; rising allowance for credit losses."
        ),
        "date": "2025-01-18",
        "source": "Equity Research",
    },
    {
        "id": "doc-013",
        "title": "Real Estate: REITs Outlook — Rate Sensitivity and Data Centre Opportunity",
        "sector": "Real Estate",
        "content": (
            "REITs underperformed in 2024 as rates stayed elevated, but are positioned for recovery as the Fed "
            "resumes cutting. The FTSE Nareit index trades at a 15% discount to NAV — historically a buying signal. "
            "Data centre REITs (EQIX, DLR) are operating at near-100% occupancy driven by AI workload demand; "
            "power capacity is the binding constraint, making sites with grid power access extremely valuable. "
            "Industrial REITs (PLD, STAG) benefit from e-commerce logistics tailwinds; same-store NOI growth +6%. "
            "Retail caution: mall REITs (SPG, MAC) face continued anchor tenant risk despite consumer resilience. "
            "Residential: Sun Belt apartment REITs (INVH, AMH) seeing rent growth decelerate to 3% as new supply. "
            "American Tower (AMT): tower leasing demand robust from 5G densification; India segment improving. "
            "Recommendation: Overweight data centres and industrial; underweight traditional retail."
        ),
        "date": "2025-02-12",
        "source": "REIT Research",
    },
    {
        "id": "doc-014",
        "title": "US Treasury and Bond Market: Duration Risk and Yield Curve Analysis",
        "sector": "Fixed Income",
        "content": (
            "The US 10-year Treasury yield has stabilized at 4.3-4.6% range after peaking at 5.0% in October 2023. "
            "The yield curve (2s10s) has re-steepened to +25bps from an inversion of -100bps, signalling reduced "
            "recession probability but not yet a clean expansion signal. "
            "Investment grade corporate spreads are tight at +90bps — minimal credit risk premium vs. history. "
            "High yield spreads at +280bps are also compressed, reducing risk-adjusted appeal vs IG. "
            "Recommended fixed income positioning: Overweight 2-5yr Treasuries (yield pickup without duration risk); "
            "underweight 30yr duration; maintain IG corporate allocation with quality bias (AA/A rated). "
            "TIPS: real yields at 2.1% attractive for inflation protection if core PCE re-accelerates. "
            "Key risk: fiscal deficit ($1.8T annual) continues to pressure term premium higher."
        ),
        "date": "2025-03-01",
        "source": "Fixed Income Strategy",
    },
    {
        "id": "doc-015",
        "title": "Utilities Sector: Rate Headwinds vs. AI Power Demand Tailwind",
        "sector": "Utilities",
        "content": (
            "The utilities sector faces a structural paradox: rate sensitivity (negative) versus AI data centre "
            "power demand (significantly positive). US data centres are projected to consume 200TWh by 2027, "
            "representing 8% of total US power generation, up from 4% today. "
            "NextEra Energy (NEE): Largest renewable energy developer globally; 14GW new capacity pipeline through "
            "2026. The FPL regulated utility in Florida provides stable cash flows with 8-10% allowed ROE. "
            "Southern Company (SO): Vogtle Unit 3 and 4 nuclear additions provide decade-long earnings visibility; "
            "data centre load growth in Georgia is substantial ($2B+ capex programme). "
            "Dominion Energy: Restructuring programme on track; Virginia service territory has Amazon, Microsoft, "
            "Google data centre clusters driving demand growth of 8% annually. "
            "Sector P/E 16x vs. historical 18x — discounted while rate cut trajectory supports re-rating."
        ),
        "date": "2025-03-05",
        "source": "Utilities & Clean Energy Research",
    },
    {
        "id": "doc-016",
        "title": "Global Macro: China Recovery, EM Currency, and Geopolitical Risk Premium",
        "sector": "Macroeconomics",
        "content": (
            "China GDP growth of 4.8% in 2024 disappointed the 5.0% official target due to property sector drag. "
            "The PBoC cut RRR 50bps in Q4 2024, and fiscal stimulus of RMB 1T ($140B) was deployed for "
            "infrastructure and consumer subsidies. EV and battery export competitiveness remains intact. "
            "EM currency outlook: USD has softened 3% YTD as Fed cut expectations firmed; EM currencies broadly "
            "stable with India INR and Brazilian BRL outperforming. EM equities (MSCI EM) at 12x P/E vs. S&P 500 "
            "21x — widest valuation discount in 20 years. "
            "Geopolitical risk premium: Middle East escalation risk (+$8-12/bbl on oil), Taiwan Strait friction, "
            "and US-China tech decoupling (semiconductor export controls) remain key tail risks for global portfolios. "
            "Recommendation: Selective EM overweight (India, Indonesia); China market-weight pending policy clarity."
        ),
        "date": "2025-03-10",
        "source": "Global Macro Strategy",
    },
    {
        "id": "doc-017",
        "title": "Consumer Discretionary: Amazon, Tesla, and the E-Commerce Evolution",
        "sector": "Consumer Discretionary",
        "content": (
            "Amazon Q4 2024: AWS revenue $28.8B (+19% YoY) with operating margin expanding to 38% — highest ever. "
            "North America retail operating income $6.6B; same-day delivery investments are driving Prime member "
            "spend frequency (+18% for same-day users). Advertising revenue $17.3B (+27%) now third-largest "
            "digital ad platform globally. "
            "Tesla Q4 2024: Deliveries 495,000 (-7% YoY) as competition from BYD intensifies in China. "
            "Gross margin 17.9% under pressure from price cuts. Full Self-Driving (FSD) robotaxi launch in Austin "
            "is the near-term catalyst; Energy storage (Megapack) generated $3.1B revenue at strong margins. "
            "E-commerce macro: US online retail penetration plateaued at 22%; growth now driven by grocery/beauty "
            "categories and international expansion. SHEIN, Temu continue to pressure mid-market apparel. "
            "Recommendation: Overweight Amazon (AWS/ads diversification); Tesla neutral (execution risk)."
        ),
        "date": "2025-02-25",
        "source": "Consumer Internet Research",
    },
    {
        "id": "doc-018",
        "title": "Risk Management: VaR, Drawdown Analysis, and Tail Hedging Strategies",
        "sector": "Portfolio Management",
        "content": (
            "A 95% 1-day Value-at-Risk (VaR) of 1.5% on a $1M equity portfolio implies a potential daily loss of "
            "$15,000 under normal market conditions. Historical simulation using 2008, 2020, and 2022 data "
            "suggests a 5% probability of drawdowns exceeding 30% in any given bear market. "
            "Tail hedging approaches: (1) Long put options on SPX (3-5% OTM, 3-month expiry) cost 0.8-1.2% "
            "of portfolio annually; (2) VIX call spread (15/25 strike) provides leverage on volatility spikes; "
            "(3) Managed futures (trend-following CTAs) historically provide positive returns in equity bear markets. "
            "Concentration risk alert: Single-position weights above 8% require stress-testing under -50% scenario. "
            "Correlation risk: In 2022, equities and bonds both fell > 15%, challenging 60/40 diversification logic. "
            "Recommendation: Allocate 2-3% to explicit tail protection; size single positions at max 7% of portfolio."
        ),
        "date": "2025-03-15",
        "source": "Risk Management",
    },
    {
        "id": "doc-019",
        "title": "Berkshire Hathaway Annual Letter Analysis: Buffett Quality Framework",
        "sector": "Financials",
        "content": (
            "Warren Buffett's 2024 annual letter highlighted several key investment principles relevant to "
            "today's market. On valuation: Berkshire's $334B cash position reflects difficulty finding quality "
            "businesses at sensible prices — a cautionary signal for market valuations. "
            "Buffett reiterated the 'economic moat' framework: durable competitive advantages in pricing power, "
            "switching costs, network effects, and cost advantages are prerequisites for long-term holding. "
            "On insurance (GEICO, Gen Re): combined ratio improved to 88.1, generating $9.6B underwriting profit. "
            "BNSF railroad earnings declined 14% on volume weakness and cost inflation — a leading indicator "
            "for industrial activity. "
            "Apple remains BRK's largest equity holding (~28% of portfolio); Buffett endorsed AI productivity "
            "benefits for Apple's ecosystem. "
            "Investment implication: BRK.B trading at 1.4x book value — fair entry for quality-oriented investors."
        ),
        "date": "2025-03-01",
        "source": "Equity Research",
    },
    {
        "id": "doc-020",
        "title": "Factor Investing: Quality, Momentum, and Low Volatility in 2025",
        "sector": "Portfolio Management",
        "content": (
            "Systematic factor strategies delivered differentiated returns in 2024: Quality (+18%) and Momentum "
            "(+22%) significantly outperformed Value (+8%) and Low Volatility (+6%) as AI-driven growth dominated. "
            "Quality factor characteristics: high ROE (>15%), low debt/equity (<0.5), stable earnings growth. "
            "In periods of rate uncertainty, quality companies with pricing power and recurring revenue outperform. "
            "Momentum: 12-month minus 1-month return signal continues to work in trending markets; mean-reversion "
            "risk is elevated when momentum is concentrated in a narrow set of large-cap tech names. "
            "Low volatility: Underperformed in bull markets but provides meaningful downside protection; "
            "utilities, staples, and healthcare are natural constituents. "
            "Practical implementation: Factor ETFs (QUAL, MTUM, USMV) provide efficient exposure. "
            "Blending factors reduces drawdown; quality + momentum blended portfolio historically Sharpe 1.4 vs. "
            "S&P 500 Sharpe 0.85 over 20-year lookback."
        ),
        "date": "2025-03-20",
        "source": "Quantitative Research",
    },
    {
        "id": "doc-021",
        "title": "Industrials Sector: Caterpillar, Honeywell and Infrastructure Super-Cycle",
        "sector": "Industrials",
        "content": (
            "US infrastructure spending under IIJA ($1.2T) is sustaining above-trend demand for construction "
            "and industrial equipment through 2026. Caterpillar (CAT) construction equipment orders remain elevated "
            "despite a mild destocking cycle in dealer inventories; Energy & Transportation segment at record "
            "backlogs driven by oil & gas and data centre power generation. "
            "Honeywell (HON) announced plans to spin off its Automation business, unlocking sum-of-parts value "
            "estimated at $30-40/share. Building technologies and aerospace segments are highest-margin divisions. "
            "UPS faces structural headwinds: Amazon in-sourcing 50% of own deliveries by 2025-end; B2B volume "
            "recovery is a 2026 story. "
            "Defence adjacency: L3Harris, Northrop, and Raytheon are benefiting from NATO re-armament budgets "
            "(2% GDP target compliance). "
            "Sector P/E 20x vs. historical 18x; premium justified by infrastructure tailwind. Overweight CAT, HON."
        ),
        "date": "2025-03-18",
        "source": "Industrials Research",
    },
    {
        "id": "doc-022",
        "title": "Payments Ecosystem: Visa, Mastercard, and Fintech Disruption",
        "sector": "Financials",
        "content": (
            "Visa and Mastercard process $15T and $9T in annual payment volume respectively, with a combined "
            "global network covering 200+ countries. Net revenue margins of 50%+ reflect the duopoly's "
            "extraordinary economics. Cross-border transaction revenue is the highest-margin line item, "
            "recovering strongly as international travel normalized post-COVID. "
            "Fintech disruption landscape: PayPal losing checkout share to Apple Pay and Shopify Pay; however, "
            "Venmo monetization improving with 90M users. Block (SQ) Cash App ecosystem growing but merchant "
            "acquiring faces margin pressure from competition. "
            "Alternative payment rails: FedNow instant payment system and RTP network are growing but "
            "primarily target bank-to-bank; card rails remain dominant for consumer e-commerce. "
            "Regulatory risk: CFPB late fee cap and DOJ antitrust scrutiny on V/MA network exclusivity agreements. "
            "Recommendation: Overweight V and MA on compounding cross-border recovery; neutral PYPL."
        ),
        "date": "2025-03-22",
        "source": "Fintech & Payments Research",
    },
    {
        "id": "doc-023",
        "title": "ESG and Sustainable Investing: Integration vs. Exclusion Debate",
        "sector": "Portfolio Management",
        "content": (
            "ESG integration in institutional portfolios has reached 85% by AUM, yet return outcomes remain "
            "mixed. In 2022-2023, energy sector exclusion cost ESG portfolios 200-350bps vs. broad market. "
            "The debate has shifted from exclusion to engagement: active ownership (proxy voting, board seats) "
            "is increasingly preferred over blanket divestment. "
            "Climate risk frameworks: TCFD-aligned disclosures are now mandatory for UK, EU, and Australian "
            "listed companies. SEC climate disclosure rules finalized Q1 2024 (Scope 1&2 required, Scope 3 large "
            "accelerated filers). "
            "Green bond market hit $1T issuance milestone in 2023; GSSS (green/social/sustainability/sustainability-"
            "linked) bonds now 15% of the investment grade corporate market. "
            "Key tension: Fiduciary duty vs. values alignment. ERISA guidance (US 2023) confirmed ESG factors "
            "permitted when material to risk/return, but cannot override financial best interests. "
            "Practical recommendation: Tilt toward low-carbon intensity rather than exclusion; target Scope 1 "
            "emissions below sector median."
        ),
        "date": "2025-03-25",
        "source": "ESG & Sustainable Finance",
    },
    {
        "id": "doc-024",
        "title": "S&P Global (SPGI): Ratings, Data Intelligence and Diversification",
        "sector": "Financials",
        "content": (
            "S&P Global operates four segments: Ratings (50% revenue), Market Intelligence (28%), Commodity "
            "Insights (12%), and Mobility (10%). The Ratings segment is a structural oligopoly with Moody's; "
            "combined market share >80% of investment grade issuance globally. "
            "The IHS Markit merger ($44B, 2022) accelerated the shift to subscription data revenue which now "
            "represents 65% of total revenue — reducing sensitivity to bond issuance cycle. "
            "Vitality Index (new product revenue as % of total) stands at 12%,  driven by private market "
            "data, AI-driven analytics (Kensho), and sustainability ratings (Trucost ESG). "
            "2025 tailwind: refinancing wave as $1.2T of corporate debt matures (2024-2026) will drive Ratings "
            "fee income materially higher. "
            "Free cash flow yield 3.2%; dividend growth 10-year CAGR of 12%. "
            "Rating: Overweight. 12-month price target $570. SPGI is a core compounding holding in diversified portfolios."
        ),
        "date": "2025-03-28",
        "source": "Data & Analytics Research",
    },
    {
        "id": "doc-025",
        "title": "Q1 2025 Earnings Preview: Key Metrics and Consensus Estimates",
        "sector": "Portfolio Management",
        "content": (
            "S&P 500 Q1 2025 earnings season preview: Consensus expects 7.9% YoY EPS growth; Technology sector "
            "leading at +18% YoY. Key reporting dates and themes: "
            "Big Tech (MSFT, GOOGL, META, AMZN reporting Apr 29-30): Focus on AI revenue disclosure, cloud growth "
            "acceleration, and capex guidance — market expects $80B+ combined Q1 capex. "
            "Financials (JPM, GS, MS reporting Apr 11-14): NII outlook with rate sensitivity; credit quality "
            "trends in consumer and CRE books; trading revenue in volatile Q1. "
            "Healthcare (LLY, UNH, JNJ reporting Apr 22-24): GLP-1 supply update from LLY; UNH MLR trajectory; "
            "J&J MedTech volumes post orthopaedic recovery. "
            "Watch for guidance cuts: Industrials (UPS, FedEx) on volume softness; Consumer discretionary "
            "(TSLA delivery miss already pre-announced). "
            "Historical precedent: When blended EPS growth exceeds 6% at start of season, final growth typically "
            "comes in at 8-10% as companies beat conservative guidance by average 4-5%."
        ),
        "date": "2025-04-07",
        "source": "Earnings Preview Research",
    },
]


async def _seed(credential, openai_api_key: str) -> None:
    from azure.search.documents.aio import SearchClient
    from azure.search.documents.indexes.aio import SearchIndexClient
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SearchableField,
        SemanticConfiguration,
        SemanticField,
        SemanticPrioritizedFields,
        SemanticSearch,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )

    # ------------------------------------------------------------------
    # Build the Azure OpenAI embedding client for content_vector fields
    # ------------------------------------------------------------------
    embedding_client = None
    if OPENAI_ENDPOINT:
        try:
            from openai import AsyncAzureOpenAI

            if openai_api_key:
                embedding_client = AsyncAzureOpenAI(
                    azure_endpoint=OPENAI_ENDPOINT,
                    api_key=openai_api_key,
                    api_version="2024-05-01-preview",
                )
            else:
                # Always use a fresh DefaultAzureCredential for embeddings.
                # The `credential` arg may be an AzureKeyCredential (search admin key)
                # which has no get_token() method — never reuse it here.
                from azure.identity.aio import DefaultAzureCredential as _DAC

                _emb_credential = _DAC()

                async def _get_token(scopes=("https://cognitiveservices.azure.com/.default",)):
                    token = await _emb_credential.get_token(scopes[0])
                    return token.token

                embedding_client = AsyncAzureOpenAI(
                    azure_endpoint=OPENAI_ENDPOINT,
                    azure_ad_token_provider=_get_token,
                    api_version="2024-05-01-preview",
                )
        except ImportError:
            print("  WARNING: openai package not installed — skipping embeddings. Run: pip install openai")
    else:
        print(
            "  WARNING: AZURE_OPENAI_ENDPOINT not set and cannot be derived from "
            "FOUNDRY_PROJECT_ENDPOINT. Skipping vector embeddings (keyword-only index)."
        )

    # ------------------------------------------------------------------
    # Index definition — keyword fields + vector field
    # ------------------------------------------------------------------
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="sector", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="date", type=SearchFieldDataType.String),
        SimpleField(name="source", type=SearchFieldDataType.String),
    ]

    vector_search = None
    if embedding_client:
        # Add the dense vector field that the agent framework looks for
        fields.append(
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=EMBEDDING_DIMENSIONS,
                vector_search_profile_name="hnsw-profile",
            )
        )
        vector_search = VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw-algo")],
            profiles=[
                VectorSearchProfile(
                    name="hnsw-profile",
                    algorithm_configuration_name="hnsw-algo",
                )
            ],
        )

    index = SearchIndex(
        name=INDEX_NAME,
        fields=fields,
        vector_search=vector_search,
        semantic_search=SemanticSearch(
            configurations=[
                SemanticConfiguration(
                    name="default",
                    prioritized_fields=SemanticPrioritizedFields(
                        title_field=SemanticField(field_name="title"),
                        content_fields=[SemanticField(field_name="content")],
                    ),
                )
            ]
        ),
    )

    print(f"Creating index '{INDEX_NAME}' at {SEARCH_ENDPOINT} ... ", end="", flush=True)
    try:
        async with SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential) as idx_client:
            await idx_client.create_or_update_index(index)
        print("OK")
    except Exception as exc:
        print(f"FAILED: {exc}")
        return

    # ------------------------------------------------------------------
    # Generate embeddings and upload documents
    # ------------------------------------------------------------------
    docs_to_upload = []
    if embedding_client:
        print(
            f"Generating embeddings with '{EMBEDDINGS_DEPLOYMENT}' "
            f"({len(RESEARCH_DOCS)} documents) ... ",
            end="",
            flush=True,
        )
        vectors_ok = False
        try:
            close_cred = "_emb_credential" in dir()
            async with embedding_client:
                for doc in RESEARCH_DOCS:
                    # Embed title + content for highest quality retrieval
                    text_to_embed = f"{doc['title']}\n\n{doc['content']}"
                    resp = await embedding_client.embeddings.create(
                        input=text_to_embed,
                        model=EMBEDDINGS_DEPLOYMENT,
                    )
                    docs_to_upload.append({**doc, "content_vector": resp.data[0].embedding})
            vectors_ok = True
            print("OK")
        except Exception as exc:
            print(f"FAILED: {exc}")
            print("  Falling back to keyword-only upload (no vectors).")
            docs_to_upload = list(RESEARCH_DOCS)
        finally:
            # Close the DefaultAzureCredential created for embeddings (if any)
            try:
                await _emb_credential.close()  # type: ignore[name-defined]
            except Exception:
                pass
    else:
        vectors_ok = False
        docs_to_upload = list(RESEARCH_DOCS)

    print(f"Uploading {len(docs_to_upload)} documents ... ", end="", flush=True)
    try:
        async with SearchClient(
            endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME, credential=credential
        ) as search_client:
            result = await search_client.upload_documents(docs_to_upload)
        ok = sum(1 for r in result if r.succeeded)
        print(f"OK ({ok}/{len(docs_to_upload)} succeeded)")
    except Exception as exc:
        print(f"FAILED: {exc}")
        return

    vector_note = (
        f"  Vector field 'content_vector' populated with {EMBEDDING_DIMENSIONS}-dim embeddings "
        f"from '{EMBEDDINGS_DEPLOYMENT}'."
        if vectors_ok
        else "  No vector field — keyword-only search active."
    )
    print(f"\nSearch index seeded successfully.\n{vector_note}")


async def create_index_and_upload() -> None:
    try:
        from azure.core.credentials import AzureKeyCredential
        from azure.identity.aio import DefaultAzureCredential
    except ImportError:
        print("ERROR: azure-search-documents not installed. Run: pip install azure-search-documents azure-identity openai")
        sys.exit(1)

    admin_key = os.environ.get("AZURE_SEARCH_ADMIN_KEY", "")
    if admin_key:
        await _seed(AzureKeyCredential(admin_key), OPENAI_API_KEY)
    else:
        async with DefaultAzureCredential() as credential:
            await _seed(credential, OPENAI_API_KEY)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(create_index_and_upload())
