"""Cinematic intro for the IRIS dashboard.

Pure HTML canvas, no external libraries and no network needed (the Orbitron
font is optional and falls back to system fonts).

Scene: deep indigo space, no planet. A large, fully 3D-shaded satellite (gold
foil bus, solar wings, dish, telescope barrel) flies straight toward the
centre of the screen, then a T-3 / T-2 / T-1 countdown, a flash, and the title
while the satellite makes its final close approach.

The satellite is a hand-built polygon model lit by a single sun direction with
diffuse, specular and rim terms. It is purely illustrative: the range counter
and everything on screen is cinematic, not real telemetry.
"""
from __future__ import annotations

import streamlit.components.v1 as components

INTRO_HEIGHT = 720
INTRO_SECONDS = 10.6  # the app moves on to the dashboard after this long

INTRO_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  html, body { margin:0; height:100%; overflow:hidden; background:#020108;
    font-family:'Orbitron','Segoe UI','Helvetica Neue',Arial,sans-serif; }
  body { background:
      radial-gradient(760px 520px at 50% 52%, rgba(24,14,70,.55), rgba(2,1,8,0) 70%),
      radial-gradient(600px 420px at 10% 6%, rgba(40,20,90,.22), rgba(2,1,8,0) 65%),
      #020108; }
  canvas { position:absolute; inset:0; width:100%; height:100%; display:block; }
  #hint { position:absolute; left:0; right:0; bottom:40px; text-align:center; color:#9fb4ff;
    letter-spacing:.42em; font-size:12px; opacity:0; transition:opacity 1.2s; text-shadow:0 0 12px #6f8cff; }
  #hint.on { opacity:1; animation:bob 1.8s ease-in-out infinite; }
  @keyframes bob { 0%,100%{ transform:translateY(0); } 50%{ transform:translateY(5px); } }
  #replay { position:absolute; top:14px; right:18px; color:#8b97d6; font-size:11px; letter-spacing:.25em;
    cursor:pointer; opacity:.7; user-select:none; }
  #replay:hover { color:#9fb4ff; opacity:1; }
  #credit { position:absolute; left:0; right:0; text-align:center; bottom:14px; color:#5f6aa8; font-size:10px;
    letter-spacing:.12em; font-family:'Segoe UI',Arial,sans-serif; }
