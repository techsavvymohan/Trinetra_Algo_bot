# 👁️ TRINETRA (त्रिनेत्र) - Complete Manual Trading Strategy & Risk Blueprint
### *Ek Complete, In-Depth Guide: Algorithm aur Bot ki Mathematical Strategy ko Manual Trader ki Tarah Kaise Samjhein aur Trade Karein*

---

## 📌 Introduction (Yeh Guide Kiske Liye Hai?)

Yeh document **TRINETRA (त्रिनेत्र)** algo bot ki complete core strategy, market microstructure logic, risk management, aur order execution ko aasan aur detailed **Hinglish** mein explain karta hai.

Agar aap ek **Manual Trader** hain jisko Python code ya algorithmic programming nahi aati, lekin aap yeh samajhna chahte hain ki:
1. Yeh bot market mein entry aur exit kaise plan karta hai?
2. Smart Money (Institutional Banks, Liquidity Providers) retail traders ko trap kaise karti hai?
3. Kaunse rules aur filters use karke bot 76%+ win rate aur 3.0+ Profit Factor generate karta hai?
4. Aap is exact same system ko apne charts par **manual trading** ke liye kaise follow kar sakte hain?

Toh yeh master guide aapko step-by-step sab kuch samjhayegi.

---

## 🏛️ Strategy ka Core Concept: "The Three Eyes" (त्रिनेत्र)

Retail traders aam taur par lagging indicators (RSI overbought/oversold, MACD crossover, ya normal support/resistance) par trade karte hain aur banks ke dwara hunt ho jaate hain.

TRINETRA kisi single indicator par trade nahi karta. Yeh **3-Tier Hierarchy** follow karta hai jise **"The Three Eyes"** kaha gaya hai:

```
                  +----------------------------------------------+
                  |         THE THREE EYES OF TRINETRA           |
                  +----------------------------------------------+
                                         │
         ┌───────────────────────────────┼───────────────────────────────┐
         ▼                               ▼                               ▼
  [ 1ST EYE: MACRO ]            [ 2ND EYE: STRUCTURE ]           [ 3RD EYE: EXECUTION ]
    H4 / H1 Direction             M15 Key Liquidity Levels         M1 Microstructure
  • EMA 50/200 Trend Bias       • 20-Bar Buy/Sell Liquidity      • Sweep Breach >= 0.30
  • Choppiness Index Filter     • Liquidity Pools (BSL / SSL)    • Tick Delta Absorption
  • Macro News Blackout         • Session Timing (Killzones)     • Energetic Displacement
                                                                 • M1 MSS + FVG Limit Retest
```

1. **Pehli Aankh (1st Eye - Macro Vision / H4 & H1)**: 
   * Market ka broad direction kya hai? 
   * Kya market trend mein hai ya sideways chop mein phas chuka hai? 
   * Kya koi high-impact news aane wali hai?
2. **Doosri Aankh (2nd Eye - Structural Vision / M15)**: 
   * Institutional liquidity kahan baithi hai? 
   * Retail traders ke stop losses kahan pade hain (Buy-Side Liquidity BSL vs Sell-Side Liquidity SSL)?
3. **Teesri Aankh (3rd Eye - Microstructure Execution / M1)**: 
   * Liquidity sweep hui ya nahi? 
   * Absorption hua? 
   * Aggressive displacement candle aayi? 
   * Market Structure Shift (MSS) hua aur Fair Value Gap (FVG) bana?

Jab yeh teeno aankhein ek hi direction mein align hoti hain, **tabhi aur sirf tabhi** order place hota hai.

---

## 🛡️ Step 1: Pre-Trade Filters (Trade Kab Bilkul NAHI Lena?)

Ek profitable trader ya bot ki 50% kamyabi is baat par depend karti hai ki woh **kharab market conditions mein trade nahi karta**. Bot live entry lene se pehle 3 strict filters check karta hai:

### 1. High-Impact News Blackout Filter (±30 Minutes)
* **Rule**: ForexFactory ya Economic Calendar par **Red Folder News** (CPI, NFP, FOMC, Fed Rate Decision, PPI, GDP) aane ke **30 minute pehle** aur aane ke **30 minute baad** tak bot trading categorically band kar deta hai.
* **Reason**: News release ke time spreads 10x tak badh jaate hain aur price dono side fakeout karta hai. Manual trader ko bhi news se theek pehle ya turant baad trade nahi lena chahiye.

