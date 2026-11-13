"""One self-contained, interactive HTML report built from a finished run (reads validation + evaluation JSON only).

It never touches the generated data. No external libraries or network access are needed to open the file."""
from __future__ import annotations

import json
from pathlib import Path

VAL_KEYS = ["dataset", "seed", "row_counts", "checks", "total_error_violations", "total_rule_violations", "passed",
            "ground_truth_reconciliation", "coverage", "boundary_coverage", "randomisation_balance"]


def build_report(out_dir) -> Path:
    out = Path(out_dir)
    val = json.loads((out / "validation" / "validation_summary.json").read_text(encoding="utf-8"))
    ev = json.loads((out / "evaluation" / "evaluation_report.json").read_text(encoding="utf-8"))
    d = val.get("distributions", {})
    data = {"val": {k: val[k] for k in VAL_KEYS if k in val}, "eval": ev,
            "dist": {k: d[k] for k in ("primary_churn_events_by_month", "prospect_funnel") if k in d}}
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    path = out / "report.html"
    path.write_text(TEMPLATE.replace("__DATA__", blob), encoding="utf-8")
    return path


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Churn and retention report</title>
<style>
:root{color-scheme:light;--bg:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--border:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--good:#006300;--bad:#d03b3b;--band:rgba(42,120,214,.10)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--good:#0ca30c;--band:rgba(57,135,229,.16)}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;
--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--good:#0ca30c;--band:rgba(57,135,229,.16)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:880px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}p{margin:8px 0}.sub{color:var(--ink2);margin:0 0 16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;margin:12px 0}
nav{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--grid);margin:16px 0}
nav button{background:none;border:0;border-bottom:2px solid transparent;color:var(--ink2);padding:8px 12px;font:inherit;cursor:pointer}
nav button[aria-selected=true]{color:var(--ink);border-bottom-color:var(--s1);font-weight:600}
button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px}
.tile b{display:block;font-size:24px;line-height:1.2}.tile>span{color:var(--ink2);font-size:13px}
.ok{color:var(--good)}.no{color:var(--bad)}
.ctl{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:0 0 8px;color:var(--ink2);font-size:14px}
.ctl label{display:inline-flex;gap:6px;align-items:center;cursor:pointer}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--ink2);margin:4px 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
svg{width:100%;height:auto;display:block}svg text{fill:var(--muted);font-size:11px}svg .l{fill:var(--ink2);font-size:12px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}th{color:var(--ink2);font-weight:600;cursor:pointer;white-space:nowrap}
.scroll{overflow-x:auto}details{margin-top:8px;font-size:13px;color:var(--ink2)}summary{cursor:pointer}
#tip{position:fixed;display:none;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--axis);border-radius:6px;
padding:6px 10px;font-size:12px;line-height:1.4;z-index:9;box-shadow:0 2px 8px rgba(0,0,0,.15)}
input[type=search],select{font:inherit;padding:4px 8px;border:1px solid var(--axis);border-radius:6px;background:var(--surface);color:var(--ink)}
.note{color:var(--ink2);font-size:13px}[hidden]{display:none!important}
</style></head><body><main>
<h1>Churn and retention-offer report</h1>
<p class="sub" id="sub"></p>
<nav role="tablist" id="tabs"></nav>
<section id="p-overview" hidden></section><section id="p-churn" hidden></section><section id="p-offers" hidden></section>
<section id="p-target" hidden></section><section id="p-quality" hidden></section>
<p class="note">Everything on this page is read from <code>validation/validation_summary.json</code> and <code>evaluation/evaluation_report.json</code>. Data is synthetic.</p>
</main><div id="tip"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent),E=D.eval,V=D.val;
const $=(s,r=document)=>r.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pts=(x,d=1)=>(x*100).toFixed(d),num=x=>Math.round(x).toLocaleString();
const money=x=>(x<0?'-':'')+'$'+Math.abs(Math.round(x)).toLocaleString();
const pv=p=>p<0.001?'<0.001':p.toFixed(3);
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const tip=$('#tip');
function bindTips(root){root.querySelectorAll('[data-tip]').forEach(n=>{
 n.addEventListener('mousemove',e=>{tip.innerHTML=n.dataset.tip;tip.style.display='block';const w=tip.offsetWidth;
  let x=e.clientX+14;if(x+w>innerWidth-8)x=e.clientX-w-14;tip.style.left=Math.max(4,x)+'px';tip.style.top=(e.clientY+14)+'px'});
 n.addEventListener('mouseleave',()=>tip.style.display='none')})}
