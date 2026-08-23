(function(){
  var b=document.querySelector('.theme-toggle');
  if(b){b.addEventListener('click',function(){
    var r=document.documentElement;
    var cur=r.dataset.theme||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');
    var next=cur==='light'?'dark':'light';
    r.dataset.theme=next;
    try{localStorage.setItem('ajm-theme',next);}catch(e){}
  });}
  var rp=document.getElementById('rp');
  window.addEventListener('scroll',function(){
    if(!rp)return;
    var pct=window.scrollY/(document.body.scrollHeight-window.innerHeight)*100;
    rp.style.width=Math.min(pct,100)+'%';
  });
})();