### 2. Sideways Market Avoidance Filter (Chop Filter)
* **Rule**:
  * Agar **Choppiness Index (CHOP 14) > 61.8** ho, YA
  * Agar **ADX (14) < 20.0** ho, YA
  * Bollinger Bandwidth apne 50-bar rolling minimum par squeeze ho,
* **Action**: Trading strictly **BLOCK** ho jaati hai.
* **Reason**: Chop/sideways market mein koi trend ya clear liquidity displacement nahi hoti; wahan sirf fakeouts aur stop-loss hunting hoti hai.

### 3. Session Timing & Killzones
Bot 24 ghante blind trading nahi karta. Yeh sirf un ghanton mein active hota hai jab institutional volume aur bank participation sabse zyada hoti hai:
* **Gold (XAUUSD)**:
  * **London Open Killzone**: 07:45 UTC se 09:30 UTC *(Indian Time: ~1:15 PM se 3:00 PM)*
  * **New York Core Killzone**: 13:00 UTC se 15:00 UTC *(Indian Time: ~6:30 PM se 8:30 PM)*
* **Nasdaq (NAS100 / USTECH100)**:
  * **Afternoon Continuation Killzone**: 15:45 UTC se 20:00 UTC *(Indian Time: ~9:15 PM se 1:30 AM)*
  * *Note*: US market open (13:30–15:30 UTC) ke shuruati 2 ghante Nasdaq avoid kiya jaata hai kyunki tab institutional whip aur spread manipulation hoti hai. Bot tab entry leta hai jab market afternoon mein solid one-way momentum pakad leta hai.

---

## 🔍 Step 2: Macro Trend Alignment (1st Eye - H4 & H1)

Entry lene se pehle H1 aur H4 charts par directional bias decide hota hai:

* **Bullish Bias (Sirf BUY dekhenge)**:
  * Price H1 chart par **50 EMA** ke upar trade kar raha ho.
  * H1 50 EMA > 200 EMA ho.
* **Bearish Bias (Sirf SELL dekhenge)**:
  * Price H1 chart par **50 EMA** ke neeche trade kar raha ho.
  * H1 50 EMA < 200 EMA ho.
* **Golden Rule**: Agar H1 chart par clear downtrend hai, toh M1 chart par kitna bhi sundar buy setup kyu na ban raha ho, bot usko **ignore** kar deta hai. Trend ke against trade kabhi nahi li jaati.

---

## 🎯 Step 3: M15 Structural Liquidity (2nd Eye)

Banks aur Smart Money ko badi quantity buy ya sell karne ke liye **counter-liquidity** ki zaroorat hoti hai. 
* Agar bank ko $100 Million ka Gold BUY karna hai, toh unhe samne $100 Million bechne wale sellers chahiye.
* Sellers kahan milenge? Retail traders ke Stop Losses par!

Bot M15 chart par pichhle 20 bars ke **5-bar Bill Williams Fractals** scan karke 2 critical levels mark karta hai:
1. **BSL (Buy-Side Liquidity)**:
   * Pichhle M15 swing highs jahan retail sellers ke Stop Loss (jo ki Buy Stops hote hain) baithe hain, ya breakout buyers buy stop order laga kar baithe hain.
2. **SSL (Sell-Side Liquidity)**:
   * Pichhle M15 swing lows jahan retail buyers ke Stop Loss (jo ki Sell Stops hote hain) baithe hain.

---

## ⚡ Step 4: M1 Microstructure Execution (3rd Eye - The Lethal Trigger)

Yeh bot ka core execution setup hai jo M1 chart par 5 steps mein trigger hota hai.

```
       M15 Old High (BSL)
───────────▲──────────────────────────────────────
           │ [1. Liquidity Sweep Breach >= $0.30]
           │
      ┌────┴────┐ 
      │ Wick    │ [2. Tick Delta Absorption - Rejection]
      └────┬────┘
           │
           ▼ [3. Energetic Displacement Bearish Candle (Body >= 0.60 ATR)]
           │
     ══════╪══════ M1 Swing Low Break [4. Market Structure Shift - MSS]
           │
        ┌──┴──┐
        │ FVG │   [5. Fair Value Gap Retest -> PENDING LIMIT ORDER ENTRY]
        └──┬──┘
           ▲
           │ Price pulls back into FVG -> Order Fill!
           ▼
           Run down to Target!
```

Aaiye in 5 stages ko detail mein samjhein:

### Stage 1: The Liquidity Sweep (The Trap)
* Market M15 BSL (High) ya SSL (Low) ko violently breach karta hai.
* **Condition**: Sweep breach kam se kam **0.30 points ($0.30 on Gold)** hona chahiye. Yeh ensure karta hai ki retail breakout traders trap ho chuke hain aur unke stops trigger ho gaye hain.

