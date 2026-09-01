"""데모 제어 서버 전용 운영 화면."""
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies.auth import require_role

router = APIRouter()
control_router = APIRouter(dependencies=[Depends(require_role("admin"))])


@router.get("/", include_in_schema=False)
async def demo_entry() -> RedirectResponse:
    return RedirectResponse("/login")


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def demo_login() -> HTMLResponse:
    return HTMLResponse(_LOGIN_PAGE)


@control_router.get("/control", response_class=HTMLResponse, include_in_schema=False)
async def demo_console() -> HTMLResponse:
    return HTMLResponse(_PAGE)


_LOGIN_PAGE = r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SOOM-GIL · 데모 제어실 로그인</title><style>
:root{color-scheme:dark;--bg:#080b0e;--panel:#11181e;--line:#2a3740;--text:#eef3f5;--muted:#89969e;--cyan:#71d8ff;--amber:#ffbd45;--red:#ff7276}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 75% 10%,#17323e,transparent 35%),var(--bg);color:var(--text);font-family:"Apple SD Gothic Neo","Noto Sans KR",sans-serif}.login{width:min(420px,calc(100% - 32px));padding:32px;border:1px solid var(--line);background:#10161ceF;box-shadow:0 30px 80px #0009}.eyebrow{color:var(--cyan);font:700 10px ui-monospace,monospace;letter-spacing:.18em}.login h1{margin:10px 0 7px;font-size:30px}.login h1 em{color:var(--amber);font-style:normal}.login p{margin:0 0 24px;color:var(--muted);font-size:12px}.login label{display:grid;gap:7px;margin-top:14px;color:var(--muted);font-size:11px}.login input{width:100%;height:46px;padding:0 13px;border:1px solid var(--line);background:#090d11;color:var(--text);font:inherit}.login input:focus{outline:2px solid var(--cyan);outline-offset:2px}.login button{width:100%;height:48px;margin-top:22px;border:1px solid var(--amber);background:#ffbd4517;color:var(--amber);font-weight:800;cursor:pointer}.login button:disabled{opacity:.5}.error{min-height:18px;margin:12px 0 0!important;color:var(--red)!important}
</style></head><body><form class="login" id="login"><span class="eyebrow">SOOM-GIL / CONTROL ROOM</span><h1>데모 <em>제어실</em></h1><p>관리자 계정으로 로그인하면 촬영 시나리오를 실행할 수 있습니다.</p><label>사용자 이름<input id="username" autocomplete="username" required autofocus></label><label>비밀번호<input id="password" type="password" autocomplete="current-password" required></label><button id="submit" type="submit">제어실 로그인</button><p class="error" id="error" role="alert"></p></form><script>
const form=document.querySelector('#login'),button=document.querySelector('#submit'),error=document.querySelector('#error');form.onsubmit=async e=>{e.preventDefault();button.disabled=true;error.textContent='';try{const response=await fetch('/api/auth/login',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.querySelector('#username').value,password:document.querySelector('#password').value})});if(!response.ok)throw Error(response.status===401?'아이디 또는 비밀번호를 확인하세요.':'로그인에 실패했습니다.');location.replace('/control')}catch(reason){error.textContent=reason.message;button.disabled=false}};
</script></body></html>'''


_PAGE = r'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SOOM-GIL · 데모 제어실</title>
  <style>
    :root{--bg:#080b0e;--panel:#10151a;--panel2:#151c22;--line:#29343d;--text:#eef3f5;--muted:#86949d;--green:#42d392;--amber:#ffbd45;--red:#ff5b5f;--cyan:#71d8ff;--shadow:0 24px 70px #0008}
    *{box-sizing:border-box}html{color-scheme:dark}body{margin:0;min-height:100vh;background:radial-gradient(circle at 78% 5%,#18303b 0,transparent 31%),linear-gradient(145deg,#06080a,#0b1116 58%,#080b0e);color:var(--text);font-family:"Apple SD Gothic Neo","Noto Sans KR",sans-serif}
    body:before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.22;background-image:linear-gradient(#ffffff08 1px,transparent 1px),linear-gradient(90deg,#ffffff08 1px,transparent 1px);background-size:32px 32px;mask-image:linear-gradient(to bottom,#000,transparent 75%)}
    button{font:inherit}.shell{width:min(1180px,calc(100% - 36px));margin:auto;padding:32px 0 48px;position:relative}.top{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:24px}.eyebrow{margin:0 0 7px;color:var(--cyan);font:700 11px ui-monospace,SFMono-Regular,monospace;letter-spacing:.18em}.title{margin:0;font-size:clamp(28px,4vw,48px);line-height:.95;letter-spacing:-.05em}.title em{color:var(--amber);font-style:normal}.sub{margin:11px 0 0;color:var(--muted);font-size:13px}.clock{text-align:right;font-family:ui-monospace,SFMono-Regular,monospace}.clock strong{display:block;font-size:22px;letter-spacing:.06em}.clock span{color:var(--muted);font-size:10px;letter-spacing:.15em}
    .status{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:center;padding:18px 20px;border:1px solid var(--line);background:linear-gradient(100deg,#11181eeb,#0c1115eb);box-shadow:var(--shadow);position:sticky;top:12px;z-index:5;backdrop-filter:blur(14px)}.status:before{content:"";position:absolute;left:-1px;top:-1px;bottom:-1px;width:4px;background:var(--muted)}.status.running:before{background:var(--green);box-shadow:0 0 18px var(--green)}.state{display:flex;align-items:center;gap:13px;min-width:0}.dot{width:10px;height:10px;border-radius:50%;background:var(--muted)}.running .dot{background:var(--green);box-shadow:0 0 0 6px #42d39218;animation:pulse 1.5s infinite}.state small{display:block;color:var(--muted);font:700 9px ui-monospace,SFMono-Regular,monospace;letter-spacing:.16em}.state strong{display:block;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:16px}.stop{min-width:132px;padding:11px 18px;border:1px solid #ff5b5f88;background:#ff5b5f12;color:#ff8a8d;font-weight:800;cursor:pointer}.stop:hover:not(:disabled){background:var(--red);color:#170304}.stop:disabled{opacity:.3;cursor:not-allowed}
    .hero{display:grid;grid-template-columns:1.35fr .65fr;gap:18px;margin-top:18px}.auto{position:relative;min-height:224px;padding:28px;text-align:left;border:1px solid #ffbd4566;background:linear-gradient(135deg,#221a0d,#12171a 68%);color:var(--text);overflow:hidden;cursor:pointer}.auto:after{content:"AUTO";position:absolute;right:-9px;bottom:-30px;color:#ffbd450d;font:900 112px ui-monospace,SFMono-Regular,monospace;letter-spacing:-.1em}.auto:hover{border-color:var(--amber);transform:translateY(-2px);box-shadow:0 18px 50px #0007}.auto small,.section-kicker{color:var(--amber);font:800 10px ui-monospace,SFMono-Regular,monospace;letter-spacing:.15em}.auto h2{max-width:540px;margin:20px 0 9px;font-size:32px;line-height:1.05;letter-spacing:-.04em}.auto p{max-width:550px;margin:0;color:#bdc6ca;font-size:13px;line-height:1.6}.auto b{display:inline-block;margin-top:24px;color:var(--amber);font-size:13px}.guide{padding:24px;border:1px solid var(--line);background:#10161bd9}.guide h3{margin:0 0 18px;font-size:15px}.steps{display:grid;gap:13px}.step{display:grid;grid-template-columns:24px 1fr;gap:10px;align-items:start}.step i{display:grid;place-items:center;width:22px;height:22px;border:1px solid var(--line);color:var(--cyan);font:700 10px ui-monospace,SFMono-Regular,monospace;font-style:normal}.step strong{display:block;font-size:12px}.step span{display:block;margin-top:3px;color:var(--muted);font-size:11px;line-height:1.4}
    .section-head{display:flex;align-items:end;justify-content:space-between;margin:34px 0 13px}.section-head h2{margin:4px 0 0;font-size:20px}.section-head span{color:var(--muted);font-size:11px}.playlists,.scenarios{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.card{display:flex;flex-direction:column;min-height:168px;padding:18px;border:1px solid var(--line);background:linear-gradient(145deg,#12191f,#0d1216);transition:.18s ease}.card:hover{border-color:#536570;transform:translateY(-2px)}.card .tag{align-self:flex-start;padding:3px 6px;border:1px solid #71d8ff55;color:var(--cyan);font:700 9px ui-monospace,SFMono-Regular,monospace;letter-spacing:.1em}.card h3{margin:15px 0 6px;font-size:15px}.card p{flex:1;margin:0;color:var(--muted);font-size:11px;line-height:1.55}.card button{margin-top:16px;padding:9px;border:1px solid var(--line);background:#171f25;color:var(--text);font-weight:700;cursor:pointer}.card button:hover:not(:disabled){border-color:var(--cyan);color:var(--cyan)}.card button:disabled,.auto:disabled{opacity:.45;cursor:wait;transform:none}.scenarios{grid-template-columns:repeat(4,minmax(0,1fr))}.scenarios .card{min-height:150px}.scenarios .card.gas .tag{border-color:#ffbd4566;color:var(--amber)}.scenarios .card.worker .tag{border-color:#42d39266;color:var(--green)}.scenarios .card.connection .tag{border-color:#ff5b5f66;color:#ff8a8d}
    .video-steps{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.video-step{display:grid;grid-template-columns:72px 1fr auto;gap:16px;align-items:center;padding:15px 16px;border:1px solid var(--line);background:#0e1419}.video-step.is-ready{border-color:#42d39288;background:#42d3920a}.video-time{color:var(--amber);font:800 12px ui-monospace,SFMono-Regular,monospace}.video-copy strong{display:block;font-size:13px}.video-copy span{display:block;margin-top:4px;color:var(--muted);font-size:10px;line-height:1.45}.video-step button{min-width:116px;padding:9px 11px;border:1px solid var(--line);background:#171f25;color:var(--text);font-size:11px;font-weight:800;cursor:pointer}.video-step button:hover:not(:disabled){border-color:var(--amber);color:var(--amber)}
    .notice{display:none;margin-top:14px;padding:11px 14px;border:1px solid #ff5b5f66;background:#ff5b5f10;color:#ff9b9e;font-size:12px}.notice.show{display:block}.foot{display:flex;justify-content:space-between;margin-top:30px;padding-top:15px;border-top:1px solid var(--line);color:var(--muted);font:10px ui-monospace,SFMono-Regular,monospace}.busy .card,.busy .auto{pointer-events:none}@keyframes pulse{50%{box-shadow:0 0 0 10px #42d39200}}
    @media(max-width:850px){.hero{grid-template-columns:1fr}.video-steps,.playlists{grid-template-columns:1fr}.scenarios{grid-template-columns:repeat(2,1fr)}}@media(max-width:520px){.shell{width:min(100% - 20px,1180px);padding-top:20px}.top{align-items:start}.clock{display:none}.status{grid-template-columns:1fr}.stop{width:100%}.video-step{grid-template-columns:62px 1fr}.video-step button{grid-column:1/-1}.scenarios{grid-template-columns:1fr}.auto{min-height:250px;padding:22px}.auto h2{font-size:27px}.foot{display:block;line-height:1.8}}
    @media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
  </style>
</head>
<body>
<main class="shell" id="app">
  <header class="top"><div><p class="eyebrow">SOOM-GIL / CONTROL ROOM</p><h1 class="title">데모 <em>제어실</em></h1><p class="sub">시연 데이터만 제어합니다. 실제 측정 화면과는 분리되어 있습니다.</p></div><div class="clock"><strong id="clock">--:--:--</strong><span>LOCAL CONTROL TIME</span></div></header>
  <section class="status" id="status"><div class="state"><i class="dot"></i><div><small>DEMO ENGINE</small><strong id="stateText">상태 확인 중…</strong></div></div><button class="stop" id="stop" disabled>■ 즉시 중지</button></section>
  <div class="notice" id="error" role="alert"></div>
  <section class="hero"><button class="auto" id="auto" disabled><small>ONE-TOUCH PRESENTATION</small><h2>전체 안전 시연을<br>처음부터 자동 재생</h2><p>CO₂ 경보부터 H₂S, 낙상, 산소 저농도, 연결 단절까지 백엔드가 순서대로 진행합니다.</p><b>▶ 전체 자동 시연 시작</b></button><aside class="guide"><h3>시연 진행 순서</h3><div class="steps" id="steps"></div></aside></section>
  <div class="section-head"><div><small class="section-kicker">2-MINUTE RECORDING CUE</small><h2>2분 영상 촬영 시나리오</h2></div><span>촬영 순서대로 하나씩 실행</span></div><section class="video-steps" id="videoSteps"></section>
  <div class="section-head"><div><small class="section-kicker">CURATED PLAYLISTS</small><h2>자동 시연 묶음</h2></div><span>선택한 묶음을 순서대로 재생</span></div><section class="playlists" id="playlists"></section>
  <div class="section-head"><div><small class="section-kicker">MANUAL SCENARIOS</small><h2>개별 상황 실행</h2></div><span>한 번에 하나의 상황만 실행</span></div><section class="scenarios" id="scenarios"></section>
  <footer class="foot"><span>SIMULATION DATA · NOT A LIVE MEASUREMENT</span><span>DEMO BACKEND :8010</span></footer>
</main>
<script>
  const $=s=>document.querySelector(s), app=$('#app'), statusBox=$('#status'), stateText=$('#stateText'), stopBtn=$('#stop'), errorBox=$('#error');
  let busy=false, playlists=[], scenarios=[];
  const labels={normal_steady:'정상 상태',gas_spread:'가스 확산',exposure_h2s_danger:'H₂S 누적 노출 위험',worker_walk:'작업자 위치',worker_walk_uwb:'UWB 위치',co2_warning:'CO₂ 경보',h2s_warning:'H₂S 경보',o2_low:'산소 저농도',fall_detection:'낙상 감지',node_offline:'연결 단절'};
  const sensors=['sensor-01','sensor-02','sensor-03','sensor-04'];
  const videoSteps=[
    {time:'0:00–0:06',title:'로그인 · 촬영 대기 상태',hint:'L3 연결 끊김 경보 없이 정상 heartbeat를 유지',action:'scenario',scenario:'normal_steady',nodes:sensors,duration:3600,button:'촬영 대기 상태 시작'},
    {time:'0:06–0:20',title:'현장 하드웨어 촬영',hint:'센서 노드 4개와 웨어러블·전원 LED 촬영',action:'manual',button:'촬영 준비 완료'},
    {time:'0:20–0:33',title:'MQTT 데이터 흐름',hint:'시리얼·MQTT 구독·대시보드 동일 값 연결',action:'scenario',scenario:'normal_steady',nodes:sensors,duration:60,button:'실시간 데이터 시작'},
    {time:'0:33–0:48',title:'정상 통합 모니터링',hint:'4개 노드 측정값과 BE·MQTT·WS 연결 확인',action:'scenario',scenario:'normal_steady',nodes:sensors,duration:60,button:'정상 상태 시작'},
    {time:'0:48–1:02',title:'CO₂ 단계별 위험 경보',hint:'정상 → 주의 → 경고 → 위험과 경보 배너',action:'scenario',scenario:'co2_warning',nodes:['sensor-03'],button:'CO₂ 경보 시작'},
    {time:'1:02–1:17',title:'3D 가스 분포 · 작업자 위치',hint:'4개 센서 공간 보간과 3D 트윈 확대',action:'scenario',scenario:'gas_spread',nodes:sensors,duration:75,button:'가스 확산 시작'},
    {time:'1:17–1:32',title:'H₂S 누적 노출 위험',hint:'4개 센서 분포를 유지하며 H₂S가 위험 1순위로 상승',action:'scenario',scenario:'exposure_h2s_danger',nodes:sensors,duration:45,button:'누적 노출 위험 시작'},
    {time:'1:32–1:45',title:'비상 탈출 경로',hint:'L2 이상 도달 후 2D·3D 대피 경로 촬영',action:'scenario',scenario:'gas_spread',nodes:sensors,duration:75,button:'위험·탈출로 시작'},
    {time:'1:45–1:52',title:'이벤트 로그 · AI 연구',hint:'현재 시연을 멈추고 저장된 경보 이력 촬영',action:'stop',button:'시연 중지·로그 확인'},
    {time:'1:52–1:56',title:'마무리 전체 대시보드',hint:'정상 화면과 하드웨어·팀명으로 마무리',action:'scenario',scenario:'normal_steady',nodes:sensors,duration:30,button:'정상 화면 복귀'}
  ];
  function cookie(name){const m=document.cookie.match(new RegExp('(?:^|; )'+name+'=([^;]*)'));return m?decodeURIComponent(m[1]):null}
  async function api(path,init={}){const h=new Headers(init.headers);if(init.body)h.set('Content-Type','application/json');if(init.method&&init.method!=='GET'){const t=cookie('hp015_csrf');if(t)h.set('X-CSRF-Token',t)}const r=await fetch('/api/demo'+path,{...init,headers:h,credentials:'include'});if(!r.ok){let d='요청 실패 ('+r.status+')';try{d=(await r.json()).detail||d}catch{}throw Error(d)}return r.json()}
  function setBusy(v){busy=v;app.classList.toggle('busy',v);document.querySelectorAll('button').forEach(b=>{if(b!==stopBtn)b.disabled=v});stopBtn.disabled=v||!statusBox.classList.contains('running')}
  function fail(e){errorBox.textContent=e.message||String(e);errorBox.classList.add('show');setBusy(false)}
  function kind(s){if(/co2|h2s|gas/.test(s.name))return['gas','GAS'];if(/worker|o2|fall/.test(s.name))return['worker','WORKER'];return['connection','SYSTEM']}
  function render(){const all=playlists.find(p=>p.name==='demo');if(all){$('#steps').innerHTML='';all.steps.forEach((s,i)=>{const el=document.createElement('div');el.className='step';el.innerHTML='<i>'+(i+1)+'</i><div><strong>'+labels[s]+'</strong><span>'+s+'</span></div>';$('#steps').append(el)})}
    $('#videoSteps').innerHTML='';videoSteps.forEach((step,i)=>{const el=document.createElement('article');el.className='video-step';const time=document.createElement('span');time.className='video-time';time.textContent=step.time;const copy=document.createElement('div');copy.className='video-copy';const title=document.createElement('strong');title.textContent=(i+1)+'. '+step.title;const hint=document.createElement('span');hint.textContent=step.hint;copy.append(title,hint);const b=document.createElement('button');b.textContent='▶ '+step.button;b.onclick=async()=>{if(step.action==='manual'){el.classList.toggle('is-ready');b.textContent=el.classList.contains('is-ready')?'✓ 준비 완료':'▶ '+step.button;return}if(step.action==='stop'){await stop();el.classList.add('is-ready');return}await runScenario(step.scenario,step.nodes,step.duration);el.classList.add('is-ready')};el.append(time,copy,b);$('#videoSteps').append(el)});
    $('#playlists').innerHTML='';playlists.filter(p=>p.name!=='demo').forEach(p=>$('#playlists').append(card('AUTO',p.label,p.description,p.steps.length+'단계 자동 시작',()=>runPlaylist(p.name))));
    $('#scenarios').innerHTML='';scenarios.forEach(s=>{const [cls,tag]=kind(s),el=card(tag,s.label,s.description,'이 상황 실행',()=>runScenario(s.name));el.classList.add(cls);$('#scenarios').append(el)});$('#auto').disabled=false}
  function card(tag,title,desc,action,fn){const el=document.createElement('article');el.className='card';const badge=document.createElement('span');badge.className='tag';badge.textContent=tag;const h=document.createElement('h3');h.textContent=title;const p=document.createElement('p');p.textContent=desc;const b=document.createElement('button');b.textContent='▶ '+action;b.onclick=fn;el.append(badge,h,p,b);return el}
  async function runPlaylist(name){setBusy(true);errorBox.classList.remove('show');try{await api('/playlist/run',{method:'POST',body:JSON.stringify({playlist:name})});await refresh()}catch(e){fail(e)}finally{setBusy(false)}}
  async function runScenario(name,node_ids,duration_s){setBusy(true);errorBox.classList.remove('show');const body={scenario:name};if(node_ids)body.node_ids=node_ids;if(duration_s)body.duration_s=duration_s;try{await api('/run',{method:'POST',body:JSON.stringify(body)});await refresh()}catch(e){fail(e)}finally{setBusy(false)}}
  async function stop(){setBusy(true);try{await api('/stop',{method:'POST'});await refresh()}catch(e){fail(e)}finally{setBusy(false)}}
  async function refresh(){try{const s=await api('/status');statusBox.classList.toggle('running',s.running);stateText.textContent=s.running?(s.scenario.startsWith('playlist:')?'자동 시연 실행 중 · '+s.scenario.split(':')[1]:'개별 상황 실행 중 · '+(labels[s.scenario]||s.scenario)):'대기 · 실행 중인 시연 없음';stopBtn.disabled=!s.running||busy}catch(e){fail(e)}}
  async function init(){try{[playlists,scenarios]=await Promise.all([api('/playlists'),api('/scenarios')]);render();await refresh()}catch(e){fail(e)}}
  $('#auto').onclick=()=>runPlaylist('demo');stopBtn.onclick=stop;setInterval(refresh,2500);setInterval(()=>$('#clock').textContent=new Date().toLocaleTimeString('ko-KR',{hour12:false}),1000);init();
</script>
</body></html>'''