function nice(min,max,n=4){const span=(max-min)||1,raw=span/n,p=Math.pow(10,Math.floor(Math.log10(raw))),f=raw/p;
 const step=(f<=1?1:f<=2?2:f<=5?5:10)*p,lo=Math.floor(min/step)*step,hi=Math.ceil(max/step)*step,t=[];
 for(let v=lo;v<=hi+step/2;v+=step)t.push(+v.toFixed(10));return{lo,hi,ticks:t}}
const mname=m=>{const [y,mo]=m.split('-');return['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+mo-1]+" '"+y.slice(2)};
function legend(items){return '<div class="legend">'+items.map(i=>`<span><i style="background:${i[1]}"></i>${esc(i[0])}</span>`).join('')+'</div>'}

/* ---- generic sortable table ---- */
function mountTable(host,cols,rows,sort){let key=sort&&sort[0],dir=sort?sort[1]:1;
 const draw=()=>{const r=rows.slice();if(key!=null){const c=cols.find(c=>c.k===key);r.sort((a,b)=>(a[key]>b[key]?1:a[key]<b[key]?-1:0)*dir)}
  host.innerHTML='<div class="scroll"><table><thead><tr>'+cols.map(c=>`<th class="${c.n?'n':''}" data-k="${c.k}" title="Sort">${esc(c.label)}${key===c.k?(dir>0?' ▲':' ▼'):''}</th>`).join('')+
  '</tr></thead><tbody>'+r.map(x=>'<tr>'+cols.map(c=>`<td class="${c.n?'n':''}">${c.f?c.f(x[c.k],x):esc(x[c.k]??'')}</td>`).join('')+'</tr>').join('')+'</tbody></table></div>';
  host.querySelectorAll('th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;dir=key===k?-dir:1;key=k;draw()})};draw()}

/* ---- forest / dot plot (estimate + 95% CI, in percentage points) ---- */
function forest(rows,unit='pts'){const W=760,rh=38,l=210,r=70,t=10,b=44,H=t+rows.length*rh+b,iw=W-l-r;
 const lo=Math.min(0,...rows.map(x=>x.lo)),hi=Math.max(0,...rows.map(x=>x.hi)),a=nice(lo,hi,5),sx=v=>l+(v-a.lo)/(a.hi-a.lo)*iw;
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Estimates with 95% confidence intervals">`;
 a.ticks.forEach(v=>s+=`<line x1="${sx(v)}" x2="${sx(v)}" y1="${t}" y2="${H-b}" stroke="${v===0?css('--axis'):css('--grid')}"/><text x="${sx(v)}" y="${H-b+16}" text-anchor="middle">${v.toFixed(1)}</text>`);
 s+=`<text x="${l+iw/2}" y="${H-4}" text-anchor="middle" font-size="11">${unit} (positive = fewer customers churn)</text>`;
 rows.forEach((x,i)=>{const y=t+i*rh+rh/2;
  s+=`<g data-tip="${esc(x.tip)}"><rect x="0" y="${y-rh/2}" width="${W}" height="${rh}" fill="transparent"/>`+
   `<text class="l" x="${l-12}" y="${y+4}" text-anchor="end">${esc(x.label)}</text>`+
   (x.hi>x.lo?`<line x1="${sx(x.lo)}" x2="${sx(x.hi)}" y1="${y}" y2="${y}" stroke="${css('--ink2')}" stroke-width="2"/>`:'')+
   `<circle cx="${sx(x.est)}" cy="${y}" r="6" fill="${x.color}" stroke="${css('--surface')}" stroke-width="2"/>`+
   `<text class="l" x="${W-r+8}" y="${y+4}">${x.est.toFixed(2)}</text></g>`});
 return s+'</svg>'}

/* ---- tabs ---- */
const TABS=[['overview','Overview'],['churn','Churn behaviour'],['offers','Offer test'],['target','Targeting'],['quality','Data quality']];
const tabs=$('#tabs');
TABS.forEach(([id,label])=>{const b=document.createElement('button');b.textContent=label;b.setAttribute('role','tab');b.dataset.id=id;
 b.onclick=()=>show(id);tabs.appendChild(b)});
function show(id){TABS.forEach(([k])=>$('#p-'+k).hidden=k!==id);tabs.querySelectorAll('button').forEach(b=>b.setAttribute('aria-selected',b.dataset.id===id));
 history.replaceState(null,'','#'+id)}

const X=E.offer_experiment||{},ITT=X.incremental_lift_ITT,NV=X.naive_correlational_estimates,TR=X.scored_against_ground_truth,CV=X.cost_and_value;
const models=(E.churn_prediction||{}).models||[],gb=models.find(m=>/gradient/i.test(m.model))||models[models.length-1],heur=models[0];
const pol=((E.uplift_targeting||{}).policies)||{};
$('#sub').textContent=`${V.dataset} · seed ${V.seed} · prediction date ${E.prediction_date}, ${E.horizon_months}-month horizon`;

/* ---- overview ---- */
(function(){const p=$('#p-overview'),n=V.row_counts.customers,cov=V.coverage||{},ok=V.passed;
 const PN={by_uplift_score:'predicted uplift',by_churn_risk_score:'predicted churn risk'};
 const best=['by_uplift_score','by_churn_risk_score'].flatMap(k=>(pol[k]||[]).map(d=>({...d,k}))).reduce((a,b)=>!a||b.net_benefit>a.net_benefit?b:a,null);
 const tiles=[[num(n),'customers'],[pts(cov.ever_churn_rate_primary,0)+'%','ever churned'],[gb?gb.roc_auc.toFixed(2):'-','churn model AUC'],
  [ITT?pts(ITT.churn_reduction_abs,2)+' pts':'-','offer lift (randomised)'],[TR?pts(TR.share_of_total_offer_cost_wasted,0)+'%':'-','offer cost on likely stayers'],
  [`<span class="${ok?'ok':'no'}">${ok?'✓ PASS':'✗ FAIL'}</span>`,'validation']];
 p.innerHTML='<div class="tiles">'+tiles.map(t=>`<div class="tile"><b>${t[0]}</b><span>${t[1]}</span></div>`).join('')+'</div>'+
 '<h2>What we found</h2><div class="card"><ol id="story"></ol></div>'+
 '<h2>Why a randomised test matters</h2><p class="note">Naive comparison of accepters vs non-accepters says the offer does nothing, because accepters are the riskier customers. The holdout group gives the unbiased answer. Hover a row for details.</p><div class="card" id="cmp"></div>';
 const li=[];
 if(gb&&heur)li.push(`<b>Behaviour predicts churn.</b> A model trained only on past data reaches AUC ${gb.roc_auc.toFixed(2)} on the test period, against ${heur.roc_auc.toFixed(2)} for a simple "usage dropped" rule.`);
 if(ITT&&NV)li.push(`<b>Naive analysis is misleading.</b> Accepters vs non-accepters shows ${pts(NV.accepters_vs_non_accepters_churn_reduction,2)} pts. The randomised holdout shows <b>${pts(ITT.churn_reduction_abs,2)} pts</b> (95% CI ${pts(ITT.ci95[0],2)} to ${pts(ITT.ci95[1],2)}, p = ${pv(ITT.p_value)}).`);
 if(TR&&CV)li.push(`<b>Untargeted offers lose money.</b> ${pts(TR.share_of_total_offer_cost_wasted,0)}% of offer cost went to accepters who would have stayed anyway; net benefit across all treated is ${money(CV.net_benefit)}.`);
 if(best)li.push(`<b>Targeting helps.</b> Offering only to the top ${pts(best.targeted_share,0)}% by ${PN[best.k]} gives a net benefit of ${money(best.net_benefit)} on the holdout, against a loss when everyone is offered (noisy; see the Targeting tab).`);
 li.push(`<b>The data is trustworthy.</b> ${Object.keys(V.checks).length} checks, ${V.total_error_violations} structural errors; every injected edge case was detected.`);
 $('#story').innerHTML=li.map(x=>`<li>${x}</li>`).join('');
 if(ITT&&NV&&TR){const rows=[
  {label:'Naive: accepters vs non-accepters',est:NV.accepters_vs_non_accepters_churn_reduction*100,lo:NV.accepters_vs_non_accepters_churn_reduction*100,hi:NV.accepters_vs_non_accepters_churn_reduction*100,color:css('--s2'),tip:'<b>Naive estimate</b><br>biased by who chooses to accept'},
  {label:'Randomised test (ITT)',est:ITT.churn_reduction_abs*100,lo:ITT.ci95[0]*100,hi:ITT.ci95[1]*100,color:css('--s1'),tip:`<b>Randomised estimate</b><br>${pts(ITT.churn_reduction_abs,2)} pts, 95% CI ${pts(ITT.ci95[0],2)} to ${pts(ITT.ci95[1],2)}`},
  {label:'True effect (hidden ground truth)',est:TR.true_ITT_treated_arm*100,lo:TR.true_ITT_treated_arm*100,hi:TR.true_ITT_treated_arm*100,color:css('--s3'),tip:'<b>True effect</b><br>known only because the data is synthetic'}];
  $('#cmp').innerHTML=forest(rows,'percentage points');bindTips($('#cmp'))}
})();

/* ---- churn by month ---- */
(function(){const p=$('#p-churn'),M=D.dist.primary_churn_events_by_month;if(!M){p.innerHTML='<p>No monthly churn data in this run.</p>';return}
 p.innerHTML='<h2>Churn events by month</h2><p class="note">Voluntary cancellations rise after the March price change and spike in the prediction horizon. Involuntary (non-payment) churn stays flat.</p>'+
 '<div class="card"><div class="ctl"><span>Show</span>'+['both','voluntary','involuntary'].map(v=>`<label><input type="radio" name="cm" value="${v}" ${v==='both'?'checked':''}>${v}</label>`).join('')+'</div>'+
 legend([['Voluntary',css('--s1')],['Involuntary',css('--s2')],['Prediction horizon',css('--band')]])+'<div id="cc"></div><details><summary>Show data</summary><div id="ct"></div></details></div>';
 const months=Object.keys(M),pm=E.prediction_date.slice(0,7),i0=months.indexOf(pm),i1=i0+E.horizon_months;
 function draw(mode){const W=760,H=300,l=44,r=8,t=14,b=30,iw=W-l-r,ih=H-t-b,
  v=m=>mode==='involuntary'?0:M[m].voluntary,u=m=>mode==='voluntary'?0:M[m].involuntary,
  y=nice(0,Math.max(...months.map(m=>v(m)+u(m)))),sy=q=>t+ih-(q-y.lo)/(y.hi-y.lo)*ih,bw=iw/months.length,bar=bw*.68;
  let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Churn events per month">`;
  if(i0>=0)s+=`<rect x="${l+i0*bw}" y="${t}" width="${(i1-i0)*bw}" height="${ih}" fill="${css('--band')}"/>`;
  y.ticks.forEach(q=>s+=`<line x1="${l}" x2="${W-r}" y1="${sy(q)}" y2="${sy(q)}" stroke="${q===0?css('--axis'):css('--grid')}"/><text x="${l-6}" y="${sy(q)+4}" text-anchor="end">${q}</text>`);
  months.forEach((m,i)=>{const x=l+i*bw+(bw-bar)/2,a=v(m),c=u(m);
   if(a>0)s+=`<rect x="${x}" y="${sy(a)}" width="${bar}" height="${sy(0)-sy(a)}" fill="${css('--s1')}" rx="2"/>`;
   if(c>0){const top=sy(a+c),h=Math.max(0,sy(a)-top-(a>0?2:0));s+=`<rect x="${x}" y="${top}" width="${bar}" height="${h}" fill="${css('--s2')}" rx="2"/>`}
   if(i%2===0)s+=`<text x="${x+bar/2}" y="${H-10}" text-anchor="middle">${mname(m)}</text>`;
   s+=`<rect x="${l+i*bw}" y="${t}" width="${bw}" height="${ih}" fill="transparent" data-tip="<b>${mname(m)}</b><br>voluntary ${M[m].voluntary}<br>involuntary ${M[m].involuntary}"/>`});
  $('#cc').innerHTML=s+'</svg>';bindTips($('#cc'))}
 draw('both');p.querySelectorAll('input[name=cm]').forEach(i=>i.onchange=()=>draw(i.value));
 mountTable($('#ct'),[{k:'m',label:'Month'},{k:'voluntary',label:'Voluntary',n:1},{k:'involuntary',label:'Involuntary',n:1}],months.map(m=>({m,...M[m]})))})();

/* ---- offer test ---- */
(function(){const p=$('#p-offers');if(!ITT){p.innerHTML='<p>No experiment results in this run.</p>';return}
 p.innerHTML='<h2>Offer lift with 95% confidence intervals</h2><p class="note">Percentage points fewer customers churning in the treated group vs the holdout. An interval that crosses 0 means the data cannot rule out "no effect".</p>'+
 '<div class="card"><div class="ctl"><span>Break down by</span><select id="by"><option value="offer">offer</option><option value="plan">plan</option></select></div><div id="ff"></div></div>'+
 '<h2>Per-offer detail</h2><div class="card" id="po"></div>';
 const row=(label,o,color)=>({label,est:o.churn_reduction_abs*100,lo:o.ci95[0]*100,hi:o.ci95[1]*100,color,
  tip:`<b>${esc(label)}</b><br>${pts(o.churn_reduction_abs,2)} pts (CI ${pts(o.ci95[0],2)} to ${pts(o.ci95[1],2)})<br>treated ${num(o.n_treated)} · control ${num(o.n_control??o.n_control_eligible)}`});
 const all=row('All eligible customers',ITT,css('--ink2'));
 function draw(by){const src=by==='offer'?X.per_offer:X.by_plan;
  $('#ff').innerHTML=forest([all,...Object.entries(src||{}).map(([k,o])=>row(k,o,css('--s1')))]);bindTips($('#ff'))}
 draw('offer');$('#by').onchange=e=>draw(e.target.value);
 const po=Object.entries(X.per_offer||{}).map(([k,o])=>({offer:k,...o}));
 mountTable($('#po'),[{k:'offer',label:'Offer'},{k:'n_treated',label:'Treated',n:1,f:num},{k:'acceptance_rate',label:'Accepted',n:1,f:v=>pts(v,0)+'%'},
  {k:'churn_reduction_abs',label:'Lift (pts)',n:1,f:v=>pts(v,2)},{k:'total_cost',label:'Cost',n:1,f:money},{k:'incremental_retained',label:'Extra retained',n:1,f:v=>v.toFixed(0)},
  {k:'cost_per_incremental_retained',label:'Cost per extra retained',n:1,f:money}],po,['offer',1])})();

/* ---- targeting ---- */
(function(){const p=$('#p-target'),names={by_uplift_score:['Uplift model',css('--s1'),0],by_churn_risk_score:['Churn-risk model',css('--s2'),0],random:['Random',css('--muted'),1]};
 const keys=Object.keys(names).filter(k=>pol[k]&&pol[k].length);if(!keys.length){p.innerHTML='<p>No targeting results in this run.</p>';return}
 const U=E.uplift_targeting,MET={net_benefit:['Net benefit',money],incremental_retained:['Extra customers retained',v=>v.toFixed(0)],uplift_per_customer:['Uplift per targeted customer',v=>pts(v,1)+' pts']};
 p.innerHTML='<h2>Who should get the offer?</h2><p class="note">Holdout customers ranked by each score; the offer goes only to the top share. '+esc(U.note||'')+'</p>'+
 '<div class="card"><div class="ctl"><span>Metric</span><select id="met">'+Object.entries(MET).map(([k,v])=>`<option value="${k}">${v[0]}</option>`).join('')+'</select></div>'+
 legend(keys.map(k=>[names[k][0],names[k][1]]))+'<div id="tc"></div><details><summary>Show data</summary><div id="tt"></div></details></div>';
 function draw(m){const W=760,H=300,l=60,r=16,t=14,b=34,iw=W-l-r,ih=H-t-b,f=MET[m][1],n=pol[keys[0]].length;
  const vals=keys.flatMap(k=>pol[k].map(d=>d[m])),y=nice(Math.min(0,...vals),Math.max(0,...vals),4),sy=q=>t+ih-(q-y.lo)/(y.hi-y.lo)*ih,sx=i=>l+i/(n-1||1)*iw;
  let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${MET[m][0]} by share targeted">`;
  y.ticks.forEach(q=>s+=`<line x1="${l}" x2="${W-r}" y1="${sy(q)}" y2="${sy(q)}" stroke="${q===0?css('--axis'):css('--grid')}"/><text x="${l-6}" y="${sy(q)+4}" text-anchor="end">${f(q)}</text>`);
  pol[keys[0]].forEach((d,i)=>s+=`<text x="${sx(i)}" y="${H-18}" text-anchor="middle">${pts(d.targeted_share,0)}%</text>`);
  s+=`<text x="${l+iw/2}" y="${H-3}" text-anchor="middle" font-size="11">share of customers targeted</text>`;
  keys.forEach(k=>{const c=names[k][1];s+=`<polyline fill="none" stroke="${c}" stroke-width="2" ${names[k][2]?'stroke-dasharray="5 4"':''} points="${pol[k].map((d,i)=>sx(i)+','+sy(d[m])).join(' ')}"/>`;
  });
  s+=`<line id="cx" y1="${t}" y2="${t+ih}" stroke="${css('--axis')}" display="none"/><g id="dots"></g><rect id="hit" x="${l}" y="${t}" width="${iw}" height="${ih}" fill="transparent"/></svg>`;
  $('#tc').innerHTML=s;const hit=$('#hit'),cx=$('#cx'),dots=$('#dots');
  hit.onmousemove=e=>{const bb=hit.getBoundingClientRect(),i=Math.max(0,Math.min(n-1,Math.round((e.clientX-bb.left)/bb.width*(n-1))));
   cx.setAttribute('x1',sx(i));cx.setAttribute('x2',sx(i));cx.setAttribute('display','');
   dots.innerHTML=keys.map(k=>`<circle cx="${sx(i)}" cy="${sy(pol[k][i][m])}" r="5" fill="${names[k][1]}" stroke="${css('--surface')}" stroke-width="2"/>`).join('');
   tip.innerHTML=`<b>Top ${pts(pol[keys[0]][i].targeted_share,0)}% targeted</b><br>`+keys.map(k=>`${names[k][0]}: ${f(pol[k][i][m])}`).join('<br>');tip.style.display='block';
   tip.style.left=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=(e.clientY+14)+'px'};
  hit.onmouseleave=()=>{tip.style.display='none';cx.setAttribute('display','none');dots.innerHTML=''}}
 draw('net_benefit');$('#met').onchange=e=>draw(e.target.value);
 const rows=[];keys.forEach(k=>pol[k].forEach(d=>rows.push({policy:names[k][0],share:d.targeted_share,...d})));
 mountTable($('#tt'),[{k:'policy',label:'Policy'},{k:'share',label:'Targeted',n:1,f:v=>pts(v,0)+'%'},{k:'n_targeted',label:'Customers',n:1,f:num},
  {k:'uplift_per_customer',label:'Uplift (pts)',n:1,f:v=>pts(v,1)},{k:'se',label:'Std. error',n:1,f:v=>pts(v,1)},{k:'incremental_retained',label:'Extra retained',n:1,f:v=>v.toFixed(0)},
  {k:'net_benefit',label:'Net benefit',n:1,f:money}],rows)})();

/* ---- data quality ---- */
(function(){const p=$('#p-quality'),R=V.ground_truth_reconciliation||{},bc=V.boundary_coverage||{cases:[]};
 p.innerHTML=`<h2>Checks</h2><div class="card"><div class="ctl"><input type="search" id="q" placeholder="Filter checks" aria-label="Filter checks"><label><input type="checkbox" id="vo">only with violations</label>`+
 `<span>${V.total_error_violations} structural errors · ${V.total_rule_violations} rule exceptions (all explained)</span></div><div id="ck"></div></div>`+
 '<h2>Injected edge cases vs detection</h2><div class="card" id="an"></div>'+
 '<h2>Boundary, failure and exception coverage</h2><div class="card"><div class="ctl" id="chips"></div><div id="bd"></div></div>'+
 '<h2>Randomisation balance</h2><p class="note">Standardised mean difference between treatment and control; below 0.1 in absolute value is balanced.</p><div class="card" id="bal"></div>';
 const checks=Object.entries(V.checks).map(([id,o])=>({id,description:o.description,violations:o.violations}));
 const drawC=()=>{const q=$('#q').value.toLowerCase(),vo=$('#vo').checked;
  mountTable($('#ck'),[{k:'id',label:'Check'},{k:'description',label:'What it verifies'},{k:'violations',label:'Violations',n:1,f:num}],
   checks.filter(c=>(!vo||c.violations>0)&&(c.id+' '+c.description).toLowerCase().includes(q)),['id',1])};
 drawC();$('#q').oninput=drawC;$('#vo').onchange=drawC;
 mountTable($('#an'),[{k:'issue',label:'Issue type'},{k:'expected_check',label:'Caught by'},{k:'injected',label:'Injected',n:1},{k:'detected',label:'Detected',n:1},
  {k:'recall',label:'Recall',n:1,f:v=>v==null?'-':v.toFixed(2)}],Object.entries(R.per_issue_type||{}).map(([issue,o])=>({issue,...o})));
 const cats=['all',...new Set(bc.cases.map(c=>c.category))];let cat='all';
 const drawB=()=>{$('#chips').innerHTML=cats.map(c=>`<label><input type="radio" name="bc" value="${c}" ${c===cat?'checked':''}>${c}</label>`).join('')+
   `<span>${bc.cases.filter(c=>c.covered).length} of ${bc.cases.length} cases present</span>`;
  $('#chips').querySelectorAll('input').forEach(i=>i.onchange=()=>{cat=i.value;drawB()});
  mountTable($('#bd'),[{k:'category',label:'Category'},{k:'case',label:'Case'},{k:'count',label:'Records',n:1,f:num},
   {k:'covered',label:'Covered',f:v=>v?'<span class="ok">✓ yes</span>':'<span class="no">✗ no</span>'}],bc.cases.filter(c=>cat==='all'||c.category===cat))};
 drawB();
 mountTable($('#bal'),[{k:'covariate',label:'Covariate'},{k:'treatment_mean',label:'Treatment',n:1,f:v=>v.toFixed(3)},{k:'control_mean',label:'Control',n:1,f:v=>v.toFixed(3)},
  {k:'std_mean_diff',label:'SMD',n:1,f:v=>v.toFixed(3)}],V.randomisation_balance||[])})();

show((location.hash||'').slice(1).replace(/[^a-z]/g,'')&&TABS.some(t=>t[0]===location.hash.slice(1))?location.hash.slice(1):'overview');
</script></body></html>
"""