### Stage 2: Tick Delta Absorption (Rejection)
* Jaise hi price level ke upar jata hai, banks apne opposite limit orders dump karte hain.
* Candle upar sustain nahi kar paati aur wick chhod kar level ke andar wapas close ho jaati hai (Reclaim).
* Bot check karta hai ki reclaim volume sweep volume se zyada ya barabar hona chahiye ($\Delta_{\text{reclaim}} \ge \Delta_{\text{sweep}}$).

### Stage 3: Energetic Displacement Candle
* Absorption ke turant baad ek badi, strong institutional candle banti hai.
* **Condition**: Candle ki real body kam se kam **$0.60 \times \text{ATR(14)}$** honi chahiye. Chhoti candles ko bot consider nahi karta. Badi body yeh prove karti hai ki Smart Money ne control le liya hai.

### Stage 4: Market Structure Shift (MSS)
* Is strong displacement candle ki wajah se pichhla M1 recent swing high (Buy ke case mein) ya swing low (Sell ke case mein) break ho jata hai. Isko Smart Money Concepts (SMC) mein **Change of Character (CHoCH)** ya **Market Structure Shift (MSS)** kehte hain.

### Stage 5: Fair Value Gap (FVG) aur Pending Limit Entry
* Displacement ke time 3-candle imbalance banta hai jise **Fair Value Gap (FVG)** kehte hain:
  * Sell setup mein: Candle 1 ka Low aur Candle 3 ke High ke beech ka empty space.
  * Buy setup mein: Candle 1 ka High aur Candle 3 ke Low ke beech ka empty space.
* **Order Execution Rule**:
  * Bot market price par direct blind buy/sell nahi karta.
  * Bot FVG zone ke andar **Pending Limit Order (Buy Limit / Sell Limit)** place karta hai.
  * Jab price wapas thoda sa pull-back karke FVG ko tap karta hai, order execute ho jata hai.
  * **Patience Rule**: Agar Gold par 8 candles (8 minutes) ke andar aur Nasdaq par 15 candles (15 minutes) ke andar price FVG par wapas nahi aata, toh pending limit order cancel ho jata hai (No chase policy).

---

## 💰 Step 5: Master Risk Management Blueprint

Chahe strategy kitni bhi achhi ho, bina strict mathematical risk management ke koi bhi trader ya bot long-term survive nahi kar sakta. TRINETRA institutional prop-firm rules par based hai:

### 1. Risk Per Trade & Account Modes
* **Prop Firm Mode (FTMO / FundedNext / The5%ers)**:
  * Base Risk per trade: **0.85%** of Equity.
  * (Example: $10,000 account par har trade par exact risk = **$85.00**).
* **Personal Real Account Mode (Aggressive Compounding)**:
  * Base Risk per trade: **1.5% se 2.0%** of Equity.

### 2. Manual Trader ke liye Exact Lot Size Formula
Manual trading mein kabhi bhi andaze se ya fixed 0.10 / 1.00 lot mat lagaiye! Har trade ka Stop Loss points alag hota hai, isliye lot size hamesha mathematically calculate hona chahiye:

$$\text{Lot Size} = \frac{\text{Account Balance} \times \text{Risk Percentage}}{\text{Stop Loss Distance (in points)} \times \text{Contract Size}}$$

#### Real-Life Example on XAUUSD (Gold):
* **Account Balance**: $10,000
* **Risk Selected**: 0.85% = **$85.00**
* **Gold Entry Price**: $2650.00
* **Stop Loss (Sweep High ke upar)**: $2655.00
* **Stop Loss Distance**: $2655.00 - $2650.00 = **$5.00 points ($50 pips)**
* **Gold Contract Size**: 100 oz per lot

$$\text{Lot Size} = \frac{85}{5.00 \times 100} = \frac{85}{500} = \mathbf{0.17\text{ Lots}}$$

Agar Stop Loss $3.00 points ka hota:
$$\text{Lot Size} = \frac{85}{3.00 \times 100} = \mathbf{0.28\text{ Lots}}$$
*Matlab: SL jitna chhota hoga, lot size badh jayega; SL jitna bada hoga, lot size chhota ho jayega. Lekin loss hone par hamesha exact $85 hi jayenge!*

---

### 3. Tiered Conviction Position Sizing (Unicorn Kelly)
Bot har setup ko ek jaisa risk nahi deta. Setup ki quality ke hisab se conviction multiplier lagta hai:

