"""
Beta / Alpha Screener page for Bharat Market Dashboard
Port of the TradingView Pine script "Scr αβ".  Run:  py screener_page.py
Output: public/index.html (opens automatically on your PC; on GitHub it is published online).  Needs: pip install yfinance pandas numpy requests

Like TradingView: choose the bar timeframe (15m / Daily / Weekly / Monthly / Quarterly) and the
Beta-Alpha period (number of bars) separately, and set the risk-free rate in the page.
Symbols: official Nifty 200 list (cached as nifty200.csv) or your own custom_symbols.txt.
"""
import json, os, pathlib, re, sys, webbrowser
from datetime import date
import pandas as pd, requests, yfinance as yf

HERE = pathlib.Path(__file__).parent
OUT = HERE / "public" / "index.html"   # GitHub Pages serves the "public" folder
CI = bool(os.environ.get("CI"))        # True when running on GitHub Actions
LIST_URL = "https://niftyindices.com/IndexConstituent/ind_nifty200list.csv"
NB = {"15m": 1000, "D": 520, "W": 270, "M": 120, "Q": 90}   # bars stored per timeframe
TFL = {"15m": "15 minute", "D": "Daily", "W": "Weekly", "M": "Monthly", "Q": "Quarterly"}
PPY = {"15m": 6300, "D": 252, "W": 52, "M": 12, "Q": 4}     # bars per year (corrected-alpha mode)
RULE = {"W": ("W-MON", dict(label="left", closed="left")), "M": ("MS", {}), "Q": ("QS", {})}
EMBED_DAYS = 1260


def load_symbols():
    custom = HERE / "custom_symbols.txt"
    if custom.exists():
        raw = re.split(r"[,\s]+", custom.read_text())
        return [s.upper().replace("NSE:", "").replace("_", "-") for s in raw if s.strip()]
    cache = HERE / "nifty200.csv"
    try:
        r = requests.get(LIST_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
        r.raise_for_status()
        cache.write_bytes(r.content)
    except Exception as e:
        if not cache.exists():
            sys.exit(f"Could not download Nifty 200 list ({e}).\nDownload it from {LIST_URL} "
                     f"and save as {cache}, then run again.")
        print("Using cached nifty200.csv")
    return pd.read_csv(cache)["Symbol"].astype(str).str.strip().tolist()


def get(raw, t, min_len):
    try:
        d = raw[t][["Close", "High"]].dropna()
    except KeyError:
        return None
    return d if len(d) >= min_len else None


def arr(s):
    return [None if pd.isna(v) else round(float(v), 2) for v in s]


def close_bars(s, tf):
    if tf in ("D", "15m"):
        return s
    r, kw = RULE[tf]
    return s.resample(r, **kw).last().dropna()


def index_bars(idx, tf):
    d = idx.copy()
    d["t"] = d.index
    if tf not in ("D", "15m"):
        r, kw = RULE[tf]
        d = d.resample(r, **kw).agg({"Close": "last", "High": "max", "t": "last"}).dropna()
    return d.tail(NB[tf])


def main():
    syms = load_symbols()
    tk = [s + ".NS" for s in syms] + ["^NSEI"]
    print(f"{len(syms)} symbols. Downloading daily prices (a few minutes)...")
    raw = yf.download(tk, period="max", auto_adjust=True, group_by="ticker", threads=True, progress=False)
    idx = get(raw, "^NSEI", 300)
    if idx is None:
        sys.exit("Could not download Nifty 50 index data (^NSEI).")
    raw15 = idx15 = None
    try:
        print("Downloading 15-minute prices (last 60 days)...")
        raw15 = yf.download(tk, period="60d", interval="15m", auto_adjust=True, group_by="ticker",
                            threads=True, progress=False)
        if raw15.index.tz is not None:
            raw15.index = raw15.index.tz_convert("Asia/Kolkata").tz_localize(None)
        idx15 = get(raw15, "^NSEI", 100)
    except Exception as e:
        print("15m data skipped:", e)
    dates = idx.index[-EMBED_DAYS:]
    ib, tfd = {}, {}
    for tf in NB:
        base = idx15 if tf == "15m" else idx
        if base is None:
            continue
        ib[tf] = index_bars(base, tf)
        fmt = "%Y-%m-%d %H:%M" if tf == "15m" else "%Y-%m-%d"
        pos = dates.searchsorted(pd.DatetimeIndex(ib[tf]["t"]).normalize(), side="right") - 1
        tfd[tf] = {"t": list(ib[tf].index.strftime(fmt)), "p": [int(x) for x in pos],
                   "i": arr(ib[tf]["Close"])}
    stocks, skipped = {}, []
    for sym in syms:
        df = get(raw, sym + ".NS", 300)
        if df is None:
            skipped.append(sym)
            continue
        b = {}
        for tf in ib:
            src = df
            if tf == "15m":
                src = get(raw15, sym + ".NS", 100) if raw15 is not None else None
                if src is None:
                    continue
            b[tf] = arr(close_bars(src["Close"], tf).reindex(ib[tf].index).ffill())
        stocks[sym] = {"c": arr(df["Close"].reindex(dates).ffill()), "h": arr(df["High"].reindex(dates)), "b": b}
    data = {"dates": list(dates.strftime("%Y-%m-%d")), "tfl": {k: TFL[k] for k in ib},
            "ppy": PPY, "tf": tfd, "ix": arr(idx["Close"].reindex(dates).ffill()), "stocks": stocks}
    meta = (f"Generated {date.today():%d %b %Y} | last daily price {data['dates'][-1]} | {len(stocks)} stocks"
            + (f" | skipped: {', '.join(skipped)}" if skipped else ""))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")))
                   .replace("__META__", meta), encoding="utf-8")
    print("Done ->", OUT)
    if not CI:
        webbrowser.open(OUT.resolve().as_uri())


TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Beta / Alpha Screener - Bharat Market Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#1f7a55">
<link rel="icon" href="icon-192.png">
<link rel="apple-touch-icon" href="icon-192.png">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{--bg:#f6f4ee;--card:#fffdf8;--ink:#1c2a26;--mut:#5d6b66;--line:#d9d4c5;--g:#1f7a55;--r:#b3402e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
.tri{height:6px;background:linear-gradient(90deg,#FF9933 33%,#fff 33% 66%,#138808 66%)}
.w{width:100%;padding:16px 24px 50px}h1{margin:.2em 0;font:700 1.6rem Georgia,serif}h3{margin:.1em 0 .4em}
.m{color:var(--mut);font-size:.85rem}.c{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:10px 0}
.f{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
label{display:block;font-size:.78rem;color:var(--mut)}
input,select{width:100%;font:inherit;padding:6px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}
.tw{max-height:420px;overflow:auto}table{width:100%;border-collapse:collapse}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{position:sticky;top:0;background:var(--card);cursor:pointer}tbody tr{cursor:pointer}tbody tr:hover{background:#0000000d}
tr.sel{background:#c98a1233}.up{color:var(--g);font-weight:600}.dn{color:var(--r);font-weight:600}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}
.k{border:1px solid var(--line);border-radius:8px;padding:10px;background:var(--bg)}.k b{font-size:1.25rem;display:block}
@media(max-width:600px){.w{padding:12px 10px 40px}h1{font-size:1.3rem}}
</style></head><body><div class="tri"></div><div class="w">
<h1>Beta / Alpha Screener</h1>
<p class="m">Same logic as the TradingView "Scr αβ" script. Chart timeframe, period and risk-free rate work independently, just like the indicator settings. Click a stock to see what happened after its signal. Educational only, not investment advice.</p>
<div class="c"><div class="f">
<div><label>Chart timeframe</label><select id="tf"></select></div>
<div><label>Beta &amp; Alpha period (bars)</label><input id="n" list="nl" type="number" min="2" value="52"><datalist id="nl"><option value="30" label="Short 30"><option value="90" label="Short 90"><option value="52" label="Medium 52"><option value="104" label="Medium 104"><option value="24" label="Long 24"><option value="48" label="Long 48"><option value="252" label="252"></datalist></div>
<div><label>Risk-free symbol</label><select id="ten"><option>IN03MY</option><option>IN06MY</option><option>IN01Y</option><option>IN02Y</option><option>IN03Y</option><option>IN05Y</option><option>IN10Y</option></select></div>
<div><label>Risk-free yield % <span id="rfh"></span></label><input id="rf" type="number" step="0.01" value="5.75"></div>
<div><label>Returns type</label><select id="rt"><option value="s">Returns</option><option value="log">Logarithmic Returns</option></select></div>
<div><label>Alpha formula</label><select id="am"><option value="fix">Corrected (alpha in % per bar)</option><option value="pine">Same as Pine script (matches TradingView)</option></select></div>
<div><label>Beta from</label><input id="bf" type="number" step="0.1" value="2"></div>
<div><label>Beta to</label><input id="bt" type="number" step="0.1" value="10"></div>
<div><label>Alpha from</label><input id="af" type="number" step="0.1" value="1"></div>
<div><label>Alpha to</label><input id="at" type="number" step="0.1" value="100"></div>
<div><label>Signals within</label><select id="rec"><option value="0">All bars stored</option><option value="1">Today / last day</option><option value="5">Last 5 days</option><option value="21">Last 1 month</option><option value="63">Last 3 months</option><option value="126">Last 6 months</option><option value="252">Last 1 year</option></select></div>
<div><label><input type="checkbox" id="auto" checked style="width:auto"> Auto-apply best setup when timeframe changes</label></div>
<div><label>Search symbol</label><input id="q" placeholder="e.g. JIOFIN"></div></div></div>
<p class="m" id="why"></p>
<div class="c m" id="stat"></div>
<p class="m" id="cnt"></p>
<div class="c tw"><table><thead><tr><th data-k="sym">Symbol</th><th data-k="date">Latest signal</th><th data-k="beta">β</th><th data-k="alpha">α</th><th data-k="price">Price at signal</th><th data-k="now">Current</th><th data-k="chg">Change</th><th data-k="n">Signals</th></tr></thead><tbody id="tb"></tbody></table></div>
<div id="dt"></div>
<p class="m">__META__</p>
<p class="m">Risk-free yield: type the current value of the TradingView symbol you use (e.g. TVC:IN03MY) for the selected tenor; the page remembers it per tenor. The indicator reads the yield bar by bar, this page uses one value for all bars, so old signals can differ slightly. In "Same as Pine" mode the yield is subtracted as a raw number (e.g. 5.75) from fractional returns, so alpha is roughly yield x (beta - 1) and changing the yield changes every alpha, which matches what you see in TradingView. 15-minute data from Yahoo covers only the last ~60 days. 3M/6M/1Y results use 63/126/252 trading days after the signal day.</p>
</div><script>
const D=__DATA__,$=id=>document.getElementById(id);
const esc=s=>s.replace(/&/g,"&amp;"),fmt=n=>n==null?"-":n.toLocaleString("en-IN",{maximumFractionDigits:2});
const cl=v=>v==null?"":v>=0?"up":"dn",pc=(v,b)=>v==null?null:(v/b-1)*100,ps=p=>p==null?"-":(p>=0?"+":"")+p.toFixed(1)+"%";
let rows=[],sk="date",sd=-1,OS=null;
const RF={IN03MY:5.75};try{Object.assign(RF,JSON.parse(localStorage.rf||"{}"))}catch(e){}
$("rf").value=RF.IN03MY;
$("tf").innerHTML=Object.entries(D.tfl).map(([k,v])=>`<option value="${k}"${k=="W"?" selected":""}>${v}</option>`).join("");
function calc(c,ic,n,lg,rf,pine,ppy){
 const L=c.length,r=new Float64Array(L),m=new Float64Array(L),bad=new Int32Array(L+1);
 const sr=new Float64Array(L+1),sm=new Float64Array(L+1),srm=new Float64Array(L+1),smm=new Float64Array(L+1);
 const f=(a,b)=>lg?Math.log(a/b):a/b-1;
 for(let i=0;i<L;i++){
  const ok=i>0&&c[i]!=null&&c[i-1]!=null&&ic[i]!=null&&ic[i-1]!=null&&c[i]>0&&c[i-1]>0;
  r[i]=ok?f(c[i],c[i-1]):0;m[i]=ok?f(ic[i],ic[i-1]):0;
  bad[i+1]=bad[i]+(ok?0:1);sr[i+1]=sr[i]+r[i];sm[i+1]=sm[i]+m[i];srm[i+1]=srm[i]+r[i]*m[i];smm[i+1]=smm[i]+m[i]*m[i];
 }
 const rfb=pine?rf:rf/100/ppy,out=[];
 for(let i=n;i<L;i++){
  const a=i-n+1,b=i+1;if(bad[b]-bad[a])continue;
  const er=(sr[b]-sr[a])/n,em=(sm[b]-sm[a])/n,cov=(srm[b]-srm[a])/n-er*em,v=(smm[b]-smm[a])/n-em*em;
  if(!(v>0))continue;
  const beta=cov/v;const al=r[i]-(rfb+beta*(m[i]-rfb));out.push([i,beta,pine?al:al*100]);
 }
 return out;
}
function draw(){
 const tf=$("tf").value,n=Math.max(2,+$("n").value|0),lg=$("rt").value=="log",pine=$("am").value=="pine",rf=+$("rf").value;
 const bf=+$("bf").value,bt=+$("bt").value,af=+$("af").value,at=+$("at").value,rc=+$("rec").value,q=$("q").value.trim().toUpperCase();
 const T=D.tf[tf],end=D.dates.length-1,cut=rc?end-rc+1:-99;rows=[];let have=0;
 const ST={3:{n:0,s:0,x:0,w:0,o:0},6:{n:0,s:0,x:0,w:0,o:0}};
 for(const [sym,s] of Object.entries(D.stocks)){
  const c=s.b[tf];if(!c)continue;have++;if(q&&!sym.includes(q))continue;
  const all=calc(c,T.i,n,lg,rf,pine,D.ppy[tf]).filter(x=>x[1]>=bf&&x[1]<=bt&&x[2]>=af&&x[2]<=at);
  let lp=-1e9;
  for(const x of all){const p=T.p[x[0]];if(p<0||p-lp<21)continue;lp=p;const pr=c[x[0]];
   for(const [d,k] of [[63,3],[126,6]]){if(p+d>end||!pr||s.c[p+d]==null||!D.ix[p]||!D.ix[p+d])continue;
    const a=s.c[p+d]/pr-1,b=D.ix[p+d]/D.ix[p]-1,o=ST[k];o.n++;o.s+=a;o.x+=b;if(a>0)o.w++;if(a>b)o.o++;}}
  const sig=all.filter(x=>T.p[x[0]]>=cut)
   .map(x=>({i:x[0],p:T.p[x[0]],beta:+x[1].toFixed(2),alpha:+x[2].toFixed(2),price:c[x[0]]}));
  if(!sig.length)continue;
  const l=sig[sig.length-1],now=s.c[end];
  rows.push({sym,tf,sig,date:l.i,beta:l.beta,alpha:l.alpha,price:l.price,now,chg:pc(now,l.price),n:sig.length});
 }
 const st=k=>{const o=ST[k];return o.n?`${k}M: ${o.n} signals, average ${ps(o.s/o.n*100)} vs Nifty ${ps(o.x/o.n*100)}, positive ${(o.w/o.n*100).toFixed(0)}%, beat Nifty ${(o.o/o.n*100).toFixed(0)}%`:`${k}M: not enough history`};
 $("stat").innerHTML="<b>Past signals of this setup</b> (one per stock per ~month, close to close, same Nifty period): "+st(3)+" | "+st(6);
 rows.sort((a,b)=>(a[sk]>b[sk]?1:a[sk]<b[sk]?-1:0)*sd);
 $("cnt").textContent=rows.length+" of "+have+" stocks match ("+D.tfl[tf]+", period "+n+")";
 $("tb").innerHTML=rows.map((r,i)=>`<tr data-i="${i}"><td><b>${esc(r.sym)}</b></td><td>${T.t[r.date]}</td><td>${r.beta}</td><td>${r.alpha}</td><td>${fmt(r.price)}</td><td>${fmt(r.now)}</td><td class="${cl(r.chg)}">${ps(r.chg)}</td><td>${r.n}</td></tr>`).join("");
}
function analyse(s,pos,base){
 const end=D.dates.length-1,mx=d=>{let m=null;for(let i=pos+1;i<=Math.min(pos+d,end);i++){const v=s.h[i];if(v!=null&&(m==null||v>m))m=v}return m};
 return{base,now:s.c[end],days:end-pos,c3:s.c[Math.min(pos+63,end)],e3:pos+63<=end,h6:mx(126),e6:pos+126<=end,h1:mx(252),e1:pos+252<=end};
}
function open(r,k,ns){
 k=k??r.sig.length-1;OS={r,k};const sg=r.sig[k],pos=sg.p,T=D.tf[r.tf],s=D.stocks[r.sym],b=sg.price,a=analyse(s,pos,b);
 const opts=r.sig.map((x,j)=>`<option value="${j}"${j==k?" selected":""}>${T.t[x.i]} (β ${x.beta}, α ${x.alpha})</option>`).reverse().join("");
 const card=(t,v,p,n)=>`<div class="k"><span class="m">${t}</span><b>${fmt(v)}</b><span class="${cl(p)}">${ps(p)}</span><div class="m">${n}</div></div>`;
 $("dt").innerHTML=`<div class="c"><div class="f" style="grid-template-columns:200px 1fr;align-items:end"><h3>${esc(r.sym)}</h3><div style="max-width:360px"><label>Signal date (all signals in your filter)</label><select id="sg">${opts}</select></div></div>
 <p class="m">${a.days} trading days since the signal (${T.t[sg.i]}). Percentages are versus the price at the signal.</p>
 <div class="g">${card("Price at signal",b,null,T.t[sg.i])}
 ${card("3-month result",a.c3,pc(a.c3,b),a.e3?"close 63 trading days later":"not complete, latest close used")}
 ${card("6-month max high",a.h6,pc(a.h6,b),a.e6?"highest high in 6 months":"window incomplete, so far")}
 ${card("1-year max high",a.h1,pc(a.h1,b),a.e1?"highest high in 1 year":"window incomplete, so far")}
 ${card("Current price",a.now,pc(a.now,b),D.dates[D.dates.length-1])}</div><div id="ch" style="height:420px;margin-top:10px"></div></div>`;
 $("sg").onchange=e=>open(r,+e.target.value);
 const xs=D.dates.slice(pos),later=r.sig.filter(x=>x.p>=pos);
 Plotly.newPlot("ch",[{x:xs,y:s.c.slice(pos),mode:"lines",name:"Close",line:{color:"#1f7a55"}},
  {x:xs,y:s.h.slice(pos),mode:"lines",name:"Daily high",line:{color:"#c98a12",width:1}},
  {x:later.map(x=>D.dates[x.p]),y:later.map(x=>x.price),mode:"markers",name:"Signals",marker:{size:9,color:"#b3402e",symbol:"triangle-up"}}],
  {title:r.sym+": "+D.dates[pos]+" to "+D.dates[D.dates.length-1],margin:{t:40,l:55,r:10,b:35},legend:{orientation:"h"},
  shapes:[{type:"line",xref:"paper",x0:0,x1:1,y0:b,y1:b,line:{dash:"dot",color:"#5d6b66"}}]},{responsive:true});
 if(!ns)$("dt").scrollIntoView({behavior:"smooth"});
}
const PS={"15m":{n:100,bf:1.2,bt:3,af:.2,rec:1,why:"15 minute: intraday trading only, not for investing. High-beta stocks beating the market on today's 15-minute bars."},
 D:{n:90,bf:1.2,bt:2.5,af:.5,rec:5,why:"Daily: swing trades (a few weeks to 3 months). 90 days of beta, fresh signals from the last 5 days."},
 W:{n:52,bf:1,bt:2,af:1,rec:21,why:"Weekly (recommended for investing, 3 to 12 months): 1 year of beta; beta 1 to 2 gives growth stocks without extreme swings; alpha above 1% means that week beat what the stock's beta explains."},
 M:{n:36,bf:.9,bt:1.8,af:2,rec:63,why:"Monthly: long-term investing (1 to 3 years). 3 years of beta, alpha above 2% in the month, signals from the last 3 months."},
 Q:{n:20,bf:.8,bt:1.5,af:3,rec:126,why:"Quarterly: very long-term compounding. 5 years of beta, moderate-beta stocks, alpha above 3% in the quarter. Few signals."}};
function apply(){const tf=$("tf").value,p=PS[tf]||PS.W,pine=$("am").value=="pine";
 $("n").value=p.n;$("bf").value=p.bf;$("bt").value=p.bt;$("af").value=pine?1:p.af;$("at").value=100;$("rec").value=p.rec;
 $("why").textContent=p.why+(pine?" (Pine mode: alpha is about yield x (beta - 1), so the beta range does the real filtering.)":"");draw();}
["n","rt","bf","bt","af","at","rec","q"].forEach(i=>$(i).oninput=draw);
["tf","am"].forEach(i=>$(i).oninput=()=>$("auto").checked?apply():draw());
$("rf").oninput=()=>{RF[$("ten").value]=+$("rf").value;try{localStorage.rf=JSON.stringify(RF)}catch(e){}draw()};
$("ten").onchange=()=>{const v=RF[$("ten").value];if(v!=null)$("rf").value=v;$("rfh").textContent=v==null?"(enter this tenor's yield from TradingView)":"";draw()};
document.querySelectorAll("th").forEach(h=>h.onclick=()=>{const k=h.dataset.k;sd=sk==k?-sd:-1;sk=k;draw()});
$("tb").onclick=e=>{const tr=e.target.closest("tr");if(!tr)return;document.querySelectorAll("tr.sel").forEach(x=>x.classList.remove("sel"));tr.classList.add("sel");open(rows[+tr.dataset.i])};
apply();
if("serviceWorker" in navigator)navigator.serviceWorker.register("sw.js").catch(()=>{});
</script></body></html>"""

if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        print(e)
        if CI:
            sys.exit(1)          # make the GitHub run fail so the old site stays online
    except Exception:
        import traceback
        traceback.print_exc()
        if CI:
            sys.exit(1)
    if not CI:
        input("\nPress Enter to close...")