</style>
</head>
<body>
<canvas id="c"></canvas>
<div id="replay">&#8635; REPLAY INTRO</div>
<div id="credit">Cinematic intro: illustrative 3D model, not real telemetry.</div>
<div id="hint">ENTERING MISSION CONTROL</div>
<script>
(function(){
"use strict";
var cv=document.getElementById('c'), ctx=cv.getContext('2d');
var W=0,H=0,DPR=1;
function resize(){
  DPR=Math.min(2,window.devicePixelRatio||1);
  W=cv.clientWidth; H=cv.clientHeight;
  cv.width=Math.round(W*DPR); cv.height=Math.round(H*DPR);
  ctx.setTransform(DPR,0,0,DPR,0,0);
}
window.addEventListener('resize',resize); resize();

function clamp(v,a,b){ return v<a?a:(v>b?b:v); }
function lerp(a,b,t){ return a+(b-a)*t; }
function smooth(a,b,v){ var t=clamp((v-a)/(b-a),0,1); return t*t*(3-2*t); }
function rnd(a,b,c){ var x=Math.sin(a*127.1+b*311.7+c*74.7)*43758.5453; return x-Math.floor(x); }

/* ---------- vector / matrix helpers ---------- */
function add(a,b){ return [a[0]+b[0],a[1]+b[1],a[2]+b[2]]; }
function sub(a,b){ return [a[0]-b[0],a[1]-b[1],a[2]-b[2]]; }
function mul(a,k){ return [a[0]*k,a[1]*k,a[2]*k]; }
function dot(a,b){ return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]; }
function norm(a){ var l=Math.sqrt(dot(a,a))||1; return [a[0]/l,a[1]/l,a[2]/l]; }
function mv(M,v){ return [M[0]*v[0]+M[1]*v[1]+M[2]*v[2], M[3]*v[0]+M[4]*v[1]+M[5]*v[2], M[6]*v[0]+M[7]*v[1]+M[8]*v[2]]; }
function mm(A,B){ var R=[],i,j; for(i=0;i<3;i++) for(j=0;j<3;j++) R[i*3+j]=A[i*3]*B[j]+A[i*3+1]*B[3+j]+A[i*3+2]*B[6+j]; return R; }
function Rx(a){ var c=Math.cos(a),s=Math.sin(a); return [1,0,0, 0,c,-s, 0,s,c]; }
function Ry(a){ var c=Math.cos(a),s=Math.sin(a); return [c,0,s, 0,1,0, -s,0,c]; }
function Rz(a){ var c=Math.cos(a),s=Math.sin(a); return [c,-s,0, s,c,0, 0,0,1]; }

/* ---------- satellite model (local units, ~18 wide) ---------- */
var FACES=[];
function M(r,g,b,spec,shin,edge){ return {c:[r,g,b],s:spec,sh:shin,e:edge||null}; }
function quad(p0,p1,p2,p3,n,m,two){ FACES.push({p:[p0,p1,p2,p3],n:n,m:m,two:!!two}); }
function grid(o,u,v,nu,nv,n,mfn){
  for(var i=0;i<nu;i++) for(var j=0;j<nv;j++){
    var a=i/nu,b=(i+1)/nu,c=j/nu*nu/nv,d=(j+1)/nv; c=j/nv;
    var p0=add(o,add(mul(u,a),mul(v,c))), p1=add(o,add(mul(u,b),mul(v,c)));
    var p2=add(o,add(mul(u,b),mul(v,d))), p3=add(o,add(mul(u,a),mul(v,d)));
    quad(p0,p1,p2,p3,n,mfn(i,j));
  }
}
/* box with per-face subdivision; skip = array of face names; mfn(face,i,j) -> material */
function box(cx,cy,cz,sx,sy,sz,div,mfn,skip){
  var hx=sx/2,hy=sy/2,hz=sz/2; skip=skip||[]; div=div||[1,1,1];
  function has(n){ return skip.indexOf(n)<0; }
  if(has('+x')) grid([cx+hx,cy-hy,cz-hz],[0,sy,0],[0,0,sz],div[1],div[2],[1,0,0],function(i,j){return mfn('+x',i,j);});
  if(has('-x')) grid([cx-hx,cy-hy,cz-hz],[0,sy,0],[0,0,sz],div[1],div[2],[-1,0,0],function(i,j){return mfn('-x',i,j);});
  if(has('+y')) grid([cx-hx,cy+hy,cz-hz],[sx,0,0],[0,0,sz],div[0],div[2],[0,1,0],function(i,j){return mfn('+y',i,j);});
  if(has('-y')) grid([cx-hx,cy-hy,cz-hz],[sx,0,0],[0,0,sz],div[0],div[2],[0,-1,0],function(i,j){return mfn('-y',i,j);});
  if(has('+z')) grid([cx-hx,cy-hy,cz+hz],[sx,0,0],[0,sy,0],div[0],div[1],[0,0,1],function(i,j){return mfn('+z',i,j);});
  if(has('-z')) grid([cx-hx,cy-hy,cz-hz],[sx,0,0],[0,sy,0],div[0],div[1],[0,0,-1],function(i,j){return mfn('-z',i,j);});
}
function flat(m){ return function(){ return m; }; }
/* cylinder / cone along z from z0 to z1 */
function cyl(cx,cy,z0,z1,r0,r1,N,m,capA,capB){
  for(var k=0;k<N;k++){
    var a0=k/N*6.2832,a1=(k+1)/N*6.2832,am=(a0+a1)/2;
    var p0=[cx+Math.cos(a0)*r0,cy+Math.sin(a0)*r0,z0], p1=[cx+Math.cos(a1)*r0,cy+Math.sin(a1)*r0,z0];
    var p2=[cx+Math.cos(a1)*r1,cy+Math.sin(a1)*r1,z1], p3=[cx+Math.cos(a0)*r1,cy+Math.sin(a0)*r1,z1];
    var dz=(z1-z0), dr=(r0-r1);
    quad(p0,p1,p2,p3,norm([Math.cos(am)*Math.abs(dz),Math.sin(am)*Math.abs(dz),dr*(dz>0?1:-1)]),m,true);
    if(capA){ quad([cx,cy,z0],p0,p1,p1,[0,0,-1],capA,true); }
    if(capB){ quad([cx,cy,z1],p3,p2,p2,[0,0,1],capB,true); }
  }
}

(function buildSatellite(){
  var gold=function(f,i,j){ var k=0.82+0.34*rnd(i,j,f.charCodeAt(0)+f.charCodeAt(1)); return M(200*k,150*k,56*k,0.75,26,'rgba(70,40,5,.35)'); };
  var silver=function(f,i,j){ var k=0.86+0.12*rnd(i,j,3); return M(196*k,204*k,218*k,0.55,40,'rgba(60,70,100,.55)'); };
  /* main bus */
  box(0,0,0, 2.2,1.9,3.4, [5,4,6], function(f,i,j){ return (f==='+x'||f==='-x')?silver(f,i,j):gold(f,i,j); });
  /* telescope barrel + hood + lens (front, toward the viewer) */
  var dark=M(34,36,52,0.4,30,'rgba(0,0,0,.4)');
  cyl(0,0,-1.7,-3.1,0.62,0.62,22,dark,null,null);
  cyl(0,0,-1.7,-2.0,0.78,0.78,22,M(150,158,178,0.6,40),null,M(150,158,178,0.6,40));
  var glass1=M(26,34,92,1.0,90); glass1.bias=0.3; cyl(0,0,-3.1,-3.1,0.5,0.5,22,dark,glass1,null);
  var glass2=M(70,150,255,1.0,120); glass2.bias=0.6; cyl(0,0,-3.12,-3.12,0.34,0.34,22,dark,glass2,null);
  /* thruster nozzle (back) */
  cyl(0,0,1.7,2.4,0.38,0.82,18,M(46,48,64,0.5,30),null,M(14,14,22,0.1,5));
  /* solar wings */
  var cell=function(i,j){ var k=0.85+0.3*rnd(i,j,9); return M(20*k,48*k,128*k,0.95,70,'rgba(130,170,255,.55)'); };
  var metal=M(120,126,146,0.45,30,'rgba(0,0,0,.35)');
  [-1,1].forEach(function(s){
    box(s*1.45,0,0, 0.9,0.16,0.16, [1,1,1], flat(metal));
    box(s*1.95,0,0, 0.22,0.22,1.9, [1,1,2], flat(metal));
    for(var i=0;i<3;i++){
      var cxp=s*(2.95+i*2.4);
      box(cxp,0,0, 2.3,0.06,3.0, [1,1,1], flat(metal), ['+y']);
      grid([cxp-1.15,0.034,-1.5],[2.3,0,0],[0,0,3.0],6,4,[0,1,0],cell);
      if(i<2) box(cxp+s*1.2,0,0, 0.12,0.1,0.5, [1,1,1], flat(metal));
    }
  });
  /* dish on a mast */
  box(0,1.25,0.3, 0.14,0.7,0.14, [1,1,1], flat(metal));
  var Rd=Rx(Math.PI+0.52), t0=[0,2.0,0.25], rings=5, segs=28, kk=0.32, rmax=1.25;
  for(var ri=0;ri<rings;ri++){
    var ra=ri/rings*rmax, rb=(ri+1)/rings*rmax;
    for(var si=0;si<segs;si++){
      var a0=si/segs*6.2832,a1=(si+1)/segs*6.2832,am=(a0+a1)/2;
      var P=function(r,a){ var q=[Math.cos(a)*r,Math.sin(a)*r,kk*r*r]; return add(mv(Rd,q),t0); };
      var rm=(ra+rb)/2, nl=norm([-2*kk*rm*Math.cos(am),-2*kk*rm*Math.sin(am),1]);
      var shade=0.9+0.1*rnd(ri,si,5);
      quad(P(ra,a0),P(ra,a1),P(rb,a1),P(rb,a0),mv(Rd,nl),M(226*shade,230*shade,240*shade,0.7,35,'rgba(80,90,130,.25)'),true);
    }
  }
  box(0,2.0+0.55*0.5,0.25-0.95*0.5, 0.08,0.08,0.95, [1,1,1], flat(metal));
  /* small details: star trackers, whip antennas, radiator patches */
  box(-0.6,1.0,-1.1, 0.35,0.12,0.35, [1,1,1], flat(dark));
  box(0.6,1.0,-1.1, 0.35,0.12,0.35, [1,1,1], flat(dark));
  box(0.9,1.15,-0.7, 0.04,0.5,0.04, [1,1,1], flat(metal));
  box(-0.9,1.15,0.9, 0.04,0.7,0.04, [1,1,1], flat(metal));
})();

var NAV=[ {p:[-8.9,0,0],col:[255,60,60],ph:0}, {p:[8.9,0,0],col:[70,255,140],ph:1.6}, {p:[0,2.35,0.25],col:[255,255,255],ph:3.2} ];

function drawSatellite(R,D,t,fade){
  var Ls=norm([-0.45,0.55,-0.7]), F=H*1.05, cx=W/2, cy=H*0.57;
  var polys=[], best=null, i,k;
  for(i=0;i<FACES.length;i++){
    var f=FACES[i], P=[], cen=[0,0,0], bad=false;
    for(k=0;k<4;k++){ var q=add(mv(R,f.p[k]),[0,0,D]); if(q[2]<0.8){ bad=true; break; } P.push(q); cen=add(cen,q); }
    if(bad) continue;
    cen=mul(cen,0.25);
    var V=norm(mul(cen,-1)), N=mv(R,f.n), nd=dot(N,V);
    if(nd<=0){ if(!f.two) continue; N=mul(N,-1); nd=-nd; }
    var diff=Math.max(0,dot(N,Ls));
    var Hh=norm(add(Ls,V)), sp=Math.pow(Math.max(0,dot(N,Hh)),f.m.sh)*f.m.s;
    var rim=Math.pow(1-nd,3)*0.45;
    var amb=[0.045,0.045,0.12], sun=[1.05,0.98,0.9], c=f.m.c, col=[0,0,0];
    for(k=0;k<3;k++) col[k]=c[k]*(amb[k]+diff*sun[k]) + sp*255*sun[k]*0.9 + rim*[40,60,230][k];
    var fg=clamp((cen[2]-50)/160,0,0.8);
    col[0]=lerp(col[0],3,fg); col[1]=lerp(col[1],2,fg); col[2]=lerp(col[2],12,fg);
    var pts=[];
    for(k=0;k<4;k++) pts.push([cx+P[k][0]*F/P[k][2], cy-P[k][1]*F/P[k][2]]);
    var rgb='rgb('+Math.round(clamp(col[0],0,255))+','+Math.round(clamp(col[1],0,255))+','+Math.round(clamp(col[2],0,255))+')';
    polys.push({z:cen[2]-(f.m.bias||0),pts:pts,fill:rgb,edge:f.m.e});
    if(sp>0.55 && (!best || sp>best.sp)) best={sp:sp,x:(pts[0][0]+pts[2][0])/2,y:(pts[0][1]+pts[2][1])/2};
  }
  polys.sort(function(a,b){ return b.z-a.z; });
  ctx.save(); ctx.globalAlpha=fade; ctx.lineJoin='round';
  for(i=0;i<polys.length;i++){
    var pl=polys[i];
    ctx.beginPath(); ctx.moveTo(pl.pts[0][0],pl.pts[0][1]);
    for(k=1;k<4;k++) ctx.lineTo(pl.pts[k][0],pl.pts[k][1]);
    ctx.closePath(); ctx.fillStyle=pl.fill; ctx.fill();
    ctx.lineWidth=pl.edge?0.7:0.8; ctx.strokeStyle=pl.edge||pl.fill; ctx.stroke();
  }
  ctx.restore();
  /* navigation lights + strobe */
  ctx.save(); ctx.globalCompositeOperation='lighter';
  for(i=0;i<NAV.length;i++){
    var nv=NAV[i], q=add(mv(R,nv.p),[0,0,D]);
    if(q[2]<0.8) continue;
    var on=i===2 ? (Math.sin(t*6+nv.ph)>0.85?1:0.08) : (0.55+0.45*Math.sin(t*3+nv.ph));
    var px=cx+q[0]*F/q[2], py=cy-q[1]*F/q[2], rr=Math.max(3,F/q[2]*0.38);
    var g=ctx.createRadialGradient(px,py,0,px,py,rr*2.6);
    g.addColorStop(0,'rgba('+nv.col[0]+','+nv.col[1]+','+nv.col[2]+','+(0.95*on*fade)+')'); g.addColorStop(1,'rgba('+nv.col[0]+','+nv.col[1]+','+nv.col[2]+',0)');
    ctx.fillStyle=g; ctx.beginPath(); ctx.arc(px,py,rr*2.6,0,6.2832); ctx.fill();
  }
  /* sun glint flare on the brightest panel facet */
  if(best){
    var fa=clamp((best.sp-0.55)/0.45,0,1)*fade, fr=Math.max(60,H*0.16);
    var fgr=ctx.createRadialGradient(best.x,best.y,0,best.x,best.y,fr);
    fgr.addColorStop(0,'rgba(255,255,255,'+(0.85*fa)+')'); fgr.addColorStop(0.25,'rgba(170,190,255,'+(0.35*fa)+')'); fgr.addColorStop(1,'rgba(90,110,255,0)');
    ctx.fillStyle=fgr; ctx.beginPath(); ctx.arc(best.x,best.y,fr,0,6.2832); ctx.fill();
    ctx.fillStyle='rgba(190,205,255,'+(0.22*fa)+')'; ctx.fillRect(best.x-fr*1.1,best.y-0.7,fr*2.2,1.4);
  }
  ctx.restore();
}

/* ---------- background ---------- */
var stars=[]; for(var si=0;si<420;si++) stars.push({x:Math.random(),y:Math.random(),z:Math.random(),sp:1+Math.random()*3,ph:Math.random()*6.28});
var clouds=[ {x:.18,y:.22,r:.42,c:'80,44,170',a:.08}, {x:.82,y:.72,r:.46,c:'36,56,170',a:.08}, {x:.62,y:.14,r:.3,c:'130,50,140',a:.035}, {x:.3,y:.85,r:.34,c:'50,36,150',a:.05} ];
var shoot=null, nextShoot=5;
function drawBackground(t){
  var i;
  for(i=0;i<clouds.length;i++){
    var cl=clouds[i], rx=cl.x*W, ry=cl.y*H, rr=cl.r*Math.max(W,H);
    var g=ctx.createRadialGradient(rx,ry,0,rx,ry,rr);
    g.addColorStop(0,'rgba('+cl.c+','+cl.a+')'); g.addColorStop(1,'rgba('+cl.c+',0)');
    ctx.fillStyle=g; ctx.fillRect(0,0,W,H);
  }
  var cx=W/2, cy=H*0.52, drift=1+0.035*t;
  for(i=0;i<stars.length;i++){
    var s=stars[i], x=cx+(s.x*W-cx)*(1+(drift-1)*s.z), y=cy+(s.y*H-cy)*(1+(drift-1)*s.z);
    if(x<-5||x>W+5||y<-5||y>H+5) continue;
    var tw=0.5+0.5*Math.sin(t*s.sp+s.ph);
    ctx.globalAlpha=clamp(tw*(0.35+s.z*0.65),0,1);
    ctx.fillStyle=(i%9===0)?'#a9b8ff':(i%13===0)?'#ffd9b0':'#ffffff';
    ctx.beginPath(); ctx.arc(x,y,0.35+s.z*1.2,0,6.2832); ctx.fill();
  }
  ctx.globalAlpha=1;
  if(t>nextShoot && !shoot){ shoot={x:Math.random()*W*0.7+W*0.05,y:Math.random()*H*0.3,vx:560,vy:230,life:0}; nextShoot=t+4+Math.random()*4; }
  if(shoot){
    shoot.life+=0.016; shoot.x+=shoot.vx*0.016; shoot.y+=shoot.vy*0.016;
    var sg=ctx.createLinearGradient(shoot.x,shoot.y,shoot.x-shoot.vx*0.12,shoot.y-shoot.vy*0.12);
    sg.addColorStop(0,'rgba(255,255,255,0.85)'); sg.addColorStop(1,'rgba(255,255,255,0)');
    ctx.strokeStyle=sg; ctx.lineWidth=1.5; ctx.beginPath(); ctx.moveTo(shoot.x,shoot.y);
    ctx.lineTo(shoot.x-shoot.vx*0.12,shoot.y-shoot.vy*0.12); ctx.stroke();
    if(shoot.life>0.9) shoot=null;
  }
}

function glowText(txt,x,y,size,col,blur,alpha,spacing){
  ctx.save(); ctx.globalAlpha=alpha; ctx.textAlign='center'; ctx.textBaseline='middle';
  ctx.font='800 '+size+'px Orbitron,"Segoe UI",Arial,sans-serif';
  if(spacing){ try{ ctx.letterSpacing=spacing+'px'; }catch(e){} }
  ctx.shadowColor=col; ctx.shadowBlur=blur; ctx.fillStyle='#ffffff';
  ctx.fillText(txt,x,y); ctx.shadowBlur=blur*0.5; ctx.fillStyle=col; ctx.globalAlpha=alpha*0.55; ctx.fillText(txt,x,y);
  ctx.restore();
}
function plainText(txt,x,y,size,col,alpha,spacing,weight){
  ctx.save(); ctx.globalAlpha=alpha; ctx.textAlign='center'; ctx.textBaseline='middle';
  ctx.font=(weight||'400')+' '+size+'px Orbitron,"Segoe UI",Arial,sans-serif';
  if(spacing){ try{ ctx.letterSpacing=spacing+'px'; }catch(e){} }
  ctx.fillStyle=col; ctx.fillText(txt,x,y); ctx.restore();
}

/* ---------- timeline ---------- */
var T0=performance.now(), APP=4.2, CD=0.8, T_CD=4.2, T_END=T_CD+3*CD, T_CLOSE=2.6;
var hint=document.getElementById('hint');
document.getElementById('replay').addEventListener('click',function(){ T0=performance.now(); hint.className=''; });
function easeOutQuart(x){ x=clamp(x,0,1); return 1-Math.pow(1-x,4); }
function easeInOut(x){ x=clamp(x,0,1); return x*x*(3-2*x); }
function distance(t){
  if(t<APP) return lerp(320,9.5,easeOutQuart(t/APP));
  return lerp(9.5,8.7,smooth(APP,APP+5.5,t));
}

function frame(now){
  var t=(now-T0)/1000, cx=W/2, cy=H*0.52;
  ctx.clearRect(0,0,W,H);
  drawBackground(t);

  var D=distance(t);
  var ex=1-easeOutQuart(t/APP);
  var yaw=0.35+0.25*Math.sin(t*0.5)+ex*2.2;
  var pitch=-(0.3+0.06*Math.sin(t*0.3))-ex*0.5;
  var roll=-0.42+0.12*Math.sin(t*0.35)+ex*7.0;
  var R=mm(Ry(yaw),mm(Rx(pitch),Rz(roll)));
  var cdw=smooth(T_CD-0.2,T_CD,t)*(1-smooth(T_END-0.1,T_END+0.3,t));
  var fade=smooth(0.0,0.5,t)*(1-0.42*cdw);
  drawSatellite(R,D,t,fade);

  /* soft vignette keeps the focus in the centre */
  var vg=ctx.createRadialGradient(cx,cy,Math.min(W,H)*0.45,cx,cy,Math.max(W,H)*0.75);
  vg.addColorStop(0,'rgba(1,0,6,0)'); vg.addColorStop(1,'rgba(1,0,6,0.78)');
  ctx.fillStyle=vg; ctx.fillRect(0,0,W,H);

  if(t<APP+0.2){
    var ta=smooth(0.3,0.8,t)*(1-smooth(APP-0.3,APP+0.1,t));
    var rng=Math.max(0,Math.round((D-8)*45/10)*10);
    plainText('SAT-01  ·  INBOUND',cx,H*0.9,13,'#a9b8ff',ta,5,'500');
    plainText('RANGE '+rng.toLocaleString('en-US')+' M',cx,H*0.9+22,11,'#7f8fe0',ta,4,'400');
  }

  if(t>=T_CD && t<T_END){
    var k=Math.floor((t-T_CD)/CD), f=(t-T_CD)-k*CD;
    var num=3-k, label='T-'+num;
    var inA=smooth(0,0.18,f)*(1-smooth(0.82,1.0,f));
    var sc=1.18-0.18*smooth(0,0.28,f);
    var sz=Math.min(H*0.24,W*0.16)*sc;
    var rr=Math.min(H*0.27,W*0.19);
    ctx.save(); ctx.globalAlpha=inA*0.9; ctx.lineWidth=3; ctx.lineCap='round';
    ctx.strokeStyle='rgba(159,180,255,0.2)'; ctx.beginPath(); ctx.arc(cx,cy,rr,0,6.2832); ctx.stroke();
    ctx.strokeStyle='#9fb4ff'; ctx.shadowColor='#6f8cff'; ctx.shadowBlur=16;
    ctx.beginPath(); ctx.arc(cx,cy,rr,-Math.PI/2,-Math.PI/2+6.2832*f); ctx.stroke(); ctx.restore();
    ctx.save(); ctx.globalAlpha=inA*0.5*(1-f); ctx.strokeStyle='#c8d4ff'; ctx.lineWidth=2;
    ctx.beginPath(); ctx.arc(cx,cy,rr*(1+f*0.55),0,6.2832); ctx.stroke(); ctx.restore();
    glowText(label,cx,cy,sz,'#7f9bff',34,inA,6);
    plainText(num===3?'ACQUIRING SATELLITE FLEET':(num===2?'ARMING TRIAGE ENGINE':'ALL SYSTEMS NOMINAL'),cx,cy+rr+30,12,'#b9c6ff',inA*0.9,5,'400');
  } else if(t>=T_END){
    var fl=1-smooth(T_END,T_END+0.45,t);
    if(fl>0){
      var fg=ctx.createRadialGradient(cx,cy,0,cx,cy,Math.max(W,H)*0.7);
      fg.addColorStop(0,'rgba(200,215,255,'+(0.5*fl)+')'); fg.addColorStop(1,'rgba(200,215,255,0)');
      ctx.fillStyle=fg; ctx.fillRect(0,0,W,H);
    }
    var tt=smooth(T_END+0.15,T_END+1.1,t);
    var tsz=Math.max(26,Math.min(W*0.062,66)), slide=(1-tt)*18;
    glowText('IRIS',cx,H*0.115+slide,tsz,'#7f9bff',26,tt,Math.max(6,tsz*0.18));
    var sa=smooth(T_END+0.7,T_END+1.5,t);
    plainText('AUTONOMOUS ORBITAL DISASTER RESPONSE',cx,H*0.115+tsz*0.95+slide,Math.max(11,Math.min(W*0.016,16)),'#c4cdf5',sa,Math.max(3,W*0.004),'400');
    plainText('BRAIN ON  VS  BRAIN OFF  ·  SAME WORLD, SAME SEEDS',cx,H*0.115+tsz*0.95+30+slide,Math.max(9,Math.min(W*0.012,12)),'#8591cc',sa,3,'400');
    if(t>T_END+1.8) hint.className='on';
  }

  var black=1-smooth(0,0.4,t);
  if(black>0){ ctx.fillStyle='rgba(2,1,8,'+black+')'; ctx.fillRect(0,0,W,H); }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
})();
</script>
</body>
</html>
"""


def render_intro(height: int = INTRO_HEIGHT) -> None:
    """Draw the animated intro inside the Streamlit page."""
    components.html(INTRO_HTML, height=height, scrolling=False)