| Setup Grade | Confluence Conditions | Risk Multiplier (Gold) | Risk Multiplier (Nasdaq) |
| :--- | :--- | :---: | :---: |
| **Grade A+ (Unicorn)** | H1 Trend Align + Clean Sweep + Delta Absorption + Body $\ge 0.60\times\text{ATR}$ + Clear FVG | **$2.60\times$ Base Risk** | **$2.40\times$ Base Risk** |
| **Grade A (Normal)** | Standard Sweep + Reclaim + FVG (moderate momentum) | **$1.00\times$ Base Risk** | **$1.00\times$ Base Risk** |
| **Grade B / C** | Partial confluences ya high chop probability | **0.50x ya NO TRADE** | **0.50x ya NO TRADE** |

---

### 4. Circuit Breakers (Account Protection Shield)
Bot ke andar 3 hard-coded emergency switches hain:
1. **Daily Loss Limit (4.5% Hard Cap)**:
   * Agar ek din ke andar closed loss + floating loss milakar **4.5%** hit ho jaye, bot immediately sabhi trades close kar deta hai aur us din ke liye trading **freeze** ho jaati hai. Next day se pehle koi trade nahi li jaati.
2. **Maximum Trailing Drawdown (10.0% Hard Cap)**:
   * Agar high-watermark peak balance se overall drawdown **10.0%** hit ho jaye, bot terminal completely freeze ho jata hai (Prop firm account breach hone se bachane ke liye).
3. **Max Consecutive Losses (Nasdaq Protection)**:
   * Nasdaq par agar lagataar **2 trades loss** mein close ho jayein, toh us din ke liye Nasdaq trading band ho jaati hai.

---

## 🎯 Step 6: Order Management & 3-Tranche Profit Harvesting

TRINETRA ka sabse bada edge uska **In-Trade Liquidity Harvesting System** hai. Aam retail traders trade lene ke baad screen dekhte rehte hain aur jab trade profit se wapas aakar loss mein chali jaati hai toh regret karte hain.

TRINETRA har trade ko **3 Parts (Tranches)** mein divide karke manage karta hai:

```
 Entry Price (100% Volume)
   │
   ▼
[ +1.00R Target Hit ] ──► TRANCHE 1: Bank 25% Profit!
   │                      AND MOVE STOP LOSS TO BREAKEVEN ($0.10 Buffer)
   │                      ★ Trade ab 100% Risk-Free ban gayi! ★
   ▼
[ +2.20R Target Hit ] ──► TRANCHE 2: Bank 35% Profit!
   │                      Ab 60% Total Profit Pocket mein Lock ho chuka hai.
   │
   ▼
[ Run the Moonbag ]  ──► TRANCHE 3: Remaining 40% Volume!
                          Fixed TP hata diya jata hai.
                          3.0x ATR Chandelier Trailing Stop lagaya jata hai.
                          Jab tak bada macro trend chalega, profit ride hoga!
```

### Detailed Breakdown of the 3 Tranches:

#### Tranche 1: Cash Extraction (+1.00R par 25% Volume Close)
* **Goal**: Immediate psychological safety aur account protection.
* Jaise hi trade aapke favour mein 1 Risk unit (+1.00R) move karti hai (e.g. agar SL $5 tha aur profit +$5 ho gaya):
  * **25% position size close** kar di jaati hai.
  * **Stop-Loss ko ratchet karke Breakeven (Entry Price + broker spread/commission buffer)** par lock kar diya jata hai.
  * *Result*: Is moment ke baad is trade mein **zero risk** hai. Worst case scenario mein bhi aap loss mein nahi nikalenge!

#### Tranche 2: Core Structural Target (+2.20R par 35% Volume Close)
* **Goal**: Big chunk of profit bank karna.
* Jab price next major structural level ya swing target hit karta hai (+2.20R):
  * Position ka agla **35% volume close** kar diya jata hai.
  * Ab total position ka **60% profit pocket mein confirm** ho chuka hai.

#### Tranche 3: The Moonbag Runner (Remaining 40% Volume)
* **Goal**: Massive trend capture (1:5, 1:10, 1:15 Risk-to-Reward trades pakadna).
* Bache hue 40% volume par koi fixed Take Profit nahi lagaya jata.
* Is par **3.0x ATR Chandelier Trailing Stop** lagta hai. Jaise-jaise price nayi candles banakar trend mein aage badhta hai, Stop Loss peeche-peeche trail hota rehta hai.
* Jab tak market reverse hokar trailing stop ko hit nahi karti, position open rehti hai.

---

## 📅 Step 7: Microstructure Seasonality Guards (Special Days Rules)

Bot ke backtest aur live stats mein 9/9 green months aane ka ek bohot bada reason yeh smart time-based rules hain:

### 1. Tuesday 0.43x Compression Rule
* **Insight**: Historical institutional data se pata chalta hai ki Tuesdays ko Gold aksar tight consolidation (30–50 pips) mein rehta hai jahan false breakouts zyada hote hain.
* **Rule**:
  * Tuesday ko bot apna base risk kam karke **0.43x** kar deta hai.
  * Breakeven trigger ko +1.00R se badhakar **+1.40R** kar deta hai taaki minor noise mein SL prematurely trigger na ho.

### 2. Friday Pre-NFP & London Opening Guard
* **Insight**: Friday morning London session mein NFP (Non-Farm Payrolls) ya weekend positioning ki wajah se aggressive stop hunting wicks banti hain.
* **Rule**:
  * Friday morning London session (07:45–09:30 UTC) mein Gold trading **skip** ki jaati hai.
  * Friday New York session mein risk ko **0.50x (half-risk)** kar diya jata hai.

### 3. Friday 14:45 UTC Weekend Flat Rule
* **Rule**: Friday ko **14:45 UTC** par bot ki sabhi open trades aur pending limit orders forcefully **liquidate / close** kar diye jaate hain.
* **Reason**: Weekend par koi position hold nahi ki jaati. Monday morning gap-openings (geopolitical news, wars, bank crises) ke risk ko 100% eliminate kar diya jata hai.

---

## 📊 Summary Comparison: XAUUSD (Gold) vs NAS100 (Nasdaq)

| Feature | XAUUSD (Gold Flagship) | NAS100 (Nasdaq Antifragile) |
| :--- | :--- | :--- |
| **Trading Killzone** | London (07:45-09:30) & NY (13:00-15:00 UTC) | Afternoon Continuation (15:45-20:00 UTC) |
| **Trend Filter** | H1 50/200 EMA + Choppiness Index | H1 EMA 50 strict trend alignment |
| **FVG Limit Order Patience**| 8 Bars (8 Minutes) | 15 Bars (15 Minutes) |
| **Breakeven Trigger** | +1.00R (+1.40R on Tuesday) | +1.25R (Stable Parameter Plateau) |
| **Trade Stagnation Timeout**| 20 Bars (Exit if no momentum in 20 mins) | 40 Bars (Index needs consolidation room) |
| **Consecutive Loss Cap**| Governed by Daily 4.5% Cap | Hard 2 consecutive losses per day cutoff |
| **Unicorn Kelly Sizing** | Up to **$2.60\times$** Base Risk | Up to **$2.40\times$** Base Risk |

---

## 📝 Manual Trader Checklist (Trade Lene Se Pehle Ka 7-Step Routine)

Agar aap is system ko manually charts par execute karna chahte hain, toh har trade se pehle yeh checklist follow karein:

- [ ] **1. News Check**: Kya agle 30 minute mein koi Red Folder News (CPI, NFP, FOMC) hai? *(Agar haan, chart band karein)*.
- [ ] **2. Chop Check**: Kya M15/H1 par Choppiness Index > 61.8 ya ADX < 20 hai? *(Agar haan, trade na lein)*.
- [ ] **3. Macro Trend (H1)**: Kya price H1 50 EMA ke upar hai (Bullish) ya neeche (Bearish)?
- [ ] **4. M15 Key Liquidity**: Pichhle swing high (BSL) ya swing low (SSL) level kahan hai?
- [ ] **5. M1 Liquidity Sweep & Shift**:
  - Kya price ne level ko sweep kiya?
  - Kya wick rejection aur tick delta absorption dikhi?
  - Kya M1 structure break (MSS) hua with a big body displacement candle?
- [ ] **6. FVG Entry & Exact Risk**:
  - FVG zone mark karein aur limit order lagayein.
  - Formula use karke exact 0.85% ya 1.5% risk ke mutabiq lot size calculate karein.
- [ ] **7. 3-Tranche Execution**:
  - +1.00R par 25% close karein aur SL Breakeven par shift karein.
  - +2.20R par 35% close karein.
  - Remaining 40% par Chandelier ATR trail lagakar bada runner enjoy karein.

---

<div align="center">
<b>TRINETRA (त्रिनेत्र) Strategy Blueprint</b><br>
<i>Mathematical Discipline • Microstructure Precision • Zero Emotional Trading</i>
</div>
